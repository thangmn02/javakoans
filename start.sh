#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ -x ".venv/bin/python" ]; then
    exec ".venv/bin/python" koan.py "$@"
fi
python3 -c "import textual" >/dev/null 2>&1 || python3 -m pip install -r requirements.txt
exec python3 koan.py "$@"
