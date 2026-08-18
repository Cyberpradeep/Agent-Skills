# Consistency & hallucination testing

A single passing run of an LLM-backed agent proves almost nothing — the same
input can produce a different answer next time. The signal you actually want is
**stability across repeats**: run the same input several times and see whether the
agent agrees with itself. Disagreement is the fingerprint of hallucination and
non-determinism.

## Why repeat runs surface hallucination

A hallucination is the model confidently producing something not grounded in its
input. You usually can't catch it by staring at one output — it looks fluent and
plausible. But hallucinations are often *unstable*: run the input five times and
the fabricated detail changes, while the grounded parts stay put. So divergence
across repeats localizes the ungrounded parts. Consistency is not proof of
correctness, but **inconsistency is strong evidence of a problem**, and *where*
the outputs diverge points at *what* isn't grounded.

## Two regimes, two different bugs

Run each input in both:

1. **Determinism check (temperature 0).** With sampling off, a well-behaved agent
   should return near-identical outputs every time. If it doesn't, something is
   injecting nondeterminism — unfixed seeds, ordering, time, or genuine model
   instability. Any divergence here is a defect, full stop.

2. **Robustness check (temperature > 0, and/or paraphrased inputs).** This is the
   realistic regime. Some variation in *wording* is expected and fine. What you're
   hunting for is variation in the **decision or the facts** — the agent picking a
   different route, a different host, a different number, a different yes/no.

Keep the two regimes separate in the report. "Non-deterministic at temp 0" and
"decision wobbles at temp 0.7" are different severities.

## Compare decisions, not prose

The most common mistake is scoring raw string equality and flagging harmless
rewordings as failures. Two answers that say the same thing in different words are
**consistent**. Two answers that reach different conclusions are **not**, even if
they share 90% of their words.

So extract the load-bearing part of each output before comparing:

- If the output is structured (JSON, a dict, a decision + args), compare the
  structure and the values, ignoring incidental formatting.
- If the output is prose, extract the **claim / decision** — the host chosen, the
  route taken, the number returned, the yes/no — and compare those. The
  surrounding explanation can vary freely.

`scripts/consistency.py` does the mechanical part (exact match, structural match,
token-set similarity, majority vote, outlier detection). Your job is to tell it
*what* to extract as the decision for a given agent, when the output is prose.

## Metrics to report per input

- **Exact-match rate** — fraction of the N runs identical to the modal output.
  Meaningful mainly at temp 0.
- **Structural / semantic agreement** — agreement on the *extracted decision*,
  ignoring wording. This is the one that matters most at temp > 0.
- **Self-consistent (majority) answer** — the most common decision across runs.
  Self-consistency (majority vote over samples) is also a decent proxy for the
  agent's "confident" answer.
- **Outliers** — the specific runs that disagreed with the majority. Keep them;
  their reasoning traces are where you look next.
- **Stability verdict** — a single label per input:
  - `stable` — all runs agree on the decision.
  - `drifting` — a clear majority, a few outliers.
  - `non-deterministic` — no majority / near-even split.

## Contradiction detection

Beyond "did the decisions match", check for **direct contradiction** between runs:
one run says X, another says not-X. Contradictions are worse than mere drift —
they mean the agent has no stable position at all on that input. Flag any input
where the runs contain contradictory decisions, even if a bare majority exists.

## From metrics to patterns

Per-input numbers aren't the deliverable — patterns are. After scoring every
input, look across them:

- **Which inputs are unstable?** Sort by stability; the `non-deterministic` and
  `drifting` inputs are your list.
- **What do they share?** A feature of the input (a boundary value, a missing
  field, an ambiguous phrasing), a position (always the same turn), or an agent
  (one layer is unstable across the board).
- **Do the unstable runs share a reasoning fork?** Read the traces of the
  outliers (see step 5 in SKILL.md) and find the branch point where the reasoning
  diverged.

A finding like "routing is non-deterministic exactly when confidence lands in
0.4–0.5" is worth a hundred individual failing rows. Cluster, then report the
cluster.

## What consistency does *not* tell you

Consistency is necessary, not sufficient. An agent can be perfectly consistent and
perfectly wrong — it reliably returns the same bad answer. So pair consistency
with the contract checks from step 2: contract checks tell you *correct*,
consistency tells you *stable*. You need both.
