"""Run the real UI against disposable data; no download or player writes."""
from pathlib import Path
import json
import sys
import tempfile
from datetime import datetime

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playlist_sync.engine import SyncEngine, folder_identity
from playlist_sync.server import Server, Handler

root=Path(tempfile.mkdtemp(prefix='pocket-sync-ui-'))
folder=root/'Music';folder.mkdir()
engine=SyncEngine(root/'runtime')
library=engine.libraries.get();engine.libraries.update(library['id'],folder=str(folder))
engine.folder=folder;engine.identity=folder_identity(folder)
tracks=[]
for i in range(9):
    sid=str(i).zfill(22)
    tracks.append({'id':sid,'name':['Example song','Another song','Last song'][i%3]+f' {i+1}',
                   'artists':['Example Artist'],'album':'Children’s songs','duration':115,'cover':None,'url':'https://open.spotify.com/track/'+sid,
                   'position':i+1,'status':'missing','file':None,'reason':'Not found','error':'Automatic matching could not find a suitable recording.',
                   'error_code':'no_match','help':'Choose a recording.'})
engine.update(phase='ready',scan_id='fixture-scan',playlist_name='Manual matching QA',tracks=tracks,
              settings={'playlist':'https://open.spotify.com/playlist/'+'a'*22,'folder':str(folder)},checked_at=datetime.now().astimezone().isoformat())
engine.last_scan=__import__('time').time()
class FixtureHandler(Handler):
    def do_POST(self):
        if self.path=='/api/recordings/search':
            self.rfile.read(int(self.headers['Content-Length']))
            return self.respond(200,{'videos':[{'id':'jNQXAC9IVRw','title':'Me at the zoo — preview test','channel':'jawed','duration':19,
                                              'url':'https://www.youtube.com/watch?v=jNQXAC9IVRw','thumbnail':'https://i.ytimg.com/vi/jNQXAC9IVRw/hqdefault.jpg'},
                                             {'id':'dQw4w9WgXcQ','title':'Second preview choice','channel':'Rick Astley','duration':115,
                                              'url':'https://www.youtube.com/watch?v=dQw4w9WgXcQ','thumbnail':'https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg'}]})
        if self.path=='/api/sync':
            data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            (root/'submitted.json').write_text(json.dumps(data))
            print('BATCH',json.dumps(data),flush=True)
            return self.respond(202,{'ok':True})
        return super().do_POST()
server=Server(('127.0.0.1',8891),engine);server.RequestHandlerClass=FixtureHandler
print('Fixture:',root,flush=True)
server.serve_forever()
