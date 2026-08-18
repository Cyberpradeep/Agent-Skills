# Isolating an agent without touching real code

The goal of isolation is to answer one question cleanly: *given a fixed input,
does **this single agent** produce the right output?* Everything that makes that
question murky — upstream dependencies, real side effects, shared mutable state —
has to be neutralized first. If you skip this, a failure could belong to any
layer, and a "pass" could be another layer quietly compensating.

## The one rule

**Wrap the agent; never invoke the live pipeline.** You call the agent function
directly with inputs you control. You do not run the end-to-end system and try to
observe the agent from outside — that reintroduces every dependency you were
trying to remove.

## The three things you must neutralize

### 1. Side effects → stubs / spies

Every tool the agent can call that changes the world (writes a file, hits an API,
sends a message, charges a card, mutates a database) must be replaced with a
**stub** that records the *intended* action and returns a canned result, instead
of performing it. The recorded actions are themselves test data — you assert on
them ("the execution agent tried to run against host `srv-01`") without anything
real happening.

A stub that records is called a **spy**. Prefer spies: they give you both safety
(no real effect) and observability (you can assert on what the agent tried to
do).

```python
class ToolSpy:
    """Records calls instead of performing them; returns a canned result or calls a dynamic handler."""
    def __init__(self, name, returns=None, handler=None):
        self.name = name
        self.returns = returns
        self.handler = handler     # optional dynamic callback for multi-step reasoning
        self.calls = []            # every (args, kwargs) the agent attempted

    def __call__(self, *args, **kwargs):
        self.calls.append({"tool": self.name, "args": args, "kwargs": kwargs})
        if self.handler is not None:
            return self.handler(*args, **kwargs)
        return self.returns        # deterministic canned response
```

#### Dynamic / Stateful Spies for Multi-Step Tool Loops
If your agent calls a tool in a loop where Step 2 depends on the output of Step 1 (e.g. `search()` followed by `fetch_details()`), pass a dynamic `handler`:

```python
def dynamic_db_handler(query_type, **kwargs):
    if query_type == "check_status":
        return {"active": True, "balance": 150}
    return {"status": "ok"}

db_spy = ToolSpy("db_query", handler=dynamic_db_handler)
```

### 2. Upstream dependencies → frozen inputs

An agent in a pipeline normally receives its input from the agent before it. If
you feed it *live* upstream output, you are no longer testing one agent — a
failure could originate two layers up. So **freeze the input**: hand the agent a
fixed, hand-written (or recorded-once) input that represents what the upstream
layer *should* produce. Now the only thing under test is this agent's transform
from that fixed input to its output.

Keep a small library of frozen inputs per agent: the normal case, the edge cases,
and the known-tricky cases. These double as your regression fixtures.

### 3. Shared state → copies / scratch stores

If the agent reads or writes shared state (a memory store, a session object, a
scratchpad), point it at a **copy or a scratch instance**, never the real one.
Snapshot the state before the run, run against the copy, and discard it after.
For memory agents specifically, give them an in-memory scratch store so the
planted-fact tests (see `memory-tests.md`) can't pollute anything real.

## The adapter pattern

`scripts/run_isolated.py` expects each agent under test to look like a small,
uniform callable. Your job is to write a thin **adapter** that maps the user's
real agent onto that interface and wires in the spies and frozen inputs. The
adapter is the only framework-specific code you write; the harness handles
repeated running, timing, error capture, and trace recording.

An adapter takes a single test input and returns a result dict with at least:

```python
{
  "output":    <the agent's final output>,
  "reasoning": <chain-of-thought / intermediate steps, if available, else None>,
  "tool_calls": <list of recorded spy calls>,
  "error":     <None, or the exception string if the agent raised>,
}
```

### 1. Synchronous Adapter Example:

```python
def make_adapter(real_agent_factory):
    def adapter(test_input, *, temperature=0.0):
        # fresh spies per run so calls don't accumulate across runs
        db   = ToolSpy("db_write", returns={"ok": True})
        http = ToolSpy("http_post", returns={"status": 200})

        # build the real agent with tools swapped for spies + scratch state
        agent = real_agent_factory(tools={"db_write": db, "http_post": http},
                                   temperature=temperature)

        result = agent.run(test_input)     # the real agent's own entrypoint
        return {
            "output":     result.output,
            "reasoning":  getattr(result, "reasoning", None),
            "tool_calls": db.calls + http.calls,
            "error":      None,
        }
    return adapter
```

### 2. Asynchronous & Streaming Adapter Example:

The harness natively detects `async def` and async generators without requiring manual event-loop management:

```python
async def async_adapter(test_input, *, temperature=0.0):
    spy = ToolSpy("fetch_profile", returns={"tier": "gold"})
    agent = RealAsyncAgent(tools=[spy], temperature=temperature)
    
    # Execute async agent
    result = await agent.ainvoke(test_input)
    
    return {
        "output": result.output,
        "reasoning": result.thought_log,
        "tool_calls": spy.calls,
        "error": None
    }
```

For streaming agents (async generators yielding tokens or chunks), `run_isolated.py` automatically gathers the chunks into a unified string output:

```python
async def streaming_adapter(test_input, *, temperature=0.0):
    async for chunk in agent.stream(test_input, temperature=temperature):
        yield chunk.text
```

## Resilience: Timeouts & Rate-Limit Retries

When running repeat evaluations ($N=5$ or $N=10$), agents can hang in reasoning loops or encounter API rate limits (HTTP 429). You can configure timeouts and backoff retries in `run_suite`:

```python
from scripts.run_isolated import run_suite

run_suite(
    agent_name="billing_agent",
    adapter=async_adapter,
    inputs=fixtures,
    repeats=5,
    regimes=[0.0, 0.7],
    timeout_seconds=15.0,  # Execution timeout per run
    max_retries=3,         # Exponential backoff retry on 429 / network errors
    backoff_factor=1.5,
    out_path="runs/billing.jsonl"
)
```

## Determinism knobs

You want to run each input in **both** regimes, because they catch different
bugs:

- **temperature = 0** — the determinism check. Outputs should be near-identical
  across repeats. Divergence here means the agent is non-deterministic even when
  it shouldn't be — a real defect, not noise.
- **temperature > 0** (and/or lightly paraphrased inputs) — the robustness check.
  Measures how much the answer wobbles under realistic conditions. Some wobble in
  phrasing is fine; wobble in the *decision* is not.

Fix every other source of randomness you can: seeds, clocks, ordering. The less
ambient randomness, the more any remaining divergence points at the agent itself.

## Isolation checklist

Before you trust a result, confirm:

- [ ] No real tool ran — every side-effecting call went through a spy.
- [ ] The input was frozen, not produced by a live upstream agent.
- [ ] Shared state was a copy / scratch instance; nothing real was mutated.
- [ ] Spies were reset per run (call lists don't leak between repeats).
- [ ] The same input was run in both temp=0 and temp>0 regimes.
- [ ] Timeouts and rate-limit retries are enabled for long-running batches.
