#!/bin/zsh
cd "${0:A:h}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! .venv/bin/python -c 'from importlib.metadata import version; assert version("spotdl") == "4.6.0" and version("spotapi") == "1.2.8"' >/dev/null 2>&1; then
  /bin/zsh scripts/setup_macos.sh || exit 1
fi
if lsof -nP -iTCP:8801 -sTCP:LISTEN >/dev/null 2>&1; then
  echo 'Port 8801 is already in use. Stop the other server before opening spotDL.'
  read 'reply?Press Return to close.'
  exit 0
fi
.venv/bin/python scripts/fix_spotdl_web.py || exit 1
.venv/bin/spotdl web --audio youtube --lyrics --yt-dlp-args "--flat-playlist --socket-timeout 20 --retries 1 --extractor-retries 1" --host 127.0.0.1 --port 8801 --keep-alive --web-use-output-dir --output 'Downloads/{artists} - {title}.{output-ext}'
result=$?
read 'reply?Press Return to close.'
exit "$result"
