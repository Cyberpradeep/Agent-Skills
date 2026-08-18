#!/usr/bin/env python3
"""
consistency.py — score repeated runs of the same input for agreement, and emit a
stability verdict per (input, temperature). This is the hallucination / drift
signal: run an input N times and see whether the agent agrees with itself.

Reads a runs file produced by run_isolated.py (JSON lines, one RunRecord each).

KEY IDEA: compare the *decision*, not the prose. Two answers worded differently
that reach the same conclusion are consistent; two that reach different
conclusions are not, even if 90% of the words match. See references/consistency.md.

USAGE
-----
    python consistency.py runs.jsonl                 # decision = whole output
    python consistency.py runs.jsonl --key route     # decision = output["route"]
    python consistency.py runs.jsonl --key route --out consistency.json

If your decision lives deep in a prose output, extract it upstream (add a field to
the adapter's output) rather than trying to regex it here — explicit is better.

VERDICTS
--------
    stable             all runs agree on the decision
    drifting           a clear majority (>50%), with outliers
    non-deterministic  no majority / near-even split
Any group with >1 distinct decision has `disagreement=True`. At temperature 0 that
is a determinism defect; at temperature>0 it is drift you must judge.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple


def load_runs(path: str) -> List[Dict[str, Any]]:
    runs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                runs.append(json.loads(line))
    return runs


def extract_decision(output: Any, key: Optional[str]) -> Any:
    """The load-bearing part of the output to compare on."""
    if key is not None and isinstance(output, dict):
        return output.get(key)
    return output


def canonical(decision: Any) -> str:
    """Normalize a decision to a canonical string so equivalent decisions group
    together regardless of dict ordering / incidental formatting."""
    try:
        return json.dumps(decision, sort_keys=True, default=str)
    except TypeError:
        return str(decision)


def token_set(s: str) -> set:
    return set(s.lower().split())


def mean_pairwise_similarity(strings: List[str]) -> float:
    """Auxiliary signal for prose: average SequenceMatcher ratio over all pairs.
    High even when decisions differ = 'sounds the same, decides differently',
    which is the sneaky case worth surfacing."""
    if len(strings) < 2:
        return 1.0
    ratios = []
    for i in range(len(strings)):
        for j in range(i + 1, len(strings)):
            ratios.append(SequenceMatcher(None, strings[i], strings[j]).ratio())
    return round(sum(ratios) / len(ratios), 3)


def verdict_for_group(decisions: List[str]) -> Tuple[str, float, List[str]]:
    """Return (verdict, agreement_fraction, minority_decisions)."""
    counts = Counter(decisions)
    n = len(decisions)
    modal, modal_count = counts.most_common(1)[0]
    agreement = modal_count / n if n else 0.0
    minority = [d for d in counts if d != modal]

    distinct = len(counts)
    if distinct == 1:
        verdict = "stable"
    elif agreement > 0.5:
        verdict = "drifting"
    else:
        verdict = "non-deterministic"
    return verdict, round(agreement, 3), minority


def analyze(runs: List[Dict[str, Any]], key: Optional[str]) -> List[Dict[str, Any]]:
    # group by (agent, input, temperature)
    groups: Dict[Tuple[str, str, float], List[Dict[str, Any]]] = defaultdict(list)
    for r in runs:
        groups[(r["agent_name"], r["input_id"], r["temperature"])].append(r)

    results = []
    for (agent, input_id, temp), grp in sorted(groups.items()):
        errored = [r for r in grp if r.get("error")]
        ok = [r for r in grp if not r.get("error")]
        decisions = [canonical(extract_decision(r.get("output"), key)) for r in ok]
        prose = [str(r.get("output")) for r in ok]

        if decisions:
            verdict, agreement, minority = verdict_for_group(decisions)
            modal = Counter(decisions).most_common(1)[0][0]
        else:
            verdict, agreement, minority, modal = "all-errored", 0.0, [], None

        results.append({
            "agent": agent,
            "input_id": input_id,
            "temperature": temp,
            "n_runs": len(grp),
            "n_errors": len(errored),
            "verdict": verdict,
            "agreement": agreement,
            "disagreement": len(set(decisions)) > 1,
            "majority_decision": _maybe_json(modal),
            "minority_decisions": [_maybe_json(m) for m in minority],
            "prose_similarity": mean_pairwise_similarity(prose),
            "avg_duration_ms": round(sum(r.get("duration_ms", 0) for r in grp) / len(grp), 1),
        })
    return results


def _maybe_json(s: Optional[str]) -> Any:
    if s is None:
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return s


def print_table(results: List[Dict[str, Any]]):
    hdr = f"{'agent':<16}{'input':<18}{'temp':>5}  {'verdict':<18}{'agree':>6}  {'errs':>4}"
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        flag = "" if r["verdict"] == "stable" else "  <-- look"
        print(f"{r['agent']:<16}{r['input_id']:<18}{r['temperature']:>5.1f}  "
              f"{r['verdict']:<18}{r['agreement']:>6.0%}  {r['n_errors']:>4}{flag}")
    unstable = [r for r in results if r["verdict"] != "stable"]
    print(f"\n{len(unstable)}/{len(results)} groups are not stable.")
    if unstable:
        print("Next: read the reasoning traces of the minority runs for these "
              "groups to find where the reasoning forked.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", help="runs file from run_isolated.py (JSON lines)")
    ap.add_argument("--key", default=None,
                    help="field of a dict output to treat as the decision")
    ap.add_argument("--out", default=None, help="write full results JSON here")
    args = ap.parse_args()

    runs = load_runs(args.runs)
    results = analyze(runs, args.key)
    print_table(results)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
