#!/usr/bin/env bash
# Commit the given paths and push to main, retrying if another job pushed first.
# usage: scripts/git_push.sh "commit message" path [path...]
# Paths that do not exist (and were never tracked) are skipped, e.g. data/private.enc before the
# first /start, so a quiet first run does not fail.
set -euo pipefail

msg="$1"
shift

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

paths=()
for p in "$@"; do
  if [ -e "$p" ] || git ls-files --error-unmatch -- "$p" >/dev/null 2>&1; then
    paths+=("$p")
  fi
done
if [ "${#paths[@]}" -eq 0 ]; then
  echo "nothing to commit"
  exit 0
fi

git add -A -- "${paths[@]}"
if git diff --cached --quiet; then
  echo "nothing to commit"
  exit 0
fi
git commit -q -m "$msg"

for i in 1 2 3 4; do
  if git pull --rebase -q origin main && git push -q origin HEAD:main; then
    echo "pushed"
    exit 0
  fi
  git rebase --abort 2>/dev/null || true
  sleep $((i * 3))
done
echo "push failed after retries"
exit 1
