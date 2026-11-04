#!/bin/zsh
set -e

cd "${0:A:h}/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if ! command -v ffmpeg >/dev/null; then
  echo 'FFmpeg is required. Install it with brew install ffmpeg, then run setup again.' >&2
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  python=python3.14
  if ! command -v "$python" >/dev/null; then
    python=python3
  fi
  if ! "$python" -c 'import sys; sys.exit(not ((3, 11) <= sys.version_info[:2] < (3, 16)))' 2>/dev/null; then
    echo 'Install Python 3.14 with brew install python@3.14, then run setup again.' >&2
    exit 1
  fi
  "$python" -m venv .venv
fi

.venv/bin/python -m pip install -r requirements.txt

if ! command -v deno >/dev/null && [[ ! -x ~/.spotdl/deno ]]; then
  echo 'Install Deno with brew install deno before downloading from YouTube.'
fi
if ! xcode-select -p >/dev/null 2>&1; then
  echo 'Python setup is complete. To build the desktop app, run xcode-select --install, then rerun setup.'
  echo 'For browser access now, run .venv/bin/python -m playlist_sync.server.'
  exit 0
fi

.venv/bin/python scripts/build_desktop_app.py
echo 'Open .runtime/Pocket Sync.app in Finder.'
