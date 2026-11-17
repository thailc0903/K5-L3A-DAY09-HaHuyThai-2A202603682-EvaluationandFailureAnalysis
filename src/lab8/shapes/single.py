"""Shape B — one ReAct agent. Student work.

Use `lab8.runtime.run_react` with max_steps=8. `decide` may pick a read tool.
It must not call `issue_refund`. After the loop, the host validates the quote
and is the only writer.

A decide() that trusts ticket text over the order row will fail hidden claims
where the customer overstates the delay or cites a superseded clause.

Per-order cap: an order may already have been refunded by an earlier claim.
The read tool `lookup_refund_history` shows how much. The host still enforces
the cap, so pass the full quote to `durability.issue_refund`, not a net amount.

Caps: stop at 8 steps. Count model calls in the Budget so cost stays comparable.

Trace contract v1 (docs/contracts.md): return a trace_path to a JSON file written in this run,
{"run_id": <same run_id>, "events": [...]}, on every return path including early
ones. `lab8.trace.Trace` does this; your own tracer is fine if it matches.
"""

from __future__ import annotations

from lab8.db import connect
from lab8.durability import issue_refund
from lab8.mock_llm import complete
from lab8.runtime import dispatch, run_react
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


def _run(conn, claim_id: str, *, seed: int, crash_at: str | None) -> RunResult:
    budget = Budget()
    trace = Trace(make_run_id("single", claim_id, seed))

    def done(status, proposal=0, reason=None):
        complete(budget, seed=seed, purpose="draft", prompt=status)
        trace.add("draft", {"status": status})
        trace.add("decision", {"status": status, "reason": reason})
        return finish(
            conn, shape="single", claim_id=claim_id, seed=seed,
            status=status, proposal_amount=proposal, budget=budget,
            trace=trace, error_reason=reason,
        )

    claim = dispatch(conn, budget, "get_claim_view", {"claim_id": claim_id}, worker=True)
    trace.add("claim", {"found": claim["found"]})
    order = {}

    def decide(observation):
        nonlocal order
        last = observation.get("last_tool")
        # MockLLM emits acknowledgements rather than structured tool calls.
        # A bounded code router maps the observation to a read-only action.
        complete(budget, seed=seed, purpose="plan", prompt=f"next_read:{last or 'start'}")
        trace.add("model_step", {"last_tool": last})
        if not claim["found"]:
            return {"final": {"status": "failed", "error_reason": "unknown_claim"}}
        if not claim.get("order_id"):
            return {"final": {"status": "needs_info", "error_reason": "missing_order_id"}}
        if last is None:
            return {"tool": "lookup_order", "args": {
                "order_id": claim["order_id"], "principal_id": claim["principal_id"],
            }}
        result = observation["last_result"]
        if last == "lookup_order":
            trace.add("lookup_order", result)
            if not result["visible"]:
                return {"final": {"status": "escalated", "error_reason": result["reason"]}}
            order = result["order"]
            return {"tool": "lookup_policy", "args": {}}
        if last == "lookup_policy":
            trace.add("lookup_policy", {"as_of": result["as_of"], "policy_count": len(result["policies"])})
            return {"tool": "compute_compensation", "args": {"order": order}}
        trace.add("quote", result)
        return {"final": {"proposal_amount": int(result["amount_vnd"]), "reason": result["reason"]}}

    loop = run_react(conn, budget, observation={"claim": claim}, decide=decide, max_steps=8, worker=True)
    final = loop["final"]
    if "status" in final:
        return done(final["status"], reason=final.get("error_reason"))
    proposal = final["proposal_amount"]
    if proposal <= 0:
        return done("denied", reason=final["reason"])
    trace.add("refund_request", {"proposal_amount": proposal})
    trace.write()
    outcome = issue_refund(conn, claim_id, proposal, crash_at=crash_at)
    trace.add("host_outcome", {"ok": outcome["ok"], "reason": outcome["reason"]})
    if not outcome["ok"]:
        return done("failed" if outcome["conflict"] else "denied", proposal, outcome["reason"])
    return done("resolved", proposal)
