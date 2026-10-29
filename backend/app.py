import os
import sys
import time
import json
import uuid
import platform
import shutil
import threading
import requests
from flask import (
    Flask, request, Response, jsonify,
    send_from_directory, send_file, stream_with_context
)

from backend import __version__
from backend.config import CONFIG, get_bundle_dir
from backend.db import DB
from backend.auth import (
    SESSION_COOKIE, SESSION_TTL_SECONDS, AuthError,
    count_users, setup_initial_admin, create_user, authenticate_user,
    create_session, revoke_session, get_request_token, get_current_user,
    list_users, update_own_profile, change_own_password,
    update_user_by_admin, delete_user_by_admin, require_admin
)
from backend.events import EVENTS
from backend.playlists import (
    PlaylistError, list_playlists_for_user, get_playlist_detail,
    create_playlist, update_playlist, update_playlist_sharing,
    delete_playlist, leave_shared_playlist, add_tracks_to_playlist,
    remove_track_from_playlist, reorder_playlist_tracks,
    distribute_playlist, resolve_online_track, queue_playlist_downloads,
    get_playback_state, save_playback_state
)
from backend.sources_registry import (
    SOURCE_CATALOG, SOURCE_ORDER, CATEGORY_LABELS,
    MANAGER, get_catalog_info
)
from backend.albums import album_from_url
from backend.streamer import (
    REGISTRY, search_stream, playlist_stream, album_stream
)
from backend.downloader import (
    run_download, cancel_download, get_all_downloads
)
from backend.library import (
    scan_local_library, get_library_cover, get_library_lyric, delete_library_track
)

STATIC_DIR = os.path.join(get_bundle_dir(), 'static')

app = Flask(__name__, static_folder=None)
requests.packages.urllib3.disable_warnings()

EXT_TO_MIME = {
    'mp3': 'audio/mpeg',
    'flac': 'audio/flac',
    'wav': 'audio/wav',
    'm4a': 'audio/mp4',
    'aac': 'audio/aac',
    'ogg': 'audio/ogg',
    'opus': 'audio/opus',
    'ape': 'audio/x-ape',
}

PUBLIC_API_PATHS = {
    '/api/auth/me',
    '/api/auth/setup',
    '/api/auth/login',
    '/api/auth/register',
    '/api/auth/logout',
    '/api/system_info',
}


def _client_id_from_request(data: dict = None) -> str:
    return (
        request.headers.get('X-Client-ID')
        or (data or {}).get('client_id')
        or request.args.get('client_id')
        or ''
    ).strip()[:64]


def _set_auth_cookie(resp: Response, raw_token: str) -> Response:
    resp.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite='Lax',
        path='/',
    )
    return resp


def _clear_auth_cookie(resp: Response) -> Response:
    resp.delete_cookie(SESSION_COOKIE, path='/')
    return resp


@app.errorhandler(AuthError)
def _handle_auth_error(err: AuthError):
    return jsonify({'error': err.message}), err.status_code


@app.errorhandler(PlaylistError)
def _handle_playlist_error(err: PlaylistError):
    return jsonify({'error': err.message}), err.status_code


@app.before_request
def _require_login_for_api():
    path = request.path
    if not path.startswith('/api/'):
        return None
    if path in PUBLIC_API_PATHS:
        return None
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录账号'}), 401
    return None


# ---------------------------------------------------------------------------
# Frontend Static Files
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    return send_from_directory(STATIC_DIR, 'index.html')


@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory(STATIC_DIR, filename)


# ---------------------------------------------------------------------------
# Multi-User Auth & User Management API
# ---------------------------------------------------------------------------
@app.route('/api/auth/me')
def api_auth_me():
    total_users = count_users()
    user = get_current_user() if total_users > 0 else None
    return jsonify({
        'authenticated': user is not None,
        'needs_setup': total_users == 0,
        'allow_registration': bool(CONFIG.get('allow_registration', False)),
        'user': user,
    })


@app.route('/api/auth/setup', methods=['POST'])
def api_auth_setup():
    data = request.get_json(force=True, silent=True) or {}
    user = setup_initial_admin(
        username=data.get('username', ''),
        password=data.get('password', ''),
        display_name=data.get('display_name', ''),
    )
    token = create_session(user['id'], request.headers.get('User-Agent', ''))
    resp = jsonify({'user': user, 'authenticated': True})
    return _set_auth_cookie(resp, token)


@app.route('/api/auth/login', methods=['POST'])
def api_auth_login():
    if count_users() == 0:
        return jsonify({'error': '系统尚未初始化，请先创建管理员账号'}), 400
    data = request.get_json(force=True, silent=True) or {}
    user = authenticate_user(
        username=data.get('username', ''),
        password=data.get('password', ''),
    )
    token = create_session(user['id'], request.headers.get('User-Agent', ''))
    resp = jsonify({'user': user, 'authenticated': True})
    return _set_auth_cookie(resp, token)


@app.route('/api/auth/register', methods=['POST'])
def api_auth_register():
    if count_users() == 0:
        return api_auth_setup()
    if not CONFIG.get('allow_registration', False):
        return jsonify({'error': '当前未开放自助注册，请联系管理员创建账号'}), 403
    data = request.get_json(force=True, silent=True) or {}
    user = create_user(
        username=data.get('username', ''),
        password=data.get('password', ''),
        display_name=data.get('display_name', ''),
        role='user',
    )
    token = create_session(user['id'], request.headers.get('User-Agent', ''))
    resp = jsonify({'user': user, 'authenticated': True})
    return _set_auth_cookie(resp, token)


@app.route('/api/auth/logout', methods=['POST'])
def api_auth_logout():
    raw_token = get_request_token()
    if raw_token:
        revoke_session(raw_token)
    resp = jsonify({'success': True})
    return _clear_auth_cookie(resp)


@app.route('/api/auth/profile', methods=['PUT'])
def api_auth_profile():
    user = get_current_user()
    data = request.get_json(force=True, silent=True) or {}
    updated = update_own_profile(user['id'], data.get('display_name', ''))
    return jsonify({'user': updated})


@app.route('/api/auth/password', methods=['PUT'])
def api_auth_password():
    user = get_current_user()
    data = request.get_json(force=True, silent=True) or {}
    change_own_password(
        user['id'],
        data.get('current_password', ''),
        data.get('new_password', ''),
    )
    return jsonify({'success': True})


@app.route('/api/users', methods=['GET', 'POST'])
def api_users():
    user = get_current_user()
    is_admin = user.get('role') == 'admin'

    if request.method == 'POST':
        if not is_admin:
            return jsonify({'error': '需要管理员权限'}), 403
        data = request.get_json(force=True, silent=True) or {}
        created = create_user(
            username=data.get('username', ''),
            password=data.get('password', ''),
            display_name=data.get('display_name', ''),
            role=data.get('role', 'user'),
        )
        return jsonify({'user': created}), 201

    return jsonify({'users': list_users(include_admin_details=is_admin)})


@app.route('/api/users/<int:user_id>', methods=['PUT', 'DELETE'])
@require_admin
def api_user_detail(user_id):
    actor = get_current_user()
    if request.method == 'DELETE':
        delete_user_by_admin(user_id, actor['id'])
        return jsonify({'success': True})

    data = request.get_json(force=True, silent=True) or {}
    updated = update_user_by_admin(
        user_id=user_id,
        display_name=data.get('display_name') if 'display_name' in data else None,
        role=data.get('role') if 'role' in data else None,
        password=data.get('password') if data.get('password') else None,
    )
    return jsonify({'user': updated})


# ---------------------------------------------------------------------------
# Real-time Sync SSE Channel & Playback Queue Sync
# ---------------------------------------------------------------------------
@app.route('/api/events')
def api_events():
    user = get_current_user()
    client_id = _client_id_from_request()
    return Response(
        stream_with_context(EVENTS.subscribe(user['id'], client_id)),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@app.route('/api/me/playback', methods=['GET', 'PUT'])
def api_me_playback():
    user = get_current_user()
    if request.method == 'PUT':
        data = request.get_json(force=True, silent=True) or {}
        if 'client_id' not in data:
            data['client_id'] = _client_id_from_request(data)
        state = save_playback_state(user['id'], data)
        return jsonify(state)
    return jsonify(get_playback_state(user['id']))


# ---------------------------------------------------------------------------
# Playlists & Multi-User Sharing / Distribution API
# ---------------------------------------------------------------------------
@app.route('/api/playlists', methods=['GET', 'POST'])
def api_playlists():
    user = get_current_user()
    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        created = create_playlist(
            actor=user,
            name=data.get('name', ''),
            description=data.get('description', ''),
            visibility=data.get('visibility', 'private'),
            public_editable=bool(data.get('public_editable', False)),
            owner_id=data.get('owner_id'),
            members=data.get('members'),
            initial_tracks=data.get('tracks'),
            client_id=_client_id_from_request(data),
        )
        return jsonify({'playlist': created}), 201

    playlists = list_playlists_for_user(user)
    return jsonify({'playlists': playlists, 'count': len(playlists)})


@app.route('/api/playlists/<playlist_id>', methods=['GET', 'PUT', 'DELETE'])
def api_playlist_detail(playlist_id):
    user = get_current_user()
    if request.method == 'GET':
        return jsonify(get_playlist_detail(playlist_id, user))

    if request.method == 'PUT':
        data = request.get_json(force=True, silent=True) or {}
        updated = update_playlist(
            playlist_id=playlist_id,
            actor=user,
            data=data,
            client_id=_client_id_from_request(data),
        )
        return jsonify({'playlist': updated})

    delete_playlist(playlist_id, user, client_id=_client_id_from_request())
    return jsonify({'success': True})


@app.route('/api/playlists/<playlist_id>/tracks', methods=['POST'])
def api_playlist_add_tracks(playlist_id):
    user = get_current_user()
    data = request.get_json(force=True, silent=True) or {}
    raw_tracks = data.get('tracks')
    if raw_tracks is None and isinstance(data.get('track'), dict):
        raw_tracks = [data['track']]
    result = add_tracks_to_playlist(
        playlist_id=playlist_id,
        actor=user,
        raw_tracks=raw_tracks or [],
        client_id=_client_id_from_request(data),
    )
    return jsonify(result)


@app.route('/api/playlists/<playlist_id>/tracks/<int:item_id>', methods=['DELETE'])
def api_playlist_remove_track(playlist_id, item_id):
    user = get_current_user()
    remove_track_from_playlist(
        playlist_id=playlist_id,
        item_id=item_id,
        actor=user,
        client_id=_client_id_from_request(),
    )
    return jsonify({'success': True})


@app.route('/api/playlists/<playlist_id>/tracks/reorder', methods=['PUT'])
def api_playlist_reorder_tracks(playlist_id):
    user = get_current_user()
    data = request.get_json(force=True, silent=True) or {}
    reorder_playlist_tracks(
        playlist_id=playlist_id,
        item_ids=data.get('item_ids') or [],
        actor=user,
        client_id=_client_id_from_request(data),
    )
    return jsonify({'success': True})


@app.route('/api/playlists/<playlist_id>/share', methods=['PUT'])
def api_playlist_share(playlist_id):
    user = get_current_user()
    data = request.get_json(force=True, silent=True) or {}
    updated = update_playlist_sharing(
        playlist_id=playlist_id,
        actor=user,
        visibility=data.get('visibility', 'private'),
        public_editable=bool(data.get('public_editable', False)),
        members=data.get('members') or [],
        client_id=_client_id_from_request(data),
    )
    return jsonify({'playlist': updated})


@app.route('/api/playlists/<playlist_id>/members/me', methods=['DELETE'])
def api_playlist_leave(playlist_id):
    user = get_current_user()
    leave_shared_playlist(playlist_id, user, client_id=_client_id_from_request())
    return jsonify({'success': True})


@app.route('/api/playlists/<playlist_id>/distribute', methods=['POST'])
def api_playlist_distribute(playlist_id):
    user = get_current_user()
    data = request.get_json(force=True, silent=True) or {}
    result = distribute_playlist(
        playlist_id=playlist_id,
        target_user_ids=data.get('target_user_ids') or [],
        actor=user,
        mode=data.get('mode', 'sync'),
        client_id=_client_id_from_request(data),
    )
    return jsonify(result)


@app.route('/api/playlists/<playlist_id>/download', methods=['POST'])
def api_playlist_download(playlist_id):
    user = get_current_user()
    result = queue_playlist_downloads(playlist_id, user)
    return jsonify(result)


@app.route('/api/tracks/resolve', methods=['POST'])
def api_resolve_track():
    data = request.get_json(force=True, silent=True) or {}
    resolved = resolve_online_track(data)
    return jsonify(resolved)


# ---------------------------------------------------------------------------
# Music Sources & Catalog API
# ---------------------------------------------------------------------------
@app.route('/api/sources')
def api_sources():
    catalog = get_catalog_info()
    return jsonify({
        'sources': catalog,
        'categories': CATEGORY_LABELS,
        'active': CONFIG.get('active_sources', [])
    })


# ---------------------------------------------------------------------------
# Search Streaming API (SSE)
# ---------------------------------------------------------------------------
@app.route('/api/search')
def api_search():
    keyword = (request.args.get('q') or '').strip()
    raw_sources = (request.args.get('sources') or '').strip()

    if not keyword:
        return jsonify({'error': '请输入搜索关键词'}), 400

    if raw_sources:
        sources = [s for s in raw_sources.split(',') if s in SOURCE_CATALOG]
    else:
        sources = CONFIG.get('active_sources', [])
        if not sources:
            sources = [s for s in SOURCE_ORDER if SOURCE_CATALOG[s].get('default')]

    @stream_with_context
    def generate():
        yield 'retry: 10000\n\n'
        for msg in search_stream(keyword, sources):
            yield msg

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    )


# ---------------------------------------------------------------------------
# Playlist Parsing API (SSE)
# ---------------------------------------------------------------------------
@app.route('/api/parse_playlist', methods=['POST'])
def api_parse_playlist():
    data = request.get_json(force=True, silent=True) or {}
    url = (data.get('url') or '').strip()
    source_hint = data.get('source')

    if not url:
        return jsonify({'error': '请输入有效的歌单链接'}), 400

    @stream_with_context
    def generate():
        yield 'retry: 10000\n\n'
        for msg in playlist_stream(url, source_hint=source_hint):
            yield msg

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    )


# ---------------------------------------------------------------------------
# Album Parsing API (SSE)
# ---------------------------------------------------------------------------
@app.route('/api/parse_album', methods=['POST'])
def api_parse_album():
    data = request.get_json(force=True, silent=True) or {}
    source = (data.get('source') or '').strip()
    album_id = (data.get('album_id') or '').strip()
    url = (data.get('url') or '').strip()

    if url and not (source and album_id):
        found = album_from_url(url)
        if found:
            source = found['source']
            album_id = found['album_id']

    if source not in SOURCE_CATALOG or not album_id:
        return jsonify({'error': '无法识别这张专辑'}), 400

    @stream_with_context
    def generate():
        yield 'retry: 10000\n\n'
        for msg in album_stream(source, album_id):
            yield msg

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    )


# ---------------------------------------------------------------------------
# Audio & Cover Streaming Proxy
# ---------------------------------------------------------------------------
@app.route('/api/stream/<token>')
def api_stream(token):
    """Proxy audio stream with HTTP 206 Range seeking support."""
    entry = REGISTRY.get(token)
    if not entry:
        return 'Audio token expired or not found', 404

    song = entry['song_info']
    url = getattr(song, 'download_url', None)
    if not isinstance(url, str) or not url.startswith('http'):
        return 'No downloadable audio url for this track', 404

    upstream_headers = dict(entry['headers'])
    range_header = request.headers.get('Range')
    if range_header:
        upstream_headers['Range'] = range_header

    try:
        up = requests.get(
            url,
            headers=upstream_headers,
            cookies=entry['cookies'],
            stream=True,
            timeout=(10, 30),
            verify=False
        )
    except Exception as err:
        return f'Upstream error: {err}', 502

    ext = (str(getattr(song, 'ext', 'mp3')) or 'mp3').lower().lstrip('.')
    resp_headers = {
        'Content-Type': EXT_TO_MIME.get(ext, 'application/octet-stream'),
        'Accept-Ranges': 'bytes',
        'Cache-Control': 'no-cache',
    }

    for h in ('Content-Length', 'Content-Range'):
        if h in up.headers:
            resp_headers[h] = up.headers[h]

    def generate():
        try:
            for chunk in up.iter_content(chunk_size=64 * 1024):
                if chunk:
                    yield chunk
        finally:
            up.close()

    return Response(
        stream_with_context(generate()),
        status=up.status_code,
        headers=resp_headers
    )


@app.route('/api/cover/<token>')
def api_cover(token):
    """Proxy cover images to bypass anti-hotlinking."""
    entry = REGISTRY.get(token)
    if not entry:
        return '', 404

    url = getattr(entry['song_info'], 'cover_url', None)
    if not isinstance(url, str) or not url.startswith('http'):
        return '', 404

    try:
        headers = {'User-Agent': entry['headers'].get('User-Agent', 'Mozilla/5.0')}
        up = requests.get(url, headers=headers, timeout=(8, 15), verify=False)
        return Response(
            up.content,
            status=up.status_code,
            headers={
                'Content-Type': up.headers.get('Content-Type', 'image/jpeg'),
                'Cache-Control': 'public, max-age=86400'
            }
        )
    except Exception:
        return '', 502


@app.route('/api/lyric/<token>')
def api_lyric(token):
    """Return lyric string for track."""
    entry = REGISTRY.get(token)
    if not entry:
        return jsonify({'lyric': ''})
    lyric = getattr(entry['song_info'], 'lyric', '') or ''
    return jsonify({'lyric': lyric})


# ---------------------------------------------------------------------------
# Download Management API
# ---------------------------------------------------------------------------
@app.route('/api/download', methods=['POST'])
def api_download():
    """Initiate track download."""
    data = request.get_json(force=True, silent=True) or {}
    token = data.get('token')
    if not token:
        return jsonify({'error': '缺少曲目 token'}), 400

    entry = REGISTRY.get(token)
    if not entry:
        return jsonify({'error': '曲目已过期，请重新搜索'}), 404

    download_id = uuid.uuid4().hex[:16]
    threading.Thread(
        target=run_download,
        args=(download_id, token),
        daemon=True
    ).start()

    return jsonify({'download_id': download_id, 'status': 'queued'})


@app.route('/api/download/progress')
def api_download_progress():
    """SSE endpoint broadcasting download status."""
    @stream_with_context
    def generate():
        yield 'retry: 5000\n\n'
        while True:
            all_dl = get_all_downloads()
            yield f'event: downloads\ndata: {json.dumps(all_dl, ensure_ascii=False)}\n\n'
            time.sleep(0.5)

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    )


@app.route('/api/download/cancel/<download_id>', methods=['POST'])
def api_cancel_download(download_id):
    success = cancel_download(download_id)
    return jsonify({'success': success})


@app.route('/api/download/history')
def api_download_history():
    return jsonify(get_all_downloads())


# ---------------------------------------------------------------------------
# Local Music Library API
# ---------------------------------------------------------------------------
@app.route('/api/library/tracks')
def api_library_tracks():
    tracks = scan_local_library()
    return jsonify({'tracks': tracks, 'count': len(tracks)})


@app.route('/api/library/stream/<path:rel_path>')
def api_library_stream(rel_path):
    """Stream downloaded audio file directly with Range support."""
    download_root = CONFIG.get('download_dir', os.path.join(os.getcwd(), 'downloads'))
    full_path = os.path.abspath(os.path.join(download_root, rel_path))

    if not full_path.startswith(os.path.abspath(download_root)) or not os.path.exists(full_path):
        return 'File not found', 404

    return send_file(full_path, conditional=True)


@app.route('/api/library/cover/<path:rel_path>')
def api_library_cover(rel_path):
    """Serve embedded cover art of downloaded track."""
    data = get_library_cover(rel_path)
    if not data:
        return '', 404
    return Response(data, mimetype='image/jpeg', headers={'Cache-Control': 'public, max-age=86400'})


@app.route('/api/library/lyric/<path:rel_path>')
def api_library_lyric(rel_path):
    lyric = get_library_lyric(rel_path)
    return jsonify({'lyric': lyric})


@app.route('/api/library/download/<path:rel_path>')
def api_library_download(rel_path):
    """Download local music file to client browser."""
    download_root = CONFIG.get('download_dir', os.path.join(os.getcwd(), 'downloads'))
    full_path = os.path.abspath(os.path.join(download_root, rel_path))

    if not full_path.startswith(os.path.abspath(download_root)) or not os.path.exists(full_path):
        return 'File not found', 404

    filename = os.path.basename(full_path)
    return send_file(full_path, as_attachment=True, download_name=filename)


@app.route('/api/library/track/<path:rel_path>', methods=['DELETE'])
@require_admin
def api_library_delete(rel_path):
    success = delete_library_track(rel_path)
    if success:
        with DB.connection() as conn:
            conn.execute('UPDATE playlist_tracks SET rel_path = ? WHERE rel_path = ?', ('', rel_path))
        EVENTS.publish_all('library_changed', {'rel_path': rel_path, 'action': 'deleted'})
    return jsonify({'success': success})


# ---------------------------------------------------------------------------
# Configuration & System Info API
# ---------------------------------------------------------------------------
@app.route('/api/config', methods=['GET', 'PUT'])
def api_config():
    user = get_current_user()
    is_admin = user and user.get('role') == 'admin'

    if request.method == 'PUT':
        if not is_admin:
            return jsonify({'error': '只有管理员可以修改系统配置'}), 403
        data = request.get_json(force=True, silent=True) or {}
        updated = CONFIG.update(data)
        MANAGER.reset()
        return jsonify(updated)

    all_cfg = CONFIG.get_all()
    if not is_admin:
        return jsonify({
            'active_sources': all_cfg.get('active_sources', []),
            'search_size_per_source': all_cfg.get('search_size_per_source', 8),
            'allow_registration': bool(all_cfg.get('allow_registration', False)),
        })
    return jsonify(all_cfg)


@app.route('/api/system_info')
def api_system_info():
    user = get_current_user()
    if not user:
        return jsonify({
            'status': 'ok',
            'version': __version__,
        })

    download_root = CONFIG.get('download_dir', os.path.join(os.getcwd(), 'downloads'))
    total_space, used_space, free_space = 0, 0, 0
    if os.path.exists(download_root):
        try:
            total_space, used_space, free_space = shutil.disk_usage(download_root)
        except Exception:
            pass

    payload = {
        'version': __version__,
        'os': platform.system(),
        'platform': platform.platform(),
        'machine': platform.machine(),
        'python_version': platform.python_version(),
        'disk_free_gb': round(free_space / (1024 ** 3), 2),
        'disk_total_gb': round(total_space / (1024 ** 3), 2),
    }
    if user.get('role') == 'admin':
        payload['download_dir'] = download_root
    return jsonify(payload)


# ---------------------------------------------------------------------------
# Server Startup
# ---------------------------------------------------------------------------
def run_server():
    DB.ensure_initialized()
    host = os.environ.get('HOST', CONFIG.get('host', '127.0.0.1'))
    port = int(os.environ.get('PORT', CONFIG.get('port', 8080)))

    print(f"\n  🎵 musicdl-web v{__version__}")
    print(f"  🚀 Server running at: http://{host}:{port}")
    print(f"  📂 Downloads directory: {CONFIG.get('download_dir')}\n")

    try:
        from waitress import serve
        serve(app, host=host, port=port, threads=8)
    except ImportError:
        app.run(host=host, port=port, threaded=True, debug=False)


if __name__ == '__main__':
    run_server()
