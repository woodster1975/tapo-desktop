#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
python_bin="${1:-python3}"
"$python_bin" -c 'import sys; sys.exit("Tapo Desk requires Python 3.11 or newer; choose an installed newer interpreter, e.g. bash setup.sh python3.12") if sys.version_info < (3, 11) else None'
"$python_bin" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
printf '\nReady. Run ./start.sh\n'
