---
name: agent-eval-tracer
description: >-
  Trace, evaluate, and observe the outputs of AI agents — especially multi-agent
  systems — by testing each agent in ISOLATION instead of only end-to-end. Use
  this whenever the user wants to evaluate, test, debug, trace, or observe an AI
  agent or multi-agent pipeline; check an agent's outputs for hallucination or
  inconsistency by running the same input multiple times and comparing; verify a
  memory / summarization layer actually retains facts (planted-fact recall
  tests); write per-agent contract / regression tests that need no LLM; or
  produce an evaluation / observability report for an agentic system. Trigger
  even when the user just says "test my agent", "is my agent hallucinating",
  "my eval pass rate looks suspiciously high", "check my agent's memory",
  "trace what each agent is doing", or "evaluate each agent separately" —
  isolated per-agent evaluation catches failures that end-to-end pass rates hide.
---

# Agent Eval Tracer

A methodology and toolkit for evaluating multi-agent AI systems by testing each
agent **in isolation**, checking outputs for **consistency / hallucination**
across repeated runs, verifying **memory** actually retains facts, and compiling
everything into a single **report**.

## The core idea (why this exists)

End-to-end pass rates lie. On a multi-agent pipeline, one agent (or layer) can be
completely broken and the aggregate score barely moves — the other layers quietly
compensate, or most test cases never exercise the broken path. A dead memory
layer passes every short test because the answer is still sitting in the active
prompt; a broken escalation path passes because most tickets never escalate. The
single number tells you *whether* something regressed, never *where*.

So this skill does not just check the final answer. It checks **what each
component actually produced on its own**, and it does so without letting the test
touch real production code or state. The unit of evaluation is the *individual
agent*, not the pipeline.

Four questions drive everything here:

1. **Isolation** — when I run this one agent alone, on fixed inputs, does it
   produce the right output? (Not "does the whole pipeline pass.")
2. **Consistency** — if I run the same input several times, do I get the same
   answer, or does it wobble / contradict itself? (Hallucination signal.)
3. **Memory** — does the memory / summarization layer still hold a fact planted
   many turns ago, after that detail has scrolled out of the active window?
4. **Patterns** — across all of the above, which inputs, agents, or turns are
   unstable, and what do their reasoning traces have in common?

## When to use this skill

Use it when the user hands you an agent or multi-agent system (as code, as an
API/callable, or as saved traces/logs) and wants any of: isolated per-agent
evaluation, hallucination / consistency checking, memory-retention testing,
contract/regression tests, or an evaluation report. If they only have logs and
no runnable code, you can still do the consistency, memory, and pattern analysis
on the recorded traces — you just skip the active isolated runs.

## Workflow

Do these in order. Steps 3–8 each have a matching reference doc and/or script —
read the reference before writing code, and prefer adapting the bundled script
over writing a new one from scratch.

### 1. Map the system into agents / layers

Before testing anything, get an inventory. Read the user's code or traces and
list every distinct agent or architectural layer (e.g. intent, routing,
planning, decomposition, execution, escalation, safety, memory,
summarization). For each, note: its input, its output, and any side effects
(tool calls, writes, external requests). This inventory is what makes isolation
possible — you can't isolate what you haven't named.

If the system is large, present the inventory to the user and confirm it before
proceeding. Ask which agents matter most so you spend effort where it counts.

### 2. Write a contract per agent

For each agent, state its contract: **given this input, it must produce this
output** (or satisfy this property). Where the output is deterministic given the
input, write a plain assertion test that needs **no LLM call** — these run in
milliseconds, never flake, and form the fast regression layer the blog argues
for. Where the output is open-ended, define a checkable property instead (e.g.
"routing decision is one of {A,B,C}", "escalates when confidence < threshold",
"never returns a host it wasn't given"). Keep the LLM out of the loop wherever
the logic is deterministic.

### 3. Isolate each agent — without touching real code

Read `references/isolation.md`. The rule: **wrap, never invoke the live
pipeline.** Replace every side-effecting tool with a stub/spy (supporting static
returns or dynamic callback handlers) that records the intended action instead
of performing it, freeze the agent's upstream inputs so you're testing *this*
agent and not its dependencies, and run against copies of any shared state so
nothing real is mutated. Adapt each real agent (synchronous, asynchronous, or
streaming) to the harness interface in `scripts/run_isolated.py`; that harness
handles repeated running, timing, timeout protection, rate-limit backoffs, error
capture, and trace recording for you.

### 4. Run each input N times and check consistency (hallucination)

Read `references/consistency.md`. Run every test input through the isolated agent
several times (start with N=5). Two regimes matter:

- **Determinism check** (temperature 0): outputs should be near-identical.
  Divergence here is a real defect, not noise.
- **Robustness check** (temperature > 0, and/or lightly paraphrased inputs):
  measures how much the answer wobbles under normal conditions.

Use `scripts/consistency.py` to score the N outputs: exact-match rate, structural
/ semantic agreement, a majority ("self-consistent") answer, outlier detection,
and a stability verdict (stable / drifting / non-deterministic). Compare the
*extracted decisions or claims*, not the raw prose — a reworded answer that says
the same thing is consistent; two answers that pick different hosts are not.

### 5. Capture and analyze reasoning, not just output

For every run, record the full trace: the agent's reasoning / intermediate steps,
its tool calls (as recorded by the stubs), and its final output — the harness
saves all three. When outputs diverge across the N runs, read the reasoning
traces of the divergent runs and look for the branch point: where did the
reasoning fork? A wrong answer with sound reasoning is a different bug than a
right answer reached by luck. Note both in the report.

### 6. Test memory with a planted fact

Read `references/memory-tests.md`. This is the highest-value, most-overlooked
test. Plant a specific arbitrary detail at an early turn, run enough filler turns
that the detail falls out of the active context window, then probe for it (or
make a decision that depends on it) at a much later turn. Run this against the
**summarized / memory state**, not the raw conversation — summarization is the
lossy step where facts silently vanish. If recall fails, you've localized the
bug to retrieval/persistence, not model capability. Use
`scripts/planted_fact.py` as the scaffold.

### 7. Identify patterns

Pull it together across agents and runs. Which inputs are unstable? Do the
unstable runs share a reasoning pattern, an input feature, or a turn position?
Does any agent look fine end-to-end but fail in isolation (the masking case)?
Cluster the failures rather than listing them one by one — a report that says
"escalation is non-deterministic whenever confidence lands in 0.4–0.5" is far
more useful than 12 individual failing rows.

### 8. Build the report

Read `references/report-format.md` and run `scripts/build_report.py` over the
collected results. The report must, above all, **put the per-agent verdicts next
to the end-to-end verdict and flag any masking** — any agent that is red while the
pipeline is green is the headline finding. Include per-agent contract results,
consistency metrics, reasoning notes on divergences, memory-recall results, the
pattern findings, and concrete recommendations.

## Bundled scripts

All scripts are framework-agnostic scaffolds — you adapt the user's real agents
to a small interface, and the script handles the repetitive machinery. Read the
top-of-file docstring of each before running.

- `scripts/run_isolated.py` — runs one adapted agent in isolation (supports sync,
  async, and streaming), N times per input, with timeout and retry guardrails,
  capturing reasoning + tool calls + output + timing to a runs file.
- `scripts/consistency.py` — scores a set of runs for agreement / divergence and
  emits a stability verdict per input.
- `scripts/planted_fact.py` — plant → filler → probe memory-recall scaffold, with
  a recall checker; runs against raw or summarized state.
- `scripts/build_report.py` — assembles runs + consistency + memory results into
  a single markdown (and optional HTML) report.

## Principles / gotchas

- **Test the agent, not its dependencies.** Freeze upstream inputs. If you feed
  an agent live upstream output, a failure could belong to any layer.
- **Isolation must be side-effect-free.** If a test can write to a real store,
  send a real request, or mutate shared state, it is not isolated — stub it.
- **Repeat before you trust.** A single passing run of an LLM proves almost
  nothing. Consistency across repeats is the actual signal.
- **A green end-to-end number is not evidence a layer works.** It's evidence the
  layer wasn't needed by those test cases. Deliberately build cases that force
  each layer to matter — especially long-running ones that force a memory recall.
- **Localize, don't just detect.** The point of isolation is to say *which* agent
  broke and *why* (retrieval vs reasoning vs capability), not just that something
  did.
