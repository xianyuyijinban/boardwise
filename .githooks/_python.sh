#!/bin/sh
# Sourced by the hooks next to this file: find a python that **actually runs**.
#
# Not `command -v python3 || command -v python`: on Windows that finds the
# Microsoft Store's `python3` stub under AppData\Local\Microsoft\WindowsApps,
# which reports success to `command -v`, accepts the call, and exits 49 printing
# nothing — a hook that appears to run and guards nothing (measured; the
# pre-commit hook failed exactly that way in 193's own test). Each candidate is
# therefore executed once with `-c ""` before it is believed.
#
# Sets `$py`. Exits 1 (refusing the commit or the push) when there is no usable
# interpreter: a secrecy gate that did not run has not checked anything, and
# "it printed nothing, so I committed" is the failure mode.
#
# `$root` must be set by the caller (git rev-parse --show-toplevel).

py=""
for candidate in "$root/.venv/Scripts/python.exe" python python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "" >/dev/null 2>&1; then
        py=$candidate
        break
    fi
done

if [ -z "$py" ]; then
    echo "repo hygiene: no python found (.venv and PATH both failed); refusing rather than committing or pushing unscanned" >&2
    exit 1
fi
