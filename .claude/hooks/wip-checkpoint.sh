#!/usr/bin/env bash
#
# wip-checkpoint.sh — Stop hook (registered in .claude/settings.json).
#
# Snapshots this worktree's uncommitted state to refs/wip/<branch> at the end of
# every turn, WITHOUT modifying the working tree, the index, or HEAD. It is a
# safety net against the concurrent-agent worktree-sync race that can silently
# discard uncommitted edits / untracked files between turns. The snapshot lives
# under refs/wip/* and is NEVER on the branch, so a `git merge --ff-only <branch>`
# can never carry it onto main — main stays pristine.
#
# If a worktree is ever clobbered, recover everything that was present at the last
# turn boundary with (run from the worktree root):
#
#     git checkout refs/wip/<branch> -- .          # restore all files
#     git diff HEAD refs/wip/<branch>              # or just inspect what was saved
#
# Guards:
#   * only ever acts inside .claude/worktrees/ — never the main checkout
#   * no-op when the tree is clean
#   * never creates a commit on the branch or on main; only refs/wip/* moves
#
set -u

# Must be inside a git work tree.
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

top=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0

# Only ever snapshot an agent worktree, never the main checkout or anywhere else.
case "$top" in
  */.claude/worktrees/*) ;;
  *) exit 0 ;;
esac

# Nothing uncommitted? Nothing to protect.
[ -n "$(git status --porcelain 2>/dev/null)" ] || exit 0

# Ref name: the branch, or _detached/<worktree> when HEAD is detached (a detached
# worktree is itself the bad state we guard against — still worth snapshotting).
branch=$(git symbolic-ref --quiet --short HEAD 2>/dev/null) \
  || branch="_detached/$(basename "$top")"

# Build the snapshot in a SCRATCH index seeded from the real one, so the agent's
# actual index / staging area is never touched. write-tree / commit-tree do not
# modify the working tree, and we never move HEAD or the branch ref.
real_index=$(git rev-parse --git-path index)
tmp_index="${real_index}.wip.$$"
trap 'rm -f "$tmp_index"' EXIT
cp -p "$real_index" "$tmp_index" 2>/dev/null || :
GIT_INDEX_FILE="$tmp_index" git add -A 2>/dev/null
tree=$(GIT_INDEX_FILE="$tmp_index" git write-tree 2>/dev/null) || exit 0

# Skip if identical to HEAD's tree (e.g. only ignored churn slipped through).
head_tree=$(git rev-parse --quiet --verify 'HEAD^{tree}' 2>/dev/null || true)
[ -n "$head_tree" ] && [ "$tree" = "$head_tree" ] && exit 0

parent=$(git rev-parse --quiet --verify HEAD 2>/dev/null || true)
if [ -n "$parent" ]; then
  commit=$(git commit-tree "$tree" -p "$parent" -m "wip checkpoint (auto)" 2>/dev/null) || exit 0
else
  commit=$(git commit-tree "$tree" -m "wip checkpoint (auto)" 2>/dev/null) || exit 0
fi

git update-ref "refs/wip/$branch" "$commit" 2>/dev/null || exit 0
exit 0
