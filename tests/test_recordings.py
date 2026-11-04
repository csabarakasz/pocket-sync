import json
import subprocess
import unittest
from unittest.mock import Mock,patch
from playlist_sync.recordings import search_recordings


class RecordingSearchTests(unittest.TestCase):
    def test_results_are_bounded_normalized_and_live_videos_excluded(self):
        entries=[{'id':'abcdefghijk','title':'A <recording>','channel':'Artist','duration':123},
                 {'id':'bad/link','title':'Invalid'}, {'id':'12345678901','is_live':True},
                 {'id':'zyxwvutsrqp','duration':None}]
        with patch('playlist_sync.recordings.subprocess.run',return_value=Mock(returncode=0,stdout=json.dumps({'entries':entries}))) as run:
            videos=search_recordings('  Artist song  ')
        self.assertEqual(len(videos),2)
        self.assertEqual(videos[0]['url'],'https://www.youtube.com/watch?v=abcdefghijk')
        self.assertEqual(videos[0]['duration'],123)
        self.assertIsNone(videos[1]['duration'])
        args=run.call_args.args[0]
        self.assertEqual(args[-2:],['--','ytsearch8:Artist song'])
        self.assertIn('--skip-download',args)
        self.assertEqual(run.call_args.kwargs['timeout'],35)

    def test_timeout_and_service_errors_remain_retryable(self):
        with patch('playlist_sync.recordings.subprocess.run',side_effect=subprocess.TimeoutExpired('search',35)):
            with self.assertRaisesRegex(ValueError,'too long'):search_recordings('Song')
        with patch('playlist_sync.recordings.subprocess.run',return_value=Mock(returncode=1)):
            with self.assertRaisesRegex(ValueError,'unavailable'):search_recordings('Song')
        with patch('playlist_sync.recordings.subprocess.run',return_value=Mock(returncode=0,stdout='{"entries":[]}')):
            self.assertEqual(search_recordings('Song'),[])
        with self.assertRaises(ValueError):search_recordings('')
        with self.assertRaises(ValueError):search_recordings('x'*251)
