#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

/usr/bin/env python3 "$SCRIPT_DIR/makerworld_receiver.py" "$@"
