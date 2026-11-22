"""Remember original music locations; reuse only currently verified MP3 files."""
import json
from pathlib import Path

from download import audit
from playlist_sync.library import scan_folder, compare, read_track


class ReuseStore:
    def __init__(self, runtime, cache=None):
        self.cache = cache
        self.validated = {}
        self.path = Path(runtime)/'local-files.json'
        try:
            self.data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.data = {'folders': [], 'tracks': {}}

    def save(self):
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2))
        temp.replace(self.path)

    def register(self, folder):
        if folder and str(folder) not in self.data['folders']:
            self.data['folders'].append(str(folder))
            self.save()

    def remember(self, sid, path):
        path = str(path)
        paths = self.data['tracks'].setdefault(sid, [])
        if path not in paths:
            paths.append(path)
            self.save()

    @staticmethod
    def valid(song, path):
        try:
            path = Path(path)
            if path.suffix.lower() != '.mp3' or path.is_symlink() or not path.is_file():
                return False
            track = read_track(path)
            if not track.error and song['song_id'] in track.group_ids:
                return True
            if track.error or (track.ids and song['song_id'] not in track.ids):
                return False
            return not audit(path.parent, [song], {song['song_id']: path})[0]['issues']
        except (OSError, ValueError):
            return False

    def verified(self, song, path):
        try:
            stat = Path(path).stat()
            key = (str(path), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns,
                   json.dumps({k:v for k,v in song.items() if not k.startswith('_') and not k.startswith('list_')}, sort_keys=True))
            if key not in self.validated:
                self.validated[key] = self.valid(song, path)
            return self.validated[key]
        except OSError:
            return False

    def discover(self, songs):
        scanned = {}
        # Only user-selected music roots are searched, never the whole computer.
        for folder in self.data['folders']:
            root = Path(folder)
            if not root.is_dir() or root.is_symlink():
                continue
            records = scan_folder(root, self.cache)
            scanned[str(root)] = records
            rows, _ = compare(songs, records, root)
            by_id = {s['song_id']: s for s in songs}
            for row in rows:
                if row['status'] == 'present':
                    path = root/row['file']
                    if self.verified(by_id[row['id']], path):
                        self.remember(row['id'], path)

        return scanned

    def find(self, song, destination):
        for value in self.data['tracks'].get(song['song_id'], []):
            path = Path(value)
            if path.parent != destination and self.verified(song, path):
                return path
        return None
