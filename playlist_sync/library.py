"""Read music identity without modifying existing files."""
from dataclasses import dataclass, field
from pathlib import Path
import re
import unicodedata
import mutagen
from playlist_sync.compilations import coverage, import_identity

AUDIO = {'.mp3', '.m4a', '.flac', '.ogg', '.opus', '.wav', '.aac', '.wma'}
ID = re.compile(r'(?:spotify:track:|open\.spotify\.com/track/|\[)([A-Za-z0-9]{22})(?:\]|\b)')


def normalize(text):
    text = unicodedata.normalize('NFKD', text.casefold())
    return ''.join(c for c in text if c.isalnum() and not unicodedata.combining(c))


def artist_key(text):
    return normalize(re.sub(r'\s*-\s*topic\s*$', '', text, flags=re.I))


def filename_title(path):
    name = re.sub(r'^\d+[ _.-]+', '', path.stem)
    name = re.sub(r'[_ -]*SpotiDost$', '', name, flags=re.I)
    name = re.sub(r'\[[A-Za-z0-9]{22}\]', '', name)
    return normalize(name)


@dataclass
class LocalTrack:
    path: Path
    title: str = ''
    artists: list = field(default_factory=list)
    duration: float = 0
    ids: set = field(default_factory=set)
    group_ids: set = field(default_factory=set)
    import_id: str = ''
    error: str = ''
    fingerprint: str = ''


def read_track(path):
    record = LocalTrack(path)
    try:
        stat = path.stat()
        record.fingerprint = f'{stat.st_size}:{stat.st_mtime_ns}'
        audio = mutagen.File(path)
        if not audio or not audio.info or audio.info.length <= 0:
            raise ValueError('File contains no readable audio')
        record.duration = float(audio.info.length)
        record.group_ids = coverage(audio)
        record.import_id = import_identity(audio) or ''
        easy = mutagen.File(path, easy=True)
        if easy and easy.tags:
            record.title = (easy.tags.get('title') or [''])[0]
            record.artists = list(easy.tags.get('artist') or [])
        if audio.tags:
            # WAV ID3 and formats without an EasyTags adapter.
            record.title = record.title or str(audio.tags.get('TIT2', ''))
            if not record.artists and audio.tags.get('TPE1'):
                record.artists = list(audio.tags['TPE1'].text)
            for key, value in audio.tags.items():
                if key.startswith('APIC') or key in {'covr', 'metadata_block_picture'}:
                    continue
                record.ids.update(ID.findall(str(value)))
        record.ids.update(ID.findall(path.name))
    except Exception as error:
        record.error = f'Cannot read audio: {error}'
    return record


def scan_folder(folder):
    records = []
    # Never follow symlinks outside the selected music folder.
    for base, dirs, files in __import__('os').walk(folder, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not (Path(base)/d).is_symlink())
        for name in sorted(files):
            path = Path(base)/name
            if not name.startswith('.') and path.suffix.lower() in AUDIO and not path.is_symlink():
                records.append(read_track(path))
    return records


def compare(songs, records, folder, remembered=None):
    remembered = remembered or {}
    matched, rows, used = {}, [], set()
    seen = set()
    for song in songs:
        sid = song['song_id']
        if sid in seen:
            continue
        seen.add(sid)
        title = normalize(song['name'])
        artists = {artist_key(a) for a in song['artists']}
        exact, possible = [], []
        for local in records:
            rel = str(local.path.relative_to(folder))
            stored = remembered.get(sid, {})
            manual = stored.get('file') == rel and stored.get('fingerprint') == local.fingerprint
            title_same = bool(title) and normalize(local.title) == title
            artist_same = bool(artists) and any(artist_key(a) in artists for a in local.artists)
            duration_same = abs(local.duration - song['duration']) <= 10
            id_same = sid in local.ids
            # A different embedded Spotify ID must not silently match another release.
            group_same = sid in local.group_ids
            if not local.error and (group_same or manual or ((id_same or (title_same and artist_same and not local.ids)) and duration_same)):
                exact.append((local, 'Confirmed combined recording' if group_same else 'Confirmed by you' if manual else 'Spotify track ID' if id_same else 'Title, artist & duration'))
            elif id_same or title_same or filename_title(local.path) == title:
                possible.append(local)
        # A fallback file cannot silently stand in for two separate Spotify IDs.
        exact.sort(key=lambda x: str(x[0].path))
        hit = next((x for x in exact if sid in x[0].group_ids or str(x[0].path) not in matched or matched[str(x[0].path)] == sid), None)
        if hit:
            local, reason = hit
            used.add(str(local.path))
            matched[str(local.path)] = sid
            row = {'status': 'present', 'file': str(local.path.relative_to(folder)), 'reason': reason}
        else:
            possible += [x[0] for x in exact]
            row = {'status': 'review' if possible else 'missing', 'file': None,
                   'reason': 'Check a possible existing match' if possible else 'Not found in this folder',
                   'candidates': [{'file': str(x.path.relative_to(folder)), 'title': x.title or x.path.stem,
                                   'artist': ', '.join(x.artists), 'duration': round(x.duration), 'error': x.error} for x in possible]}
            used.update(str(x.path) for x in possible)
        rows.append({**row, 'id': sid, 'name': song['name'], 'artists': song['artists'],
                     'album': song['album_name'], 'duration': song['duration'], 'cover': song.get('cover_url'),
                     'url': song['url'], 'position': song.get('list_position', len(rows)+1)})
    extras = [{'file': str(x.path.relative_to(folder)), 'name': x.title or x.path.stem,
               'artist': ', '.join(x.artists), 'error': x.error, 'import_id': x.import_id} for x in records if str(x.path) not in used]
    return rows, extras
