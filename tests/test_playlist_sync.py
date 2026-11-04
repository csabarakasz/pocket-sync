import copy
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch
from PIL import Image
from mutagen.mp3 import MP3
from mutagen.id3 import TIT2,TPE1,TALB,TRCK,TDRC,APIC,WOAS
from playlist_sync.engine import SyncEngine, folder_identity, install_file, clean_filename
from playlist_sync.library import LocalTrack, compare, read_track, scan_folder
from playlist_sync.server import Server

SONG = {'song_id':'a'*22,'name':'Don’t Stop Believin’','artists':['Journey'],'duration':1,
        'album_name':'Escape','url':'https://open.spotify.com/track/'+'a'*22,'list_position':1}


def make_audio(path, song=SONG, art=True):
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=330:duration=1',str(path)],check=True)
    a=MP3(path)
    if a.tags is None:a.add_tags()
    for frame in [TIT2(text=song['name']),TPE1(text=song['artists']),TALB(text=song['album_name']),TRCK(text='1/1'),TDRC(text='2026')]:a.tags.add(frame)
    if art:
        buffer=io.BytesIO();Image.new('RGB',(20,20),'blue').save(buffer,format='JPEG')
        a.tags.add(APIC(mime='image/jpeg',type=3,data=buffer.getvalue()))
    a.tags.add(WOAS(url=song['url']))
    a.save()


class ComparisonTests(unittest.TestCase):
    def test_existing_spotidost_artist_tags_and_unrelated_file(self):
        folder=Path('/music')
        local=LocalTrack(folder/'01_Dont_Stop_Believin_SpotiDost.mp3',"Don't Stop Believin",['Journey - Topic'],1)
        extra=LocalTrack(folder/'extra.mp3','Other song',['Someone'],2)
        rows,extras=compare([SONG,SONG],[local,extra],folder)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['status'],'present')
        self.assertEqual(extras[0]['file'],'extra.mp3')

    def test_same_title_wrong_artist_or_duration_needs_review(self):
        folder=Path('/music')
        for artist,length in [('Someone',1),('Journey',100)]:
            local=LocalTrack(folder/'song.mp3',SONG['name'],[artist],length)
            rows,_=compare([SONG],[local],folder)
            self.assertEqual(rows[0]['status'],'review')

    def test_filename_only_is_not_silently_accepted(self):
        folder=Path('/music')
        local=LocalTrack(folder/'05_Dont_Stop_Believin_SpotiDost.mp3',duration=1)
        self.assertEqual(compare([SONG],[local],folder)[0][0]['status'],'review')

    def test_corrupt_id_file_is_not_present(self):
        folder=Path('/music')
        local=LocalTrack(folder/'x.mp3',ids={SONG['song_id']},error='corrupt')
        self.assertEqual(compare([SONG],[local],folder)[0][0]['status'],'review')

    def test_manual_match_requires_same_file_fingerprint(self):
        folder=Path('/music')
        local=LocalTrack(folder/'file.mp3',duration=1,fingerprint='123:456')
        remembered={SONG['song_id']:{'file':'file.mp3','fingerprint':'123:456'}}
        self.assertEqual(compare([SONG],[local],folder,remembered)[0][0]['status'],'present')
        local.fingerprint='new'
        self.assertEqual(compare([SONG],[local],folder,remembered)[0][0]['status'],'missing')

    def test_different_track_ids_do_not_consume_same_file(self):
        folder=Path('/music')
        local=LocalTrack(folder/'file.mp3',SONG['name'],['Journey'],1)
        second={**SONG,'song_id':'b'*22}
        self.assertEqual([r['status'] for r in compare([SONG,second],[local],folder)[0]],['present','review'])


class FileAndSyncTests(unittest.TestCase):
    def test_exclusive_copy_and_disconnected_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'music';folder.mkdir();src=root/'song.mp3';src.write_bytes(b'music')
            identity=folder_identity(folder)
            install_file(src,folder,identity)
            src.write_bytes(b'changed')
            with self.assertRaises(FileExistsError):install_file(src,folder,identity)
            self.assertEqual((folder/'song.mp3').read_bytes(),b'music')
            self.assertFalse(list(folder.glob('*.part')))
            folder.rename(root/'old');folder.mkdir()
            with self.assertRaises(ValueError):install_file(src,folder,identity)
            self.assertFalse(list(folder.iterdir()))

    def test_clean_names_preserve_distinct_tracks_and_existing_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'music';folder.mkdir()
            src=root/f"Artist - Title [{SONG['song_id']}].mp3"
            src.write_bytes(b'new music')
            name=clean_filename(src.name)
            self.assertEqual(name,'Artist - Title.mp3')
            self.assertEqual(clean_filename('Artist - Title [Live].mp3'),'Artist - Title [Live].mp3')
            (folder/name).write_bytes(b'keep existing music')
            copied=install_file(src,folder,folder_identity(folder),filename=name)
            self.assertEqual(copied.name,'Artist - Title (2).mp3')
            self.assertEqual((folder/name).read_bytes(),b'keep existing music')
            self.assertEqual(copied.read_bytes(),b'new music')

    def test_staged_verification_sync_is_idempotent_and_preserves_extras(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'music';folder.mkdir();(folder/'keep.txt').write_text('leave me')
            engine=SyncEngine(root/'runtime');engine.folder=folder;engine.identity=folder_identity(folder)
            engine.songs=[copy.deepcopy(SONG)];engine.last_scan=time.time()
            engine.update(phase='ready',scan_id='test');engine.refresh_local()
            def download(command,timeout,logfile,**kwargs):
                manifest=Path(command[command.index('download')+1]);song=json.loads(manifest.read_text())[0]
                make_audio(manifest.parent/f"track [{song['song_id']}].mp3",song)
                return 0
            with patch.object(engine,'run_process',download):
                engine.start_sync('test')
                for _ in range(200):
                    if engine.snapshot()['phase']!='syncing':break
                    time.sleep(.02)
            self.assertEqual(engine.snapshot()['tracks'][0]['status'],'present')
            self.assertEqual(len(list(folder.glob('*.mp3'))),1)
            self.assertEqual(next(folder.glob('*.mp3')).name, 'track.mp3')
            self.assertIn(SONG['song_id'],read_track(next(folder.glob('*.mp3'))).ids)
            self.assertEqual((folder/'keep.txt').read_text(),'leave me')
            with self.assertRaisesRegex(ValueError,'no missing'):engine.start_sync('test')

    def test_bad_artwork_stays_out_of_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'music';folder.mkdir()
            engine=SyncEngine(root/'runtime');engine.folder=folder;engine.identity=folder_identity(folder)
            engine.songs=[copy.deepcopy(SONG)];engine.last_scan=time.time();engine.update(phase='ready',scan_id='test');engine.refresh_local()
            def download(command,timeout,logfile,**kwargs):
                manifest=Path(command[command.index('download')+1]);make_audio(manifest.parent/f"track [{SONG['song_id']}].mp3",art=False)
                return 0
            with patch.object(engine,'run_process',download):
                engine.start_sync('test')
                for _ in range(200):
                    if engine.snapshot()['phase']!='syncing':break
                    time.sleep(.02)
            self.assertEqual(list(folder.iterdir()),[])
            self.assertIn('cover art',engine.snapshot()['errors'][0])


class HTTPTests(unittest.TestCase):
    def test_localhost_csrf_guard_and_invalid_requests(self):
        with tempfile.TemporaryDirectory() as temp:
            server=Server(('127.0.0.1',0),SyncEngine(temp));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                with urlopen(base+'/api/state') as response:data=json.load(response)
                for headers in [{'Content-Type':'application/json'}, {'Content-Type':'application/json','X-Sync-Token':data['token'],'Origin':'https://evil.test'}]:
                    with self.assertRaises(HTTPError) as error:urlopen(Request(base+'/api/stop',data=b'{}',headers=headers))
                    self.assertEqual(error.exception.code,403)
                    error.exception.close()
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base+'/api/check',data=b'{"playlist":"bad","folder":"/tmp"}',headers={'Content-Type':'application/json','X-Sync-Token':data['token']}))
                self.assertEqual(error.exception.code,400)
                error.exception.close()
            finally:server.shutdown();server.server_close();thread.join()

class PlaylistFetchTests(unittest.TestCase):
    def test_complete_listing_and_cache_avoid_redundant_metadata_calls(self):
        from playlist_sync.spotify_fetch import fetch
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'cache.json'
            raw={'name':'Test playlist','content':{'totalCount':2,'items':[
                {'itemV3':{'data':{'uri':'spotify:track:'+SONG['song_id']}}},
                {'itemV3':{'data':{'uri':'spotify:local:unavailable'}}}]}}
            client=Mock();client.get_playlist_info.return_value={'data':{'playlistV2':raw}}
            with patch('playlist_sync.spotify_fetch.SpotifyClient.init'),patch('playlist_sync.spotify_fetch.spotapi.PublicPlaylist',return_value=client),patch('playlist_sync.spotify_fetch.Song.from_url',return_value=Mock(json=copy.deepcopy(SONG))) as metadata:
                first=fetch('https://open.spotify.com/playlist/'+'z'*22,path)
                second=fetch('https://open.spotify.com/playlist/'+'z'*22,path)
                self.assertEqual(metadata.call_count,1)
                self.assertEqual(len(first['songs']),1)
                self.assertEqual(len(second['skipped']),1)
                self.assertEqual(first['total'],2)

    def test_incomplete_playlist_is_never_accepted(self):
        from playlist_sync.spotify_fetch import fetch
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as temp:
            client=Mock();client.get_playlist_info.return_value={'data':{'playlistV2':{'name':'Test','content':{'totalCount':2,'items':[]}}}}
            with patch('playlist_sync.spotify_fetch.SpotifyClient.init'),patch('playlist_sync.spotify_fetch.spotapi.PublicPlaylist',return_value=client):
                with self.assertRaisesRegex(ValueError,'incomplete'):fetch('test',Path(temp)/'cache.json')

class StopTests(unittest.TestCase):
    def test_stopping_job_terminates_subprocess(self):
        import sys
        with tempfile.TemporaryDirectory() as temp:
            engine=SyncEngine(temp);errors=[]
            def run():
                try:engine.run_process([sys.executable,'-c','import time; time.sleep(30)'],60,Path(temp)/'test.log')
                except InterruptedError:errors.append('stopped')
            thread=threading.Thread(target=run);thread.start()
            for _ in range(100):
                if engine.process:break
                time.sleep(.01)
            engine.stop();thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors,['stopped'])
            self.assertIsNone(engine.process)


if __name__=='__main__':
    unittest.main()
