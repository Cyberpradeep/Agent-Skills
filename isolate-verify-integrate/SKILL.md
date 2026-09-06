---
name: isolate-verify-merge
description: Use this any time an agent is asked to add a feature, change logic, fix a bug, refactor, or otherwise modify code that already works, including implementing an approved plan step by step against an existing codebase. Trigger this even if the user does not explicitly say "be careful" or "test first" - any edit to already-working or production code qualifies. This skill stops the agent from touching the real, main file until the new logic has been built and proven correct in complete isolation, using the agent's own terminal and code execution, protecting working code from hallucinated logic, half-finished edits, and context lost across a long task. Skip it only for brand-new files with nothing existing to protect, or when the user explicitly asks for a direct, unverified edit right now.
compatibility: Works in any agent that reads SKILL.md (Claude Code, Antigravity, Claude.ai, and similar) with terminal or code-execution access, including git. Uses a git worktree as the default sandbox for full-protocol changes, falling back to a plain scratch folder for lightweight ones or non-git projects; references/claude-code-protection-hook.md is an optional add-on for Claude Code specifically.
---

# Isolate, Verify, Merge

## Why this exists

The riskiest moment in agentic coding is not writing new code, it's touching code that
already works. When an agent edits the live file directly while it's still figuring out
the logic, three things tend to go wrong at once: a half-correct idea gets committed
straight into production, a long task loses track of what was actually confirmed versus
assumed (leading to hallucinated "it should work now"), and a small logic change turns
into an undiagnosable mix of old and new behavior. None of this is a character flaw in
the agent, it's a structural problem: nothing forced a checkpoint between "I think this
is right" and "this is now part of the real system."

Git already gives you rollback once something's landed - history, branches, diffs,
`git revert`. That's real protection, but it's reactive: it only helps after the agent
has already touched the file you care about. This protocol is about the moment before
that - making sure nothing lands in the first place until it's actually been proven
correct, and, for changes that matter, until a person has actually said so. The pieces
aren't competing: git supplies isolation and rollback, this protocol supplies the
discipline of what must be true before anything merges, and the human approval step
below supplies the one thing neither git nor tests can give you - permission.

The fix is to physically separate three activities that usually get blurred together:
building the new logic, proving the new logic is correct, and folding it into the real
codebase. Each one gets its own space and its own moment to fail safely, so a wrong
guess costs a few minutes on a throwaway branch instead of a broken main file.

## The protocol

### Phase 0 — Pin the contract, before writing any code

Before creating anything, write down (in a sentence or two, doesn't need ceremony):
- The exact function, class, or module name this will eventually be, and its signature
  (inputs, outputs, error/edge behavior).
- At least one concrete input to expected-output example. Pull this from the user, from
  existing tests, or from the surrounding code's own conventions - if none exists, ask,
  or state the example you're assuming and proceed.
- If this replaces or changes existing logic: what the *current* behavior is for a couple
  of representative cases, so you have something to diff against later.

This is the acceptance test for everything that follows. Skipping it is how sandboxed
code ends up "working" but not actually fitting where it needs to plug in.

### Phase 1 — Isolate

Build and verify the new logic somewhere that can't touch the file you're eventually
going to change - by default, that "somewhere" should be a real git worktree on its own
branch, not a hand-built scratch folder.

**Default: a git worktree.** If the project is a git repo (true for almost everything):

```bash
git worktree add .agent_sandbox/<feature-slug> -b agent/<feature-slug>
```

This checks out a second, fully real copy of the repository into
`.agent_sandbox/<feature-slug>/`, on its own branch, sharing the same `.git` history. It
solves the read-only-dependencies problem structurally instead of by discipline: the
real `auth`, `database`, `config` modules are just *there*, checked out for real, so
there's nothing to fake and nothing to remember not to fake. Because the worktree is
isolated by branch, it's also safe to edit existing files inside it, including the
file(s) you'll eventually need to wire the new logic into - that edit lives on the
`agent/<feature-slug>` branch, invisible to `main` until you deliberately merge it.

**Fallback: a plain scratch folder.** Use this only when there's no git repo to work
with, or for a lightweight-tier change where a whole worktree is overkill (see "Scaling
the protocol" below). In that case, give the sandbox **read-only** access to the real
interfaces it depends on rather than hand-rolling `fake_database.py`-style stand-ins of
the surrounding system - a project with everything faked is a simulation of your
application, not your application, and a pass there proves very little. Reserve real
mocks/fakes for things genuinely unsafe or unavailable to run for real (a live payment
gateway, a destructive external call).

Either way:
- Write the implementation as a complete, runnable unit against the Phase 0 contract.
- Record environment parity: the runtime and key dependency versions, the shape of any
  relevant config/environment variables, and which external interfaces (a database, a
  framework, a queue) the feature actually needs. Reproduce these where practical - a
  worktree gives you the real *files*, not automatically a matching runtime, so this is
  still a separate thing to check. A bug that only shows up under the real Python
  version, the real database version, or a real env var you didn't set is exactly the
  kind of thing "the logic looks correct" testing misses. Where you can't reproduce
  something practically, state that explicitly in the manifest as an open assumption to
  re-check during Phase 3, rather than silently hoping it lines up.

### Phase 2 — Verify (unit: does the new thing work on its own?)

This phase asks only one question: does the isolated implementation do what the Phase 0
contract says? It does not yet ask whether the whole application still works with this
wired in - that's answered in Phase 3, and passing this one does not guarantee that one.

- Actually run it, inside the worktree (or scratch folder). Not "this reads correctly,"
  but executed, through your terminal or interpreter, against the Phase 0 example plus
  edge cases (empty input, wrong type, boundary values).
- If you're changing existing logic, also run the old representative cases from Phase 0
  through the new code, as regression checks. Silent behavior changes are the most
  common way this kind of task quietly breaks something unrelated.
- When something fails, fix it and rerun it right there. `main` is not part of this loop
  at all yet.
- Keep a running log of what was tried and what passed (see manifest below). This is
  what protects you against your own context loss - if the task runs long, gets
  compacted, or hands off to a fresh instance, re-reading the manifest recovers the
  actual state instead of re-guessing or re-deriving it from memory.

Do not proceed to Phase 3 until every case you defined actually passed, not "probably
passes" or "looks right on inspection."

### Phase 3 — Integrate (system: does the whole application still work?)

With a worktree, "integrate" splits into several moments: proving the fully-wired branch
actually works, getting a person to say it's safe to land, then folding it into `main` -
so the risky part happens *before* anything touches `main`, and the irreversible part
doesn't happen without a human decision.

1. **Wire the connection on the branch, not on `main`.** Add the import, the call site,
   the config - inside `.agent_sandbox/<feature-slug>/`, where it's still isolated. This
   is the same wiring Phase 3 always required; the difference is where it happens.
2. **System-verify on the branch.** Run the full existing test suite, or a smoke test of
   the real entry point, against the worktree itself - it already has the whole repo,
   wiring included, so this is a true system-level check, done entirely before `main` is
   at risk. Record the commit of `main` you verified against in the manifest (you'll need
   it in step 4).
3. **Request human approval before merging** (see "Human approval" below). Passing step 2
   proves the branch works - it does not, by itself, grant permission to merge.
4. **Re-check `main` for drift.** If `main` has moved past the commit you verified
   against in step 2, rebase or merge the latest `main` into the branch and repeat steps
   2-3 before proceeding - a branch verified against an old `main` and the same branch
   against today's `main` are two different claims.
5. **Check `git status` on `main`** before merging anything. If it's not clean, that's
   the user's pre-existing state - don't fold it silently into what you're about to bring
   in. Note it, and where practical ask the user whether it should be included, stashed,
   or left alone.

   ```
   system-verify → approval → drift check → git status (main)
        │
        ▼
   checkpoint  = exactly the state you found (user's, none of yours yet)
        │
        ▼
   merge       = the already-verified, already-approved branch
        │
        ▼
   confirm
   ```

   The failure mode this avoids: a checkpoint that already mixes the user's uncommitted
   work with your own, so a rollback lands you in an unknown mixed state instead of
   cleanly back to where the user actually was.
6. **Checkpoint `main`** (a commit, stash, or branch) capturing exactly that pre-existing
   state - one command away if you need it back.
7. **Merge the branch into `main`** (`git merge agent/<feature-slug>`, or your project's
   preferred integration method). Because everything on the branch was already verified
   and approved, the merge itself should introduce nothing new or unverified - resist the
   urge to "clean up" or resolve a conflict by rewriting logic here. If a conflict forces
   a real logic decision, take the resolved version back to Phase 2, not to improvise
   inside the merge.
8. **Run a quick confirmation smoke test on `main` post-merge.** This is no longer your
   primary gate (step 2 was) - it's a cheap check for merge-conflict mistakes or anything
   that changed in `main` concurrently since your checkpoint.
9. **If something fails:** for a step-2 failure, the bug is almost always in the wiring
   or an environment-parity gap you flagged in Phase 1 - fix it on the branch and
   re-verify (and re-approve) before merging. For a step-8 failure (post-merge), first
   suspect the merge or conflict resolution itself, then a concurrent change in `main`;
   only touch the already-verified logic if you can show the logic itself is wrong, and
   if so, revert the merge, return to Phase 2, and re-verify before trying again.

If you're on the plain-scratch-folder fallback instead of a worktree, steps 1-2 happen
as a direct (but checkpointed) edit to `main` itself, guarded the same way: smallest
possible diff, checkpoint main first, don't rewrite verified logic while wiring, run the
full suite before calling it done. Lightweight and skip-tier changes (see "Scaling the
protocol") don't have a merge step at all, so the human-approval gate below doesn't apply
to them - just report what you did afterward, as usual.

## Human approval

For full-protocol changes, passing Phase 3 step 2 does not grant permission to merge.
Merging into `main` is the one action in this whole protocol that isn't the agent's to
take unilaterally by default - unless the user has explicitly said this task can be
merged autonomously, stop here and ask.

**What to put in the request** - enough for the person to actually decide, not just
"tests passed":
- What changed: which files, and roughly how much (a line/file-count summary is plenty).
- Why: the one or two sentence purpose, tying back to the Phase 0 contract.
- What was verified, specifically: which contract cases passed, and how many
  unit/regression/system tests ran and passed - a count is more useful than the word
  "passed" on its own.
- Any environment-parity gaps flagged in Phase 1 that are still open.
- Your own read on risk and blast radius: which parts of the system this touches, and
  how central they are.
- The merge you're proposing (base branch, feature branch, strategy).

**Handling the response** - this isn't just approve/reject:
- **Approved** - continue to step 4 (drift check) and on toward merging.
- **Changes requested** - stay on the same branch, address the feedback, go back through
  Phase 2 and Phase 3 step 2 (re-verify), then request approval again. Do not merge on
  the strength of an earlier approval once changes have been requested - it no longer
  applies to what's now on the branch.
- **Rejected** - abandon the branch (clean up the worktree), don't merge, and don't retry
  the same approach without new direction from the user.

Move the manifest's `Status` along with the decision (`verified` -> `approved` ->
`integrated`, or `rolled-back` on rejection) - and only write `approved` once the person
has actually responded, never on your own inference that they probably would. That
inference is exactly the kind of shortcut this gate exists to prevent.

## Sandbox conventions

Use a consistent, disposable location so nothing about "where is the in-progress work"
has to be re-decided or re-found every turn.

**Git repos (default):**

```
.agent_sandbox/
├── <feature-slug>.manifest.md   # your external memory: goal, contract, environment, status, test log
└── <feature-slug>/               # git worktree, branch agent/<feature-slug> - a full real checkout
```

The manifest lives as a sibling *outside* the worktree, not inside it - that way the
worktree's tracked content is 100% real project files, and merging the branch never
accidentally drags your bookkeeping notes into `main`. Add `.agent_sandbox/` to `main`'s
ignore file so it doesn't show up as noise in the `git status` checks in Phase 3.

**Non-git projects or lightweight changes (fallback):**

```
.agent_sandbox/
└── <feature-slug>/
    ├── manifest.md
    ├── src/
    └── tests/
```

Same manifest, same idea, just without the worktree/branch machinery underneath it.

A minimal manifest:

```markdown
# <feature-slug>

## Contract
- Function/module: ...
- Inputs / outputs / errors: ...
- Example: input X -> output Y

## Environment
- Runtime: e.g. Python 3.12
- Key dependencies: e.g. Postgres 17, ORM vX
- Relevant config/env vars: e.g. DATABASE_URL shape
- Reproduced in sandbox: yes / partially (note gaps here)

## Status
sandboxed | verified | approved | integrated | rolled-back

## Test log
- [x] example from contract
- [x] edge case: empty input
- [ ] regression: old case still holds
- [ ] system test on the branch (Phase 3 step 2)

## Integration point
- Branch: agent/<feature-slug>          (git path)
- File / anchor to wire into: ...        (either path)
- Verified against main @ <commit-sha>   (for the drift check in Phase 3 step 4)
```

Update the status line as you move through phases - it's the single source of truth for
"has `main` actually changed yet," both for you across a long task and for the user if
they ask. Once merged and you no longer need the rollback reference, clean up with
`git worktree remove .agent_sandbox/<feature-slug>` and `git branch -d agent/<feature-slug>`.

## Working through a multi-step plan

When a plan has several units (module A, then B, then C), take each one all the way
through Phases 0-3, including approval, before starting the next. Don't start building B
while A is still on its branch and unmerged - that's exactly the pattern that produces a
pile of half-finished, mutually-inconsistent changes. One verified, approved, merged unit
at a time, even if it feels slower; it's the difference between N clean small merges and
one large unreviewable one.

## Scaling the protocol to the size and risk of the change

Not everything needs the full three-phase treatment, and not everything needs a worktree.
The right amount of ceremony scales with what's actually at risk, not with how the change
happens to be labeled - a "bug fix" can be a one-line, zero-coupling tweak or a deeply
coupled change to shared logic, and it's the coupling and blast radius that should decide
the tier, not the name:

| Change | Protocol |
|---|---|
| New feature, business-logic change, refactor of coupled logic, bug fix in shared/critical code | Full protocol - worktree + branch, all phases, human approval before merge |
| Small, self-contained change with no dependency coupling (a constant, a simple config value, an isolated conditional) | Lightweight - use the scratch-folder fallback (or even a throwaway local branch without a full worktree), skip the full manifest/environment ceremony and the approval gate; a quick "does this produce the right output" check is enough, report what you did afterward |
| Typo, comment, docstring, brand-new file with nothing existing to protect | Skip the protocol and edit directly - still worth running the existing test suite afterward as a cheap sanity check |

When you're unsure which tier a change belongs in, default up a tier. The cost of extra
care here is a few minutes; the cost of skipping it on something that turns out to matter
is a broken main file. Don't let the lightweight and skip tiers turn into a place to ask
permission for everything, either - they exist precisely so small changes don't carry the
full ceremony, approval gate included.

## The gate, made explicit

For full-protocol changes, all of these should be true before merging into `main`:

- [ ] The contract was pinned before code was written
- [ ] Environment parity (runtime/dependencies/config) was captured and reproduced where
      practical - any gaps are flagged, not assumed away
- [ ] The standalone implementation was actually executed (not just read/reasoned about)
- [ ] Every case from the contract, plus edge cases, passed
- [ ] If replacing existing logic: the old behavior's known cases still pass
- [ ] The connection was wired on the branch, and the full test suite / smoke test passed
      *against the branch itself* - this is what "verified" means before requesting approval
- [ ] A human has actually approved the merge (or explicitly authorized autonomous
      merging for this task) - passing tests never substitutes for this
- [ ] If `main` moved since verification, the branch was rebased and re-verified (and
      re-approved) before merging
- [ ] `git status` on `main` was checked before merging, and any pre-existing
      modifications were recorded/handled separately rather than folded into the checkpoint
- [ ] A checkpoint of `main` exists (commit/branch/stash), capturing only that
      pre-existing state

If any box isn't checked, you're not ready to merge yet - go back to Phase 2, the
branch-wiring step, or the approval step in Phase 3.

## Talking to the user

State plainly which phase you're in, especially whether `main` has actually been touched:

- "Building and testing this on an isolated branch first - `main` hasn't been touched
  yet."
- "The branch passes the full test suite - here's what changed and what was verified.
  Want me to merge it in?"
- "Changes requested - staying on the branch, addressing that, then I'll re-verify and
  check back in before merging."
- "The post-merge smoke test failed - rolling back the merge and looking at the wiring
  or the merge itself, not the already-verified logic."

This keeps the user oriented without them needing to check the diff themselves at every
step.

## Notes for specific tools

Claude Code and Antigravity both auto-discover skills by reading `SKILL.md` files and
loading them when their description matches the task (Antigravity calls this the same
"progressive disclosure" mechanism), and both give the agent real terminal/bash access,
so `git worktree` commands work out of the box with no extra setup. Drop this whole
folder at:

- Claude Code: `.claude/skills/isolate-verify-merge/`
- Antigravity: `.agents/skills/isolate-verify-merge/`

and it will be picked up automatically - no extra wiring needed. For any other agent that
reads a standing instructions file (`AGENTS.md`, `CLAUDE.md`, `.cursorrules`, etc.) but
doesn't have its own skill-discovery system, add one line pointing at this file, e.g.
"Before modifying existing code, follow `isolate-verify-merge/SKILL.md`."

If you're in Claude Code and want this enforced technically rather than just followed by
convention, see `references/claude-code-protection-hook.md` for optional hooks that block
edits to `main`-tree files, or block the merge itself, until the manifest says `approved`.
