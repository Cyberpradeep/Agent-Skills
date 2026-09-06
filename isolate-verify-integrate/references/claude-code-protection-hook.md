# Optional: enforcing this with a Claude Code hook

The SKILL.md protocol relies on the agent choosing to follow it. In Claude Code you can
go one step further and make it a real technical gate: a `PreToolUse` hook that runs
before every `Edit`/`Write` (or `Bash`) call and can flat-out deny it (exit code 2)
before it happens. This turns "please build on the branch first" from a convention into
something the agent physically cannot bypass for the paths and commands you designate.

This is optional. Read this file only if you're setting up enforcement inside a Claude
Code project - it isn't needed to just follow the protocol in SKILL.md. Two variants are
below: one gates direct edits to `main`-tree files, the other gates the merge itself,
which fits the git-worktree default better.

## Variant A: block direct edits to protected paths

Useful mainly on the scratch-folder fallback, where there's no branch isolation and a
direct edit to `main` is the actual risk.

Save as `.claude/hooks/protect-until-verified.sh` and make it executable (`chmod +x`).
Adjust `PROTECTED_PATTERNS` to match your project's real source directories:

```bash
#!/bin/bash
# protect-until-verified.sh
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

PROTECTED_PATTERNS=("src/" "lib/" "app/")

is_protected=false
for pattern in "${PROTECTED_PATTERNS[@]}"; do
  if [[ "$FILE_PATH" == *"$pattern"* ]]; then
    is_protected=true
    break
  fi
done

if [ "$is_protected" = false ]; then
  exit 0  # not a protected path, nothing to check
fi

if grep -rl "^## Status" .agent_sandbox/*.manifest.md 2>/dev/null | \
   xargs grep -l "verified\|integrated" 2>/dev/null | grep -q .; then
  exit 0  # at least one sandbox has been marked verified - allow it through
fi

echo "Blocked: $FILE_PATH is a protected file and no sandbox manifest is marked 'verified' yet. Build and verify in .agent_sandbox/ first (see isolate-verify-merge/SKILL.md)." >&2
exit 2
```

## Variant B: block the merge itself (fits the worktree default)

With the git-worktree flow, the moment that actually matters is the `git merge` (or
`git checkout main` / `git switch main` followed by a merge), not individual file edits
inside the worktree - those are already isolated by branch. This variant matches on
`Bash` and inspects the command text instead of a file path.

Note it checks for `approved`, not `verified` - passing tests earns `verified`, but the
protocol requires an actual human response before merging (see SKILL.md, "Human
approval"), and the hook should reflect that rather than letting a passing test suite
alone unlock the merge.

Save as `.claude/hooks/protect-merge.sh` and make it executable:

```bash
#!/bin/bash
# protect-merge.sh
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# Only care about commands that merge an agent/* branch into main
if [[ "$COMMAND" != *"git merge"* ]] || [[ "$COMMAND" != *"agent/"* ]]; then
  exit 0
fi

if grep -rl "^## Status" .agent_sandbox/*.manifest.md 2>/dev/null | \
   xargs grep -l "^approved\|^integrated" 2>/dev/null | grep -q .; then
  exit 0  # a manifest says a human approved this - allow the merge
fi

echo "Blocked: merge attempted with no sandbox manifest marked 'approved'. This branch needs an actual human sign-off first, not just passing tests (see isolate-verify-merge/SKILL.md, 'Human approval')." >&2
exit 2
```

Register whichever variant(s) you use in `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          { "type": "command", "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/protect-until-verified.sh" }
        ]
      },
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/protect-merge.sh" }
        ]
      }
    ]
  }
}
```

## Caveats

- Both variants trust a manifest text file that the agent itself writes - a determined
  or careless agent could edit the manifest to say `verified` or `approved` without
  either actually happening. A stricter version would gate on an artifact only a real
  test run can produce (e.g. a hash or timestamp file written by your test runner on
  success) rather than free-text status. The version here is a meaningful speed bump,
  not a cryptographic guarantee.
- `approved` is a stronger claim than `verified` - it asserts a specific person actually
  said yes, not just that a command exited 0. Nothing here can force an agent to only
  write it after real human input, so this is exactly the kind of thing worth spot-
  checking if you're relying on it for anything that matters.
- Match Variant B's grep more strictly if you want it tied to *this specific* branch
  rather than "any manifest says verified" - e.g. extract the branch name from `COMMAND`
  and check that exact `<feature-slug>.manifest.md`.
- Hooks run with your own user permissions and block synchronously - keep the script
  fast, and treat it like any other code you'd review before trusting it.
- Hook configuration keys and behavior are a Claude Code feature and may change between
  versions - check Claude Code's own hooks documentation if this stops matching what you
  see in `/hooks`.
- Antigravity and other agents may have their own equivalent mechanisms (or none at all)
  - this file is Claude Code-specific; the SKILL.md protocol itself is not.
