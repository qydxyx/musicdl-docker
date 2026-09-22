import time
import uuid
import json
import queue
import threading
from typing import Dict, Any, Generator, List, Optional
from urllib.parse import urlparse

from backend.config import CONFIG
from backend.sources_registry import MANAGER, SOURCE_CATALOG

# ---------------------------------------------------------------------------
# In-memory TrackRegistry (Token -> Track Data)
# ---------------------------------------------------------------------------
class TrackRegistry:
    def __init__(self, max_tracks: int = 2000):
        self._lock = threading.Lock()
        self._tracks: Dict[str, Dict[str, Any]] = {}
        self._max_tracks = max_tracks

    def add(self, song_info: Any, source: str) -> str:
        token = uuid.uuid4().hex[:16]
        client = MANAGER.get_client(source)
        headers = dict(getattr(client, 'default_download_headers', {}) or {})
        headers.update(dict(getattr(song_info, 'default_download_headers', {}) or {}))
        cookies = dict(getattr(client, 'default_download_cookies', {}) or {})
        cookies.update(dict(getattr(song_info, 'default_download_cookies', {}) or {}))

        with self._lock:
            # Prune old tracks if exceeding maximum capacity
            if len(self._tracks) >= self._max_tracks:
                # Remove oldest 20%
                keys_to_remove = list(self._tracks.keys())[:int(self._max_tracks * 0.2)]
                for k in keys_to_remove:
                    self._tracks.pop(k, None)

            self._tracks[token] = {
                'song_info': song_info,
                'source': source,
                'headers': headers,
                'cookies': cookies,
                'created_at': time.time(),
            }
        return token

    def get(self, token: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._tracks.get(token)


REGISTRY = TrackRegistry()


class _NullProgress:
    """Null object replacing rich.Progress for headless musicdl _search."""
    def add_task(self, *a, **k): return 0
    def update(self, *a, **k): pass
    def advance(self, *a, **k): pass
    def __getattr__(self, _): return lambda *a, **k: None


def track_to_payload(song_info: Any, token: str, source: str) -> Dict[str, Any]:
    """Serialize a SongInfo into frontend JSON payload."""
    def s(v):
        return '' if v is None else str(v)

    ext = s(song_info.ext).lower().lstrip('.')
    source_meta = SOURCE_CATALOG.get(source, {})

    download_url = getattr(song_info, 'download_url', None)
    has_valid_url = isinstance(download_url, str) and download_url.startswith('http')

    return {
        'token': token,
        'source': source,
        'source_label': source_meta.get('label', source),
        'source_short': source_meta.get('short', source),
        'song_name': s(song_info.song_name) or '未知曲目',
        'singers': s(song_info.singers) or '未知艺人',
        'album': s(song_info.album),
        'ext': ext or 'mp3',
        'file_size': s(song_info.file_size),
        'duration': s(song_info.duration),
        'cover_url': s(song_info.cover_url),
        'has_lyric': bool(getattr(song_info, 'lyric', None)),
        'has_url': has_valid_url,
        'lossless': ext in {'flac', 'wav', 'ape', 'alac', 'dsd', 'dff'},
    }


# ---------------------------------------------------------------------------
# Streaming Search Implementation (SSE)
# ---------------------------------------------------------------------------
def search_stream(keyword: str, sources: List[str]) -> Generator[str, None, None]:
    """Concurrent multi-source search generator emitting SSE messages."""
    out_q: queue.Queue = queue.Queue()
    seen_identifiers = set()
    seen_lock = threading.Lock()
    active_count = {'val': 0}
    timeout = int(CONFIG.get('per_source_timeout', 25))

    def emit(event: str, data: Any):
        out_q.put(f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n')

    def run_source(src: str):
        try:
            client = MANAGER.get_client(src)
            if not client:
                emit('source_error', {'source': src, 'message': 'Client not found'})
                return

            progress = _NullProgress()
            try:
                search_urls = client._constructsearchurls(keyword=keyword, rule={}, request_overrides={})
            except Exception as err:
                emit('source_error', {'source': src, 'message': str(err)})
                return

            buckets = [[] for _ in search_urls]
            threads = []
            for i, url in enumerate(search_urls):
                t = threading.Thread(
                    target=_safe_search_call,
                    args=(client, keyword, url, buckets[i], progress),
                    daemon=True,
                )
                t.start()
                threads.append(t)

            deadline = time.time() + timeout
            cursors = [0] * len(buckets)
            count = 0
            while True:
                drained = _drain_bucket_items(buckets, cursors, src, seen_identifiers, seen_lock, emit)
                count += drained
                alive = any(t.is_alive() for t in threads)
                if not alive or time.time() > deadline:
                    break
                time.sleep(0.1)

            # Final flush of any trailing items
            count += _drain_bucket_items(buckets, cursors, src, seen_identifiers, seen_lock, emit)
            timed_out = any(t.is_alive() for t in threads)
            emit('source_done', {'source': src, 'count': count, 'timed_out': timed_out})

        except Exception as err:
            emit('source_error', {'source': src, 'message': str(err)})
        finally:
            with seen_lock:
                active_count['val'] -= 1
                if active_count['val'] <= 0:
                    out_q.put(None)  # Sentinel: all source threads ended

    valid_sources = [s for s in sources if s in SOURCE_CATALOG]
    if not valid_sources:
        yield 'event: done\ndata: {"count": 0}\n\n'
        return

    active_count['val'] = len(valid_sources)
    for s in valid_sources:
        emit('source_start', {
            'source': s,
            'label': SOURCE_CATALOG[s]['label']
        })
        threading.Thread(target=run_source, args=(s,), daemon=True).start()

    total = 0
    while True:
        try:
            msg = out_q.get(timeout=timeout + 5)
            if msg is None:
                break
            if msg.startswith('event: result'):
                total += 1
            yield msg
        except queue.Empty:
            break

    yield f'event: done\ndata: {{"count": {total}}}\n\n'


def _safe_search_call(client: Any, keyword: str, url: str, bucket: list, progress: Any):
    try:
        client._search(
            keyword=keyword,
            search_url=url,
            request_overrides={},
            song_infos=bucket,
            progress=progress
        )
    except Exception as e:
        print(f"[streamer] _search error: {e}")


def _drain_bucket_items(buckets: list, cursors: list, source: str,
                        seen: set, lock: threading.Lock, emit: Any) -> int:
    """Drain newly resolved song_infos across buckets, deduplicate, and emit."""
    emitted = 0
    for i, bucket in enumerate(buckets):
        while cursors[i] < len(bucket):
            song_info = bucket[cursors[i]]
            cursors[i] += 1
            try:
                ident = str(getattr(song_info, 'identifier', '') or '')
                if not ident:
                    ident = f"{source}_{getattr(song_info, 'song_name', '')}_{getattr(song_info, 'singers', '')}"

                with lock:
                    if ident in seen:
                        continue
                    seen.add(ident)

                token = REGISTRY.add(song_info, source)
                emit('result', track_to_payload(song_info, token, source))
                emitted += 1
            except Exception:
                continue
    return emitted


# ---------------------------------------------------------------------------
# Playlist / Link Parsing Implementation (SSE)
# ---------------------------------------------------------------------------
URL_SOURCE_MAPPING = [
    (['163.com', 'music.163.com', '163cn.tv'], 'NeteaseMusicClient'),
    (['qq.com', 'y.qq.com', 'c6.y.qq.com'], 'QQMusicClient'),
    (['kuwo.cn'], 'KuwoMusicClient'),
    (['kugou.com'], 'KugouMusicClient'),
    (['migu.cn'], 'MiguMusicClient'),
    (['bilibili.com', 'b23.tv'], 'BilibiliMusicClient'),
    (['spotify.com'], 'SpotifyMusicClient'),
    (['soundcloud.com'], 'SoundCloudMusicClient'),
    (['apple.com'], 'AppleMusicClient'),
    (['jamendo.com'], 'JamendoMusicClient'),
    (['deezer.com'], 'DeezerMusicClient'),
]


def detect_source_from_url(url: str) -> Optional[str]:
    """Detect appropriate music client from URL domain."""
    domain = urlparse(url).netloc.lower()
    for hosts, src in URL_SOURCE_MAPPING:
        if any(h in domain for h in hosts):
            return src
    return None


def playlist_stream(playlist_url: str, source_hint: Optional[str] = None) -> Generator[str, None, None]:
    """Parse a playlist URL and stream resolved tracks via SSE."""
    out_q: queue.Queue = queue.Queue()

    def emit(event: str, data: Any):
        out_q.put(f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n')

    source = source_hint or detect_source_from_url(playlist_url)
    if not source:
        # Default try Netease or QQ
        source = 'NeteaseMusicClient'

    client = MANAGER.get_client(source)
    if not client or not hasattr(client, 'parseplaylist'):
        yield f'event: playlist_error\ndata: {{"message": "源 {source} 不支持歌单解析"}}\n\n'
        return

    emit('playlist_start', {
        'source': source,
        'label': SOURCE_CATALOG.get(source, {}).get('label', source),
        'url': playlist_url,
    })

    def run_parse():
        try:
            song_infos = client.parseplaylist(playlist_url=playlist_url)
            if not song_infos:
                emit('playlist_empty', {'message': '未在歌单中找到曲目'})
                return

            count = 0
            for song in song_infos:
                token = REGISTRY.add(song, source)
                emit('playlist_track', track_to_payload(song, token, source))
                count += 1

            emit('playlist_done', {'count': count})
        except Exception as err:
            emit('playlist_error', {'message': str(err)})
        finally:
            out_q.put(None)

    threading.Thread(target=run_parse, daemon=True).start()

    while True:
        try:
            msg = out_q.get(timeout=60)
            if msg is None:
                break
            yield msg
        except queue.Empty:
            break
