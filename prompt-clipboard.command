#!/bin/bash
# Double-click in Finder to run from source (no .app needed).
cd "$(dirname "$0")" || exit 1
exec python3 prompt_clipboard.py
