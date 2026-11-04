import argparse
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from PIL import Image
from mutagen.id3 import TIT2, TPE1, TALB, TRCK, TDRC, APIC, WOAS
from mutagen.mp3 import MP3
from download import spotify_link, audit


class DownloadTests(unittest.TestCase):
    def test_links(self):
        identifier = '0VjIjW4GlUZAMYd2vXMi3b'
        expected = f'https://open.spotify.com/track/{identifier}'
        self.assertEqual(spotify_link(f'spotify:track:{identifier}'), expected)
        self.assertEqual(spotify_link(expected + '?si=test'), expected)
        for value in ['https://evil.test/track/' + identifier, '--help', 'https://open.spotify.com/track/no']:
            with self.assertRaises(argparse.ArgumentTypeError):
                spotify_link(value)

    def test_real_mp3_artwork_tags_and_missing_track(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            path = folder / 'Artist - Example [abc].mp3'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', str(path)], check=True)
            song = {'song_id': 'abc', 'name': 'Example', 'artists': ['Artist'], 'album_name': 'Album', 'duration': 1}
            self.assertTrue(audit(folder, [song])[0]['issues'])
            audio = MP3(path)
            if audio.tags is None:
                audio.add_tags()
            for frame in [TIT2(text='Example'), TPE1(text='Artist'), TALB(text='Album'), TRCK(text='1/1'), TDRC(text='2026')]:
                audio.tags.add(frame)
            cover = io.BytesIO()
            Image.new('RGB', (20, 20), 'red').save(cover, format='JPEG')
            audio.tags.add(APIC(mime='image/jpeg', type=3, data=cover.getvalue()))
            audio.save()
            self.assertEqual(audit(folder, [song])[0]['issues'], [])
            audio.tags.delall('APIC')
            audio.save()
            self.assertIn('Missing embedded cover art', audit(folder, [song])[0]['issues'])
            path.unlink()
            self.assertEqual(audit(folder, [song])[0]['issues'], ['Audio file missing'])

    def test_clean_filename_is_audited_by_embedded_spotify_url(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            sid='a'*22
            path=folder/'Artist - Example.mp3'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=1',str(path)],check=True)
            audio=MP3(path)
            if audio.tags is None:audio.add_tags()
            for frame in [TIT2(text='Example'),TPE1(text='Artist'),TALB(text='Album'),TRCK(text='1/1'),TDRC(text='2026'),WOAS(url='https://open.spotify.com/track/'+sid)]:
                audio.tags.add(frame)
            cover=io.BytesIO();Image.new('RGB',(20,20),'red').save(cover,format='JPEG')
            audio.tags.add(APIC(mime='image/jpeg',type=3,data=cover.getvalue()));audio.save()
            result=audit(folder,[{'song_id':sid,'name':'Example','artists':['Artist'],'album_name':'Album','duration':1}])[0]
            self.assertEqual(result['issues'],[])
            self.assertEqual(result['file'],str(path))


if __name__ == '__main__':
    unittest.main()
