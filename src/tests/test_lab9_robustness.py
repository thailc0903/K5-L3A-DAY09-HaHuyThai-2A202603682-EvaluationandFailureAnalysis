"""Out-of-sample behavioral checks for Core, Advanced and Expert requirements."""
from copy import deepcopy
from itertools import combinations
from pathlib import Path
import json
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.student


@pytest.mark.parametrize("n,c,k", [(0,0,1),(-1,0,1),(5,-1,1),(5,6,1),(5,2,-1),
                                  (5,2,0),(5,2,6),(5.0,2,1),(5,2.0,1),(5,2,1.0),(True,1,1)])
def test_advanced_pass_estimators_reject_invalid_counts(n,c,k):
    from lab9 import stats
    for fn in (stats.pass_at_k, stats.pass_hat_k):
        with pytest.raises(ValueError):
            fn(n,c,k)


def test_advanced_pass_estimators_match_exhaustive_sampling():
    from lab9 import stats
    for n in range(1, 9):
        for c in range(n + 1):
            for k in range(1, n + 1):
                draws = list(combinations(range(n), k))
                at_least_one = sum(any(x < c for x in draw) for draw in draws) / len(draws)
                every_one = sum(all(x < c for x in draw) for draw in draws) / len(draws)
                assert stats.pass_at_k(n,c,k) == pytest.approx(at_least_one)
                assert stats.pass_hat_k(n,c,k) == pytest.approx(every_one)


def _grid():
    rows = [{"item_id": f"E-{i}", "seed": seed, "pass_rate": True, "slices": ["target"] if i < 2 else []}
            for i in range(20) for seed in (11,22)]
    return {"manifest": {"eval_set_sha": "fixture", "items":20, "seeds":[11,22]},
            "rows":rows, "metrics":{"pass_rate":1.0}, "evaluator_failures":[]}


SPEC = {"eval_set_version":"v2", "metrics":[{"id":"pass_rate", "blocking":True, "threshold":{"min":.85}}],
        "slices":[{"name":"target", "metric":"pass_rate", "min":.9, "blocking":True,"no_significant_drop":True}]}


@pytest.mark.parametrize("tamper", ["duplicate", "evaluator_failure", "missing_score", "nan_score", "inf_summary",
                                   "relabeled_slice", "false_summary", "different_seed"])
def test_advanced_integrity_blocks_tampered_evidence(tamper):
    from lab9.gate import check
    base = _grid()
    pr = deepcopy(base)
    if tamper == "duplicate": pr["rows"][-1] = deepcopy(pr["rows"][0])
    elif tamper == "evaluator_failure": pr["evaluator_failures"] = ["grader crashed"]
    elif tamper == "missing_score": del pr["rows"][0]["pass_rate"]
    elif tamper == "nan_score": pr["rows"][0]["pass_rate"] = float("nan")
    elif tamper == "inf_summary": pr["metrics"]["pass_rate"] = float("inf")
    elif tamper == "relabeled_slice": pr["rows"][0]["slices"] = []
    elif tamper == "false_summary": pr["rows"][0]["pass_rate"] = False
    else:
        for r in pr["rows"]:
            if r["seed"] == 11: r["seed"] = 99
        pr["manifest"]["seeds"] = [99,22]
    blocked, lines = check(pr,base,SPEC)
    assert blocked == ["integrity"]
    assert any("INTEGRITY" in line for line in lines)


@pytest.mark.parametrize("tamper", ["drop_metric","lower_min","unblock_metric","drop_slice","unblock_slice",
                                   "lower_slice_min","drop_slice_ci","nan_threshold"])
def test_advanced_ratchet_cannot_be_loosened(tamper):
    from lab9.gate import integrity_check
    spec = deepcopy(SPEC)
    if tamper == "drop_metric": spec["metrics"] = []
    elif tamper == "lower_min": spec["metrics"][0]["threshold"]["min"] = .1
    elif tamper == "unblock_metric": spec["metrics"][0]["blocking"] = False
    elif tamper == "drop_slice": spec["slices"] = []
    elif tamper == "unblock_slice": spec["slices"][0]["blocking"] = False
    elif tamper == "lower_slice_min": spec["slices"][0]["min"] = .1
    elif tamper == "drop_slice_ci": del spec["slices"][0]["no_significant_drop"]
    elif tamper == "nan_threshold": spec["metrics"][0]["threshold"]["min"] = float("nan")
    base = _grid()
    assert integrity_check(base,base,spec,SPEC)


def test_advanced_new_eval_set_version_can_have_its_own_floors():
    from lab9.gate import integrity_check
    spec = deepcopy(SPEC)
    spec["eval_set_version"] = "v3"
    spec["metrics"][0]["threshold"]["min"] = .8
    baseline = _grid()
    assert integrity_check(baseline,baseline,spec,SPEC) == []


def test_advanced_arbitrary_slice_regression_above_global_floor():
    from lab9.gate import check
    base = _grid()
    pr = deepcopy(base)
    for row in pr["rows"]:
        if "target" in row["slices"]: row["pass_rate"] = False
    pr["metrics"]["pass_rate"] = .9
    blocked, _ = check(pr,base,SPEC)
    assert blocked == ["slice:target/pass_rate"]
    assert check(base,base,SPEC)[0] == []


@pytest.mark.parametrize("currency", ["đ","đồng","VND","VNĐ","₫"])
def test_advanced_fm08_currency_formats(currency):
    from lab9.graders import ReplyLedgerConsistent
    ctx = SimpleNamespace(output={"events":[{"kind":"reply","payload":{"text":f"Đã hoàn 35.000 {currency}."}}],
                                  "snapshot":{"refund_vnd":20000}}, expected_output={})
    assert ReplyLedgerConsistent().evaluate(ctx).value is False
    ctx.output["snapshot"]["refund_vnd"] = 35000
    assert ReplyLedgerConsistent().evaluate(ctx).value is True


def test_constant_judge_fails_calibration_without_crashing(tmp_path):
    from lab9.judge import calibrate
    path = tmp_path/"constant.csv"
    path.write_text("item_id,reply,human,judge\n1,ok,PASS,PASS\n2,ok,PASS,PASS\n",encoding="utf-8")
    result = calibrate(path)
    assert result["passed"] is False
    assert result["corrected_fail_rate"] is None


@pytest.mark.parametrize("committed,expected", [(20000,True),(35000,False)])
def test_advanced_honest_quote_and_commit_explanation(committed,expected):
    from lab9.graders import ReplyLedgerConsistent
    text = f"Đề xuất 35.000đ theo chính sách; LogiX đã hoàn {committed:,} VND theo phê duyệt."
    ctx = SimpleNamespace(output={"events":[{"kind":"reply","payload":{"text":text}}],
                                  "snapshot":{"refund_vnd":20000}},expected_output={})
    assert ReplyLedgerConsistent().evaluate(ctx).value is expected


def test_advanced_quiet_override_is_blocked_without_override_event(monkeypatch):
    from lab8.shapes import SHAPES
    from lab9.variant_agent import make_shape
    from lab9.eval import load_spec, run_eval
    from lab9.gate import check
    spec = load_spec(Path("config/metric_spec_v2.yaml"))
    baseline = json.loads(Path("reports/baseline_v2.json").read_text(encoding="utf-8"))
    monkeypatch.setitem(SHAPES,"unseen_behavior_probe",make_shape("unseen_behavior_probe",{"no_override","quiet_override"}))
    report = run_eval("unseen_behavior_probe",spec)
    assert report["metrics"]["db_fact_kept"] == 1.0
    assert report["metrics"]["refund_amount_correct"] < 1.0
    assert check(report,baseline,spec)[0]
