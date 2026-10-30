#!/bin/sh
# AdvPrint Pro - LIVE TEST (A-to-Z self-check)
# by Bit Dream IT - Innovative Healthcare Solutions
# usage: advprint-livetest.sh [print]   ("print" also queues a real test page)
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$DIR/hub/advprint.py" livetest "$@"
