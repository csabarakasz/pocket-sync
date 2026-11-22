# Contributing to Pocket Sync

Use [GitHub Issues](https://github.com/csabarakasz/pocket-sync/issues/new/choose) for bugs and feature requests. Include your macOS version and chip, the workflow you tried, and what you expected. Use fictional examples when possible and redact private paths and playlist links from logs and screenshots.

For a proposed change, describe it in an issue first. Set up the app from source using the README and run the tests:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Tests generate audio locally with FFmpeg and simulate service responses. Node.js enables the browser selection test. When changing a dialog, also try it in a compact window and verify keyboard focus and scrolling.


## Matching and settings UI tests

The separate DOM suite checks the nine-song matching queue, preview cleanup, batch submission, stale comparisons, default-off numbering, padding controls and enabling/disabling. It uses disposable fixture data and does not download audio or write to a connected player.

Start the fixture in one terminal:

```sh
.venv/bin/python -B scripts/ui_fixture.py
```

In a second terminal, from the project root:

```sh
npm install --prefix /tmp/pocket-sync-ui-test jsdom@31.0.1 --no-audit --no-fund
node tests/test_matching_ui.cjs
```

This pinned jsdom release requires Node 22.22.2+ (22.x), 24.15.0+ (24.x), or 26+. If installed elsewhere, set `JSDOM_PATH` to the jsdom package directory. Stop the fixture with Control+C after testing. For native checks, build the app and launch its executable with `POCKET_SYNC_TEST_URL=http://127.0.0.1:8891/`; this points only that launch at the fixture. Verify settings with numbering off, enable it and change the digit count, then review/apply. Test inline YouTube playback in the native app as well as the DOM behavior.
