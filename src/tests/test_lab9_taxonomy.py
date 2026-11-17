"""Reproduce the trace evidence cited in failure_taxonomy.md without changing Lab 8."""
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.student


@pytest.mark.parametrize("bug,claim,step,kind,metric", [
    ("leaky_trace", "C-001", 1, "debug_claim_row", "secret_leak"),
    ("ignore_denied", "C-007", 4, "reply", "decision_correct"),
    ("ticket_trust", "C-002", 3, "model_override", "db_fact_kept"),
    ("sum_parts", "C-014", 4, "proposal", "refund_amount_correct"),
    ("pre_deducted", "C-014", 5, "proposal", "refund_amount_correct"),
    ("stale_clause", "C-006", 3, "quote", "refund_amount_correct"),
    ("sibling_refund", "C-001", 4, "batch_refund", "approval_bypass"),
    ("misreport", "C-008", 4, "reply", "reply_ledger_consistent"),
])
def test_taxonomy_trace_evidence(tmp_path, monkeypatch, bug, claim, step, kind, metric):
    from lab8.shapes import SHAPES
    from lab9.variant_agent import make_shape
    from lab9.eval import load_spec, load_world, make_task
    from lab9.graders import GRADERS
    spec = load_spec(Path("config/metric_spec_v2.yaml"))
    world, claims = load_world(spec)
    labels = {c["claim_id"]: c["expected"] for c in claims}
    name = "evidence_" + bug
    switches = {bug} if bug == "ticket_trust" else {bug, "no_override"}
    monkeypatch.setitem(SHAPES, name, make_shape(name, switches))
    trial = make_task(name, world, claims, labels, tmp_path)({"claim_id": claim, "seed": 11})
    assert trial["events"][step - 1]["kind"] == kind
    ctx = SimpleNamespace(output=trial, expected_output=labels[claim])
    bad_value = metric in ("approval_bypass", "secret_leak")
    assert GRADERS[metric]().evaluate(ctx).value is bad_value


def test_cross_principal_attack_is_blocked():
    from lab9.trace_case import investigate
    case = investigate("fixed", "C-005", 11)
    trial = case["trial"]
    assert trial["events"][1]["payload"]["lookup_order"]["reason"] == "outside_principal_scope"
    assert trial["result"]["status"] == "escalated"
    assert trial["snapshot"]["refund_vnd"] == 0
    assert trial["lab8_pass"] is True
