#!/bin/zsh
cd "${0:A:h}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! .venv/bin/python -c 'from importlib.metadata import version; assert version("spotdl") == "4.6.0" and version("spotapi") == "1.2.8"' >/dev/null 2>&1; then
  /bin/zsh scripts/setup_macos.sh || exit 1
fi
.venv/bin/python download.py "$@"
result=$?
echo ""
read 'reply?Press Return to close.'
exit "$result"
