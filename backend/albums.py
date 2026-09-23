"""Album identity and full-album track listing.

Search hits only carry a slice of an album. Whole-album download uses the
platform album id stored on the raw search payload, then resolves every
track through the same client parsers used for search.
"""
import json
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse


def _search_blob(song_info: Any) -> Dict[str, Any]:
    raw = getattr(song_info, 'raw_data', None)
    if not isinstance(raw, dict):
        return {}
    search = raw.get('search')
    return search if isinstance(search, dict) else {}


def _text(value: Any) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ''
    text = str(value).strip()
    return '' if text.lower() in {'none', 'null'} else text


def extract_album(song_info: Any, source: str) -> Optional[Dict[str, Any]]:
    """Return an album identity when the raw search payload has one."""
    search = _search_blob(song_info)
    album_name = _text(getattr(song_info, 'album', None))
    artist = _text(getattr(song_info, 'singers', None))
    cover = _text(getattr(song_info, 'cover_url', None))
    album_id = ''

    if source == 'NeteaseMusicClient':
        al = search.get('al') if isinstance(search.get('al'), dict) else {}
        album = search.get('album') if isinstance(search.get('album'), dict) else {}
        album_id = _text(al.get('id') or album.get('id'))
        album_name = album_name or _text(al.get('name') or album.get('name'))
        cover = cover or _text(al.get('picUrl') or album.get('picUrl'))
    elif source == 'QQMusicClient':
        album = search.get('album') if isinstance(search.get('album'), dict) else {}
        album_id = _text(album.get('mid') or search.get('albummid') or search.get('albumMid'))
        album_name = album_name or _text(album.get('title') or album.get('name') or search.get('albumname'))
        if album_id and not cover:
            cover = f'https://y.gtimg.cn/music/photo_new/T002R300x300M000{album_id}.jpg'
    elif source == 'KuwoMusicClient':
        album_id = _text(search.get('ALBUMID') or search.get('albumid') or search.get('albumId'))
        album_name = album_name or _text(search.get('ALBUM') or search.get('album'))
    elif source == 'KugouMusicClient':
        info = search.get('albuminfo') if isinstance(search.get('albuminfo'), dict) else {}
        album_id = _text(search.get('album_id') or search.get('AlbumID') or info.get('id'))
        album_name = album_name or _text(search.get('album_name') or search.get('AlbumName') or info.get('name'))
    elif source == 'MiguMusicClient':
        albums = search.get('albums') if isinstance(search.get('albums'), list) else []
        first = albums[0] if albums and isinstance(albums[0], dict) else {}
        album_id = _text(search.get('albumId') or first.get('id'))
        album_name = album_name or _text(search.get('album') or first.get('name'))

    if not album_name and not album_id:
        return None
    return {
        'id': album_id,
        'name': album_name,
        'artist': artist,
        'cover': cover,
        'downloadable': bool(album_id),
    }


def album_from_url(url: str) -> Optional[Dict[str, str]]:
    """Recognize an album share link. Playlist links return None."""
    raw = (url or '').strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    host = (parsed.netloc or '').lower()
    path = parsed.path or ''
    query = parse_qs(parsed.query)
    fragment = parsed.fragment or ''
    blob = f'{path} {fragment}'

    if '163.com' in host and 'album' in blob:
        album_id = (query.get('id') or parse_qs(urlparse(fragment).query).get('id') or [''])[0]
        if not album_id:
            parts = [p for p in path.split('/') if p]
            if 'album' in parts:
                album_id = parts[-1].split('.')[0]
        if album_id.isdigit():
            return {'source': 'NeteaseMusicClient', 'album_id': album_id}

    if 'qq.com' in host and 'album' in blob.lower():
        parts = [p for p in path.split('/') if p]
        album_id = parts[-1] if parts else ''
        if album_id and album_id.lower() not in {'album', 'albumdetail'}:
            return {'source': 'QQMusicClient', 'album_id': album_id}

    if 'kuwo.cn' in host and 'album' in path:
        parts = [p for p in path.split('/') if p]
        album_id = parts[-1] if parts else ''
        if album_id.isdigit():
            return {'source': 'KuwoMusicClient', 'album_id': album_id}

    if 'kugou.com' in host and 'album' in path:
        parts = [p for p in path.split('/') if p]
        album_id = parts[-1].split('.')[0] if parts else ''
        if album_id.isdigit():
            return {'source': 'KugouMusicClient', 'album_id': album_id}

    if 'migu.cn' in host and 'album' in blob.lower():
        album_id = (query.get('id') or query.get('albumId') or [''])[0]
        if album_id:
            return {'source': 'MiguMusicClient', 'album_id': album_id}
    return None


def _loads(text: str) -> Any:
    body = (text or '').strip()
    if not body:
        return {}
    if body[0] not in '{[':
        start = body.find('{')
        end = body.rfind('}')
        body = body[start:end + 1] if start >= 0 and end > start else ''
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {}


def tracks_from_netease(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    songs = payload.get('songs')
    if not isinstance(songs, list):
        album = payload.get('album') if isinstance(payload.get('album'), dict) else {}
        songs = album.get('songs') or []
    return [song for song in songs if isinstance(song, dict) and song.get('id')]


def tracks_from_qq(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get('data') if isinstance(payload.get('data'), dict) else {}
    songs = data.get('list') or data.get('songlist') or []
    cleaned = []
    for song in songs:
        if not isinstance(song, dict):
            continue
        if not song.get('mid') and song.get('songmid'):
            song['mid'] = song['songmid']
        if song.get('mid') or song.get('songmid') or song.get('id'):
            cleaned.append(song)
    return cleaned


def tracks_from_kuwo(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get('data') if isinstance(payload.get('data'), dict) else {}
    songs = data.get('musicList') or data.get('musiclist') or []
    cleaned = []
    for song in songs:
        if not isinstance(song, dict):
            continue
        rid = _text(song.get('rid') or song.get('musicrid') or song.get('MUSICRID'))
        if not rid:
            continue
        song['MUSICRID'] = rid if rid.startswith('MUSIC_') else f'MUSIC_{rid}'
        cleaned.append(song)
    return cleaned


def tracks_from_kugou(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get('data') if isinstance(payload.get('data'), dict) else {}
    songs = data.get('info') or data.get('songs') or []
    return [song for song in songs if isinstance(song, dict) and (song.get('hash') or song.get('FileHash'))]


def tracks_from_migu(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get('data') if isinstance(payload.get('data'), dict) else payload
    songs = []
    if isinstance(data, dict):
        songs = data.get('songList') or data.get('songs') or data.get('list') or []
    return [song for song in songs if isinstance(song, dict) and song.get('contentId') and song.get('copyrightId')]


def list_album_tracks(client: Any, source: str, album_id: str) -> List[Dict[str, Any]]:
    """Fetch the platform album and return track dicts the client can parse."""
    album_id = (album_id or '').strip()
    if not album_id or client is None:
        return []

    if source == 'NeteaseMusicClient':
        resp = client.get(f'https://music.163.com/api/v1/album/{album_id}', timeout=20)
        resp.raise_for_status()
        return tracks_from_netease(_loads(resp.text))

    if source == 'QQMusicClient':
        resp = client.get(
            'https://c.y.qq.com/v8/fcg-bin/fcg_v8_album_info_cp.fcg',
            params={'albummid': album_id, 'format': 'json', 'newsong': 1},
            headers={'Referer': 'https://y.qq.com/'},
            timeout=20,
        )
        resp.raise_for_status()
        return tracks_from_qq(_loads(resp.text))

    if source == 'KuwoMusicClient':
        songs: List[Dict[str, Any]] = []
        for page in range(1, 6):
            resp = client.get(
                'https://www.kuwo.cn/api/www/album/albumInfo',
                params={'albumId': album_id, 'pn': page, 'rn': 50},
                headers={'Referer': 'https://www.kuwo.cn/'},
                timeout=20,
            )
            resp.raise_for_status()
            batch = tracks_from_kuwo(_loads(resp.text))
            if not batch:
                break
            songs.extend(batch)
            if len(batch) < 50 or len(songs) >= 200:
                break
        return songs[:200]

    if source == 'KugouMusicClient':
        songs = []
        for page in range(1, 6):
            resp = client.get(
                'http://mobilecdn.kugou.com/api/v3/album/song',
                params={'albumid': album_id, 'page': page, 'pagesize': 50, 'plat': 0, 'version': 9108},
                timeout=20,
            )
            resp.raise_for_status()
            batch = tracks_from_kugou(_loads(resp.text))
            if not batch:
                break
            songs.extend(batch)
            if len(batch) < 50 or len(songs) >= 200:
                break
        return songs[:200]

    if source == 'MiguMusicClient':
        resp = client.get(
            'https://app.c.nf.migu.cn/MIGUM2.0/v1.0/content/queryAlbumSong',
            params={'albumId': album_id, 'pageNo': 1, 'pageSize': 100},
            timeout=20,
        )
        resp.raise_for_status()
        return tracks_from_migu(_loads(resp.text))[:200]

    return []


def resolve_track(client: Any, track: Dict[str, Any]) -> Optional[Any]:
    """Turn one album track dict into a downloadable SongInfo."""
    official = None
    if hasattr(client, '_parsewithofficialapiv1'):
        try:
            official = client._parsewithofficialapiv1(
                search_result=track,
                song_info_flac=None,
                lossless_quality_is_sufficient=False,
                request_overrides={},
            )
        except Exception:
            official = None
    if getattr(official, 'with_valid_download_url', False):
        return official

    if hasattr(client, '_parsewiththirdpartapis'):
        try:
            extra = client._parsewiththirdpartapis(search_result=track, request_overrides={})
        except Exception:
            extra = None
        if getattr(extra, 'with_valid_download_url', False):
            return extra
    return None
