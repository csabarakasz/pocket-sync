import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from playlist_sync.engine import SyncEngine, folder_identity
from playlist_sync.history import HistoryStore, download_failure, youtube_url
from test_playlist_sync import SONG, make_audio


def wait(engine):
    for _ in range(300):
        if engine.snapshot()['phase']!='syncing':return
        time.sleep(.02)
    raise AssertionError('Sync did not finish')


class HistoryTests(unittest.TestCase):
    def test_search_failure_explains_spotify_link_and_persists_across_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'music';folder.mkdir()
            engine=SyncEngine(root/'runtime');engine.folder=folder;engine.identity=folder_identity(folder)
            engine.songs=[copy.deepcopy(SONG)];engine.last_scan=time.time();engine.update(phase='ready',scan_id='test');engine.refresh_local()
            def download(command,timeout,logfile,**kwargs):
                logfile.write_text('1/1 complete\nLookupError: No results found for song: Journey - Example\n')
                return 0
            with patch.object(engine,'run_process',download):
                engine.start_sync('test');wait(engine)
            run=engine.history.list(str(folder))[0]
            self.assertEqual(run['status'],'issues')
            self.assertEqual(run['items'][0]['error_code'],'no_match')
            self.assertIn('Spotify link',run['items'][0]['help'])
            self.assertNotIn('Audio file missing',run['items'][0]['message'])
            self.assertEqual(list(folder.iterdir()),[])
            restarted=SyncEngine(root/'runtime');restarted.folder=folder;restarted.identity=folder_identity(folder);restarted.songs=[copy.deepcopy(SONG)];restarted.refresh_local()
            self.assertEqual(restarted.history.list()[0]['items'][0]['status'],'failed')
            self.assertIn('YouTube',restarted.snapshot()['tracks'][0]['error'])

    def test_completed_history_records_exact_filename_and_verified_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'music';folder.mkdir()
            engine=SyncEngine(root/'runtime');engine.folder=folder;engine.identity=folder_identity(folder)
            engine.songs=[copy.deepcopy(SONG)];engine.last_scan=time.time();engine.update(phase='ready',scan_id='test');engine.refresh_local()
            def download(command,timeout,logfile,**kwargs):
                manifest=Path(command[command.index('download')+1]);song=json.loads(manifest.read_text())[0]
                self.assertEqual(song['download_url'],'https://www.youtube.com/watch?v=abcdefghijk')
                make_audio(manifest.parent/f"Example [{song['song_id']}].mp3",song)
                logfile.write_text('Downloaded: https://www.youtube.com/watch?v=abcdefghijk')
                return 0
            with patch.object(engine,'run_process',download):
                engine.start_sync('test',sources={SONG['song_id']:'https://youtu.be/abcdefghijk'});wait(engine)
            run=HistoryStore(root/'runtime').list()[0]
            self.assertEqual(run['status'],'completed')
            self.assertEqual(run['counts'],{'added':1})
            self.assertEqual(run['items'][0]['file'],str(folder/'Example.mp3'))
            self.assertTrue(run['items'][0]['verified'])
            self.assertTrue(run['started_at']);self.assertTrue(run['finished_at'])
            saved=json.loads((root/'runtime'/'recordings.json').read_text())
            self.assertEqual(saved[SONG['song_id']]['url'],'https://www.youtube.com/watch?v=abcdefghijk')
            # A later sync to the player's folder reuses the verified choice.
            other=root/'player';other.mkdir()
            restarted=SyncEngine(root/'runtime');restarted.folder=other;restarted.identity=folder_identity(other)
            restarted.songs=[copy.deepcopy(SONG)];restarted.last_scan=time.time();restarted.update(phase='ready',scan_id='again');restarted.refresh_local()
            with patch.object(restarted,'run_process',download):
                restarted.start_sync('again');wait(restarted)
            self.assertEqual(restarted.history.list(str(other))[0]['status'],'completed')
            self.assertTrue((other/'Example.mp3').exists())


    def test_interrupted_history_does_not_report_unattempted_songs_as_completed(self):
        with tempfile.TemporaryDirectory() as temp:
            store=HistoryStore(temp)
            run={'id':'a'*32,'status':'running','started_at':'2026-11-03T12:00:00+01:00','items':[
                {'id':'a'*22,'status':'added'}, {'id':'b'*22,'status':'downloading'}, {'id':'c'*22,'status':'queued'}]}
            store.save(run)
            recovered=HistoryStore(temp).list()[0]
            self.assertEqual(recovered['status'],'interrupted')
            self.assertEqual([x['status'] for x in recovered['items']],['added','interrupted','not_attempted'])

    def test_legacy_report_import_uses_only_attempted_tracks_and_tracks_renames(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);job=root/('d'*32);stage=job/SONG['song_id'];stage.mkdir(parents=True)
            (stage/'track.spotdl').write_text(json.dumps([SONG]))
            (stage/'download.log').write_text('Downloaded: https://www.youtube.com/watch?v=abcdefghijk')
            (job/'report.json').write_text(json.dumps({'time':'2026-11-03T12:00:00+01:00','folder':'/music','added':1,'errors':[],
                 'tracks':[{'id':SONG['song_id'],'file':'Old [id].mp3','status':'present'},{'id':'z'*22,'file':'unrelated.mp3','status':'present'}]}))
            (root/'filename-cleanup-test.json').write_text(json.dumps([{'before':'/music/Old [id].mp3','after':'/music/Clean.mp3','status':'renamed'}]))
            store=HistoryStore(root);run=store.list()[0]
            self.assertEqual(len(run['items']),1)
            self.assertEqual(run['items'][0]['file'],'/music/Clean.mp3')
            self.assertEqual(run['items'][0]['status'],'added')
            self.assertEqual(len(HistoryStore(root).list()),1)
            with self.assertRaises(ValueError):store.log('../other',SONG['song_id'])

    def test_source_validation_and_failure_diagnostics(self):
        self.assertEqual(youtube_url('https://youtu.be/abcdefghijk?t=12'),'https://www.youtube.com/watch?v=abcdefghijk')
        for value in ['http://localhost/video','https://youtube.com.evil.test/watch?v=abcdefghijk','https://www.youtube.com/playlist?list=x']:
            with self.assertRaises(ValueError):youtube_url(value)
        self.assertEqual(download_failure('ERROR: Sign in to confirm you are not a bot')['code'],'source_blocked')
        self.assertEqual(download_failure('', ['Missing embedded cover art'])['code'],'verification')


if __name__=='__main__':unittest.main()
