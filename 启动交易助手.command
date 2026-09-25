#!/bin/zsh
set -e
P03_PROJECT_DIR="${0:A:h}"
cd "$P03_PROJECT_DIR"
exec python3 "$P03_PROJECT_DIR/src/trade.py" serve
