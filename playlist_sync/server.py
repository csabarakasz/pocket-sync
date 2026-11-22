"""Loopback-only browser application. Run with python -m playlist_sync.server."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
from urllib.parse import urlsplit, parse_qs
import webbrowser
from playlist_sync.engine import SyncEngine
from playlist_sync.recordings import search_recordings
from playlist_sync.compilations import inspect_playlist, start_compilation, start_custom

WEB = Path(__file__).parent/'web'


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, engine):
        self.engine = engine
        self.token = secrets.token_urlsafe(32)
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if args and str(args[1] if len(args)>1 else '').startswith('5'):
            super().log_message(fmt, *args)

    def respond(self, status, data, mime='application/json; charset=utf-8'):
        body = json.dumps(data, ensure_ascii=False).encode() if mime.startswith('application/json') else data
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' https://i.scdn.co https://mosaic.scdn.co https://i.ytimg.com; script-src 'self'; style-src 'self'; connect-src 'self'; frame-src https://www.youtube-nocookie.com https://www.youtube.com; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def allowed_host(self):
        return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}

    def do_GET(self):
        if not self.allowed_host():
            return self.respond(403, {'error': 'Use the localhost address to access this app.'})
        route = urlsplit(self.path).path
        if route == '/api/state':
            return self.respond(200, {**self.server.engine.snapshot(), 'token': self.server.token})
        if route == '/api/history':
            folder = parse_qs(urlsplit(self.path).query).get('folder', [None])[0]
            library_id = parse_qs(urlsplit(self.path).query).get('library', [None])[0]
            return self.respond(200, {'runs': self.server.engine.history.list(folder, library_id=library_id)})
        if route.startswith('/api/history/'):
            parts = route.split('/')
            if len(parts) == 6 and parts[4] == 'log':
                try:
                    return self.respond(200, {'log': self.server.engine.history.log(parts[3], parts[5])})
                except (ValueError, OSError, KeyError):
                    return self.respond(404, {'error': 'History log not found.'})
            return self.respond(404, {'error': 'History entry not found.'})
        if route == '/api/health':
            return self.respond(200, {'app': 'pocket-sync', 'ok': True})
        assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8'), '/logo.svg': ('logo.svg', 'image/svg+xml')}
        if route in assets:
            file, mime = assets[route]
            return self.respond(200, (WEB/file).read_bytes(), mime)
        self.respond(404, {'error': 'Not found'})

    def do_POST(self):
        origin = self.headers.get('Origin')
        allowed_origins = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
        if not self.allowed_host() or (origin and origin not in allowed_origins) or not secrets.compare_digest(self.headers.get('X-Sync-Token', ''), self.server.token):
            return self.respond(403, {'error': 'This request must come from the local app.'})
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.respond(415, {'error': 'Expected JSON'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 65536:
                raise ValueError('Invalid request size')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Expected a JSON object')
            engine = self.server.engine
            if data.get('library_id') and data['library_id'] != engine.library_id:
                raise ValueError('The active library changed. Review the selected library before continuing.')
            if self.path == '/api/custom/preview':
                from playlist_sync.compilations import find_custom
                result=inspect_playlist(engine, data.get('url',''), custom=True)
                folder=Path(str(data.get('folder',''))).expanduser()
                if str(data.get('folder','')).strip():
                    folder=folder.absolute();existing=find_custom(engine,result['source_id'],folder)
                    result.update(folder=str(folder),folder_available=folder.is_dir(),existing_file=str(existing) if existing else None,
                                  in_destination=bool(existing and folder in existing.parents))
                return self.respond(200, result)
            elif self.path == '/api/custom/start':
                start_custom(engine,data)
            elif self.path == '/api/compilations/preview':
                return self.respond(200, inspect_playlist(engine, data.get('url','')))
            elif self.path == '/api/compilations/start':
                start_compilation(engine, data)
            elif self.path == '/api/recordings/search':
                return self.respond(200, {'videos': search_recordings(data.get('query', ''))})
            elif self.path == '/api/libraries/add':
                engine.add_library(data.get('name',''), data.get('playlist',''), data.get('folder',''))
            elif self.path == '/api/libraries/select':
                engine.select_library(data.get('id'))
            elif self.path == '/api/libraries/update':
                fields = {key:data[key] for key in ('name','playlist','folder') if key in data}
                engine.edit_library(data.get('id'), **fields)
            elif self.path == '/api/folder':
                selected = engine.select_folder(str(data.get('initial','')), data.get('library_id'))
                return self.respond(200, {'path': selected, 'cancelled': selected is None})
            elif self.path == '/api/check':
                engine.start_scan(str(data.get('playlist', '')), str(data.get('folder', '')))
            elif self.path == '/api/order/preview':
                return self.respond(200, engine.preview_order(data.get('digits'),data.get('enabled',True)))
            elif self.path == '/api/order/apply':
                return self.respond(200, engine.apply_order(data.get('plan_id')))
            elif self.path == '/api/sync':
                engine.start_sync(data.get('scan_id'), data.get('ids'), data.get('sources'))
            elif self.path == '/api/match':
                engine.remember(data.get('id'), data.get('file'))
            elif self.path == '/api/stop':
                engine.stop()
            else:
                return self.respond(404, {'error': 'Not found'})
            self.respond(202, {'ok': True})
        except (ValueError, OSError, StopIteration) as error:
            self.respond(400, {'error': str(error) or 'File no longer available. Check the folder again.'})


def main():
    parser = argparse.ArgumentParser(description='Pocket Sync — add missing playlist songs to a local music folder.')
    parser.add_argument('--port', type=int, default=8878)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--runtime', type=Path, help='Store settings and history in this folder')
    args = parser.parse_args()
    try:
        server = Server(('127.0.0.1', args.port), SyncEngine(args.runtime))
    except OSError as error:
        parser.exit(1, f'Could not start Pocket Sync on port {args.port}: {error}\n')
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Pocket Sync is ready at {url}', flush=True)
    print('Keep this window open. Press Control+C to stop.', flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.engine.shutdown()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
