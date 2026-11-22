import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from playlist_sync.library import FileIndex, LocalTrack, scan_folder, compare
from playlist_sync.playback import update_playlist, PLAYLIST
from playlist_sync.engine import install_file, folder_identity


class OptimizationTests(unittest.TestCase):
    def test_tag_cache_persists_and_invalidates_on_file_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); folder = root/'music'; folder.mkdir()
            track = folder/'song.mp3'; track.write_bytes(b'first')
            cache = FileIndex(root/'index.json')
            with patch('playlist_sync.library.read_track', side_effect=lambda p: LocalTrack(p, title='Song')) as read:
                scan_folder(folder, cache)
                scan_folder(folder, FileIndex(cache.path))
                self.assertEqual(read.call_count, 1)
                track.write_bytes(b'changed audio')
                scan_folder(folder, cache)
                self.assertEqual(read.call_count, 2)
                track.unlink()
                self.assertEqual(scan_folder(folder, cache), [])

    def test_order_survives_two_batches_collision_and_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); folder = root/'music'; folder.mkdir()
            (folder/'Zebra.mp3').write_bytes(b'old')
            source = root/'source.mp3'; source.write_bytes(b'new')
            identity = folder_identity(folder)
            install_file(source, folder, identity, filename='Alpha.mp3')
            install_file(source, folder, identity, filename='Aardvark.mp3')
            install_file(source, folder, identity, filename='Alpha.mp3')
            self.assertEqual(update_playlist(folder), ['Zebra.mp3', 'Alpha.mp3', 'Aardvark.mp3', 'Alpha (2).mp3'])
            (folder/'Alpha.mp3').unlink()
            self.assertEqual(update_playlist(folder), ['Zebra.mp3', 'Aardvark.mp3', 'Alpha (2).mp3'])
            self.assertEqual((folder/'Zebra.mp3').read_bytes(), b'old')

    def test_playlist_rejects_traversal_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); music=root/'music';music.mkdir()
            (root/'outside.mp3').write_bytes(b'outside')
            (music/'link.mp3').symlink_to(root/'outside.mp3')
            (music/PLAYLIST).write_text('#EXTM3U\n../outside.mp3\nlink.mp3\n')
            self.assertEqual(update_playlist(music), [])

    def test_expired_metadata_does_not_block_check_but_marks_for_refresh(self):
        from playlist_sync.spotify_fetch import fetch
        from test_playlist_sync import SONG
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'cache.json'
            path.write_text(json.dumps({SONG['song_id']:{'fetched_at':time.time()-10*86400,'song':SONG}}))
            raw={'name':'Changed playlist','content':{'totalCount':1,'items':[{'itemV3':{'data':{'uri':'spotify:track:'+SONG['song_id']}}}]}}
            client=Mock();client.get_playlist_info.return_value={'data':{'playlistV2':raw}}
            with patch('playlist_sync.spotify_fetch.SpotifyClient.init'),patch('playlist_sync.spotify_fetch.spotapi.PublicPlaylist',return_value=client),patch('playlist_sync.spotify_fetch.Song.from_url') as metadata:
                result=fetch('test',path)
                metadata.assert_not_called()
                self.assertTrue(result['songs'][0]['_metadata_stale'])
                self.assertEqual(result['songs'][0]['list_name'],'Changed playlist')

    def test_twenty_second_comparison_boundary(self):
        song={'song_id':'a'*22,'name':'Song','artists':['Artist'],'duration':100,'album_name':'Album','url':'test'}
        local=LocalTrack(Path('/music/Song.mp3'),title='Song',artists=['Artist'],duration=120,ids={song['song_id']})
        self.assertEqual(compare([song],[local],Path('/music'))[0][0]['status'],'present')
        local.duration=120.01
        self.assertEqual(compare([song],[local],Path('/music'))[0][0]['status'],'review')

    def test_audit_twenty_second_boundary(self):
        from download import audit
        song={'song_id':'id','name':'Song','artists':['Artist'],'duration':100,'album_name':'Album'}
        audio=Mock();audio.info.length=120
        audio.tags={'TIT2':'Song','TPE1':'Artist','TALB':'Album','TRCK':'1','TDRC':'2026'}
        class Tags(dict):
            def getall(self,key): return [Mock(data=b'cover')]
        audio.tags=Tags(audio.tags)
        with patch('mutagen.mp3.MP3',return_value=audio):
            self.assertEqual(audit(Path('/tmp'),[song],{'id':'/tmp/audio.mp3'})[0]['issues'],[])
            audio.info.length=120.01
            self.assertIn('Duration differs by more than 20 seconds; check recording version',audit(Path('/tmp'),[song],{'id':'/tmp/audio.mp3'})[0]['issues'])

    def test_stale_metadata_refresh_preserves_manual_url_and_continues_after_failure(self):
        from playlist_sync.engine import SyncEngine
        from test_playlist_sync import SONG, make_audio
        from test_history import wait
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); folder=root/'player';folder.mkdir()
            songs=[dict(copy.deepcopy(SONG),song_id='a'*22,name='First',_metadata_stale=True),
                   dict(copy.deepcopy(SONG),song_id='b'*22,name='Second',_metadata_stale=True)]
            for song in songs:song['url']='https://open.spotify.com/track/'+song['song_id']
            engine=SyncEngine(root/'runtime');engine.folder=folder;engine.identity=folder_identity(folder)
            engine.songs=songs;engine.last_scan=time.time();engine.update(phase='ready',scan_id='test')
            engine.refresh_local()
            def process(command,timeout,logfile,**kwargs):
                if '--track' in command:
                    sid=command[command.index('--track')+1]
                    if sid=='a'*22:return 1
                    fresh=dict(songs[1],download_url=None);fresh.pop('_metadata_stale')
                    Path(command[-1]).write_text(json.dumps(fresh));return 0
                manifest=Path(command[command.index('download')+1]);song=json.loads(manifest.read_text())[0]
                self.assertEqual(song['download_url'],'https://www.youtube.com/watch?v=abcdefghijk')
                self.assertFalse(any(k.startswith('_') for k in song))
                make_audio(logfile.parent/f"Second [{song['song_id']}].mp3",song)
                logfile.write_text('Downloaded');return 0
            with patch.object(engine,'run_process',side_effect=process):
                engine.start_sync('test',[s['song_id'] for s in songs],{s['song_id']:'https://youtu.be/abcdefghijk' for s in songs})
                wait(engine)
            run=engine.history.list()[0]
            self.assertEqual([x['status'] for x in run['items']],['failed','added'])
            self.assertEqual(engine.state['tracks'][1]['status'],'present')
            self.assertEqual(len(list(folder.glob('*.mp3'))),1)

    def test_clean_installer_copy_preserves_executable_permission(self):
        import os
        from scripts.install_desktop_app import copy_clean
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'launcher';target=root/'installed'
            source.write_bytes(b'#!/bin/sh\nexit 0\n');source.chmod(0o755)
            copy_clean(source,target)
            self.assertTrue(os.access(target,os.X_OK))
            self.assertEqual(target.read_bytes(),source.read_bytes())

    def test_filename_order_migration_and_two_appended_batches(self):
        from playlist_sync.ordering import preview,apply,load
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'player';folder.mkdir()
            names=['01_One Thing.mp3','02_Party.mp3','Zebra.mp3']
            original={name:('audio:'+name).encode() for name in names}
            for name,content in original.items():(folder/name).write_bytes(content)
            plan=preview(folder);mapping,journal=apply(folder,plan,lambda:None)
            self.assertEqual(list(mapping),names)
            for old,new in mapping.items():self.assertEqual((folder/new).read_bytes(),original[old])
            source=Path(temp)/'Alpha.mp3';source.write_bytes(b'new')
            identity=folder_identity(folder)
            first=install_file(source,folder,identity,filename='Alpha.mp3')
            second=install_file(source,folder,identity,filename='Aardvark.mp3')
            self.assertEqual(first.name,'004 - Alpha.mp3');self.assertEqual(second.name,'005 - Aardvark.mp3')
            second.unlink()
            third=install_file(source,folder,identity,filename='Another.mp3')
            self.assertEqual(third.name,'006 - Another.mp3')
            self.assertEqual(json.loads(journal.read_text())['status'],'completed')
            self.assertEqual(load(folder)['last_number'],6)
            self.assertEqual(update_playlist(folder),list(mapping.values())+[first.name,third.name])

    def test_numbering_rejects_changed_preview_and_new_unnumbered_files(self):
        from playlist_sync.ordering import preview,apply,next_filename
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);(folder/'Original.mp3').write_bytes(b'original')
            plan=preview(folder);(folder/'Changed.mp3').write_bytes(b'new')
            with self.assertRaisesRegex(ValueError,'changed'):apply(folder,plan,lambda:None)
            apply(folder,preview(folder),lambda:None)
            (folder/'External.mp3').write_bytes(b'external')
            with self.assertRaisesRegex(ValueError,'Unnumbered'):next_filename(folder,'Next.mp3')

    def test_numbering_rollback_on_failed_rename_keeps_original_bytes(self):
        from playlist_sync.ordering import preview,apply,STATE
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);(folder/'One.mp3').write_bytes(b'one');(folder/'Two.mp3').write_bytes(b'two')
            original=Path.replace
            def fail(source,target):
                if Path(target).suffix=='.mp3' and Path(target).name.startswith('002'):raise OSError('simulated copy error')
                return original(source,target)
            with patch.object(Path,'replace',fail):
                with self.assertRaises(OSError):apply(folder,preview(folder),lambda:None)
            self.assertEqual((folder/'One.mp3').read_bytes(),b'one');self.assertEqual((folder/'Two.mp3').read_bytes(),b'two')
            self.assertFalse((folder/STATE).exists());self.assertFalse(list(folder.glob('[0-9][0-9][0-9] - *.mp3')))

    def test_numbering_updates_manual_matches_history_and_reuse_references(self):
        from playlist_sync.ordering import rewrite_references
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'player';folder.mkdir();runtime=root/'runtime';runtime.mkdir()
            (runtime/'matches.json').write_text(json.dumps({str(folder):{'song':{'file':'Old.mp3','fingerprint':'abc'}}}))
            job=runtime/'job';job.mkdir();(job/'history.json').write_text(json.dumps({'items':[{'file':str(folder/'Old.mp3')}]}))
            (runtime/'local-files.json').write_text(json.dumps({'tracks':{'song':[str(folder/'Old.mp3')]}}))
            backup=rewrite_references(runtime,folder,{'Old.mp3':'001 - Old.mp3'})
            self.assertEqual(json.loads((runtime/'matches.json').read_text())[str(folder)]['song']['file'],'001 - Old.mp3')
            self.assertEqual(json.loads((job/'history.json').read_text())['items'][0]['file'],str(folder/'001 - Old.mp3'))
            self.assertEqual(json.loads((backup/'matches.json').read_text())[str(folder)]['song']['file'],'Old.mp3')

    def test_numbering_can_restore_exact_original_names_and_bytes(self):
        from playlist_sync.ordering import preview,apply,restore,STATE
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);original={'01_Song.mp3':b'one','Artist - Song.mp3':b'two'}
            for name,data in original.items():(folder/name).write_bytes(data)
            mapping,journal=apply(folder,preview(folder),lambda:None)
            reverse=restore(folder,journal,lambda:None)
            self.assertEqual(reverse,{v:k for k,v in mapping.items()})
            for name,data in original.items():self.assertEqual((folder/name).read_bytes(),data)
            self.assertFalse((folder/STATE).exists())

    def test_numbering_handles_hungarian_unicode_names(self):
        from playlist_sync.ordering import preview,apply,restore
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);name='DICS-SULI - Tena\u0301lad Van Otthonom.mp3'
            (folder/name).write_bytes(b'original audio')
            mapping,journal=apply(folder,preview(folder),lambda:None)
            self.assertEqual((folder/mapping[name]).read_bytes(),b'original audio')
            restore(folder,journal,lambda:None)
            self.assertEqual((folder/name).read_bytes(),b'original audio')

    def test_fat_rename_retries_equivalent_unicode_forms(self):
        from playlist_sync.ordering import rename_file
        import unicodedata
        name='Tena\u0301lad.mp3';attempts=[]
        def rename(source,destination):
            attempts.append(str(source))
            if str(source)!=unicodedata.normalize('NFC',name):raise FileNotFoundError('FAT lookup mismatch')
            return destination
        with patch('playlist_sync.ordering.sys.platform','darwin'),patch.object(Path,'rename',rename):
            rename_file(Path(name),Path('temporary'))
        self.assertEqual(attempts,[name,unicodedata.normalize('NFC',name)])

    def test_existing_six_digit_numbers_shorten_without_renumbering(self):
        from playlist_sync.ordering import preview,apply,save,next_filename
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            (folder/'000001 - First.mp3').write_bytes(b'first')
            (folder/'000071 - Last.mp3').write_bytes(b'last')
            save(folder,{'version':1,'last_number':71})
            plan=preview(folder)
            self.assertEqual([x['new'] for x in plan['changes']],['001 - First.mp3','071 - Last.mp3'])
            apply(folder,plan,lambda:None)
            self.assertEqual(next_filename(folder,'Next.mp3'),'072 - Next.mp3')
            self.assertEqual(preview(folder)['changes'],[])
            save(folder,{'version':1,'last_number':999})
            with self.assertRaisesRegex(ValueError,'999 songs'):next_filename(folder,'Overflow.mp3')

    def test_simple_filenames_are_default_and_settings_are_destination_scoped(self):
        from playlist_sync.ordering import preference,next_filename,preview,apply
        with tempfile.TemporaryDirectory() as temp:
            first=Path(temp)/'first';first.mkdir();second=Path(temp)/'second';second.mkdir()
            self.assertEqual(preference(first),{'enabled':False,'digits':3})
            self.assertEqual(next_filename(first,'Artist - Title.mp3'),'Artist - Title.mp3')
            apply(first,preview(first,4,True),lambda:None)
            self.assertEqual(next_filename(first,'Artist - Title.mp3'),'0001 - Artist - Title.mp3')
            self.assertFalse(preference(second)['enabled'])
            self.assertEqual(next_filename(second,'Artist - Title.mp3'),'Artist - Title.mp3')

    def test_padding_change_preserves_ordinals_and_disabling_preserves_existing_files(self):
        from playlist_sync.ordering import preview,apply,next_filename,preference
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);(folder/'Song.mp3').write_bytes(b'audio')
            apply(folder,preview(folder,2,True),lambda:None)
            self.assertTrue((folder/'01 - Song.mp3').exists())
            plan=preview(folder,4,True)
            self.assertEqual(plan['changes'][0]['new'],'0001 - Song.mp3')
            apply(folder,plan,lambda:None)
            self.assertEqual(next_filename(folder,'Next.mp3'),'0002 - Next.mp3')
            apply(folder,preview(folder,4,False),lambda:None)
            self.assertFalse(preference(folder)['enabled'])
            self.assertTrue((folder/'0001 - Song.mp3').exists())
            self.assertEqual(next_filename(folder,'Next.mp3'),'Next.mp3')
            apply(folder,preview(folder,4,True),lambda:None)
            self.assertEqual(next_filename(folder,'Next.mp3'),'0002 - Next.mp3')

    def test_padding_validation_and_insufficient_width(self):
        from playlist_sync.ordering import preview,save
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            for bad in [0,7,True,'3',3.5]:
                with self.assertRaises(ValueError):preview(folder,bad)
            save(folder,{'version':1,'last_number':100,'digits':3})
            with self.assertRaisesRegex(ValueError,'Choose more digits'):preview(folder,2)

    def test_reusing_numbered_source_does_not_number_a_default_destination(self):
        from playlist_sync.ordering import save
        from playlist_sync.engine import SyncEngine
        from test_playlist_sync import SONG, make_audio
        from test_history import wait
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source_folder=root/'source';source_folder.mkdir();destination=root/'destination';destination.mkdir()
            source=source_folder/'001 - Journey - Song.mp3';make_audio(source)
            save(source_folder,{'version':1,'last_number':1,'digits':3,'enabled':True})
            engine=SyncEngine(root/'runtime');engine.reuse.remember(SONG['song_id'],source)
            engine.folder=destination;engine.identity=folder_identity(destination);engine.songs=[copy.deepcopy(SONG)]
            engine.last_scan=time.time();engine.update(phase='ready',scan_id='simple-reuse');engine.refresh_local()
            with patch.object(engine,'run_process',side_effect=AssertionError('Must reuse audio')):
                engine.start_sync('simple-reuse');wait(engine)
            self.assertTrue((destination/'Journey - Song.mp3').exists())
            self.assertFalse((destination/'001 - Journey - Song.mp3').exists())
