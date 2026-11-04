"""Bounded YouTube search for the local recording picker; no audio download."""
import json
import re
import subprocess
import sys
import threading

_slots = threading.BoundedSemaphore(2)


def search_recordings(query):
    query = str(query).strip()
    if not 1 <= len(query) <= 250:
        raise ValueError('Enter a search between 1 and 250 characters.')
    if not _slots.acquire(blocking=False):
        raise ValueError('Another search is running. Try again in a moment.')
    try:
        try:
            result = subprocess.run([
                sys.executable, '-m', 'yt_dlp', '--ignore-config', '--flat-playlist',
                '--dump-single-json', '--skip-download', '--no-warnings',
                '--socket-timeout', '10', '--retries', '0', '--extractor-retries', '0',
                '--', 'ytsearch8:'+query,
            ], capture_output=True, text=True, timeout=35)
        except subprocess.TimeoutExpired as error:
            raise ValueError('YouTube search took too long. Try again or paste a video link below.') from error
        if result.returncode:
            raise ValueError('YouTube search is unavailable right now. Try again or paste a video link below.')
        try:
            data = json.loads(result.stdout)
        except ValueError as error:
            raise ValueError('YouTube returned an unreadable search result. Try again.') from error
        videos = []
        for entry in data.get('entries', []) or []:
            if not entry or not re.fullmatch(r'[A-Za-z0-9_-]{11}', str(entry.get('id', ''))):
                continue
            if entry.get('is_live') or entry.get('live_status') in ('is_live', 'is_upcoming'):
                continue
            video_id = entry['id']
            length = entry.get('duration')
            videos.append({'id': video_id, 'title': str(entry.get('title') or 'Untitled video')[:300],
                           'channel': str(entry.get('channel') or entry.get('uploader') or '')[:150],
                           'duration': length if isinstance(length, (int, float)) and length > 0 else None,
                           'url': 'https://www.youtube.com/watch?v='+video_id,
                           'thumbnail': 'https://i.ytimg.com/vi/'+video_id+'/hqdefault.jpg'})
        return videos[:8]
    finally:
        _slots.release()
