# Pocket Sync

A local browser app for adding Spotify playlist songs to a music folder or mounted MP3 player. Nothing is uploaded. Playlist metadata comes from Spotify; audio is matched on YouTube using spotDL. Use it for music you have permission to download.

## Open it

Open **Pocket Sync.app** from Applications or your Desktop. The app opens in its own Mac window. The local server runs in the background, so a sync can continue after you close the window. Open the app again to return to it.

If you installed [from source](README.md), setup creates `.runtime/Pocket Sync.app`. You can also open **Open Pocket Sync.command** for browser access. Keep its Terminal window open while using that launcher. Rebuild the source app after moving the project folder.

Choose a saved playlist under **Your Library**. Each library remembers its name, Spotify link, destination folder, and sync history. The app reopens the last selected library.

## Your libraries and folders

**Add playlist** saves another playlist. Give it a name, paste its Spotify playlist link, and choose a destination. You can leave the destination blank and choose it later. **Library settings** changes the selected library's name, link, or folder.

Click the **Music folder or MP3 player** field or its folder button to open the macOS folder chooser. Select an existing folder, create a new one with **New Folder**, or choose a folder on a mounted player. Cancel keeps the previous destination. **Enter path manually** remains available when needed.

Switch playlists by clicking their names in the sidebar. The chevron expands or collapses each library's sync history and three most recent runs. Comparisons stay available while switching during the same app session; changing the playlist or destination requires another check. Library changes are disabled while checking, syncing, or choosing a folder.

## Each time you add music

1. Add songs to the Spotify playlist.
2. Select the library you want to update. Connect the MP3 player if you want to sync directly to it, then click the destination field and select its music folder. Leave the library's Mac folder selected to update that instead.
3. Click **Check for new songs**. This reads the current Spotify playlist and scans the destination, including subfolders.
4. Review **To add**, **Review**, and **In folder**. **Other files** shows files outside the playlist; they are kept.
5. In **To add**, uncheck any songs you want to leave out of this round. **Select all to add** selects every missing song, including those hidden by search; **Clear selection** lets you build a batch from scratch. Click **Sync N selected songs**, or **Add song** for an individual track. Selection survives page refreshes during this comparison and resets for a new comparison, library, or destination. Leave the player plugged in until the sync finishes, then eject it normally in Finder.

Sync only updates the selected folder. If you select the folder on your Mac, copy the resulting music to the MP3 player yourself; selecting the mounted player's folder writes to it directly. The player must appear as a normal mounted disk in Finder. The app does not control MTP-only devices.

## Custom audio without Spotify

Choose **Custom audio** in the sidebar, then **Add from YouTube…**. Paste a YouTube video or playlist link and choose a destination folder or mounted MP3 player. **Read link** previews the parts; edit the title, author/artist, and album/book before clicking **Add to folder**. A playlist is joined into one MP3 in playlist order. Cover art comes from YouTube's thumbnail. No Spotify link or comparison is required.

Imports store their source identity inside the MP3 and keep a local master for copying to other destinations. Reimporting the same recording checks the destination (including subfolders) first, even if its file was renamed. A matching local recording is copied rather than downloaded. Previously combined Spotify-linked stories are recognized too. Other files are preserved and appear under **Other files** when checking a Spotify library; managed custom files are labeled there.

The Custom audio area lists saved imports and their locations, with **Copy to folder…** and **Import history**. If a source playlist changes its parts or their order, it is treated as a different recording. Metadata for custom audio is reviewed by you; no release date is invented when YouTube supplies none.

## Combining stories split into parts

After checking the destination, click **Combine YouTube parts…**. Paste a YouTube playlist link (a video link containing `list=` also works), then click **Read playlist**. The app shows every YouTube part in playlist order and suggests Spotify tracks with the same story title. Check the exact Spotify tracks covered, edit the combined title if needed, and confirm that the recording covers those tracks even when the splits or durations differ.

**Combine and add to folder** downloads all playlist parts, checks each one, joins them into one MP3, embeds cover art and tags from the first selected Spotify track, and copies the completed file to the destination. No Spotify tracks are marked covered if a part, artwork, combination, or copy fails. Existing files are preserved.

The MP3 itself stores the confirmed Spotify track IDs. A folder check recognizes all those tracks as **Combined file**, including after restarting or copying the MP3 to another folder. The app keeps a verified master on the Mac for later copying, and ordinary sync reuses it once even if several covered tracks are selected. Sync history records one file and all tracks it covers. Changing the combined file's length or removing its coverage tags requires a new confirmation.

## Recognizing existing songs

The app reads audio tags and checks files are readable. It uses an embedded Spotify track ID or the ID in filenames first. Otherwise, it matches title and artist tags plus duration (within ten seconds). Accents, punctuation, case, and the YouTube `- Topic` artist suffix are normalized. A file cannot automatically match two different Spotify track IDs.

Filename-only matches, conflicting artist tags, unreadable audio, and materially different durations go to **Review**. Choose **Use this file** if it really is the recording you want, or **Download a separate copy**. Confirmed matches are remembered for that folder while the file's size and modification time stay the same. Existing songs are not retagged or repaired.

## Sync history

Open **Sync history** in the sidebar or **View sync history** above the playlist controls. Each run records its start/finish time, selected folder, requested songs, and individual outcomes:

- **Added & verified**: audio, artwork, and tags passed checks and the file was copied. The exact saved filename is listed.
- **Already present**: the song appeared in the folder before copying; no duplicate was added.
- **Failed**: no verified file was copied for that attempt. The actual reason and a saved technical log are available.
- **Stopped / Not attempted / Interrupted**: the run did not finish those songs. Completed songs stay recorded as completed.

History persists after restarting the app. Previous sync reports are imported; older records identify information that was not recorded at the time. Filename cleanup is reflected in the imported saved-file paths. History describes what happened during each attempt; a later folder check separately shows whether the song is currently present.

By default, history shows the selected library, including its earlier destinations. **Show all libraries** includes other playlists. The most recent 100 runs are displayed; older records stay on disk.

A working **Spotify page** link does not guarantee an automatic YouTube audio match. For **Automatic matching could not find a suitable YouTube recording**, use **Choose recording…** to search inside the app. The overlay shows up to eight recordings with thumbnails, channels, and durations. Click a result to fill its video link, then click **Download this recording**. You can edit the search or paste a link manually. Results with materially different durations are marked for attention. Duration, cover art, and tag checks still apply. A successful chosen recording is remembered for later syncs, including when you select another destination. You can choose a different recording if a source later becomes unavailable.

## Downloads and checks

Before downloading, the app looks for the track in previously selected music folders and files recorded in sync history. These locations are remembered after restarting and after changing the destination to your MP3 player. It also recognizes existing MP3s in those folders by Spotify identity or matching title, artist, and duration.

Reusable tracks show **Copy song** and their source path. Sync copies the original MP3 without re-encoding, preserving artwork and tags. Both the source and staged copy must pass the audio, album, title, artist, artwork, and duration checks. History identifies **Copied locally & verified**, the original file, and the destination. If a source was deleted, disconnected, changed, or fails verification, the app downloads instead. Keep the original Mac music folder available when syncing the player. **Choose recording…** deliberately downloads the newly selected recording.

Downloads happen in a staging folder on the Mac, independently of the browser page. Every new MP3 is checked for readable audio, title, artist, album, release date, track number, embedded cover art, and duration before it is copied to the selected folder. A file that fails stays out of the destination and is reported for retry. Only verified tracks appear as present after a sync.

Filenames use `Artist - Title.mp3`, without a Spotify ID suffix. The track ID stays in the embedded source URL so future syncs still recognize the song. Separate tracks with the same filename get a simple `(2)`, `(3)`, etc. suffix without overwriting existing files.

Output is MP3 at 128 kbps with album cover art inside the file. Metadata available from Spotify also includes album artist, disc number, and ISRC; optional fields such as genre may be absent. Re-encoding at a higher bitrate would not improve the source audio. Automatic matching cannot prove that two recordings are acoustically identical, so listen to unfamiliar matches.

No deletion or replacement of existing music is performed. Tracks removed from Spotify remain in the folder. A repeat sync rescans the folder and skips tracks already present. Disconnecting/replacing the destination stops copying; the app does not recreate a missing player folder. Files appear under their finished names only after the copy has been flushed. Other applications should avoid writing to the same folder during a sync.

## Troubleshooting

- **Folder unavailable:** reconnect the player or choose an existing folder. You can create a destination explicitly with **New Folder** in the chooser; the app does not recreate disconnected player folders.
- **Folder chooser unavailable:** use **Enter path manually**. On macOS, the chooser is a small local helper compiled on first use with the installed Swift command-line tools; no extra Python package is needed.
- **Spotify error:** the playlist must be public. Retry **Check for new songs**. The app verifies the complete listing and retries transient Spotify failures; it does not silently accept a partial list.
- **Failed download or metadata check:** expand **Activity & download details**. Retry the individual track using **Add song**. Other tracks can finish independently.
- **Wrong version:** use the review information and listen before transferring. Existing files are preserved.
- **File already exists:** a conflicting filename was preserved. Review that file in Finder before deciding what to do with it.
- **Connection to local app lost:** reopen the launcher or keep its Terminal window open. Refreshing/closing the browser does not cancel a job while the server is running.

Public Spotify/YouTube access can change or be rate-limited. The app uses the installed spotDL 4.6.0 and its dependencies. It does not collect Spotify passwords or browser cookies. Spotify membership is read afresh on every comparison; track metadata is cached for seven days to avoid fetching the same album details repeatedly.

## Files and verification

The downloaded app stores libraries, settings, confirmed matches, metadata cache, and per-job logs in `~/Library/Application Support/Pocket Sync/`. The source install stores its separate data in `.runtime/playlist-sync/`. Both locations contain a `desktop-launcher.log` with startup details.

Run from the project folder:

```sh
.venv/bin/python -m playlist_sync.server
.venv/bin/python -m unittest discover -s tests -v
```

The tests use generated audio and cover matching, artwork checks, preservation of existing files, repeated sync, changed or disconnected destinations, and local HTTP request guards. Physical MP3 player compatibility depends on its filesystem, character support, and artwork display.
