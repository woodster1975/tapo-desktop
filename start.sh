#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python run.py "$@"
fi
if [[ -x ../tapo-poc/.venv/bin/python ]]; then
  exec ../tapo-poc/.venv/bin/python run.py "$@"
fi
if [[ ! -x .venv/bin/python ]]; then
  printf 'Run bash setup.sh first.\n' >&2
  exit 1
fi
