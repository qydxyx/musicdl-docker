import os
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from backend.app import app
from backend.config import ConfigManager, CONFIG, DEFAULT_CONFIG
from backend.db import DB
from backend.events import EventBus
from backend.playlists import bind_downloaded_file
from backend.sources_registry import (
    SOURCE_CATALOG, CATEGORY_LABELS, get_catalog_info
)
from backend.albums import (
    album_from_url, extract_album, tracks_from_netease, tracks_from_qq,
)
from backend.streamer import REGISTRY, track_to_payload, detect_source_from_url
from backend.library import (
    scan_local_library, get_library_lyric, delete_library_track
)
from backend.downloader import sanitize_filename


class BackendTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp_data = tempfile.TemporaryDirectory()
        self._tmp_dl = tempfile.TemporaryDirectory()
        self._env_patcher = patch.dict(
            os.environ,
            {
                'MUSICDL_DATA_DIR': self._tmp_data.name,
                'MUSICDL_DOWNLOAD_DIR': self._tmp_dl.name,
            },
        )
        self._env_patcher.start()

        self._orig_cfg = CONFIG.get_all()
        CONFIG._config = dict(DEFAULT_CONFIG)
        CONFIG._config['download_dir'] = self._tmp_dl.name
        CONFIG._config['allow_registration'] = False
        DB.ensure_initialized()

        app.testing = True
        self.app = app.test_client()

    def tearDown(self):
        CONFIG._config = self._orig_cfg
        self._env_patcher.stop()
        self._tmp_data.cleanup()
        self._tmp_dl.cleanup()

    def _setup_admin(self, client=None, username='admin', password='password123', display_name='Admin'):
        c = client or self.app
        res = c.post('/api/auth/setup', json={
            'username': username,
            'password': password,
            'display_name': display_name,
        })
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        return res.get_json()['user']

    def _create_and_login_user(self, admin_client, username, password='password123', display_name=None, role='user'):
        res = admin_client.post('/api/users', json={
            'username': username,
            'password': password,
            'display_name': display_name or username,
            'role': role,
        })
        self.assertEqual(res.status_code, 201, res.get_data(as_text=True))
        user_info = res.get_json()['user']

        user_client = app.test_client()
        login_res = user_client.post('/api/auth/login', json={
            'username': username,
            'password': password,
        })
        self.assertEqual(login_res.status_code, 200)
        return user_info, user_client

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
        dummy_song.identifier = 'migu-999'
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
        self.assertEqual(payload['song_id'], 'migu-999')
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
        # 1. Index & unauthenticated healthcheck
        res = self.app.get('/')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'musicdl', res.data)

        health = self.app.get('/api/system_info')
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.get_json().get('status'), 'ok')

        # Unauthenticated API call returns 401
        self.assertEqual(self.app.get('/api/sources').status_code, 401)

        # Authenticate as admin
        self._setup_admin()

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

        # 4. Authenticated system info
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
        tracks = scan_local_library()
        self.assertEqual(len(tracks), 0)

        dummy_audio = os.path.join(self._tmp_dl.name, 'Artist - Title.mp3')
        with open(dummy_audio, 'wb') as f:
            f.write(b'ID3\x03\x00\x00\x00\x00\x00\x00fake audio content')

        dummy_lrc = os.path.join(self._tmp_dl.name, 'Artist - Title.lrc')
        with open(dummy_lrc, 'w', encoding='utf-8') as f:
            f.write('[00:01.00]Hello world')

        tracks = scan_local_library()
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]['filename'], 'Artist - Title.mp3')
        self.assertTrue(tracks[0]['has_lyric'])

        lyric = get_library_lyric('Artist - Title.mp3')
        self.assertIn('Hello world', lyric)

        deleted = delete_library_track('Artist - Title.mp3')
        self.assertTrue(deleted)
        self.assertFalse(os.path.exists(dummy_audio))
        self.assertFalse(os.path.exists(dummy_lrc))

    def test_search_endpoint_validation(self):
        self._setup_admin()
        res = self.app.get('/api/search')
        self.assertEqual(res.status_code, 400)

        res = self.app.get('/api/search?q=')
        self.assertEqual(res.status_code, 400)

    def test_audio_stream_endpoint_404_for_invalid(self):
        self._setup_admin()
        res = self.app.get('/api/stream/nonexistent_token')
        self.assertEqual(res.status_code, 404)

    def test_auth_setup_login_logout_and_registration(self):
        me = self.app.get('/api/auth/me').get_json()
        self.assertFalse(me['authenticated'])
        self.assertTrue(me['needs_setup'])

        admin = self._setup_admin(username='owner', password='secretpassword', display_name='Owner')
        self.assertEqual(admin['role'], 'admin')

        # Duplicate setup rejected
        dup = self.app.post('/api/auth/setup', json={'username': 'other', 'password': 'secretpassword'})
        self.assertEqual(dup.status_code, 409)

        # Logout revokes session
        self.assertEqual(self.app.post('/api/auth/logout').status_code, 200)
        self.assertEqual(self.app.get('/api/playlists').status_code, 401)

        # Bad password fails
        bad = self.app.post('/api/auth/login', json={'username': 'owner', 'password': 'wrong'})
        self.assertEqual(bad.status_code, 401)

        # Good login succeeds
        ok = self.app.post('/api/auth/login', json={'username': 'owner', 'password': 'secretpassword'})
        self.assertEqual(ok.status_code, 200)

        # Self-registration blocked by default
        anon = app.test_client()
        reg_blocked = anon.post('/api/auth/register', json={'username': 'guest1', 'password': 'password123'})
        self.assertEqual(reg_blocked.status_code, 403)

        # Enable self-registration via admin config
        self.assertEqual(self.app.put('/api/config', json={'allow_registration': True}).status_code, 200)
        reg_ok = anon.post('/api/auth/register', json={'username': 'guest1', 'password': 'password123'})
        self.assertEqual(reg_ok.status_code, 200)
        self.assertEqual(reg_ok.get_json()['user']['role'], 'user')

    def test_rbac_and_user_management(self):
        admin = self._setup_admin()
        alice, alice_client = self._create_and_login_user(self.app, 'alice', display_name='Alice')

        # Regular user cannot modify system config or create/delete users
        self.assertEqual(alice_client.put('/api/config', json={'proxy': 'http://127.0.0.1:7890'}).status_code, 403)
        self.assertEqual(alice_client.post('/api/users', json={'username': 'bob', 'password': 'password123'}).status_code, 403)
        self.assertEqual(alice_client.delete(f"/api/users/{admin['id']}").status_code, 403)

        # Regular user config response hides sensitive fields
        alice_cfg = alice_client.get('/api/config').get_json()
        self.assertNotIn('cookies', alice_cfg)
        self.assertNotIn('download_dir', alice_cfg)

        # Regular user cannot delete physical files from shared library
        dummy_audio = os.path.join(self._tmp_dl.name, 'Shared - Song.mp3')
        with open(dummy_audio, 'wb') as f:
            f.write(b'ID3\x03\x00\x00\x00\x00\x00\x00audio')
        self.assertEqual(alice_client.delete('/api/library/track/Shared - Song.mp3').status_code, 403)
        self.assertTrue(os.path.exists(dummy_audio))

        # Admin can delete physical files
        self.assertEqual(self.app.delete('/api/library/track/Shared - Song.mp3').status_code, 200)
        self.assertFalse(os.path.exists(dummy_audio))

        # Last-admin protection prevents demoting sole admin
        demote = self.app.put(f"/api/users/{admin['id']}", json={'role': 'user'})
        self.assertEqual(demote.status_code, 400)

        # Admin can update and delete regular user
        upd = self.app.put(f"/api/users/{alice['id']}", json={'display_name': 'Alice Updated'})
        self.assertEqual(upd.status_code, 200)
        self.assertEqual(upd.get_json()['user']['display_name'], 'Alice Updated')

        self.assertEqual(self.app.delete(f"/api/users/{alice['id']}").status_code, 200)
        self.assertEqual(alice_client.get('/api/playlists').status_code, 401)

    def test_playlists_crud_admin_owner_and_dedup(self):
        self._setup_admin()
        alice, alice_client = self._create_and_login_user(self.app, 'alice')
        bob, bob_client = self._create_and_login_user(self.app, 'bob')

        # Regular user cannot create a playlist owned by another user
        forbid = alice_client.post('/api/playlists', json={'name': 'Hack', 'owner_id': bob['id']})
        self.assertEqual(forbid.status_code, 403)

        # Admin can create a playlist directly for Bob
        for_bob = self.app.post('/api/playlists', json={
            'name': 'Bob 专属歌单',
            'description': '管理员创建',
            'owner_id': bob['id'],
            'tracks': [
                {'song_name': '夜曲', 'singers': '周杰伦', 'album': '十一月的萧邦', 'source': 'NeteaseMusicClient', 'song_id': '101'},
            ],
        })
        self.assertEqual(for_bob.status_code, 201)
        pl_id = for_bob.get_json()['playlist']['id']

        # Bob sees it as owner and can add/deduplicate/reorder/remove tracks
        bob_list = bob_client.get('/api/playlists').get_json()['playlists']
        self.assertEqual(len(bob_list), 1)
        self.assertEqual(bob_list[0]['access_role'], 'owner')

        add_res = bob_client.post(f'/api/playlists/{pl_id}/tracks', json={
            'tracks': [
                {'song_name': '夜曲', 'singers': '周杰伦', 'source': 'NeteaseMusicClient', 'song_id': '101'},  # duplicate
                {'song_name': '晴天', 'singers': '周杰伦', 'source': 'MiguMusicClient', 'song_id': '202'},
                {'song_name': '七里香', 'singers': '周杰伦', 'source': 'KuwoMusicClient', 'song_id': '303'},
            ]
        }).get_json()
        self.assertEqual(add_res['added'], 2)
        self.assertEqual(add_res['skipped'], 1)

        detail = bob_client.get(f'/api/playlists/{pl_id}').get_json()
        item_ids = [t['item_id'] for t in detail['tracks']]
        self.assertEqual([t['song_name'] for t in detail['tracks']], ['夜曲', '晴天', '七里香'])

        # Reorder tracks (reverse)
        rev_ids = list(reversed(item_ids))
        self.assertEqual(
            bob_client.put(f'/api/playlists/{pl_id}/tracks/reorder', json={'item_ids': rev_ids}).status_code,
            200,
        )
        reordered = bob_client.get(f'/api/playlists/{pl_id}').get_json()['tracks']
        self.assertEqual([t['song_name'] for t in reordered], ['七里香', '晴天', '夜曲'])

        # Remove middle track
        self.assertEqual(bob_client.delete(f"/api/playlists/{pl_id}/tracks/{reordered[1]['item_id']}").status_code, 200)
        after_rm = bob_client.get(f'/api/playlists/{pl_id}').get_json()['tracks']
        self.assertEqual([t['song_name'] for t in after_rm], ['七里香', '夜曲'])

    def test_playlist_sharing_permissions(self):
        self._setup_admin()
        alice, alice_client = self._create_and_login_user(self.app, 'alice')
        bob, bob_client = self._create_and_login_user(self.app, 'bob')
        carol, carol_client = self._create_and_login_user(self.app, 'carol')

        created = alice_client.post('/api/playlists', json={
            'name': '合辑',
            'visibility': 'private',
            'tracks': [{'song_name': '稻香', 'singers': '周杰伦', 'source': 'MiguMusicClient', 'song_id': '1'}],
        }).get_json()['playlist']
        pl_id = created['id']

        # Private: Bob & Carol get 403
        self.assertEqual(bob_client.get(f'/api/playlists/{pl_id}').status_code, 403)

        # Share with Bob (viewer) and Carol (editor)
        share_res = alice_client.put(f'/api/playlists/{pl_id}/share', json={
            'visibility': 'private',
            'public_editable': False,
            'members': [
                {'user_id': bob['id'], 'permission': 'viewer'},
                {'user_id': carol['id'], 'permission': 'editor'},
            ],
        })
        self.assertEqual(share_res.status_code, 200)

        # Bob can view, cannot add tracks
        self.assertEqual(bob_client.get(f'/api/playlists/{pl_id}').status_code, 200)
        self.assertEqual(
            bob_client.post(f'/api/playlists/{pl_id}/tracks', json={'tracks': [{'song_name': '简单爱'}]}).status_code,
            403,
        )

        # Carol (editor) can add tracks, but cannot delete playlist or alter share settings
        self.assertEqual(
            carol_client.post(f'/api/playlists/{pl_id}/tracks', json={'tracks': [{'song_name': '简单爱', 'singers': '周杰伦'}]}).status_code,
            200,
        )
        self.assertEqual(carol_client.delete(f'/api/playlists/{pl_id}').status_code, 403)
        self.assertEqual(carol_client.put(f'/api/playlists/{pl_id}/share', json={'visibility': 'public'}).status_code, 403)

        # Bob can leave shared playlist
        self.assertEqual(bob_client.delete(f'/api/playlists/{pl_id}/members/me').status_code, 200)
        self.assertEqual(bob_client.get(f'/api/playlists/{pl_id}').status_code, 403)

    def test_playlist_multi_user_distribute_and_resync(self):
        self._setup_admin()
        alice, alice_client = self._create_and_login_user(self.app, 'alice', display_name='Alice')
        bob, bob_client = self._create_and_login_user(self.app, 'bob', display_name='Bob')

        src = self.app.post('/api/playlists', json={
            'name': '每周精选 Vol.1',
            'description': '第一期',
            'tracks': [
                {'song_name': '富士山下', 'singers': '陈奕迅', 'source': 'NeteaseMusicClient', 'song_id': '801'},
            ],
        }).get_json()['playlist']
        src_id = src['id']

        # First distribute (sync mode) -> creates copies for Alice and Bob
        dist1 = self.app.post(f'/api/playlists/{src_id}/distribute', json={
            'target_user_ids': [alice['id'], bob['id']],
            'mode': 'sync',
        }).get_json()
        self.assertEqual(len(dist1['created']), 2)
        self.assertEqual(len(dist1['synced']), 0)

        alice_pls = alice_client.get('/api/playlists').get_json()['playlists']
        self.assertEqual(len(alice_pls), 1)
        alice_copy_id = alice_pls[0]['id']
        self.assertEqual(alice_pls[0]['track_count'], 1)

        # Update source playlist & add second song, then re-sync
        self.app.put(f'/api/playlists/{src_id}', json={'name': '每周精选 Vol.2', 'description': '已更新'})
        self.app.post(f'/api/playlists/{src_id}/tracks', json={
            'tracks': [{'song_name': '红玫瑰', 'singers': '陈奕迅', 'source': 'NeteaseMusicClient', 'song_id': '802'}]
        })

        dist2 = self.app.post(f'/api/playlists/{src_id}/distribute', json={
            'target_user_ids': [alice['id'], bob['id']],
            'mode': 'sync',
        }).get_json()
        self.assertEqual(len(dist2['created']), 0)
        self.assertEqual(len(dist2['synced']), 2)

        # Alice still has 1 playlist (same ID), now updated to 2 tracks and new title
        alice_pls_after = alice_client.get('/api/playlists').get_json()['playlists']
        self.assertEqual(len(alice_pls_after), 1)
        self.assertEqual(alice_pls_after[0]['id'], alice_copy_id)
        self.assertEqual(alice_pls_after[0]['name'], '每周精选 Vol.2')
        self.assertEqual(alice_pls_after[0]['track_count'], 2)

        # Copy mode creates a separate independent copy
        dist_copy = self.app.post(f'/api/playlists/{src_id}/distribute', json={
            'target_user_ids': [alice['id']],
            'mode': 'copy',
        }).get_json()
        self.assertEqual(len(dist_copy['created']), 1)
        self.assertEqual(len(alice_client.get('/api/playlists').get_json()['playlists']), 2)

    def test_download_binding_and_online_resolve(self):
        self._setup_admin()
        pl = self.app.post('/api/playlists', json={
            'name': '缓存测试',
            'tracks': [
                {'song_name': '晴天', 'singers': '周杰伦', 'source': 'MiguMusicClient', 'song_id': '777'},
            ],
        }).get_json()['playlist']
        pl_id = pl['id']

        before = self.app.get(f'/api/playlists/{pl_id}').get_json()['tracks'][0]
        self.assertFalse(before['is_local'])

        # Simulate completed local download
        rel_name = '周杰伦 - 晴天.flac'
        full_audio = os.path.join(self._tmp_dl.name, rel_name)
        with open(full_audio, 'wb') as f:
            f.write(b'fLaC\x00\x00\x00\x22fakeflac')

        bind_downloaded_file(rel_name, '晴天', '周杰伦')

        after = self.app.get(f'/api/playlists/{pl_id}').get_json()['tracks'][0]
        self.assertTrue(after['is_local'])
        self.assertEqual(after['rel_path'], rel_name)

        # Resolve endpoint returns local file immediately
        resolved_local = self.app.post('/api/tracks/resolve', json={
            'song_name': '晴天',
            'singers': '周杰伦',
        }).get_json()
        self.assertTrue(resolved_local['is_local'])
        self.assertEqual(resolved_local['rel_path'], rel_name)

        # Resolve endpoint re-searches online when not local and token expired
        fake_song = MagicMock()
        fake_song.identifier = 'net-555'
        fake_song.song_name = '匆匆那年'
        fake_song.singers = '王菲'
        fake_song.album = '匆匆那年'
        fake_song.ext = 'mp3'
        fake_song.file_size = '9.2 MB'
        fake_song.duration = '04:01'
        fake_song.cover_url = 'https://example.com/wf.jpg'
        fake_song.lyric = ''
        fake_song.download_url = 'http://example.com/wf.mp3'
        fake_song.default_download_headers = {}
        fake_song.default_download_cookies = {}
        fake_song.raw_data = {}

        with patch('backend.playlists._search_single_source_best_match', return_value=(fake_song, 'NeteaseMusicClient')):
            res_online = self.app.post('/api/tracks/resolve', json={
                'song_name': '匆匆那年',
                'singers': '王菲',
                'source': 'NeteaseMusicClient',
            })
            self.assertEqual(res_online.status_code, 200)
            payload = res_online.get_json()
            self.assertTrue(payload['token'])
            self.assertEqual(payload['song_name'], '匆匆那年')

    def test_playback_state_sync_and_event_bus(self):
        admin = self._setup_admin()

        # Subscribe two simulated tabs on EventBus
        bus = EventBus()
        gen_a = bus.subscribe(admin['id'], 'tab-a')
        gen_b = bus.subscribe(admin['id'], 'tab-b')
        self.assertIn('retry:', next(gen_a))
        self.assertIn('event: connected', next(gen_a))
        self.assertIn('retry:', next(gen_b))
        self.assertIn('event: connected', next(gen_b))

        bus.publish_users({admin['id']}, 'queue_changed', {'hello': 'world'}, exclude_client_id='tab-a')
        msg_b = next(gen_b)
        self.assertIn('event: queue_changed', msg_b)
        gen_a.close()
        gen_b.close()

        # Save & fetch playback state via API
        put_res = self.app.put(
            '/api/me/playback',
            headers={'X-Client-ID': 'device-1'},
            json={
                'queue': [
                    {'song_name': '晴天', 'singers': '周杰伦', 'source': 'MiguMusicClient', 'duration': '04:29'},
                    {'song_name': '七里香', 'singers': '周杰伦', 'source': 'MiguMusicClient', 'duration': '04:59'},
                ],
                'current_index': 1,
                'play_mode': 'shuffle',
                'position_sec': 42.5,
            },
        )
        self.assertEqual(put_res.status_code, 200)

        get_res = self.app.get('/api/me/playback').get_json()
        self.assertEqual(len(get_res['queue']), 2)
        self.assertEqual(get_res['current_index'], 1)
        self.assertEqual(get_res['play_mode'], 'shuffle')
        self.assertAlmostEqual(get_res['position_sec'], 42.5)
        self.assertEqual(get_res['client_id'], 'device-1')


if __name__ == '__main__':
    unittest.main()
