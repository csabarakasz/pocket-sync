import copy,io,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from mutagen.mp3 import MP3
from mutagen.id3 import TXXX
from playlist_sync.compilations import TAG,coverage,playlist_url,inspect_playlist,start_compilation,import_identity
from playlist_sync.engine import SyncEngine,folder_identity
from playlist_sync.library import read_track,compare
from test_playlist_sync import SONG,make_audio

class CompilationTests(unittest.TestCase):
    def prepare(self,root):
        folder=root/'player';folder.mkdir();engine=SyncEngine(root/'runtime')
        engine.edit_library(engine.library_id,folder=str(folder));engine.folder=folder;engine.identity=folder_identity(folder)
        engine.songs=[copy.deepcopy(SONG),{**SONG,'song_id':'b'*22,'name':'Story, Pt. 2','url':'https://open.spotify.com/track/'+'b'*22}]
        engine.songs[0]['cover_url']='https://i.scdn.co/image/test';engine.last_scan=time.time()
        engine.update(phase='ready',scan_id='test');engine.refresh_local()
        plan={'id':'plan','library_id':engine.library_id,'scan_id':'test','created':time.time(),
              'title':'Complete story','url':'https://www.youtube.com/playlist?list=PLabcdefghijk',
              'videos':[{'id':'abcdefghijk','title':'Part 1','duration':1,'url':'https://www.youtube.com/watch?v=abcdefghijk'},
                        {'id':'12345678901','title':'Part 2','duration':1,'url':'https://www.youtube.com/watch?v=12345678901'}]}
        engine.compilation_plan=plan
        return engine

    def test_combined_file_covers_tracks_and_reuses_once_after_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);engine=self.prepare(root);original=engine.run_process
            def process(command,timeout,logfile,**kwargs):
                if command[0]=='ffmpeg':return original(command,timeout,logfile,**kwargs)
                part=Path(command[command.index('-o')+1].replace('%(ext)s','mp3'));make_audio(part);logfile.write_text('Downloaded');return 0
            art=io.BytesIO();Image.new('RGB',(20,20),'red').save(art,format='JPEG')
            with patch.object(engine,'run_process',side_effect=process),patch('playlist_sync.compilations.urlopen',return_value=io.BytesIO(art.getvalue())):
                start_compilation(engine,{'plan_id':'plan','ids':['a'*22,'b'*22],'confirmed':True})
                engine.worker.join(15)
            run=engine.history.list()[0]
            self.assertEqual(run['status'],'completed',run)
            self.assertEqual(run['added'],1)
            self.assertEqual([x['status'] for x in engine.snapshot()['tracks']],['present','present'])
            files=list(engine.folder.glob('*.mp3'));self.assertEqual(len(files),1)
            self.assertEqual(read_track(files[0]).group_ids,{'a'*22,'b'*22})
            self.assertIsNotNone(import_identity(MP3(files[0])))
            self.assertEqual([i['status'] for i in run['items']],['covered','covered'])
            self.assertTrue(Path(run['items'][0]['source_file']).exists())
            self.assertIn('Part 1:',engine.history.log(run['id'],'b'*22))
            other=root/'second player';other.mkdir()
            restarted=SyncEngine(engine.runtime);restarted.edit_library(restarted.library_id,folder=str(other))
            restarted.folder=other;restarted.identity=folder_identity(other);restarted.songs=engine.songs;restarted.last_scan=time.time()
            restarted.update(phase='ready',scan_id='reuse');restarted.refresh_local()
            with patch.object(restarted,'run_process',side_effect=AssertionError('Must reuse combined master')):
                restarted.start_sync('reuse');restarted.worker.join(15)
            self.assertEqual(restarted.snapshot()['phase'],'ready')
            self.assertEqual(len(list(other.glob('*.mp3'))),1)
            self.assertEqual([x['status'] for x in restarted.snapshot()['tracks']],['present','present'])
            audio=MP3(files[0]);meta=json.loads(audio.tags['TXXX:'+TAG].text[0]);meta['duration']=999
            audio.tags.add(TXXX(desc=TAG,text=json.dumps(meta)));audio.save()
            self.assertEqual(coverage(MP3(files[0])),set())

    def test_confirmation_required_and_failed_part_never_covers_tracks(self):
        with tempfile.TemporaryDirectory() as temp:
            engine=self.prepare(Path(temp))
            with self.assertRaisesRegex(ValueError,'Confirm'):start_compilation(engine,{'plan_id':'plan','ids':['a'*22]})
            def fail(command,timeout,logfile,**kwargs):logfile.write_text('Unavailable');return 1
            with patch.object(engine,'run_process',side_effect=fail):
                start_compilation(engine,{'plan_id':'plan','ids':['a'*22,'b'*22],'confirmed':True});engine.worker.join(10)
            self.assertEqual(list(engine.folder.glob('*.mp3')),[])
            self.assertEqual([x['status'] for x in engine.snapshot()['tracks']],['missing','missing'])
            self.assertEqual(engine.history.list()[0]['status'],'failed')

    def test_playlist_url_validation_and_whole_playlist_from_watch_link(self):
        self.assertEqual(playlist_url('https://www.youtube.com/watch?v=abcdefghijk&list=PLabcdefghijk'), 'https://www.youtube.com/playlist?list=PLabcdefghijk')
        for url in ['https://evil.example/?list=PLabcdefghijk','https://youtube.com/watch?v=abcdefghijk','file:///etc/passwd']:
            with self.assertRaises(ValueError):playlist_url(url)
