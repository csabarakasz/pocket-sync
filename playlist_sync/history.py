"""Durable sync outcomes, including honest imports of older reports."""
from datetime import datetime
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlparse, parse_qs

JOB_ID = re.compile(r'^[a-f0-9]{32}$')
TRACK_ID = re.compile(r'^[A-Za-z0-9]{22}$')


def timestamp():
    return datetime.now().astimezone().isoformat()


def read_log(path):
    if not path.exists():
        return ''
    with path.open('rb') as stream:
        stream.seek(0, 2)
        stream.seek(max(0, stream.tell()-24000))
        return re.sub(r'\x1b\[[0-9;]*m', '', stream.read().decode('utf-8', errors='replace'))


def download_failure(log, issues=None, code=0):
    """spotDL can exit zero even after a search fails; retain its real reason."""
    lower = log.casefold()
    if 'no results found for song' in lower or 'no matching results' in lower:
        return {'code': 'no_match', 'message': 'Automatic matching could not find a suitable YouTube recording.',
                'help': 'The Spotify link opens the track page, not a downloadable audio file. Retry, or choose a specific YouTube recording.'}
    if 'sign in to confirm' in lower or 'not a bot' in lower:
        return {'code': 'source_blocked', 'message': 'YouTube blocked this download request.', 'help': 'Try again later. A working video page does not guarantee automated downloading is available.'}
    if any(word in lower for word in ['video unavailable', 'not available in your country', 'private video', 'has been removed']):
        return {'code': 'source_unavailable', 'message': 'The selected YouTube recording is unavailable to the downloader.', 'help': 'Choose another recording or retry later.'}
    if any(word in lower for word in ['timed out', 'timeout', 'name resolution', 'network is unreachable']):
        return {'code': 'network', 'message': 'The audio service could not be reached.', 'help': 'Check your connection and retry.'}
    if issues and issues != ['Audio file missing']:
        return {'code': 'verification', 'message': 'The download did not pass verification: '+ '; '.join(issues), 'help': 'No unverified file was copied. Try a different recording.'}
    errors = [x.strip() for x in log.splitlines() if re.search(r'\b(?:ERROR|\w*Error):', x)]
    return {'code': 'download_failed', 'message': errors[-1][:500] if errors else 'The downloader did not produce a usable audio file.',
            'help': 'No audio was copied. Retry or inspect the technical log below.'}


def youtube_url(value):
    parsed = urlparse(value.strip())
    if parsed.scheme != 'https':
        raise ValueError('Use an https YouTube video link.')
    if parsed.hostname in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com') and parsed.path == '/watch':
        video = parse_qs(parsed.query).get('v', [''])[0]
    elif parsed.hostname == 'youtu.be':
        video = parsed.path.strip('/')
    else:
        raise ValueError('Use a YouTube watch link or a youtu.be video link.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video):
        raise ValueError('This YouTube link has no valid video ID.')
    return 'https://www.youtube.com/watch?v='+video


class HistoryStore:
    def __init__(self, runtime):
        self.runtime = Path(runtime)
        self.lock = threading.RLock()
        self.revision = time.time_ns()
        self.import_reports()
        # A saved in-progress run belongs to a server that is no longer running.
        for path in self.runtime.glob('*/history.json'):
            try:
                run = json.loads(path.read_text())
                if run['status'] == 'running':
                    for item in run['items']:
                        if item['status'] in ('queued', 'downloading'):
                            item.update(status='not_attempted' if item['status']=='queued' else 'interrupted', message='Not started before the app closed.' if item['status']=='queued' else 'The app closed before this attempt was recorded as complete.')
                    run.update(status='interrupted', finished_at=timestamp(), message='Sync interrupted when the app stopped. Check the folder before retrying.')
                    self.save(run)
            except (OSError, ValueError, KeyError):
                continue

    def save(self, run):
        with self.lock:
            path = self.runtime/run['id']/'history.json'
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(run, ensure_ascii=False, indent=2))
            temporary.replace(path)
            self.revision = time.time_ns()

    def import_reports(self):
        renames = {}
        for path in sorted(self.runtime.glob('filename-cleanup-*.json')):
            try:
                for change in json.loads(path.read_text()):
                    if change.get('status') == 'renamed':
                        renames[change['before']] = change['after']
            except (OSError, ValueError, KeyError):
                continue
        for path in self.runtime.glob('*/report.json'):
            if not JOB_ID.fullmatch(path.parent.name) or (path.parent/'history.json').exists():
                continue
            try:
                report = json.loads(path.read_text())
                rows = {r['id']: r for r in report.get('tracks', [])}
                items = []
                for manifest in sorted(path.parent.glob('*/track.spotdl')):
                    song = json.loads(manifest.read_text())[0]
                    row = rows.get(song['song_id'], {})
                    log = read_log(manifest.parent/'download.log')
                    error = row.get('error')
                    detail = download_failure(log, [error]) if error else {}
                    file = row.get('file')
                    destination = str(Path(report['folder'])/file) if file else None
                    destination = renames.get(destination, destination)
                    source = re.findall(r'https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]{11}', log)
                    items.append({'id': song['song_id'], 'name': song['name'], 'artists': song['artists'], 'url': song['url'],
                                  'status': 'failed' if error else 'completed' if file else 'unknown',
                                  'message': detail.get('message') or ('Recorded as complete by the earlier app.' if file else 'Outcome was not recorded by the earlier app.'),
                                  'error_code': detail.get('code'), 'help': detail.get('help'), 'file': destination,
                                  'source_url': source[-1] if source else song.get('download_url'), 'verified': bool(file) if file else None})
                completed = [x for x in items if x['status'] == 'completed']
                # Only label individual older attempts "added" if the totals agree.
                if len(completed) == report.get('added', 0):
                    for item in completed:
                        item.update(status='added', message='Downloaded, verified, and copied to the music folder.')
                run = {'version': 2, 'id': path.parent.name, 'kind': 'sync', 'legacy': True,
                       'started_at': None, 'finished_at': report['time'], 'folder': report['folder'],
                       'playlist_name': 'Playlist sync',
                       'playlist_url': None, 'status': 'issues' if report.get('errors') else 'completed',
                       'message': 'Imported from an earlier sync report; start time was not recorded.',
                       'added': report.get('added', 0), 'errors': report.get('errors', []), 'items': items}
                self.save(run)
            except (OSError, ValueError, KeyError, IndexError, TypeError):
                continue

    def list(self, folder=None, library_id=None):
        with self.lock:
            runs = []
            for path in self.runtime.glob('*/history.json'):
                try:
                    run = json.loads(path.read_text())
                    if folder and run.get('folder') != folder:
                        continue
                    if library_id and run.get('library_id') != library_id:
                        continue
                    counts = {}
                    for item in run['items']:
                        counts[item['status']] = counts.get(item['status'], 0)+1
                    run['counts'] = counts
                    run['total'] = len(run['items'])
                    runs.append(run)
                except (OSError, ValueError, KeyError):
                    continue
            runs.sort(key=lambda r: r.get('started_at') or r.get('finished_at') or '', reverse=True)
            return runs[:100]

    def latest_failures(self, folder, library_id=None):
        outcomes = {}
        for run in self.list(str(folder), library_id=library_id):
            for item in run['items']:
                if item['id'] not in outcomes and item['status'] not in ('queued', 'downloading', 'not_attempted'):
                    outcomes[item['id']] = item
        return {sid: item for sid, item in outcomes.items() if item['status'] in ('failed', 'interrupted')}

    def log(self, job, track):
        if not JOB_ID.fullmatch(job) or not TRACK_ID.fullmatch(track):
            raise ValueError('Invalid history entry.')
        path = self.runtime/job/'history.json'
        run = json.loads(path.read_text())
        if not any(x['id'] == track for x in run['items']):
            raise ValueError('Track does not belong to this sync.')
        item = next(x for x in run['items'] if x['id'] == track)
        log_track = item.get('log_track', track)
        if not TRACK_ID.fullmatch(log_track):
            raise ValueError('Invalid log track.')
        return read_log(self.runtime/job/log_track/'download.log') or 'No technical log was saved.'
