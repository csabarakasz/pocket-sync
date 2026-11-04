# Privacy and local storage

Pocket Sync serves its interface on the local loopback address. It has no hosted account or app analytics. When you check a playlist, search for a recording, or import audio, Spotify and YouTube receive the relevant links or search queries. The browser may fetch cover images and thumbnails from those services. See their privacy policies for how they handle requests.

The app keeps destination paths, saved libraries, match decisions, history, and logs on your Mac. Depending on how you installed it, look under `.runtime/playlist-sync/` in the source folder or `~/Library/Application Support/Pocket Sync/` for the packaged app. spotDL can maintain its own cache and configuration. Downloaded files can contain source metadata.

Public bug reports can be read by anyone. Remove private playlist links, local paths, identifiers, and credentials before posting screenshots or logs.
