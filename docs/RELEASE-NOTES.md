# Pocket Sync updates

## 1.1.0 — source update (November 22, 2026)

- Faster repeat playlist checks: cached Spotify details, a persistent local tag index, indexed comparisons, and less repeated scanning. Playlist membership is still read fresh; older track details are refreshed before downloading.
- A manual-matching queue with Back, Skip, saved choices, review/edit, and one batch download.
- Playable YouTube search thumbnails inside the app, with playback controls. Previewing does not select or download a recording. Some videos disallow embedded playback.
- A consistent 20-second duration tolerance for automatic and manual recordings, with duration warnings before selection.
- **Unnumbered filenames remain the default:** `Artist - Title.mp3`. Optional numbering is explicitly enabled per destination under **Help & settings → Song filenames**. Choose 1–6 digits, review affected names, and apply. Changing padding retains ordinal numbers; turning numbering off affects future additions only.
- An append-maintained M3U8 playback playlist, stronger FAT Unicode rename handling, saved-reference updates and rollback records for numbering changes.
- Clean app-icon packaging and explicit initial WebKit sizing for reliable window rendering.

Validated with 65 backend tests, matching/settings DOM regressions, a native macOS build, and native settings interaction checks. This update publishes source on `main`; it does not publish a new tagged release or bundled/notarized Mac ZIP. See [installation](../README.md#install-from-source) and the [release checklist](../RELEASING.md).

## Initial source preview

Pocket Sync introduced playlist/folder comparison, manual recording selection, ordered YouTube playlist imports, per-library history, and in-app walkthroughs. The screenshot gallery illustrates that earlier interface; current workflows are documented in the [user guide](../POCKET-SYNC.md).
