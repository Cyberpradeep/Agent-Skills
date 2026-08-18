#!/usr/bin/env python3
"""
build_report.py — assemble the collected results (per-agent contract results,
consistency scores, memory-recall results, an end-to-end verdict) into a single
report. The report's whole job is to make MASKING visible: any agent that is red
while the pipeline is green is the headline. See references/report-format.md.

INPUTS (all optional except --consistency)
------------------------------------------
  --consistency consistency.json   output of consistency.py (required)
  --contracts   contracts.json     [{"agent","contract","passed","total"}, ...]
  --memory      memory.json        [{"mode","recalled","expected","probe_msg",
                                     "n_filler_turns"}, ...]
  --e2e "94%"                       the end-to-end pass rate / verdict, as text
  --title / --system               labels for the header
  --out report.md                  markdown output (default report.md)
  --html report.html               also emit a standalone HTML version

USAGE
-----
  python build_report.py --consistency consistency.json \
      --contracts contracts.json --memory memory.json \
      --e2e "94%" --system "ordering-agent" --out report.md --html report.html

  python build_report.py --demo        # write a sample report so you see the shape
"""
from __future__ import annotations

import argparse
import html
import json
from collections import defaultdict
from datetime import date
from typing import Any, Dict, List, Optional


_SEVERITY = {"stable": 0, "drifting": 1, "non-deterministic": 2, "all-errored": 3}


def _load(path: Optional[str], default):
    if not path:
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _agent_verdict(agent: str, cons_by_agent: Dict[str, list],
                   contracts_by_agent: Dict[str, dict]) -> str:
    contract = contracts_by_agent.get(agent)
    if contract and contract.get("passed", 0) < contract.get("total", 0):
        return "FAIL"
    groups = cons_by_agent.get(agent, [])
    worst = max((_SEVERITY.get(g["verdict"], 0) for g in groups), default=0)
    if worst == 0:
        return "PASS"
    return "UNSTABLE"


def build_markdown(consistency: List[dict],
                   contracts: List[dict],
                   memory: List[dict],
                   e2e: Optional[str],
                   title: str,
                   system: str) -> str:
    cons_by_agent: Dict[str, list] = defaultdict(list)
    for r in consistency:
        cons_by_agent[r["agent"]].append(r)
    contracts_by_agent = {c["agent"]: c for c in contracts}

    agents = sorted(set(cons_by_agent) | set(contracts_by_agent))
    verdicts = {a: _agent_verdict(a, cons_by_agent, contracts_by_agent) for a in agents}

    n_inputs = len({(r["agent"], r["input_id"]) for r in consistency})
    repeats = max((r.get("n_runs", 0) for r in consistency), default=0)

    red_agents = [a for a in agents if verdicts[a] != "PASS"]
    e2e_green = bool(e2e) and _looks_green(e2e)
    masking = red_agents and e2e_green

    L: List[str] = []
    L.append(f"# {title} — {system}")
    L.append(f"{date.today().isoformat()} · {n_inputs} inputs · "
             f"{len(agents)} agents · up to {repeats} runs/group\n")

    # 1. Executive summary
    L.append("## 1. Executive summary\n")
    L.append(f"- **End-to-end verdict:** {e2e or 'not provided'}")
    L.append("- **Per-agent verdicts:**")
    for a in agents:
        L.append(f"    - {a} → **{verdicts[a]}**")
    if masking:
        L.append(f"- **⚠️ MASKING DETECTED:** end-to-end reads {e2e} but these "
                 f"agents are red in isolation: {', '.join(red_agents)}. "
                 f"The aggregate number is hiding them.")
    else:
        L.append("- **Masking:** none detected "
                 "(no agent is red while end-to-end is green).")
    if memory:
        mem_line = "; ".join(f"{m.get('mode','?')}: "
                             f"{'PASS' if m.get('recalled') else 'FAIL'}"
                             for m in memory)
        L.append(f"- **Memory recall:** {mem_line}")
    L.append("")

    # 2. Per-agent results
    L.append("## 2. Per-agent results\n")
    for a in agents:
        L.append(f"### {a} — {verdicts[a]}")
        c = contracts_by_agent.get(a)
        if c:
            L.append(f"- **Contract:** {c.get('contract','(unstated)')}")
            L.append(f"- **Isolated result:** {c.get('passed',0)}/{c.get('total',0)} "
                     f"frozen inputs passed")
        groups = cons_by_agent.get(a, [])
        if groups:
            worst = max(groups, key=lambda g: _SEVERITY.get(g["verdict"], 0))
            L.append(f"- **Consistency:** worst = **{worst['verdict']}** "
                     f"(input `{worst['input_id']}`, temp {worst['temperature']}, "
                     f"agreement {worst['agreement']:.0%})")
            unstable = [g for g in groups if g["verdict"] != "stable"]
            if unstable:
                ex = unstable[0]
                L.append(f"- **Sample divergence:** input `{ex['input_id']}` — "
                         f"majority {ex['majority_decision']}, "
                         f"minority {ex['minority_decisions']}")
                L.append("- **Reasoning notes:** read the minority runs' reasoning "
                         "traces to find the branch point (fill in).")
            errs = sum(g.get("n_errors", 0) for g in groups)
            if errs:
                L.append(f"- **Errors:** {errs} run(s) raised — investigate.")
        L.append("")

    # 3. Consistency table
    L.append("## 3. Consistency / hallucination\n")
    L.append("| agent | input | temp | verdict | agreement | disagree |")
    L.append("|---|---|---|---|---|---|")
    for r in consistency:
        L.append(f"| {r['agent']} | {r['input_id']} | {r['temperature']} | "
                 f"{r['verdict']} | {r['agreement']:.0%} | "
                 f"{'yes' if r['disagreement'] else 'no'} |")
    L.append("")
    L.append("> Cluster the unstable rows by shared input feature before writing "
             "conclusions — report the cluster, not the rows.\n")

    # 4. Memory
    L.append("## 4. Memory\n")
    if memory:
        for m in memory:
            status = "PASS" if m.get("recalled") else "FAIL"
            L.append(f"- **[{m.get('mode','?')}] {status}** — planted "
                     f"`{m.get('expected','?')}`, buried under "
                     f"{m.get('n_filler_turns','?')} filler turns, probe: "
                     f"\"{m.get('probe_msg','?')}\"")
        raw = next((m for m in memory if m.get("mode") == "raw"), None)
        summ = next((m for m in memory if m.get("mode") == "summarized"), None)
        if summ and raw and raw.get("recalled") and not summ.get("recalled"):
            L.append("- **Interpretation:** raw passes, summarized fails → the "
                     "summarizer is dropping the fact. Fix summarizer/retrieval, "
                     "not the model.")
    else:
        L.append("- No memory test recorded. If this system compresses history, "
                 "this is the highest-value test to add — see references/"
                 "memory-tests.md.")
    L.append("")

    # 5. Patterns
    L.append("## 5. Patterns\n")
    L.append("- (Fill in clustered findings, most important first: the pattern, "
             "the evidence, the affected agents/inputs.)\n")

    # 6. Recommendations
    L.append("## 6. Recommendations\n")
    if masking:
        L.append(f"1. Treat `{', '.join(red_agents)}` as broken despite the green "
                 f"end-to-end number; do not ship on the aggregate.")
    L.append("2. Add a fast, no-LLM contract test in CI for every deterministic "
             "failure above, with a locked per-agent baseline, so the *per-agent* "
             "number moves on regression — not just the aggregate.")
    if memory and any(not m.get("recalled") for m in memory):
        L.append("3. Fix the memory/summarization path and add the planted-fact "
                 "test to the long-running-task suite.")
    L.append("")
    return "\n".join(L)


def _looks_green(e2e: str) -> bool:
    """Heuristic: an e2e string like '94%' or '0.94' counts as 'green' (>=80%)."""
    s = e2e.strip().rstrip("%")
    try:
        v = float(s)
        v = v / 100 if v > 1 else v
        return v >= 0.80
    except ValueError:
        return "pass" in e2e.lower() or "green" in e2e.lower()


# --------------------------------------------------------------------------- #
# Minimal, dependency-free markdown -> HTML for the constructs we emit above.
# --------------------------------------------------------------------------- #
def markdown_to_html(md: str) -> str:
    import re

    def inline(text: str) -> str:
        text = html.escape(text)
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"`([^`]+?)`", r"<code>\1</code>", text)
        return text

    lines = md.split("\n")
    out: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("### "):
            out.append(f"<h3>{inline(line[4:])}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{inline(line[2:])}</h1>")
        elif line.startswith("> "):
            out.append(f"<blockquote>{inline(line[2:])}</blockquote>")
        elif line.lstrip().startswith("- ") or line.lstrip().startswith("    - "):
            # gather a list
            items = []
            while i < len(lines) and lines[i].lstrip().startswith("- "):
                indent = len(lines[i]) - len(lines[i].lstrip())
                items.append((indent, lines[i].lstrip()[2:]))
                i += 1
            out.append("<ul>")
            for _, it in items:
                out.append(f"<li>{inline(it)}</li>")
            out.append("</ul>")
            continue
        elif line.startswith("|"):
            # gather a table
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip("|").split("|")])
                i += 1
            out.append("<table border='1' cellpadding='6' cellspacing='0'>")
            if rows:
                out.append("<tr>" + "".join(f"<th>{inline(c)}</th>" for c in rows[0]) + "</tr>")
                for r in rows[2:] if len(rows) > 1 else []:
                    out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
            out.append("</table>")
            continue
        elif line.strip() == "":
            out.append("")
        else:
            out.append(f"<p>{inline(line)}</p>")
        i += 1

    body = "\n".join(out)
    return f"""<!doctype html><meta charset="utf-8">
<title>Agent Evaluation Report</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:860px;
   margin:2rem auto;padding:0 1rem;line-height:1.5;color:#1a1a1a}}
 h1{{border-bottom:2px solid #ddd;padding-bottom:.3rem}}
 h2{{margin-top:2rem;border-bottom:1px solid #eee;padding-bottom:.2rem}}
 code{{background:#f4f4f4;padding:.1rem .3rem;border-radius:3px}}
 table{{border-collapse:collapse;margin:1rem 0;font-size:.9rem}}
 th{{background:#f4f4f4}} blockquote{{color:#555;border-left:3px solid #ddd;
   margin:1rem 0;padding-left:1rem}}
</style>
{body}"""


def _demo():
    consistency = [
        {"agent": "routing", "input_id": "clear_handle", "temperature": 0.0,
         "n_runs": 5, "n_errors": 0, "verdict": "stable", "agreement": 1.0,
         "disagreement": False, "majority_decision": {"route": "handle"},
         "minority_decisions": []},
        {"agent": "routing", "input_id": "boundary_band", "temperature": 0.7,
         "n_runs": 5, "n_errors": 0, "verdict": "non-deterministic",
         "agreement": 0.6, "disagreement": True,
         "majority_decision": {"route": "handle"},
         "minority_decisions": [{"route": "escalate"}]},
    ]
    contracts = [{"agent": "routing", "contract": "route in {handle, escalate}",
                  "passed": 3, "total": 3}]
    memory = [
        {"mode": "raw", "recalled": True, "expected": "X9-4417",
         "n_filler_turns": 30, "probe_msg": "What account number did I give?"},
        {"mode": "summarized", "recalled": False, "expected": "X9-4417",
         "n_filler_turns": 30, "probe_msg": "What account number did I give?"},
    ]
    md = build_markdown(consistency, contracts, memory, e2e="94%",
                        title="Agent Evaluation Report", system="ordering-agent (demo)")
    with open("report_demo.md", "w", encoding="utf-8") as f:
        f.write(md)
    with open("report_demo.html", "w", encoding="utf-8") as f:
        f.write(markdown_to_html(md))
    print("wrote report_demo.md and report_demo.html\n")
    print(md)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--consistency")
    ap.add_argument("--contracts")
    ap.add_argument("--memory")
    ap.add_argument("--e2e")
    ap.add_argument("--title", default="Agent Evaluation Report")
    ap.add_argument("--system", default="system under test")
    ap.add_argument("--out", default="report.md")
    ap.add_argument("--html")
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()

    if args.demo:
        _demo()
        return

    if not args.consistency:
        ap.error("--consistency is required (or use --demo)")

    consistency = _load(args.consistency, [])
    contracts = _load(args.contracts, [])
    memory = _load(args.memory, [])
    md = build_markdown(consistency, contracts, memory, args.e2e,
                        args.title, args.system)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"wrote {args.out}")
    if args.html:
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(markdown_to_html(md))
        print(f"wrote {args.html}")


if __name__ == "__main__":
    main()
