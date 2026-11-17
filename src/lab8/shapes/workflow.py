"""Shape A — deterministic workflow. Student work.

Signature (do not change):

    run_claim(claim_id, *, seed, store_path, crash_at=None) -> RunResult

Suggested steps. Money stays in code (`lab8.tools.compute_compensation`).

1. Open the store. Read the claim through `get_claim_view` (not SELECT *).
2. Missing order_id -> status `needs_info`. Do not write the ledger.
3. `lookup_order`. If not visible -> `escalated`. Do not copy phone, address, item, internal note.
4. Quote from the order row. Ignore delay numbers written in the ticket.
5. Quote amount 0 -> `denied`. Do not call issue_refund.
6. Quote amount > 0 -> `durability.issue_refund(conn, claim_id, <full quote>)`.
   Pass the FULL quote. The host checks the claim's own approval and subtracts
   what earlier claims already got for the same order (T13, T14). Do not
   subtract it yourself or the host subtracts twice.
   Auth failure or order already refunded -> `denied` (the host writes `policy_denied`).
   `proposal_amount` stays the full quote. Amount conflict -> `failed`.
7. Success -> `resolved`. One ledger row, one `refund_committed` audit.
8. Use MockLLM only to draft the reply text, if you want a model call at all.

The model must not choose the refund amount and must not commit the refund.

Trace contract v1 (docs/contracts.md): return a trace_path to a JSON file written in this run,
{"run_id": <same run_id>, "events": [...]}, on every return path including early
ones. `lab8.trace.Trace` does this; your own tracer is fine if it matches.
"""

from __future__ import annotations

import sqlite3

from lab8.db import connect
from lab8.durability import issue_refund
from lab8.mock_llm import complete
from lab8.runtime import dispatch
from lab8.schemas import Budget, RunResult, make_run_id
from lab8.shapes.common import finish
from lab8.trace import Trace


def run_claim(
    claim_id: str,
    *,
    seed: int,
    store_path: str,
    crash_at: str | None = None,
) -> RunResult:
    conn = connect(store_path)
    try:
        return _run(conn, claim_id, seed=seed, crash_at=crash_at)
    finally:
        conn.close()


def _run(
    conn: sqlite3.Connection,
    claim_id: str,
    *,
    seed: int,
    crash_at: str | None,
    draft_reply: bool = True,
    shape: str = "workflow",
) -> RunResult:
    budget = Budget()
    trace = Trace(make_run_id(shape, claim_id, seed))

    def done(status: str, proposal: int = 0, reason: str | None = None) -> RunResult:
        if draft_reply:
            complete(budget, seed=seed, purpose="draft", prompt=status)
            trace.add("draft", {"status": status})
        trace.add("decision", {"status": status, "reason": reason})
        return finish(
            conn, shape=shape, claim_id=claim_id, seed=seed,
            status=status, proposal_amount=proposal, budget=budget,
            trace=trace, error_reason=reason,
        )

    claim = dispatch(conn, budget, "get_claim_view", {"claim_id": claim_id}, worker=True)
    # The ticket is untrusted and may itself repeat sensitive text. Never log it.
    trace.add("claim", {"found": claim["found"]})
    if not claim["found"]:
        return done("failed", reason="unknown_claim")
    if not claim.get("order_id"):
        return done("needs_info", reason="missing_order_id")

    view = dispatch(conn, budget, "lookup_order", {
        "order_id": claim["order_id"], "principal_id": claim["principal_id"],
    }, worker=True)
    trace.add("lookup_order", view)
    if not view["visible"]:
        return done("escalated", reason=view["reason"])
    policy = dispatch(conn, budget, "lookup_policy", {}, worker=True)
    trace.add("lookup_policy", {"as_of": policy["as_of"], "policy_count": len(policy["policies"])})
    quoted = dispatch(conn, budget, "compute_compensation", {"order": view["order"]}, worker=True)
    trace.add("quote", quoted)
    proposal = int(quoted["amount_vnd"])
    if proposal <= 0:
        return done("denied", reason=quoted["reason"])

    # Flush the safe prefix so a real injected crash still has a trace.
    trace.add("refund_request", {"proposal_amount": proposal})
    trace.write()
    outcome = issue_refund(conn, claim_id, proposal, crash_at=crash_at)
    trace.add("host_outcome", {"ok": outcome["ok"], "reason": outcome["reason"]})
    if not outcome["ok"]:
        return done("failed" if outcome["conflict"] else "denied", proposal, outcome["reason"])
    return done("resolved", proposal)
