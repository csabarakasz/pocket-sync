import copy,io,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from PIL import Image
from mutagen.mp3 import MP3
from playlist_sync.compilations import inspect_playlist,start_custom,custom_catalog,import_identity
from playlist_sync.engine import SyncEngine
from playlist_sync.library import read_track
from test_playlist_sync import make_audio

class CustomAudioTests(unittest.TestCase):
    def test_import_without_spotify_and_reuse_and_duplicate_detection(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);destination=root/'player';destination.mkdir();engine=SyncEngine(root/'runtime')
            self.assertIsNone(engine.state['scan_id']);self.assertEqual(engine.songs,[])
            listing={'title':'A complete book','uploader':'The author','entries':[
                {'id':'abcdefghijk','title':'Part 1','duration':1},{'id':'12345678901','title':'Part 2','duration':1}]}
            with patch('playlist_sync.compilations.subprocess.run',return_value=Mock(returncode=0,stdout=json.dumps(listing))):
                plan=inspect_playlist(engine,'https://youtube.com/playlist?list=PLabcdefghijk',custom=True)
            original=engine.run_process
            def process(command,timeout,logfile,**kwargs):
                if command[0]=='ffmpeg':return original(command,timeout,logfile,**kwargs)
                make_audio(Path(command[command.index('-o')+1].replace('%(ext)s','mp3')));logfile.write_text('Downloaded');return 0
            art=io.BytesIO();Image.new('RGB',(20,20),'blue').save(art,format='JPEG')
            data={'plan_id':plan['id'],'folder':str(destination),'title':'My Book','author':'Author','album':'Book collection'}
            with patch.object(engine,'run_process',side_effect=process),patch('playlist_sync.compilations.urlopen',return_value=io.BytesIO(art.getvalue())):
                start_custom(engine,data);engine.worker.join(15)
            run=engine.history.list(library_id='custom')[0]
            self.assertEqual(run['status'],'completed',run)
            self.assertEqual(engine.snapshot()['phase'],'ready')
            file=Path(run['items'][0]['file']);self.assertTrue(file.exists())
            self.assertEqual(read_track(file).import_id,plan['source_id'])
            self.assertEqual(str(MP3(file).tags['TIT2']),'My Book')
            self.assertEqual(len(engine.snapshot()['custom_imports']),1)
            renamed=destination/'renamed.mp3';file.rename(renamed)
            with self.assertRaisesRegex(ValueError,'already in'):start_custom(engine,data)
            other=root/'second player';other.mkdir();restarted=SyncEngine(root/'runtime')
            restarted.custom_plan={**plan,'library_id':restarted.library_id,'created':time.time()}
            with patch.object(restarted,'run_process',side_effect=AssertionError('Must copy locally')):
                start_custom(restarted,{**data,'folder':str(other),'title':'New title'});restarted.worker.join(15)
            copied=list(other.glob('*.mp3'));self.assertEqual(len(copied),1)
            self.assertEqual(str(MP3(copied[0]).tags['TIT2']),'New title')
            self.assertEqual(import_identity(MP3(copied[0])),plan['source_id'])
            self.assertEqual(restarted.history.list(library_id='custom')[0]['items'][0]['method'],'local_copy')
            self.assertIsNone(restarted.snapshot()['scan_id'])

    def test_single_video_and_metadata_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);engine=SyncEngine(root/'runtime')
            with patch('playlist_sync.compilations.subprocess.run',return_value=Mock(returncode=0,stdout=json.dumps({'id':'abcdefghijk','title':'One story','duration':20,'channel':'Narrator'}))):
                plan=inspect_playlist(engine,'https://youtu.be/abcdefghijk',custom=True)
            self.assertEqual(len(plan['videos']),1);self.assertEqual(plan['author'],'Narrator')
            with self.assertRaisesRegex(ValueError,'title, author'):
                start_custom(engine,{'plan_id':plan['id'],'folder':str(root),'title':'Story','author':''})
