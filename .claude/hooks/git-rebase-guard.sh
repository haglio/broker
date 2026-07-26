#!/usr/bin/env bash
# PreToolUse(Bash) guard: enforce the "rebase onto main, never reset/merge to dig out" rule.
#
# Agents are supposed to sync by rebasing onto main and resolve conflicts in place, then
# ff-merge to land. The recurring failure is an agent that hits a collision with already-landed
# work, judges the merge "error-prone," and either merges its redundant version or resets its
# branch to main and re-applies its unique work by hand. Both are banned in CLAUDE.md; this hook
# makes the dangerous git invocations actually fail instead of relying on the agent to remember.
#
# It blocks ONLY the unambiguous dangerous forms and deliberately allows the legitimate ones:
#   BLOCK  git merge <branch>                  (non-ff merge to sync)
#   BLOCK  git reset --hard|--soft main        (resetting your branch onto main/origin)
#   ALLOW  git merge --ff-only ...             (the landing step)
#   ALLOW  git merge --abort|--continue|--quit (resolving an in-progress merge/rebase)
#   ALLOW  git reset --soft $(git merge-base main HEAD)   (the documented own-commits squash)
#   ALLOW  git reset --hard          / --hard HEAD[~n]    (discard local edits / own commits)
#   ALLOW  git rebase main           (the encouraged sync)
exit_block() {
  echo "BLOCKED by git-rebase-guard: $1" >&2
  echo "Rule: when a teammate landed overlapping work, rebase onto main and resolve the conflict in place (git checkout --theirs <file> && git add; git rebase --continue / --skip past an emptied commit). Never reset-and-reapply, and never merge to sync. To squash your OWN commits use: git reset --soft \$(git merge-base main HEAD). See CLAUDE.md 'Git: rebase onto main, then ff-merge'." >&2
  exit 2
}

input=$(cat)
cmd=$(printf '%s' "$input" | python3 -c 'import sys,json;
try: print(json.load(sys.stdin).get("tool_input",{}).get("command",""))
except Exception: pass' 2>/dev/null)
[ -z "$cmd" ] && exit 0

# collapse newlines so multiline commands are matched as one line
norm=$(printf '%s' "$cmd" | tr '\n' ' ')

# --- non-fast-forward merge to sync ---------------------------------------------------------
# (exclude `git merge-base`, where \bmerge\b matches the "merge" before the hyphen)
if printf '%s' "$norm" | grep -Eq '\bgit\b[^|;&]*\bmerge\b' \
   && ! printf '%s' "$norm" | grep -Eq 'merge-base' \
   && ! printf '%s' "$norm" | grep -Eq '\bmerge\b[^|;&]*--(ff-only|abort|continue|quit)\b'; then
  exit_block "non-fast-forward 'git merge' (merging to sync). Rebase onto main instead."
fi

# --- reset --hard/--soft onto a branch (the reset-to-dig-out / reset-to-main move) -----------
# Exclude the documented squash form, which mentions main only inside merge-base.
if printf '%s' "$norm" | grep -Eq '\bgit\b[^|;&]*\breset\b[^|;&]*--(hard|soft)\b[^|;&]*\b(main|origin/main|origin/HEAD)\b' \
   && ! printf '%s' "$norm" | grep -Eq 'merge-base'; then
  exit_block "'git reset --hard/--soft main' reverts teammates' commits and is the reset-to-dig-out move. Rebase instead."
fi

exit 0
