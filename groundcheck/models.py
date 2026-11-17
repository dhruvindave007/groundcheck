"""Model adapters and baselines behind one interface.

Every solver maps a Scenario to a Prediction. LLM solvers wrap a chat adapter
(``complete(system, user) -> str``); baselines compute citations directly.

Model specs accepted by ``get_solver``:
  baseline:random | baseline:bm25 | baseline:oracle
  mock
  openai:<model>      OpenAI-compatible /chat/completions (OpenAI, vLLM, Ollama, OpenRouter).
                      Env: OPENAI_API_KEY (optional for local servers), OPENAI_BASE_URL
                      (default https://api.openai.com/v1).
  anthropic:<model>   Anthropic Messages API via the `anthropic` SDK. Env: ANTHROPIC_API_KEY.
  bedrock:<model_id>  AWS Bedrock Converse API via boto3. Standard AWS credential chain;
                      region from AWS_REGION / AWS_DEFAULT_REGION.

Keys are read from the environment only and are never logged.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import urllib.request
from pathlib import Path

from groundcheck.bm25 import top_k
from groundcheck.metrics import Prediction
from groundcheck.prompts import PROMPT_VERSION, SYSTEM, parse_response, render_user
from groundcheck.schema import Scenario

MAX_TOKENS = 2048


# ---------------------------------------------------------------- chat adapters
class MockChat:
    """Deterministic stand-in for an LLM, driven only by the prompt text.

    It cites the two BM25-best lines for the question, invents a non-existent ID
    on roughly one prompt in four, and answers with the best line's text.
    """
    name = "mock"

    def complete(self, system: str, user: str) -> str:
        log, _, question = user.partition("\n\nQUESTION\n")
        lines = [ln for ln in log.splitlines()[1:] if ln.startswith("[")]
        ids = [ln[1:ln.index("]")] for ln in lines]
        idx = top_k(question, lines, 2)
        cites = [ids[i] for i in idx]
        h = int(hashlib.sha256(user.encode()).hexdigest(), 16)
        if h % 4 == 0:
            cites.append("FAKE-0000")
        answer = lines[idx[0]].split(": ", 1)[-1] if idx else ""
        return json.dumps({"answer": answer, "citations": cites, "insufficient_evidence": False})


def _post_json(url: str, body: dict, headers: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


class OpenAICompatChat:
    def __init__(self, model: str, temperature: float = 0.0):
        self.model, self.temperature = model, temperature
        self.name = f"openai:{model}"
        self.base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

    def complete(self, system: str, user: str) -> str:
        headers = {}
        key = os.environ.get("OPENAI_API_KEY")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        body = {"model": self.model, "temperature": self.temperature, "max_tokens": MAX_TOKENS,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        out = _post_json(f"{self.base}/chat/completions", body, headers)
        return out["choices"][0]["message"]["content"] or ""


class AnthropicChat:
    def __init__(self, model: str):
        import anthropic  # optional dependency: pip install groundcheck[anthropic]
        self.client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
        self.model, self.name = model, f"anthropic:{model}"

    def complete(self, system: str, user: str) -> str:
        msg = self.client.messages.create(model=self.model, max_tokens=16000, system=system,
                                          messages=[{"role": "user", "content": user}])
        if msg.stop_reason == "refusal":
            return ""
        return "".join(b.text for b in msg.content if b.type == "text")


class BedrockChat:
    def __init__(self, model_id: str):
        import boto3  # optional dependency: pip install groundcheck[bedrock]
        self.client = boto3.client("bedrock-runtime")
        self.model, self.name = model_id, f"bedrock:{model_id}"

    def complete(self, system: str, user: str) -> str:
        out = self.client.converse(modelId=self.model, system=[{"text": system}],
                                   messages=[{"role": "user", "content": [{"text": user}]}],
                                   inferenceConfig={"maxTokens": MAX_TOKENS})
        return "".join(c.get("text", "") for c in out["output"]["message"]["content"])


# ---------------------------------------------------------------- solvers
class LLMSolver:
    """Prompt a chat model, cache the raw reply on disk, parse citations."""

    def __init__(self, chat, condition: str = "full", cache_dir: str | None = ".cache"):
        self.chat, self.condition = chat, condition
        self.name = chat.name + ("" if condition == "full" else f"+{condition}")
        self.cache = Path(cache_dir) if cache_dir else None

    def solve(self, s: Scenario) -> Prediction:
        events = s.events
        if self.condition == "oracle-evidence":
            gold = set(s.gold_evidence)
            events = [e for e in s.events if e.id in gold] or s.events[:0]
        user = render_user(s, events)
        key = hashlib.sha256(json.dumps([self.chat.name, PROMPT_VERSION, SYSTEM, user]).encode()).hexdigest()
        path = self.cache / f"{key}.json" if self.cache else None
        if path and path.exists():
            text = json.loads(path.read_text(encoding="utf-8"))["text"]
        else:
            text = self.chat.complete(SYSTEM, user)
            if path and not isinstance(self.chat, MockChat):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"text": text}), encoding="utf-8")
        return parse_response(text)


def _k(s: Scenario) -> int:
    return len(s.gold_evidence) or 2


class RandomBaseline:
    """Cite k random log IDs, k = gold set size (2 on no-evidence scenarios). No answer."""
    name = "baseline:random"

    def solve(self, s: Scenario) -> Prediction:
        rng = random.Random(s.id)
        return Prediction(citations=rng.sample(s.event_ids, min(_k(s), len(s.events))), answers=False)


class BM25Baseline:
    """Cite the top-k BM25 events for the question, k = gold set size. No answer."""
    name = "baseline:bm25"

    def solve(self, s: Scenario) -> Prediction:
        docs = [f"{e.source} {e.text}" for e in s.events]
        return Prediction(citations=[s.events[i].id for i in top_k(s.question, docs, _k(s))], answers=False)


class OracleBaseline:
    """Cite exactly the gold set and give the gold answer; abstain on no-evidence. Metric ceiling."""
    name = "baseline:oracle"

    def solve(self, s: Scenario) -> Prediction:
        if s.no_evidence:
            return Prediction(answer="insufficient evidence", abstain=True)
        return Prediction(answer=s.answer.value, citations=list(s.gold_evidence))


def get_solver(spec: str, condition: str = "full", cache_dir: str | None = ".cache"):
    if spec == "baseline:random":
        return RandomBaseline()
    if spec == "baseline:bm25":
        return BM25Baseline()
    if spec == "baseline:oracle":
        return OracleBaseline()
    if spec == "mock":
        return LLMSolver(MockChat(), condition, cache_dir)
    provider, _, model = spec.partition(":")
    if not model:
        raise ValueError(f"model spec needs provider:model, got {spec!r}")
    chat = {"openai": OpenAICompatChat, "anthropic": AnthropicChat, "bedrock": BedrockChat}.get(provider)
    if chat is None:
        raise ValueError(f"unknown provider {provider!r}")
    return LLMSolver(chat(model), condition, cache_dir)


def safe_name(spec: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", spec)
