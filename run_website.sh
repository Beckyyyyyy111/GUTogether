#!/bin/bash
# Launches everything needed for the Gut Sound + HR/EDA Sync experiment:
#   1. GutSound-HR-EDA-Sync website backend  -> http://localhost:8000/
#   2. OpenGut-Cuda Software (waveform/spectrogram/annotation GUI)
#   3. HR-EDA-Time-Alignment's dual-emotibit-viewer
#
# River/TouchDesigner is intentionally NOT started here -- that's expected
# to already be open manually.
#
# Safe to re-run: skips anything that's already running instead of
# launching a duplicate.
#
# Usage (from the Bash tool or Git Bash): bash /d/AAAAAAAA/run_website.sh

ROOT="/d/AAAAAAAA"
GUTSOUND="$ROOT/GutSound-HR-EDA-Sync"
OPENGUT_SOFTWARE="$ROOT/OpenGut-Cuda/OpenGUT-main/OpenGUT-main/Software"
OPENGUT_ENV="$ROOT/OpenGut-Cuda/env"
HR_EDA="$ROOT/HR-EDA-Time-Alignment"

is_running() {
    ps -W | grep -i "$1" | grep -v grep > /dev/null 2>&1
}

# 1. Website backend
if is_running "GutSound-HR-EDA-Sync/.venv/Scripts/python"; then
    echo "[skip]  Website backend already running -> http://localhost:8000/"
else
    cd "$GUTSOUND/website/backend" || exit 1
    "$GUTSOUND/.venv/Scripts/python.exe" -m uvicorn server:app --port 8000 > server.log 2>&1 &
    echo "[start] Website backend (pid $!) -> http://localhost:8000/"
fi

# 2. OpenGut-Cuda Software GUI
if is_running "OpenGut-Cuda/env/Scripts/python"; then
    echo "[skip]  OpenGut-Cuda Software already running"
else
    cd "$OPENGUT_SOFTWARE" || exit 1
    "$OPENGUT_ENV/Scripts/python.exe" main.py > "$GUTSOUND/opengut_software.log" 2>&1 &
    echo "[start] OpenGut-Cuda Software (pid $!)"
fi

# 3. dual-emotibit-viewer
if is_running "dual-emotibit-viewer"; then
    echo "[skip]  dual-emotibit-viewer already running"
else
    cd "$HR_EDA" || exit 1
    "$HR_EDA/.venv/Scripts/dual-emotibit-viewer.exe" > "$GUTSOUND/dual_emotibit_viewer.log" 2>&1 &
    echo "[start] dual-emotibit-viewer (pid $!)"
fi

echo ""
echo "Done. (River/TouchDesigner intentionally skipped -- open that yourself.)"
