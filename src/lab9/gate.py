"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    import math
    from collections import Counter
    from lab9.graders import GRADERS
    from lab9.eval import aggregate
    problems = []
    for group in ("metrics", "slices"):
        seen = set()
        for entry in spec.get(group, []):
            identity = entry["id"] if group == "metrics" else (entry["name"], entry["metric"])
            if identity in seen:
                problems.append(f"duplicate spec entry: {identity}")
            seen.add(identity)
            for key, value in (entry.get("threshold", {}) if group == "metrics" else entry).items():
                if key in ("min", "max", "max_increase") and (
                    not isinstance(value, (int, float)) or not math.isfinite(value)
                ):
                    problems.append(f"invalid threshold: {identity}/{key}")
    graded = {m["id"] for m in spec["metrics"] if m["id"] in GRADERS}
    graded.update(s["metric"] for s in spec.get("slices", []) if s["metric"] in GRADERS)
    def finite(v):
        return isinstance(v, (int, float)) and math.isfinite(v)
    for name, report in (("PR", pr), ("baseline", base)):
        manifest, rows = report.get("manifest", {}), report.get("rows", [])
        seeds = manifest.get("seeds", [])
        keys = [(r.get("item_id"), r.get("seed")) for r in rows]
        items = {k[0] for k in keys}
        if not seeds or len(set(seeds)) != len(seeds):
            problems.append(f"{name}: invalid seed manifest")
        if len(rows) != manifest.get("items", 0) * len(seeds) or len(items) != manifest.get("items"):
            problems.append(f"{name}: incomplete item x seed grid")
        if len(keys) != len(set(keys)) or set(keys) != {(i, s) for i in items for s in seeds}:
            problems.append(f"{name}: duplicate or missing item/seed")
        if report.get("evaluator_failures"):
            problems.append(f"{name}: evaluator_failures")
        for mid, val in report.get("metrics", {}).items():
            if not finite(val):
                problems.append(f"{name}: invalid aggregate {mid}")
        for metric in spec["metrics"]:
            if not finite(report.get("metrics", {}).get(metric["id"])):
                problems.append(f"{name}: missing metric {metric['id']}")
        for row in rows:
            if any(not finite(row.get(mid)) or row[mid] not in (0, 1) for mid in graded):
                problems.append(f"{name}: missing/invalid grader value {row.get('item_id')}@{row.get('seed')}")
            needs_cost = any(m["id"] == "cost_per_success" for m in spec["metrics"])
            if ("cost" in row or needs_cost) and (not finite(row.get("cost")) or row["cost"] < 0):
                problems.append(f"{name}: invalid cost")
        # Recompute aggregates when all row-level inputs are available. Do not trust a green summary.
        if rows and all(all(finite(r.get(m)) for m in graded) for r in rows):
            ks = [int(m.split("_")[-1]) for m in report["metrics"] if m.startswith(("pass_hat_", "pass_at_"))]
            safe_rows = [{**r, "cost": r.get("cost", 0)} for r in rows]
            if all(finite(r["cost"]) for r in safe_rows):
                computed = aggregate(safe_rows, sorted(graded), sorted(set(ks)))
            else:
                computed = {}
            for mid, val in report["metrics"].items():
                if mid in computed and (computed[mid] is None or not finite(val) or abs(val - computed[mid]) > 0.00011):
                    problems.append(f"{name}: aggregate disagrees with rows: {mid}")
    pr_keys = Counter((r.get("item_id"), r.get("seed")) for r in pr.get("rows", []))
    base_keys = Counter((r.get("item_id"), r.get("seed")) for r in base.get("rows", []))
    if pr_keys != base_keys:
        problems.append("PR item/seed multiset differs from baseline")
    base_tags = {(r["item_id"], r["seed"]): set(r.get("slices") or []) for r in base.get("rows", [])}
    if any(set(r.get("slices") or []) != base_tags.get((r["item_id"], r["seed"])) for r in pr.get("rows", [])):
        problems.append("PR slice tags differ from baseline")
    if base_spec and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        def ratchet(old, new, label):
            if old.get("blocking") and not new.get("blocking"):
                problems.append(f"ratchet: {label} no longer blocking")
            for key, value in old.items():
                if key in ("min", "max", "max_increase"):
                    if key not in new or (new[key] < value if key == "min" else new[key] > value):
                        problems.append(f"ratchet: {label} loosened {key}")
                if key == "no_significant_drop" and value and not new.get(key):
                    problems.append(f"ratchet: {label} dropped no_significant_drop")
        for group, identity in (("metrics", lambda m: m["id"]), ("slices", lambda m: (m["name"], m["metric"]))):
            current = {identity(m): m for m in spec.get(group, [])}
            for old in base_spec.get(group, []):
                key = identity(old)
                if key not in current:
                    problems.append(f"ratchet: dropped {group} {key}")
                    continue
                ratchet(old, current[key], str(key))
                ratchet(old.get("threshold", {}), current[key].get("threshold", {}), str(key))
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for entry in spec.get("slices", []):
        name, mid = entry["name"], entry["metric"]
        ident = f"slice:{name}/{mid}"
        a, b = per_item(pr, mid, name), per_item(base, mid, name)
        bad = not a or set(a) != set(b)
        value = sum(a.values()) / len(a) if a else None
        note = ""
        if value is not None and "min" in entry and value < entry["min"]:
            bad = True
        if value is not None and "max" in entry and value > entry["max"]:
            bad = True
        if entry.get("no_significant_drop") and a and set(a) == set(b):
            keys = sorted(a)
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027), confidence=bs.get("confidence", 0.95))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            bad |= hi < 0
        if bad and entry.get("blocking"):
            blocked.append(ident)
        lines.append(f"  {ident} {value} {note} {'BLOCK' if bad and entry.get('blocking') else 'warn' if bad else 'ok'}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                                               confidence=bs.get("confidence", 0.95))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
