# Memory testing with a planted fact

Memory is the most dangerous layer to leave untested, because a broken memory
layer usually **passes every short test**. Not because it works — because the
model doesn't need it to work yet. For short tasks, everything relevant is still
in the active prompt, so the model just re-derives context from what's visible and
never touches memory at all. Your evals pass, the demo is flawless, and the memory
layer could be completely dead. The gap only appears once a task runs long enough
that the original detail has scrolled out of the active window — by which point
it's a production incident, not a caught regression.

The trigger condition (long-running tasks) is exactly the condition least likely
to be in a regression suite. So you have to **deliberately create it**.

## The protocol

1. **Plant.** At an early turn (say turn 2), introduce a specific, arbitrary
   detail — a name, a number, a stated preference — that the model has no way to
   re-derive later. Arbitrary is key: if it's guessable from context, a pass
   doesn't prove memory worked.

2. **Bury.** Let the conversation continue for many turns of unrelated filler —
   enough that, under the system's normal token budget, the planted detail falls
   out of the active context window. If you don't push past the window, you're not
   testing memory, you're testing the prompt.

3. **Probe.** At a much later turn (say turn 30), ask for the detail back, or —
   better — make the model take an action or decision that *depends* on it. A
   decision-based probe is harder to fake than a direct "what did I say earlier".

4. **Localize.** If the model can't recall it, the failure is **retrieval /
   persistence**, not reasoning or model capability. That's a completely different
   fix — and the whole point of the test is to tell those apart. A model that
   can't recall a planted fact isn't "dumb"; the memory system didn't persist or
   retrieve the data.

## Run it against the summarized state — that's where it breaks

Most systems can't keep raw turn history forever; token limits force compression,
usually rolling summarization. **Summarization is a lossy step by design**, and
it's exactly where planted facts silently disappear. The question is never whether
you summarize — you have to — it's whether your summarizer reliably preserves the
*specific facts later turns depend on*, or just produces a plausible-sounding
gist.

So run the probe against the **summarized / compressed memory state**, not the raw
conversation. If the summarizer compresses away the planted detail during a
routine pass, that's your dead-memory case — caught in a controlled test instead
of in a live conversation with a real user. Testing only against raw history
misses the failure entirely, because raw history hasn't dropped anything yet.

Concretely: drive the conversation through the system's *real* memory/summarization
path (or a faithful copy of it — see `isolation.md` on scratch stores), let it
summarize as it normally would, and probe the state that remains. Do **not** probe
a full raw transcript you kept on the side; that transcript is not what the agent
sees.

## Variations worth running

- **Multiple facts.** Plant three or four unrelated details at different early
  turns and probe them all late. Summarizers often keep some and drop others;
  which ones they drop is informative.
- **Distractor facts.** Plant the real fact alongside similar-looking decoys
  ("the server is `srv-01`" early; later mention `srv-02`, `srv-07` in passing).
  Tests whether recall is precise or just pattern-matched to the nearest similar
  token.
- **Decision-dependent probe.** Instead of "what was the server name", ask the
  agent to *do* something that only works with the right value ("deploy to the
  server I mentioned at the start"). Catches agents that can quote the fact but
  don't actually use it.
- **Vary the burial depth.** Find the turn count at which recall starts failing.
  That number is a concrete capacity limit you can report and regression-test.

## What a result means

- **Recall passes against summarized state** → the memory/summarization layer is
  preserving load-bearing facts. Good — and now you have a regression test that
  will catch it the day someone changes the summarizer.
- **Recall fails against summarized state but passes against raw history** → the
  model is capable; the summarizer is dropping the fact. Fix the summarizer /
  retrieval, not the model.
- **Recall fails even against raw history** → the fact isn't being persisted or
  retrieved at all, or the probe is beyond the model's context handling. Look at
  persistence and retrieval first.

`scripts/planted_fact.py` scaffolds this: you supply a driver that can send turn
*i* and return the response (operating through the real memory path), and it
plants, buries, probes, and checks recall for you, against either the raw or the
summarized state.

## The question to leave the user with

Does the eval suite include *any* task that intentionally runs long enough to
force a memory recall — or does every case stay comfortably inside the active
context window? If it's the latter, the memory layer is effectively untested no
matter how green the dashboard is.
