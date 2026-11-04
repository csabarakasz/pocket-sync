"""Background jobs, staged downloads, and verified, additive file copies."""
import argparse
import copy
from datetime import datetime
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

from download import spotify_link, audit
from playlist_sync.library import compare, scan_folder, read_track
from playlist_sync.libraries import LibraryStore, choose_folder
from playlist_sync.reuse import ReuseStore
from playlist_sync.history import HistoryStore, timestamp, read_log, download_failure, youtube_url

ROOT = Path(__file__).resolve().parents[1]


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    temporary.replace(path)


def folder_identity(folder):
    if not folder.is_dir():
        raise ValueError('Music folder is unavailable. Connect the player or choose an existing folder.')
    stat = folder.stat()
    return stat.st_dev, stat.st_ino


def ensure_folder(folder, identity):
    if folder_identity(folder) != tuple(identity):
        raise ValueError('The selected folder or player changed. Check the playlist again before syncing.')


def clean_filename(name):
    """Keep track IDs in tags and staging, out of the user's music filenames."""
    return re.sub(r' \[[A-Za-z0-9]{22}\](?=\.mp3$)', '', name, flags=re.I)


def install_file(source, folder, identity, filename=None):
    """Exclusive creation preserves every existing file, even on FAT/exFAT devices."""
    ensure_folder(folder, identity)
    name = filename or source.name
    if Path(name).name != name:
        raise ValueError('Expected a filename, without a directory.')
    destination = folder / name
    # Work through a directory descriptor so an unplug never falls back to a new
    # directory on the Mac. A temporary filename is never considered music.
    descriptor = os.open(folder, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    partial = f'.pocketsync-{uuid.uuid4().hex}.part'
    try:
        stat = os.fstat(descriptor)
        if (stat.st_dev, stat.st_ino) != tuple(identity):
            raise ValueError('The player disconnected before copying.')
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644, dir_fd=descriptor)
        try:
            with os.fdopen(fd, 'wb') as target, source.open('rb') as src:
                shutil.copyfileobj(src, target)
                target.flush()
                os.fsync(target.fileno())
            ensure_folder(folder, identity)
            # Reserve the name exclusively. No existing music can be overwritten.
            number = 1
            while True:
                try:
                    reservation = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644, dir_fd=descriptor)
                    os.close(reservation)
                    break
                except FileExistsError:
                    if filename is None:
                        raise
                    number += 1
                    name = f'{Path(filename).stem} ({number}){Path(filename).suffix}'
            destination = folder / name
            try:
                os.rename(partial, name, src_dir_fd=descriptor, dst_dir_fd=descriptor)
            except BaseException:
                os.unlink(name, dir_fd=descriptor)
                raise
        except BaseException:
            try:
                os.unlink(partial, dir_fd=descriptor)
            except OSError:
                pass
            raise
    finally:
        os.close(descriptor)
    return destination


class SyncEngine:
    def __init__(self, runtime=None):
        self.runtime = Path(runtime or ROOT / '.runtime' / 'playlist-sync')
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.history = HistoryStore(self.runtime)
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.process = None
        self.worker = None
        self.songs = []
        self.folder = None
        self.identity = None
        self.records = []
        self.playlist = {}
        self.last_scan = 0
        self.contexts = {}
        self.choosing_folder = False
        self._summary_revision = None
        self._summary_cache = {}
        settings = {'playlist': '', 'folder': ''}
        try:
            settings.update(json.loads((self.runtime/'settings.json').read_text()))
        except (OSError, ValueError):
            pass
        self.libraries = LibraryStore(self.runtime, settings)
        self.reuse = ReuseStore(self.runtime)
        for library in self.libraries.list():
            self.reuse.register(library['folder'])
        for run in self.history.list():
            self.reuse.register(run.get('folder'))
            for item in run['items']:
                if item.get('verified') and item.get('file'):
                    self.reuse.remember(item['id'], item['file'])
        self.library_id = self.libraries.get()['id']
        active = self.libraries.get()
        settings = {key: active[key] for key in ('playlist', 'folder')}
        self._migrate_library_history()
        self.state = {'phase': 'idle', 'message': 'Ready when you are.', 'settings': settings, 'tracks': [],
                      'extras': [], 'skipped': [], 'playlist_name': '', 'scan_id': None,
                      'checked_at': None, 'progress': {'done': 0, 'total': 0}, 'errors': [], 'log': [], 'job_id': None, 'last_sync': None}
        previous = self.history.list(library_id=self.library_id)
        if previous:
            self.state['last_sync'] = self.run_summary(previous[0])

    def _migrate_library_history(self):
        for run in self.history.list():
            if run.get('library_id'):
                continue
            matches = [x for x in self.libraries.list() if
                       (run.get('playlist_url') == x['playlist']) or
                       (not run.get('playlist_url') and run.get('folder') == x['folder'])]
            if len(matches) == 1:
                run.update(library_id=matches[0]['id'], library_name=matches[0]['name'])
                self.history.save(run)

    def _require_unlocked(self):
        if self.state['phase'] in ('checking', 'syncing') or self.choosing_folder:
            raise ValueError('Finish or stop the current operation before changing libraries.')

    def _reset_library(self, library):
        self.songs, self.records, self.playlist = [], [], {}
        self.folder, self.identity, self.last_scan = None, None, 0
        self.state.update(phase='idle', message='Choose a folder, then check for new songs.' if not library['folder'] else 'Ready to check this playlist.',
                          settings={key: library[key] for key in ('playlist','folder')}, tracks=[], extras=[], skipped=[],
                          playlist_name='', scan_id=None, checked_at=None, errors=[], log=[], job_id=None,
                          progress={'done': 0, 'total': 0}, last_sync=None, current_id=None, local_count=0)

    def select_library(self, library_id):
        with self.lock:
            self._require_unlocked()
            library = self.libraries.get(library_id)
            if library_id == self.library_id:
                return
            keys = ('state','songs','folder','identity','records','playlist','last_scan')
            self.contexts[self.library_id] = {key: copy.deepcopy(getattr(self,key)) for key in keys}
            self.libraries.select(library_id)
            self.library_id = library_id
            cached = self.contexts.get(library_id)
            settings = {key: library[key] for key in ('playlist','folder')}
            if cached and cached['state']['settings'] == settings:
                for key,value in cached.items():
                    setattr(self,key,value)
                try:
                    if self.state['scan_id']:
                        self.refresh_local()
                except (OSError, ValueError):
                    self._reset_library(library)
            else:
                self._reset_library(library)
            runs = self.history.list(library_id=library_id)
            self.state['last_sync'] = self.run_summary(runs[0]) if runs else None
            atomic_json(self.runtime/'settings.json', settings)

    def add_library(self, name, playlist, folder=''):
        with self.lock:
            self._require_unlocked()
            library = self.libraries.add(name, playlist, folder)
            self.select_library(library['id'])
            self._summary_revision = None
            return library

    def edit_library(self, library_id, **fields):
        with self.lock:
            self._require_unlocked()
            before = self.libraries.get(library_id)
            self.reuse.register(before['folder'])
            library = self.libraries.update(library_id, **fields)
            if any(before[key] != library[key] for key in ('playlist','folder')):
                self.contexts.pop(library_id, None)
                if library_id == self.library_id:
                    self._reset_library(library)
            if library_id == self.library_id:
                runs = self.history.list(library_id=library_id)
                self.state['last_sync'] = self.run_summary(runs[0]) if runs else None
                atomic_json(self.runtime/'settings.json', {key:library[key] for key in ('playlist','folder')})
            return library

    def select_folder(self, initial='', library_id=None):
        with self.lock:
            self._require_unlocked()
            if library_id and library_id != self.library_id:
                raise ValueError('The selected library changed. Choose the folder again.')
            self.choosing_folder = True
        try:
            return choose_folder(initial)
        finally:
            with self.lock:
                self.choosing_folder = False

    def snapshot(self):
        with self.lock:
            state = copy.deepcopy(self.state)
            state['history_revision'] = self.history.revision
            state['folder_available'] = bool(state['settings']['folder']) and Path(state['settings']['folder']).is_dir()
            from playlist_sync.compilations import custom_snapshot
            state['custom_imports'] = custom_snapshot(self)
            state['library_id'] = self.library_id
            state['library'] = self.libraries.get()
            state['choosing_folder'] = self.choosing_folder
            if self._summary_revision != self.history.revision:
                self._summary_cache = {}
                for library in self.libraries.list():
                    runs = self.history.list(library_id=library['id'])
                    self._summary_cache[library['id']] = [self.run_summary(x) for x in runs[:3]]
                self._summary_revision = self.history.revision
            state['libraries'] = [{**library, 'recent_syncs': self._summary_cache.get(library['id'], [])} for library in self.libraries.list()]
            return state

    @staticmethod
    def run_summary(run):
        return {key: run.get(key) for key in ('id', 'status', 'started_at', 'finished_at', 'message', 'added', 'folder', 'library_id', 'library_name')} | {
            'total': len(run['items']), 'failed': sum(x['status']=='failed' for x in run['items'])}

    def update(self, **data):
        with self.lock:
            self.state.update(data)

    def mappings(self):
        try:
            data = json.loads((self.runtime/'matches.json').read_text())
            return data.get(str(self.folder), {})
        except (OSError, ValueError):
            return {}

    def remember(self, sid, relative):
        with self.lock:
            self.require_ready()
            row = next((x for x in self.state['tracks'] if x['id'] == sid), None)
            if not row or row['status'] != 'review' or relative not in [x['file'] for x in row.get('candidates', [])]:
                raise ValueError('That file is not a current review candidate. Check the folder again.')
            ensure_folder(self.folder, self.identity)
            local = next(x for x in scan_folder(self.folder) if str(x.path.relative_to(self.folder)) == relative)
            if local.error:
                raise ValueError('This file cannot be read as audio and cannot be used as a match.')
            path = self.runtime/'matches.json'
            try:
                data = json.loads(path.read_text())
            except (OSError, ValueError):
                data = {}
            data.setdefault(str(self.folder), {})[sid] = {'file': relative, 'fingerprint': local.fingerprint}
            atomic_json(path, data)
            self.refresh_local()

    def require_ready(self):
        if self.state['phase'] in ('checking', 'syncing') or self.choosing_folder:
            raise ValueError('A check or sync is already running.')
        if not self.state['scan_id']:
            raise ValueError('Check the playlist and folder first.')

    def start_scan(self, playlist, folder):
        try:
            link = spotify_link(playlist)
        except argparse.ArgumentTypeError as error:
            raise ValueError(str(error)) from error
        if '/playlist/' not in link:
            raise ValueError('Please paste a Spotify playlist link.')
        if not folder.strip():
            raise ValueError("Choose an existing music folder.")
        folder = Path(folder).expanduser().absolute()
        identity = folder_identity(folder)
        # Resolving a volume path here would conceal an unplug/replaced mount.
        with self.lock:
            if self.state['phase'] in ('checking', 'syncing') or self.choosing_folder:
                raise ValueError('A check or sync is already running.')
            self.reuse.register(self.libraries.get()['folder'])
            self.libraries.update(self.library_id, playlist=link, folder=str(folder))
            self.cancel.clear()
            self.folder, self.identity = folder, identity
            self.songs, self.records = [], []
            self.update(phase='checking', message='Reading the playlist from Spotify…', tracks=[], extras=[], skipped=[],
                        errors=[], log=[], scan_id=None, job_id=uuid.uuid4().hex,
                        progress={'done': 0, 'total': 0}, settings={'playlist': link, 'folder': str(folder)})
            atomic_json(self.runtime/'settings.json', self.state['settings'])
            self.worker = threading.Thread(target=self._scan, args=(link,), daemon=True)
            self.worker.start()

    def run_process(self, command, timeout, logfile, cwd=None, *, playlist_progress=False):
        with logfile.open('w') as log:
            process = subprocess.Popen(command, cwd=cwd or ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            with self.lock:
                self.process = process
            start = time.monotonic()
            try:
                while process.poll() is None:
                    if self.cancel.is_set():
                        raise InterruptedError('Stopped. Files already copied are kept.')
                    if time.monotonic()-start > timeout:
                        raise TimeoutError('The music service took too long to respond. You can retry this track.')
                    lines = logfile.read_text(errors='replace').splitlines()
                    if playlist_progress:
                        for line in reversed(lines[-10:]):
                            match = re.fullmatch(r'Playlist metadata progress: (\d+)/(\d+)', line)
                            if match:
                                done, total = map(int, match.groups())
                                self.update(message='Reading track details from Spotify…', progress={'done': done, 'total': total})
                                break
                    self.update(log=[re.sub(r'\x1b\[[0-9;]*m', '', x) for x in lines[-10:]])
                    time.sleep(.3)
                return process.returncode
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(3)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                with self.lock:
                    self.process = None

    def _scan(self, link):
        job = self.runtime/self.state['job_id']
        job.mkdir()
        try:
            manifest = job/'playlist.json'
            code = self.run_process([sys.executable, str(ROOT/'playlist_sync/spotify_fetch.py'), link, str(manifest)], 600, job/'spotify.log', playlist_progress=True)
            if code or not manifest.exists():
                raise ValueError('Could not read the Spotify playlist. Make sure it is public and try again. See activity for details.')
            playlist = json.loads(manifest.read_text())
            if self.cancel.is_set():
                raise InterruptedError('Check stopped.')
            ensure_folder(self.folder, self.identity)
            self.playlist = playlist
            self.songs = playlist['songs']
            self.update(message='Looking for music you already have…', progress={'done': 0, 'total': 0})
            self.reuse.discover(self.songs)
            if self.cancel.is_set():
                raise InterruptedError
            self.update(message='Comparing the playlist with your destination folder…')
            self.refresh_local()
            if self.cancel.is_set():
                raise InterruptedError
            self.last_scan = time.time()
            self.update(phase='ready', message='Comparison complete. Choose what to add.', scan_id=uuid.uuid4().hex,
                        playlist_name=playlist['name'], skipped=playlist['skipped'], playlist_total=playlist['total'],
                        checked_at=datetime.now().astimezone().isoformat())
        except InterruptedError:
            self.update(phase='idle', message='Playlist check stopped.', tracks=[], extras=[], skipped=[])
        except Exception as error:
            self.update(phase='error', message=str(error), errors=[str(error)])

    def refresh_local(self):
        ensure_folder(self.folder, self.identity)
        self.records = scan_folder(self.folder)
        rows, extras = compare(self.songs, self.records, self.folder, self.mappings())
        self.reuse.register(self.folder)
        songs_by_id = {s['song_id']: s for s in self.songs}
        for row in rows:
            if row['status'] == 'present':
                self.reuse.remember(row['id'], self.folder/row['file'])
            elif row['status'] == 'missing':
                source = self.reuse.find(songs_by_id[row['id']], self.folder)
                if source:
                    row['reuse_file'] = str(source)
        previous = self.history.latest_failures(self.folder, library_id=self.library_id)
        for row in rows:
            item = previous.get(row['id'])
            if row['status'] != 'present' and item:
                row.update(error=item['message'], error_code=item.get('error_code'), help=item.get('help'), source_url=item.get('source_url'))
        self.update(tracks=rows, extras=extras, local_count=len(self.records))

    def start_sync(self, scan_id, selected=None, sources=None):
        with self.lock:
            self.require_ready()
            if scan_id != self.state['scan_id']:
                raise ValueError('The comparison changed. Check the playlist again.')
            if time.time()-self.last_scan > 3600:
                raise ValueError('This comparison is over an hour old. Check the playlist again before syncing.')
            ensure_folder(self.folder, self.identity)
            self.refresh_local()
            rows = self.state['tracks']
            if selected is None:
                selected = [x['id'] for x in rows if x['status'] == 'missing']
            if not isinstance(selected, list) or any(not isinstance(x, str) for x in selected):
                raise ValueError('Invalid track selection.')
            allowed = {x['id'] for x in rows if x['status'] in ('missing', 'review')}
            if any(x not in allowed for x in selected):
                raise ValueError('Some selected songs are already present. Refresh the comparison.')
            selected = set(selected)
            songs = [s for i,s in enumerate(self.songs) if s['song_id'] in selected and s['song_id'] not in {x['song_id'] for x in self.songs[:i]}]
            sources = sources or {}
            if not isinstance(sources, dict) or any(sid not in selected for sid in sources):
                raise ValueError('An audio source must belong to a selected track.')
            songs = copy.deepcopy(songs)
            try:
                saved_sources = json.loads((self.runtime/'recordings.json').read_text())
            except (OSError, ValueError):
                saved_sources = {}
            for song in songs:

                if song['song_id'] in sources:
                    song['download_url'] = youtube_url(str(sources[song['song_id']]))
                    song['_force_download'] = True
                elif song['song_id'] in saved_sources:
                    song['download_url'] = youtube_url(saved_sources[song['song_id']]['url'])
            if not songs:
                raise ValueError('There are no missing songs to add.')
            required = 0
            for song in songs:
                source = None if song.get('_force_download') else self.reuse.find(song, self.folder)
                try:
                    size = source.stat().st_size if source else 0
                except OSError:
                    size = 0
                required += max(size, song['duration']*16000+1000000)
            required *= 1.1
            if shutil.disk_usage(self.folder).free < required:
                raise ValueError('There is not enough free space in the selected folder for these songs.')
            self.cancel.clear()
            self.update(phase='syncing', message='Checking local copies before downloading…', errors=[], log=[], job_id=uuid.uuid4().hex,
                        progress={'done': 0, 'total': len(songs), 'added': 0, 'failed': 0}, current_id=None)
            run = {'version': 2, 'id': self.state['job_id'], 'kind': 'sync', 'legacy': False,
                   'started_at': timestamp(), 'finished_at': None, 'folder': str(self.folder),
                   'playlist_name': self.state.get('playlist_name') or 'Playlist sync',
                   'playlist_url': self.state['settings']['playlist'], 'library_id': self.library_id,
                   'library_name': self.libraries.get()['name'], 'status': 'running', 'message': 'Sync in progress.',
                   'added': 0, 'errors': [], 'items': [
                       {'id': song['song_id'], 'name': song['name'], 'artists': song['artists'], 'url': song['url'],
                        'status': 'queued', 'message': 'Waiting to start.', 'file': None, 'verified': False,
                        'source_url': song.get('download_url')} for song in songs]}
            self.history.save(run)
            self.update(last_sync=self.run_summary(run))
            self.worker = threading.Thread(target=self._sync, args=(songs, run), daemon=True)
            self.worker.start()

    def _sync(self, songs, run):
        job = self.runtime/run['id']
        job.mkdir(exist_ok=True)
        errors, failures, added = [], {}, 0
        finished = {}
        def checkpoint():
            run['added'] = added
            run['errors'] = list(errors)
            self.history.save(run)
            self.update(last_sync=self.run_summary(run))
        try:
            for index, song in enumerate(songs):
                if self.cancel.is_set():
                    raise InterruptedError('Sync stopped. Finished songs are kept.')
                ensure_folder(self.folder, self.identity)
                item = run['items'][index]
                self.refresh_local()
                current = next(x for x in self.state['tracks'] if x['id'] == song['song_id'])
                if current['status'] == 'present':
                    item.update(status='already_present',file=str(self.folder/current['file']),verified=True,
                                message='Already covered in the destination. No duplicate was copied.',finished_at=timestamp())
                    checkpoint()
                    self.update(progress={'done':index+1,'total':len(songs),'added':added,'failed':len(failures)})
                    continue
                item.update(status='downloading', started_at=timestamp(), message='Finding and downloading audio…')
                checkpoint()
                self.update(current_id=song['song_id'], message=f"Adding {song['name']}…")
                stage = job/song['song_id']
                stage.mkdir()
                manifest = stage/'track.spotdl'
                # Internal sync options are not fields accepted by spotDL's Song.
                atomic_json(manifest, [{key: value for key, value in song.items() if not key.startswith('_')}])
                try:
                    source = None if song.get('_force_download') else self.reuse.find(song, self.folder)
                    log = ''
                    result = None
                    if source:
                        self.update(message=f"Copying local file: {song['name']}…")
                        candidate = stage/clean_filename(source.name)
                        try:
                            shutil.copyfile(source, candidate)
                            group = read_track(candidate).group_ids
                            checked = {'file':str(candidate),'issues':[]} if song['song_id'] in group else audit(stage, [song], {song['song_id']: candidate})[0]
                            if not checked['issues'] and self.reuse.valid(song, candidate):
                                result = checked
                                item.update(method='local_copy', source_file=str(source))
                                (stage/'download.log').write_text(f'Copied existing local file: {source}\nVerified audio, cover art, and tags before copying to destination.\n')
                        except OSError:
                            pass
                        if result is None:
                            candidate.unlink(missing_ok=True)
                    if result is None:
                        item.update(method='download')
                        if not shutil.which('ffmpeg'):
                            raise ValueError('FFmpeg is missing. Install it with brew install ffmpeg to download new audio.')
                        command = [sys.executable, '-m', 'spotdl', 'download', str(manifest), '--audio', 'youtube', '--lyrics',
                                   '--yt-dlp-args', '--flat-playlist --socket-timeout 20 --retries 1 --extractor-retries 1',
                                   '--format', 'mp3', '--bitrate', '128k', '--threads', '1', '--simple-tui',
                                   '--output', '{artists} - {title} [{track-id}].{output-ext}']
                        logfile = stage/'download.log'
                        self.update(message=f'Finding and downloading {song["name"]}…')
                        code = self.run_process(command, 240, logfile, cwd=stage)
                        log = read_log(logfile)
                        result = audit(stage, [song])[0]
                        if code or result['issues']:
                            detail = download_failure(log, result['issues'], code)
                            item.update(error_code=detail['code'], help=detail['help'])
                            raise ValueError(detail['message'])
                    if self.cancel.is_set():
                        raise InterruptedError('Sync stopped. Finished songs are kept.')
                    self.update(message=f'Checking your destination for {song["name"]}…')
                    self.refresh_local()
                    current = next(x for x in self.state['tracks'] if x['id'] == song['song_id'])
                    if current['status'] != 'present':
                        destination = install_file(Path(result['file']), self.folder, self.identity, filename=clean_filename(Path(result['file']).name))
                        added += 1
                        item.update(status='added', file=str(destination), verified=True,
                                    message='Copied from an existing local file; cover art and tags verified.' if item['method']=='local_copy' else 'Downloaded, verified, and copied to the music folder.')
                        self.reuse.remember(song['song_id'], destination)
                    else:
                        item.update(status='already_present', file=str(self.folder/current['file']), verified=True,
                                    message='Already in the folder when checked again. No duplicate was copied.')
                    sources = re.findall(r'https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]{11}', log)
                    item['source_url'] = song.get('download_url') or (sources[-1] if sources else None)
                    if song.get('download_url'):
                        source_file = self.runtime/'recordings.json'
                        try:
                            saved = json.loads(source_file.read_text())
                        except (OSError, ValueError):
                            saved = {}
                        saved[song['song_id']] = {'url': song['download_url'], 'verified_at': timestamp()}
                        atomic_json(source_file, saved)
                    self.refresh_local()
                except (InterruptedError, OSError):
                    raise
                except Exception as error:
                    failure = str(error)
                    item.update(status='failed', message=failure)
                    if isinstance(error, TimeoutError):
                        item.update(error_code='timeout', help='The service took too long. Retry this song later.')
                    failures[song['song_id']] = failure
                    errors.append(f"{song['name']}: {failure}")
                item['finished_at'] = timestamp()
                checkpoint()
                self.update(progress={'done': index+1, 'total': len(songs), 'added': added, 'failed': len(failures)}, errors=errors)
            message = f"{added} song{'s' if added != 1 else ''} added." + (f' {len(failures)} failed. See Sync history for details.' if failures else ' Sync complete. See Sync history for the results.')
            run.update(status='issues' if failures else 'completed', message=message)
            finished = dict(phase='ready', current_id=None, message=message)
        except InterruptedError as error:
            run.update(status='stopped', message=str(error))
            finished = dict(phase='ready', current_id=None, message=str(error))
        except Exception as error:
            errors.append(str(error))
            run.update(status='failed', message=str(error))
            finished = dict(phase='error', current_id=None, message=str(error), errors=errors)
        finally:
            for item in run['items']:
                if item['status'] == 'downloading':
                    item.update(status='stopped' if run['status']=='stopped' else 'failed', message=run['message'], finished_at=timestamp())
                elif item['status'] == 'queued':
                    item.update(status='not_attempted', message='Not started because the sync stopped early.')
            run['finished_at'] = timestamp()
            try:
                checkpoint()
                self.refresh_local()
                atomic_json(job/'report.json', {'time': run['finished_at'], 'folder': str(self.folder),
                            'added': added, 'errors': errors, 'tracks': self.state['tracks']})
                for item in run['items']:
                    if item['status'] in ('added', 'already_present'):
                        for path in (job/item['id']).glob('*.mp3'):
                            path.unlink()
            except Exception as error:
                errors.append(f'Could not finalize the sync report: {error}')
                finished.update(phase='error', message=errors[-1], errors=errors)
            self.update(**finished)

    def shutdown(self):
        self.stop()
        if self.worker:
            self.worker.join(timeout=6)

    def stop(self):
        self.cancel.set()
