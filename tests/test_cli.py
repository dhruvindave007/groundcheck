import json

from groundcheck.cli import main


def test_run_and_report_on_mock(tmp_path):
    out = tmp_path / "runs"
    for model in ("mock", "baseline:oracle", "baseline:bm25", "baseline:random"):
        main(["run", "--model", model, "--suite", "office", "--out", str(out), "--n-boot", "200", "--cache-dir", str(tmp_path / "c")])
    rows = [json.loads(l) for l in open(out / "office__mock.jsonl", encoding="utf-8")]
    assert len(rows) == 27
    oracle = json.loads((out / "office__baseline_oracle.summary.json").read_text())["metrics"]
    assert oracle["f1"][0] == 1.0 and oracle["fabricated"][0] == 0.0 and oracle["abstained_noev"][0] == 1.0
    mock = json.loads((out / "office__mock.summary.json").read_text())["metrics"]
    assert mock["fabricated"][0] > 0  # the mock invents IDs on some prompts
    report = tmp_path / "R.md"
    main(["report", "--runs", str(out), "--out", str(report)])
    text = report.read_text()
    assert "| mock | 27 |" in text and "baseline:oracle" in text


def test_mock_is_deterministic(tmp_path):
    for d in ("a", "b"):
        main(["run", "--model", "mock", "--suite", "syslog", "--limit", "10", "--out", str(tmp_path / d), "--n-boot", "50"])
    assert (tmp_path / "a" / "syslog__mock.jsonl").read_text() == (tmp_path / "b" / "syslog__mock.jsonl").read_text()
