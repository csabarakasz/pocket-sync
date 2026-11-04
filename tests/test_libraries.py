import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock,patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen
import threading

from playlist_sync.engine import SyncEngine,folder_identity
from playlist_sync.history import HistoryStore
from playlist_sync.libraries import LibraryStore,choose_folder
from playlist_sync.server import Server
from test_playlist_sync import SONG

LINK_A='https://open.spotify.com/playlist/'+'a'*22
LINK_B='https://open.spotify.com/playlist/'+'b'*22
LINK_C='https://open.spotify.com/playlist/'+'c'*22


def load_comparison(engine,folder,scan_id,song):
    engine.folder=folder;engine.identity=folder_identity(folder);engine.songs=[copy.deepcopy(song)]
    engine.last_scan=time.time();engine.update(phase='ready',scan_id=scan_id);engine.refresh_local()


class LibraryTests(unittest.TestCase):
    def test_new_install_starts_with_an_unconfigured_library(self):
        with tempfile.TemporaryDirectory() as temp:
            engine = SyncEngine(temp)
            state = engine.snapshot()
            self.assertEqual(state['library']['name'], 'Your music')
            self.assertEqual(state['settings'], {'playlist': '', 'folder': ''})
            self.assertFalse(state['folder_available'])

            folder = Path(temp) / 'music'
            folder.mkdir()
            engine.edit_library(engine.library_id, playlist=LINK_A, folder=str(folder))
            reopened = SyncEngine(temp)
            self.assertEqual(reopened.snapshot()['settings'], {'playlist': LINK_A, 'folder': str(folder)})

    def test_migration_and_multiple_libraries_persist_names_and_folders(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);a=root/'Primary';a.mkdir();b=root/'Second';b.mkdir()
            store=LibraryStore(root,{'playlist':LINK_A,'folder':str(a)})
            primary=store.get();second=store.add('Second music',LINK_B,str(b));books=store.add('Primary stories',LINK_C)
            store.select(second['id']);store.update(second['id'],name='Second’s favourites')
            loaded=LibraryStore(root,{'playlist':'ignored','folder':'ignored'})
            self.assertEqual(len(loaded.list()),3)
            self.assertEqual(loaded.get()['name'],'Second’s favourites')
            self.assertEqual(loaded.get(primary['id'])['folder'],str(a))
            self.assertEqual(loaded.get(books['id'])['folder'],'')
            with self.assertRaisesRegex(ValueError,'already saved'):loaded.add('duplicate',LINK_B)

    def test_switching_restores_comparisons_and_rename_does_not_clear_them(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);a=root/'a';a.mkdir();b=root/'b';b.mkdir()
            engine=SyncEngine(root/'runtime');primary=engine.library_id;engine.edit_library(primary,folder=str(a))
            load_comparison(engine,a,'primary-check',SONG)
            second=engine.add_library('Second',LINK_B,str(b))
            self.assertEqual(engine.snapshot()['tracks'],[])
            self.assertEqual(engine.snapshot()['settings']['folder'],str(b))
            load_comparison(engine,b,'second-check',{**SONG,'song_id':'b'*22,'name':'Another'})
            engine.select_library(primary)
            self.assertEqual(engine.snapshot()['scan_id'],'primary-check')
            self.assertEqual(engine.songs[0]['song_id'],SONG['song_id'])
            engine.edit_library(primary,name='Primary favourites')
            self.assertEqual(engine.snapshot()['scan_id'],'primary-check')
            engine.select_library(second['id'])
            self.assertEqual(engine.snapshot()['scan_id'],'second-check')
            self.assertEqual(engine.songs[0]['name'],'Another')

    def test_destination_change_invalidates_comparison_but_retains_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);a=root/'a';a.mkdir();b=root/'b';b.mkdir()
            engine=SyncEngine(root/'runtime');library=engine.library_id;engine.edit_library(library,folder=str(a))
            load_comparison(engine,a,'checked',SONG)
            engine.history.save({'id':'f'*32,'library_id':library,'folder':str(a),'status':'completed','started_at':'2026-11-03T10:00:00+01:00','items':[],'added':0})
            engine.edit_library(library,folder=str(b))
            self.assertIsNone(engine.snapshot()['scan_id'])
            self.assertEqual(engine.snapshot()['tracks'],[])
            self.assertEqual(len(engine.history.list(library_id=library)),1)
            self.assertEqual(engine.snapshot()['last_sync']['folder'],str(a))

    def test_history_is_separate_even_when_two_libraries_share_a_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            store=HistoryStore(temp)
            for ident,library in [('a'*32,'primary'),('b'*32,'second')]:
                store.save({'id':ident,'library_id':library,'folder':'/same','status':'issues','finished_at':'2026-11-03T10:00:00+01:00','items':[
                    {'id':SONG['song_id'],'status':'failed','message':library}]})
            self.assertEqual(len(store.list('/same',library_id='primary')),1)
            self.assertEqual(store.latest_failures('/same','second')[SONG['song_id']]['message'],'second')

    def test_switching_or_editing_during_a_job_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            engine=SyncEngine(temp);primary=engine.library_id;second=engine.add_library('Second',LINK_B)
            engine.state['phase']='syncing'
            with self.assertRaises(ValueError):engine.select_library(primary)
            with self.assertRaises(ValueError):engine.edit_library(second['id'],name='Changed')
            with self.assertRaises(ValueError):engine.add_library('Books',LINK_C)
            self.assertEqual(engine.library_id,second['id'])

    def test_invalid_scan_does_not_leave_app_stuck_checking(self):
        with tempfile.TemporaryDirectory() as temp:
            engine=SyncEngine(temp);engine.add_library('Second',LINK_B)
            engine.select_library(engine.libraries.list()[0]['id'])
            with self.assertRaisesRegex(ValueError,'already saved'):engine.start_scan(LINK_B,temp)
            self.assertEqual(engine.snapshot()['phase'],'idle')

    def test_folder_picker_cancel_keeps_saved_folder_and_unlocks_app(self):
        with tempfile.TemporaryDirectory() as temp:
            engine=SyncEngine(temp);before=engine.snapshot()['settings']['folder']
            with patch('playlist_sync.engine.choose_folder',return_value=None):
                self.assertIsNone(engine.select_folder(before,engine.library_id))
            self.assertFalse(engine.choosing_folder)
            self.assertEqual(engine.snapshot()['settings']['folder'],before)

    def test_native_picker_passes_paths_as_arguments_and_handles_cancel(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch('playlist_sync.libraries.sys.platform','darwin'),patch('playlist_sync.libraries.folder_picker_binary',return_value=Path('/test/Picker')),patch('playlist_sync.libraries.subprocess.run',return_value=Mock(returncode=0,stdout=json.dumps({'path':temp}),stderr='')) as run:
                self.assertEqual(choose_folder(temp),temp)
                self.assertEqual(run.call_args.args[0],['/test/Picker',temp])
            with patch('playlist_sync.libraries.sys.platform','darwin'),patch('playlist_sync.libraries.folder_picker_binary',return_value=Path('/test/Picker')),patch('playlist_sync.libraries.subprocess.run',return_value=Mock(returncode=0,stdout='{"path":null}',stderr='')):
                self.assertIsNone(choose_folder(temp))

    def test_old_settings_and_history_migrate_to_the_original_library(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'music';folder.mkdir()
            (root/'settings.json').write_text(json.dumps({'playlist':LINK_A,'folder':str(folder)}))
            history=HistoryStore(root)
            history.save({'id':'a'*32,'folder':str(folder),'status':'completed','started_at':'2026-11-03T10:00:00+01:00','added':1,'items':[]})
            engine=SyncEngine(root);original=engine.library_id
            engine.add_library('Second',LINK_B,str(folder))
            self.assertEqual(len(engine.history.list(library_id=original)),1)
            self.assertEqual(len(engine.history.list(library_id=engine.library_id)),0)

    def test_stale_browser_request_cannot_change_the_wrong_library(self):
        with tempfile.TemporaryDirectory() as temp:
            engine=SyncEngine(temp);old=engine.library_id
            server=Server(('127.0.0.1',0),engine);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                engine.add_library('Second',LINK_B)
                req=Request(base+'/api/check',data=json.dumps({'library_id':old,'playlist':LINK_A,'folder':temp}).encode(),headers={'Content-Type':'application/json','X-Sync-Token':server.token})
                with self.assertRaises(HTTPError) as error:urlopen(req)
                self.assertEqual(error.exception.code,400);error.exception.close()
                self.assertEqual(engine.libraries.get()['playlist'],LINK_B)
                self.assertEqual(engine.snapshot()['phase'],'idle')
            finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
