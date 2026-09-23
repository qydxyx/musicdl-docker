import os
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from backend.app import app
from backend.config import ConfigManager, CONFIG
from backend.sources_registry import (
    SOURCE_CATALOG, CATEGORY_LABELS, MANAGER, get_catalog_info
)
from backend.albums import (
    album_from_url, extract_album, tracks_from_netease, tracks_from_qq,
)
from backend.streamer import REGISTRY, track_to_payload, detect_source_from_url
from backend.library import (
    scan_local_library, get_library_lyric, delete_library_track
)
from backend.downloader import (
    sanitize_filename, get_all_downloads
)


class BackendTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_config_manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {'MUSICDL_DATA_DIR': tmpdir, 'PORT': '9090'}):
                cfg = ConfigManager()
                self.assertEqual(cfg.get('port'), 9090)
                self.assertIn('MiguMusicClient', cfg.get('active_sources'))

                updated = cfg.update({'search_size_per_source': 12})
                self.assertEqual(updated['search_size_per_source'], 12)
                self.assertEqual(cfg.get('search_size_per_source'), 12)

    def test_sources_catalog(self):
        self.assertIn('MiguMusicClient', SOURCE_CATALOG)
        self.assertIn('KuwoMusicClient', SOURCE_CATALOG)
        self.assertIn('NeteaseMusicClient', SOURCE_CATALOG)
        self.assertIn('cn_major', CATEGORY_LABELS)

        catalog_info = get_catalog_info()
        self.assertTrue(len(catalog_info) > 10)
        migu = next(s for s in catalog_info if s['id'] == 'MiguMusicClient')
        self.assertEqual(migu['label'], '咪咕音乐')

    def test_album_identity(self):
        song = MagicMock()
        song.album = '叶惠美'
        song.singers = '周杰伦'
        song.cover_url = ''
        song.raw_data = {'search': {'al': {'id': 18918, 'name': '叶惠美', 'picUrl': 'https://example.com/a.jpg'}}}
        ref = extract_album(song, 'NeteaseMusicClient')
        self.assertEqual(ref['id'], '18918')
        self.assertTrue(ref['downloadable'])

        qq = MagicMock()
        qq.album = '叶惠美'
        qq.singers = '周杰伦'
        qq.cover_url = ''
        qq.raw_data = {'search': {'album': {'mid': '000MkMni19ClKG', 'title': '叶惠美'}}}
        self.assertEqual(extract_album(qq, 'QQMusicClient')['id'], '000MkMni19ClKG')

        plain = MagicMock()
        plain.album = '某张专辑'
        plain.singers = '某人'
        plain.cover_url = ''
        plain.raw_data = {}
        self.assertFalse(extract_album(plain, 'JamendoMusicClient')['downloadable'])

        self.assertEqual(
            album_from_url('https://music.163.com/album?id=18918')['album_id'],
            '18918',
        )
        self.assertEqual(
            album_from_url('https://y.qq.com/n/ryqq/albumDetail/000MkMni19ClKG')['source'],
            'QQMusicClient',
        )
        self.assertIsNone(album_from_url('https://music.163.com/playlist?id=123'))
        self.assertEqual(len(tracks_from_netease({'songs': [{'id': 1}, {'name': 'x'}]})), 1)
        self.assertEqual(tracks_from_qq({'data': {'list': [{'songmid': 'abc'}]}})[0]['mid'], 'abc')

    def test_url_detection(self):
        self.assertEqual(detect_source_from_url('https://music.163.com/#/playlist?id=123'), 'NeteaseMusicClient')
        self.assertEqual(detect_source_from_url('https://y.qq.com/n/ryqq/playlist/456'), 'QQMusicClient')
        self.assertEqual(detect_source_from_url('https://www.kuwo.cn/playlist_detail/789'), 'KuwoMusicClient')
        self.assertEqual(detect_source_from_url('https://open.spotify.com/playlist/abc'), 'SpotifyMusicClient')

    def test_track_registry_and_payload(self):
        dummy_song = MagicMock()
        dummy_song.song_name = '晴天'
        dummy_song.singers = '周杰伦'
        dummy_song.album = '叶惠美'
        dummy_song.ext = 'flac'
        dummy_song.file_size = '25.3 MB'
        dummy_song.duration = '04:29'
        dummy_song.cover_url = 'https://example.com/cover.jpg'
        dummy_song.lyric = '[00:00.00]晴天'
        dummy_song.download_url = 'http://example.com/audio.flac'
        dummy_song.default_download_headers = {}
        dummy_song.default_download_cookies = {}

        token = REGISTRY.add(dummy_song, 'MiguMusicClient')
        self.assertTrue(len(token) > 0)

        entry = REGISTRY.get(token)
        self.assertIsNotNone(entry)
        self.assertEqual(entry['source'], 'MiguMusicClient')

        payload = track_to_payload(dummy_song, token, 'MiguMusicClient')
        self.assertEqual(payload['token'], token)
        self.assertEqual(payload['song_name'], '晴天')
        self.assertEqual(payload['singers'], '周杰伦')
        self.assertTrue(payload['lossless'])
        self.assertTrue(payload['has_lyric'])

    def test_sanitize_filename(self):
        raw = '周杰伦 / 叶惠美: 晴天 <Live>*?|'
        clean = sanitize_filename(raw)
        self.assertNotIn('/', clean)
        self.assertNotIn(':', clean)
        self.assertNotIn('<', clean)
        self.assertNotIn('?', clean)

    def test_api_routes(self):
        # 1. Index
        res = self.app.get('/')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'musicdl', res.data)

        # 2. Sources
        res = self.app.get('/api/sources')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('sources', data)
        self.assertIn('categories', data)

        # 3. Config
        res = self.app.get('/api/config')
        self.assertEqual(res.status_code, 200)
        cfg = res.get_json()
        self.assertIn('download_dir', cfg)

        # 4. System info
        res = self.app.get('/api/system_info')
        self.assertEqual(res.status_code, 200)
        sys_info = res.get_json()
        self.assertIn('version', sys_info)
        self.assertIn('os', sys_info)

        # 5. Library tracks
        res = self.app.get('/api/library/tracks')
        self.assertEqual(res.status_code, 200)
        lib = res.get_json()
        self.assertIn('tracks', lib)

        # 6. Download history
        res = self.app.get('/api/download/history')
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.get_json(), list)

    def test_local_library_file_ops(self):
        with tempfile.TemporaryDirectory() as tmp_dl_dir:
            with patch.object(CONFIG, 'get', side_effect=lambda k, default=None: tmp_dl_dir if k == 'download_dir' else default):
                # Empty initially
                tracks = scan_local_library()
                self.assertEqual(len(tracks), 0)

                # Create dummy audio file + lrc
                dummy_audio = os.path.join(tmp_dl_dir, 'Artist - Title.mp3')
                with open(dummy_audio, 'wb') as f:
                    f.write(b'ID3\x03\x00\x00\x00\x00\x00\x00fake audio content')

                dummy_lrc = os.path.join(tmp_dl_dir, 'Artist - Title.lrc')
                with open(dummy_lrc, 'w', encoding='utf-8') as f:
                    f.write('[00:01.00]Hello world')

                tracks = scan_local_library()
                self.assertEqual(len(tracks), 1)
                self.assertEqual(tracks[0]['filename'], 'Artist - Title.mp3')
                self.assertTrue(tracks[0]['has_lyric'])

                lyric = get_library_lyric('Artist - Title.mp3')
                self.assertIn('Hello world', lyric)

                # Test delete
                deleted = delete_library_track('Artist - Title.mp3')
                self.assertTrue(deleted)
                self.assertFalse(os.path.exists(dummy_audio))
                self.assertFalse(os.path.exists(dummy_lrc))

    def test_search_endpoint_validation(self):
        # Empty keyword should return 400
        res = self.app.get('/api/search')
        self.assertEqual(res.status_code, 400)

        res = self.app.get('/api/search?q=')
        self.assertEqual(res.status_code, 400)

    def test_audio_stream_endpoint_404_for_invalid(self):
        res = self.app.get('/api/stream/nonexistent_token')
        self.assertEqual(res.status_code, 404)


if __name__ == '__main__':
    unittest.main()
