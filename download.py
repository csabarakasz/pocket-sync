#!/usr/bin/env python3
"""Local Spotify-link downloader with an explicit metadata audit."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime
from urllib.parse import urlparse

DURATION_TOLERANCE = 20

ROOT = Path(__file__).resolve().parent


def spotify_link(value):
    value = value.strip()
    uri = re.fullmatch(r'spotify:(track|album|playlist):([A-Za-z0-9]{22})', value)
    if uri:
        return f'https://open.spotify.com/{uri[1]}/{uri[2]}'
    parsed = urlparse(value)
    if parsed.scheme != 'https' or parsed.hostname != 'open.spotify.com':
        raise argparse.ArgumentTypeError('Use a full https://open.spotify.com track, album, or playlist link.')
    match = re.fullmatch(r'/(?:intl-[a-z]{2}/)?(track|album|playlist)/([A-Za-z0-9]{22})/?', parsed.path)
    if not match:
        raise argparse.ArgumentTypeError('Expected a Spotify track, album, or playlist link.')
    return f'https://open.spotify.com/{match[1]}/{match[2]}'


def audit(folder, songs, files=None):
    from mutagen.mp3 import MP3
    results = []
    for song in songs:
        track_id = song['song_id']
        candidates = [Path(files[track_id])] if files and track_id in files else [p for p in folder.glob('*.mp3') if p.stem.endswith(f'[{track_id}]')]
        if not candidates:
            # Clean filenames retain identity in spotDL's embedded source URL.
            expected_url = f'https://open.spotify.com/track/{track_id}'
            for path in folder.glob('*.mp3'):
                try:
                    tags = MP3(path).tags
                    if tags and str(tags.get('WOAS', '')).rstrip('/') == expected_url:
                        candidates.append(path)
                except Exception:
                    continue
        issues = []
        if not candidates:
            issues.append('Audio file missing')
        else:
            try:
                audio = MP3(candidates[0])
                tags = audio.tags
                for key, label in [('TIT2', 'title'), ('TPE1', 'artist'), ('TALB', 'album'), ('TRCK', 'track number'), ('TDRC', 'release date')]:
                    if not tags or not tags.get(key) or not str(tags.get(key)).strip():
                        issues.append(f'Missing {label}')
                if not tags or not any(frame.data for frame in tags.getall('APIC')):
                    issues.append('Missing embedded cover art')
                if tags and str(tags.get('TIT2', '')) != song['name']:
                    issues.append('Title differs from Spotify metadata')
                if tags and str(tags.get('TALB', '')) != song.get('album_name', ''):
                    issues.append('Album differs from Spotify metadata')
                if tags and any(artist not in str(tags.get('TPE1', '')) for artist in song['artists']):
                    issues.append('Artist differs from Spotify metadata')
                if audio.info.length <= 0:
                    issues.append('Empty audio')
                if abs(audio.info.length - song.get('duration', audio.info.length)) > DURATION_TOLERANCE:
                    issues.append('Duration differs by more than 20 seconds; check recording version')
            except Exception as error:
                issues.append(f'Cannot read audio: {error}')
        results.append({'title': song['name'], 'artists': song['artists'], 'spotify_url': song.get('url'), 'file': str(candidates[0]) if candidates else None, 'issues': issues})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('links', nargs='*', type=spotify_link)
    parser.add_argument('--output', type=Path, default=ROOT / 'Downloads')
    parser.add_argument('--verify', type=Path, help='Recheck a previous download folder')
    args = parser.parse_args()
    if args.verify:
        folder = args.verify.resolve()
        songs = json.loads((folder / 'tracks.spotdl').read_text())
        return report(folder, songs)
    links = args.links
    if not links:
        try:
            links = [spotify_link(input('Paste a Spotify song, album, or playlist link: '))]
        except argparse.ArgumentTypeError as error:
            parser.error(str(error))
    if not shutil.which('ffmpeg'):
        parser.error('FFmpeg is required. Install with: brew install ffmpeg')
    folder = args.output.expanduser().resolve() / datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f')
    folder.mkdir(parents=True)
    env = os.environ.copy()
    command = [sys.executable, '-m', 'spotdl']
    manifest = folder / 'tracks.spotdl'
    print(f'Files and reports: {folder}', flush=True)
    with (folder / 'download.log').open('w') as log:
        def run(arguments):
            process = subprocess.Popen(command + arguments, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            try:
                for line in process.stdout:
                    print(line, end='', flush=True)
                    log.write(line)
                    log.flush()
                return process.wait()
            except KeyboardInterrupt:
                process.terminate()
                process.wait()
                raise
        if run(['save', *links, '--save-file', str(manifest)]) or not manifest.exists():
            print('Could not read Spotify metadata. See download.log. No successful download is claimed.')
            return 1
        songs = json.loads(manifest.read_text())
        if not songs:
            print('Spotify returned no tracks. The playlist may be private or unavailable.')
            return 1
        code = run(['download', str(manifest), '--format', 'mp3', '--bitrate', '128k', '--threads', '2', '--simple-tui', '--output', str(folder / '{artists} - {title}.{output-ext}'), '--save-errors', str(folder / 'errors.txt')])
    return max(bool(code), report(folder, songs))


def report(folder, songs):
    results = audit(folder, songs)
    (folder / 'report.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    failed = sum(bool(row['issues']) for row in results)
    print(f'Checked {len(results)} tracks: {len(results)-failed} passed, {failed} need attention.')
    for row in results:
        if row['issues']:
            print(f"  {row['title']}: {'; '.join(row['issues'])}")
    print(f'Report: {folder / "report.json"}')
    return int(bool(failed) or not results)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\nStopped. Completed files remain in the download folder.')
        raise SystemExit(130)
