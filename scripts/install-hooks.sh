#!/bin/sh
# install-hooks.sh - point git at the tracked hook directory (.githooks), POSIX side.
#
# install-hooks.bat does this on Windows; this is the same step for everyone else,
# plus the one thing the batch file cannot do: **make the hooks executable**.
#
# Why the second half matters (S3#6): git only runs a hook whose file has the
# execute bit set (POSIX: `stat` + `access(X_OK)`; a hook that is not executable
# is skipped **silently** — no warning, no failure, the commit just goes out
# unguarded). The index had the three hooks at mode 100644, so a clone on POSIX
# got three inert files and `core.hooksPath` pointing at them. `git update-index
# --chmod=+x` fixes the index (done in the repository); this script fixes the
# checkout, and says so if the clone is still stale.
#
# What it does, in order:
#   1. checks this is a git checkout with the tracked hooks present;
#   2. sets core.hooksPath = .githooks (this repository's local config);
#   3. chmod +x the hooks (the whole fallback: on a clone that checked them out
#      0644 they are dead until this runs);
#   4. reports a legacy .git/hooks/pre-commit — the bare copy the tracked hooks
#      replaced. It is inert while core.hooksPath is set, so it is named, not
#      deleted: removing files is the owner's call, and on POSIX there is no
#      recycle bin to be careful with.
#
# Idempotent: run it twice.
set -eu

root=$(git rev-parse --show-toplevel)
cd "$root"

if [ ! -f pyproject.toml ]; then
    echo "install-hooks.sh: pyproject.toml is not here ($root) - wrong directory?" >&2
    exit 1
fi

if [ ! -f .githooks/pre-commit ]; then
    echo "install-hooks.sh: .githooks/pre-commit is missing - the tracked hooks are not" >&2
    echo "                 here, so pointing git at .githooks would disable the guards." >&2
    exit 1
fi

git config core.hooksPath .githooks
echo "[1/3] core.hooksPath = $(git config core.hooksPath)"

echo "[2/3] chmod +x .githooks/{pre-commit,commit-msg,pre-push,_python.sh}"
chmod +x .githooks/pre-commit .githooks/commit-msg .githooks/pre-push .githooks/_python.sh

# The index is the durable half: a mode that only exists in this working tree is
# lost on the next `git checkout` of the same path.
if [ "$(git ls-files -s .githooks/pre-push | cut -d' ' -f1)" != "100755" ]; then
    echo "install-hooks.sh: [warn] the index still records the hooks as 100644, so a fresh" >&2
    echo "                 checkout loses the bit again. Fix it once, and commit it:" >&2
    echo "                 git update-index --chmod=+x .githooks/pre-commit .githooks/commit-msg .githooks/pre-push" >&2
fi

echo "[3/3] legacy hook check"
legacy=.git/hooks/pre-commit
if [ -f "$legacy" ]; then
    echo "      [keep] $legacy is present. It is inert while core.hooksPath is set;"
    echo "             delete it yourself if it was the old copy of this guard."
else
    echo "      no legacy hook at $legacy - nothing to do."
fi

echo
echo "done. Commits and pushes are now scanned by:"
echo "  .githooks/pre-commit   staged content + sensitive words"
echo "  .githooks/commit-msg   the commit message"
echo "  .githooks/pre-push     outgoing commit messages + diff"
echo "Uninstall: git config --unset core.hooksPath"
