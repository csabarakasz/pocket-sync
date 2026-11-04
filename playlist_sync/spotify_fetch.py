"""Read a fresh, complete playlist; cache stable track metadata between checks."""
import json
import sys
import time
from pathlib import Path
import spotapi
from spotdl.types.song import Song
from spotdl.utils.config import DEFAULT_CONFIG
from spotdl.utils.spotify import SpotifyClient


def retry(function):
    for attempt in range(3):
        try:
            return function()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1+attempt)


def fetch(url, cache_path):
    SpotifyClient.init(DEFAULT_CONFIG['client_id'], DEFAULT_CONFIG['client_secret'], no_cache=True)
    # Reuse the same public-playlist client for the first page and pagination.
    # SpotipyFree otherwise constructs a new token session for each operation.
    def first_page():
        client = spotapi.PublicPlaylist(url)
        return client, client.get_playlist_info(limit=343)['data']['playlistV2']
    client, playlist = retry(first_page)
    expected = playlist['content']['totalCount']
    items = list(playlist['content']['items'])
    while len(items) < expected:
        offset = len(items)
        page = retry(lambda: client.get_playlist_info(limit=343, offset=offset)['data']['playlistV2']['content'])
        if not page['items']:
            raise ValueError('Spotify returned an incomplete playlist. Please check again.')
        items.extend(page['items'])
    if len(items) != expected:
        raise ValueError(f'Incomplete Spotify response: {len(items)} of {expected} entries.')
    try:
        cache = json.loads(cache_path.read_text())
    except (OSError, ValueError):
        cache = {}
    songs, skipped = [], []
    print(f"Reading {expected} entries from {playlist['name']}", flush=True)
    print(f'Playlist metadata progress: 0/{expected}', flush=True)
    for pos, item in enumerate(items, 1):
        raw = (item.get('itemV3') or {}).get('data') or (item.get('itemV2') or {}).get('data') or {}
        uri = raw.get('uri', '')
        if not uri.startswith('spotify:track:'):
            skipped.append({'position': pos, 'name': raw.get('name') or f'Entry {pos}', 'reason': 'Local, unavailable, or non-music entry'})
            print(f'Playlist metadata progress: {pos}/{expected}', flush=True)
            continue
        sid = uri.split(':')[-1]
        cached = cache.get(sid, {})
        if cached and time.time()-cached.get('fetched_at', 0) < 7*86400:
            song = dict(cached['song'])
        else:
            print(f'Fetching track metadata {pos}/{expected}', flush=True)
            song = retry(lambda: Song.from_url(f'https://open.spotify.com/track/{sid}').json)
            cache[sid] = {'fetched_at': time.time(), 'song': song}
            tmp = cache_path.with_suffix('.tmp')
            tmp.write_text(json.dumps(cache, ensure_ascii=False))
            tmp.replace(cache_path)
        # Positions and membership always come from the current playlist.
        song.update(list_name=playlist['name'], list_url=url, list_position=pos, list_length=expected)
        songs.append(song)
        print(f'Playlist metadata progress: {pos}/{expected}', flush=True)
    if len(songs)+len(skipped) != expected:
        raise ValueError('The playlist comparison is incomplete. Please check again.')
    print(f'Read {len(songs)} music entries; {len(skipped)} unavailable entries.', flush=True)
    return {'name': playlist['name'], 'url': url, 'total': expected, 'songs': songs, 'skipped': skipped}


if __name__ == '__main__':
    output = Path(sys.argv[2])
    cache = output.parent.parent/'metadata-cache.json'
    output.write_text(json.dumps(fetch(sys.argv[1], cache), ensure_ascii=False), encoding='utf-8')
