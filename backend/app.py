import os
import sys
import time
import json
import uuid
import platform
import shutil
import threading
from urllib.parse import quote
import requests
from flask import Flask, request, Response, jsonify, send_from_directory, send_file, stream_with_context

from backend import __version__
from backend.config import CONFIG, get_bundle_dir
from backend.sources_registry import (
    SOURCE_CATALOG, SOURCE_ORDER, CATEGORY_LABELS,
    MANAGER, get_catalog_info
)
from backend.albums import album_from_url
from backend.streamer import (
    REGISTRY, search_stream, playlist_stream, album_stream
)
from backend.downloader import (
    run_download, cancel_download, get_download_status, get_all_downloads
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
def api_library_delete(rel_path):
    success = delete_library_track(rel_path)
    return jsonify({'success': success})


# ---------------------------------------------------------------------------
# Configuration & System Info API
# ---------------------------------------------------------------------------
@app.route('/api/config', methods=['GET', 'PUT'])
def api_config():
    if request.method == 'PUT':
        data = request.get_json(force=True, silent=True) or {}
        updated = CONFIG.update(data)
        MANAGER.reset()
        return jsonify(updated)
    return jsonify(CONFIG.get_all())


@app.route('/api/system_info')
def api_system_info():
    download_root = CONFIG.get('download_dir', os.path.join(os.getcwd(), 'downloads'))
    total_space, used_space, free_space = 0, 0, 0
    if os.path.exists(download_root):
        try:
            total_space, used_space, free_space = shutil.disk_usage(download_root)
        except Exception:
            pass

    return jsonify({
        'version': __version__,
        'os': platform.system(),
        'platform': platform.platform(),
        'machine': platform.machine(),
        'python_version': platform.python_version(),
        'download_dir': download_root,
        'disk_free_gb': round(free_space / (1024 ** 3), 2),
        'disk_total_gb': round(total_space / (1024 ** 3), 2),
    })


# ---------------------------------------------------------------------------
# Server Startup
# ---------------------------------------------------------------------------
def run_server():
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
