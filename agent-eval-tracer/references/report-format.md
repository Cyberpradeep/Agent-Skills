# Report format

The report's job is to make the **masking** visible: the whole reason for isolated
evaluation is that a broken agent can hide behind a green end-to-end number. So the
report always shows per-agent verdicts *next to* the end-to-end verdict, and the
headline is any agent that is red while the pipeline is green.

`scripts/build_report.py` generates this from the collected results. Use this
structure; adapt wording to the system under test.

## Required structure

```markdown
# Agent Evaluation Report — <system name>
<date> · <N inputs> · <M agents> · <R repeats per input>

## 1. Executive summary
- End-to-end verdict:        <pass rate / verdict>
- Per-agent verdicts:        <one line each: agent → PASS / FAIL / UNSTABLE>
- ⚠️ Masking detected:        <list any agent that is red while E2E is green — THIS IS THE HEADLINE>
- Memory recall:             <PASS / FAIL, at what burial depth>
- Top 3 findings:            <the three things the reader must act on>

## 2. Per-agent results
For each agent:
### <agent name>
- Contract:        <the stated contract>
- Isolated result: <PASS / FAIL> on <k>/<n> frozen inputs
- Consistency:     <stable / drifting / non-deterministic>, agreement <x%>
- Reasoning notes: <where divergent runs forked, if any>
- Sample divergence: <one concrete example of two runs disagreeing, if any>
- Side effects:    <what the spies recorded — did it try anything it shouldn't?>

## 3. Consistency / hallucination
- Table: input → stability verdict → agreement % → contradiction? (Y/N)
- Unstable inputs called out with their shared feature (the cluster, not the rows)

## 4. Memory
- Protocol used: planted <fact> at turn <a>, buried <b> turns, probed at turn <c>
- Against summarized state: <PASS / FAIL>
- Against raw history:      <PASS / FAIL>
- Interpretation:          <retrieval vs summarizer vs capability — which layer>
- Burial depth at which recall starts failing: <turn count, if measured>

## 5. Patterns
- Clustered findings, most important first. Each: the pattern, the evidence,
  the affected agent(s)/input(s).

## 6. Recommendations
- Concrete, ordered by impact. Tie each to a finding above.
- Include which fast no-LLM contract tests to add to CI so this can't regress.
```

## Writing rules

- **Lead with masking.** If any agent is red while end-to-end is green, that goes
  in the first two lines of the summary. It is the single most important thing the
  report can say.
- **Cluster, don't enumerate.** One line describing a pattern beats twelve failing
  rows. Put the row-level detail in a table or an appendix, and let the prose
  carry the clusters.
- **Localize every failure.** For each failure, say which layer owns it —
  retrieval vs reasoning vs capability vs a broken tool contract. "It failed" is
  not a finding; "the summarizer dropped the planted fact" is.
- **Separate stable-but-wrong from unstable.** A consistently wrong agent and a
  non-deterministic agent need different fixes; don't blur them.
- **Recommend the cheap regression net.** Every deterministic failure you found
  should become a fast, no-LLM contract test in CI, with a locked per-agent
  baseline — so the number that finally moves is the *per-agent* one, not just the
  aggregate.

## Output formats

`build_report.py` writes markdown by default and can also emit a standalone HTML
version (`--html`) for sharing. The markdown is the source of truth; the HTML is a
convenience. Neither should require re-running the evaluation to read.
