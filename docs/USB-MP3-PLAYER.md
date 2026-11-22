# Sync a Spotify playlist to a USB MP3 player on macOS

Use Pocket Sync to check what’s already on a player and add only the tracks you select. This example uses the fictional **Weekend Mix** playlist.

1. Connect your MP3 player and check that it appears as a drive in Finder. Open Pocket Sync and paste the public Spotify playlist link.
2. Choose the player's music folder as the destination. Click **Check for new songs**. Playlist membership is fetched fresh; cached track details and unchanged local file tags speed up repeat checks.
3. Read the comparison. **In folder** shows recognized files, **Review** shows uncertain matches, and **To add** shows tracks the app can add. The example shows two already present, one to review, and four to add.

![Pocket Sync showing the Weekend Mix playlist comparison and how many tracks are present, missing, or need review](screenshots/playlist.png)

4. In **To add**, select a track and sync it. Pocket Sync can copy a matching file you already have or look for a matching YouTube recording. If it needs your help, use **Choose recording…** and compare the artist, version, and duration. Click **Preview** on a result thumbnail to listen inside the app before selecting it. Downloads must be within 20 seconds of Spotify’s duration; longer versions or compilations can still be rejected. Use audio you’re authorized to download.

![Recording picker showing an example studio recording and two alternate versions](screenshots/recording.png)

5. If several recordings need manual matching, choose **Match remaining songs…**. Select **Save match & next**, use **Back** or **Skip** as needed, then **Review matches → Download matched songs**. Saved choices are drafts until the audio downloads and passes verification.
6. Filenames default to **Artist - Title.mp3**, without numbers. If the player sorts filenames and you want new additions last, explicitly enable numbering in **Help & settings → Song filenames**, choose 1–6 digits, review the filename changes, and apply. The setting belongs to that destination. Disabling it affects future additions only. Players using tags or their own database may sort differently.
7. Open **Sync history** to see which files were added and which need attention. Eject the player in Finder when the sync is complete.

[Install Pocket Sync from source](../README.md#install-from-source) · [Read the full user guide](../POCKET-SYNC.md)

The images above illustrate the earlier interface and do not show the new batch queue, inline player, or naming controls. For current controls and limitations, use the [user guide](../POCKET-SYNC.md).
