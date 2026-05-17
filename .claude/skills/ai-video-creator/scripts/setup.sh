#!/usr/bin/env bash
# One-time setup for the ai-video-creator skill.
# Installs ffmpeg (if missing) and the edge-tts Python package.
# Safe to re-run.

set -euo pipefail

echo "[setup] checking ffmpeg..."
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[setup] ffmpeg not found; attempting install"
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y && sudo apt-get install -y ffmpeg
  elif command -v brew >/dev/null 2>&1; then
    brew install ffmpeg
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y ffmpeg
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -S --noconfirm ffmpeg
  else
    echo "[setup] could not auto-install ffmpeg. Install it manually and re-run." >&2
    exit 1
  fi
else
  echo "[setup] ffmpeg OK ($(ffmpeg -version | head -n1))"
fi

echo "[setup] installing python packages..."
PYTHON="${PYTHON:-python3}"
"$PYTHON" -m pip install --user --upgrade \
  "edge-tts>=6.1.9"

echo "[setup] done. You can now run:"
echo "  python3 .claude/skills/ai-video-creator/scripts/render.py work/<slug>/storyboard.json"
