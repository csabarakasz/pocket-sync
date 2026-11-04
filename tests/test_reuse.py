import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from playlist_sync.engine import SyncEngine, folder_identity
from playlist_sync.reuse import ReuseStore
from test_playlist_sync import SONG, make_audio
from test_history import wait


class ReuseTests(unittest.TestCase):
    def setup_destination(self, engine, folder):
        engine.folder = folder
        engine.identity = folder_identity(folder)
        engine.songs = [copy.deepcopy(SONG)]
        engine.last_scan = time.time()
        engine.update(phase='ready', scan_id='reuse-test')
        engine.refresh_local()

    def test_existing_files_discovered_and_copied_after_restart_without_downloader(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); music = root/'music'; music.mkdir(); player = root/'player'; player.mkdir()
            source = music/'Journey - Song.mp3'; make_audio(source)
            engine = SyncEngine(root/'runtime')
            engine.edit_library(engine.library_id, folder=str(music))
            engine.edit_library(engine.library_id, folder=str(player))
            restarted = SyncEngine(root/'runtime')
            restarted.reuse.discover([SONG])
            self.setup_destination(restarted, player)
            self.assertEqual(restarted.snapshot()['tracks'][0]['reuse_file'], str(source))
            with patch.object(restarted, 'run_process', side_effect=AssertionError('Must not download')), patch('playlist_sync.engine.shutil.which', return_value=None):
                restarted.start_sync('reuse-test'); wait(restarted)
            run = restarted.history.list(str(player))[0]
            self.assertEqual(run['status'], 'completed')
            self.assertEqual(run['items'][0]['method'], 'local_copy')
            self.assertEqual(run['items'][0]['source_file'], str(source))
            self.assertEqual((player/source.name).read_bytes(), source.read_bytes())
            self.assertEqual(restarted.snapshot()['tracks'][0]['status'], 'present')
            self.assertFalse(list((root/'runtime'/run['id']).glob('*/*.mp3')))

    def test_missing_or_changed_local_file_falls_back_to_download(self):
        for failure in ('missing', 'corrupt', 'artwork', 'wrong_id'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); music = root/'music'; music.mkdir(); player = root/'player'; player.mkdir()
                source = music/'Original.mp3'; make_audio(source)
                engine = SyncEngine(root/'runtime'); engine.reuse.remember(SONG['song_id'], source)
                if failure == 'missing': source.unlink()
                elif failure == 'corrupt': source.write_bytes(b'broken')
                else:
                    source.unlink()
                    make_audio(source, {**SONG, 'url': 'https://open.spotify.com/track/'+'b'*22} if failure=='wrong_id' else SONG, art=failure!='artwork')
                self.setup_destination(engine, player)
                self.assertNotIn('reuse_file', engine.snapshot()['tracks'][0])
                def download(command, timeout, logfile, **kwargs):
                    make_audio(logfile.parent/f"Downloaded [{SONG['song_id']}].mp3")
                    logfile.write_text('Downloaded')
                    return 0
                with patch.object(engine, 'run_process', side_effect=download) as downloader:
                    engine.start_sync('reuse-test'); wait(engine)
                    self.assertEqual(downloader.call_count, 1)
                self.assertEqual(engine.history.list(str(player))[0]['items'][0]['method'], 'download')

    def test_choose_recording_forces_new_audio_even_with_local_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); player=root/'player'; player.mkdir(); source=root/'Source.mp3'; make_audio(source)
            engine=SyncEngine(root/'runtime'); engine.reuse.remember(SONG['song_id'], source)
            self.setup_destination(engine, player)
            def download(command, timeout, logfile, **kwargs):
                manifest=Path(command[command.index('download')+1])
                exported=json.loads(manifest.read_text())[0]
                self.assertEqual(exported['download_url'], 'https://www.youtube.com/watch?v=abcdefghijk')
                self.assertNotIn('_force_download', exported)
                self.assertFalse(any(key.startswith('_') for key in exported))
                make_audio(logfile.parent/f"New [{SONG['song_id']}].mp3"); logfile.write_text('Downloaded'); return 0
            with patch.object(engine, 'run_process', side_effect=download) as downloader:
                engine.start_sync('reuse-test', sources={SONG['song_id']:'https://youtu.be/abcdefghijk'}); wait(engine)
                self.assertEqual(downloader.call_count, 1)

    def test_metadata_match_without_embedded_id_is_reusable_but_wrong_album_is_not(self):
        from mutagen.mp3 import MP3
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); store=ReuseStore(root); song=root/'Old file.mp3'; make_audio(song)
            audio=MP3(song); audio.tags.delall('WOAS'); audio.save()
            store.register(root); store.discover([SONG])
            self.assertEqual(store.find(SONG, root/'player'), song)
            self.assertIsNone(store.find({**SONG, 'album_name':'Other album'}, root/'player'))
