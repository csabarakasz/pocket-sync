#!/bin/zsh
cd "${0:A:h}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! .venv/bin/python -c 'from importlib.metadata import version; assert version("spotdl") == "4.6.0" and version("spotapi") == "1.2.8"' >/dev/null 2>&1; then
  /bin/zsh scripts/setup_macos.sh || exit 1
fi
if curl --noproxy "*" --silent --max-time 2 http://127.0.0.1:8878/api/health | /usr/bin/grep -q 'pocket-sync'; then
  .venv/bin/python -m webbrowser http://127.0.0.1:8878
  exit 0
fi
.venv/bin/python -m playlist_sync.server
result=$?
read 'reply?Press Return to close.'
exit "$result"
