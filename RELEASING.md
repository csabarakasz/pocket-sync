# Publishing Pocket Sync

The initial GitHub publication is a source preview. The source tree and screenshots can be browsed in the repository. GitHub creates its own source archives for each tagged release.

## Repository setup

- Use the README as the entry point. The screenshot gallery shows the actual app with fictional data.
- Set topics such as `macos`, `mp3`, `playlist`, `python`, and `swift`.
- Keep Issues enabled so visitors can use the bug report and feature request templates.
- To set the repository’s social card, open **Settings → General → Social preview** and upload `docs/screenshots/social-preview.png`.
- Keep virtual environments, app bundles, downloads, logs, signing material, and local state out of Git.

## Mac ZIP checklist

1. Confirm the project license and review the redistribution requirements of the exact dependencies in the bundle. The current dependency set includes GPL-licensed Mutagen and Unidecode. Review the source and notice requirements before uploading a binary. Also review the platform terms for the intended use of Spotify and YouTube.
2. Build from the commit you will tag, on Apple silicon with the Xcode developer tools and uv installed:

   ```sh
   python3 scripts/build_desktop_app.py --release
   ```

3. Sign the app and embedded code with Developer ID Application and hardened runtime. Submit this exact build to Apple, staple its ticket, and verify the re-extracted ZIP. An earlier build’s acceptance applies to that build.
4. Test first launch in a fresh macOS user account, including the folder chooser, tool setup, and walkthrough. Record the tested OS and architecture in the release notes.
5. Add the final ZIP and its SHA-256 checksum to the GitHub Release assets. Keep source ZIPs and app ZIPs clearly distinguished in the release notes.

## References

- [GitHub README guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes)
- [GitHub releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)
- [GitHub social preview guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview)
- [Apple notarization and packaging](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
- [GNU GPL distribution FAQ](https://www.gnu.org/licenses/gpl-faq.en.html#UnchangedJustBinary)
- [Spotify Developer Terms](https://developer.spotify.com/terms) and [YouTube Terms of Service](https://www.youtube.com/t/terms)
