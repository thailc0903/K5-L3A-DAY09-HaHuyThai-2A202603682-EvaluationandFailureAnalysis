"""Regression of the first wrong decision in C-002, and independent FM-08 evidence."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.student


def test_c002_first_wrong_step_regression():
    from lab9.trace_case import investigate
    from lab9.graders import RefundAmountCorrect, DbFactKept
    broken = investigate("seeded_regression", "C-002", 11)
    fixed = investigate("fixed", "C-002", 11)
    assert broken["trial"]["events"][2] == {"kind": "model_override", "payload": {"delay_days": 5}}
    assert fixed["trial"]["events"][2]["kind"] == "quote"
    for case, expected in ((broken, False), (fixed, True)):
        ctx = SimpleNamespace(output=case["trial"], expected_output=case["label"])
        assert RefundAmountCorrect().evaluate(ctx).value is expected
        assert DbFactKept().evaluate(ctx).value is expected
        assert case["trial"]["lab8_pass"] is expected


@pytest.mark.parametrize("text", [
    "Dạ, đã hoàn 35.000đ.", "LogiX đã hoàn phí 35,000 VND cho đơn hàng.",
    "Đã hoàn 35000 đồng.", "Đã hoàn 35 000 đ.",
])
def test_fm08_uses_ledger_not_proposal_or_wording(text):
    from lab9.graders import ReplyLedgerConsistent
    trial = {"events": [{"kind": "reply", "payload": {"text": text}}],
             "snapshot": {"refund_vnd": 20000}, "result": {"proposal_amount": 35000}}
    ctx = SimpleNamespace(output=trial, expected_output={})
    assert ReplyLedgerConsistent().evaluate(ctx).value is False
    trial["snapshot"]["refund_vnd"] = 35000
    assert ReplyLedgerConsistent().evaluate(ctx).value is True


def test_advanced_duplicate_grid_and_green_evaluator_failure():
    from lab9.gate import integrity_check
    rows = [{"item_id": f"E-{i}", "seed": s, "pass_rate": True, "slices": []}
            for i in range(2) for s in (11, 22)]
    base = {"manifest": {"eval_set_sha": "x", "items": 2, "seeds": [11, 22]},
            "rows": rows, "metrics": {"pass_rate": 1.0}, "evaluator_failures": []}
    spec = {"metrics": [{"id": "pass_rate", "blocking": True, "threshold": {"min": .8}}]}
    duplicate = deepcopy(base)
    duplicate["rows"][-1] = deepcopy(duplicate["rows"][0])
    assert integrity_check(duplicate, base, spec)
    green = deepcopy(base)
    green["evaluator_failures"] = ["grader crashed"]
    assert integrity_check(green, base, spec)
