# Contributing to Pocket Sync

Use [GitHub Issues](https://github.com/csabarakasz/pocket-sync/issues/new/choose) for bugs and feature requests. Include your macOS version and chip, the workflow you tried, and what you expected. Use fictional examples when possible and redact private paths and playlist links from logs and screenshots.

For a proposed change, describe it in an issue first. Set up the app from source using the README and run the tests:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Tests generate audio locally with FFmpeg and simulate service responses. Node.js enables the browser selection test. When changing a dialog, also try it in a compact window and verify keyboard focus and scrolling.
