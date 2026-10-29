import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.config import CONFIG
from backend.db import DB
from backend.downloader import init_pending_download, run_download, sanitize_filename
from backend.events import EVENTS
from backend.library import AUDIO_EXTENSIONS
from backend.sources_registry import MANAGER, SOURCE_CATALOG, SOURCE_ORDER
from backend.streamer import REGISTRY, _NullProgress, track_to_payload

PLAYLIST_DL_EXECUTOR = ThreadPoolExecutor(max_workers=3, thread_name_prefix='pl-dl')


class PlaylistError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _norm_text(val: str) -> str:
    s = (val or '').strip().lower()
    s = re.sub(r'\s+', ' ', s)
    return s


def _build_local_file_index() -> Tuple[Set[str], Dict[str, str]]:
    """Return (all_rel_paths, normalized_stem_to_rel_path) for fast local matching."""
    download_root = CONFIG.get('download_dir', os.path.join(os.getcwd(), 'downloads'))
    rel_paths: Set[str] = set()
    stem_map: Dict[str, str] = {}
    if not os.path.exists(download_root):
        return rel_paths, stem_map

    for root, _, files in os.walk(download_root):
        for fname in files:
            stem, ext = os.path.splitext(fname)
            if ext.lower() not in AUDIO_EXTENSIONS:
                continue
            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, download_root)
            rel_paths.add(rel_path)
            norm_stem = _norm_text(stem)
            # Prefer lossless if multiple formats exist for the same stem
            if norm_stem not in stem_map or ext.lower() in {'.flac', '.wav', '.ape'}:
                stem_map[norm_stem] = rel_path

    return rel_paths, stem_map


def _match_local_rel_path(
    rel_path: str,
    singers: str,
    song_name: str,
    rel_paths: Set[str],
    stem_map: Dict[str, str],
) -> str:
    if rel_path and rel_path in rel_paths:
        return rel_path
    clean_singers = sanitize_filename(singers or 'unknown')
    clean_song = sanitize_filename(song_name or 'track')
    candidate_stem = _norm_text(f"{clean_singers} - {clean_song}")
    if candidate_stem in stem_map:
        return stem_map[candidate_stem]
    raw_stem = _norm_text(f"{singers} - {song_name}")
    if raw_stem in stem_map:
        return stem_map[raw_stem]
    return ''


def normalize_track_input(
    raw: Dict[str, Any],
    rel_paths: Optional[Set[str]] = None,
    stem_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise PlaylistError('曲目数据格式无效', 400)

    # Enrich from REGISTRY if token is active
    token = str(raw.get('token') or '').strip()
    reg_entry = REGISTRY.get(token) if token else None
    song_obj = reg_entry['song_info'] if reg_entry else None

    song_name = str(raw.get('song_name') or getattr(song_obj, 'song_name', '') or '').strip()
    if not song_name:
        raise PlaylistError('曲目名称不能为空', 400)

    singers = str(raw.get('singers') or getattr(song_obj, 'singers', '') or '未知艺人').strip() or '未知艺人'
    album = str(raw.get('album') or getattr(song_obj, 'album', '') or '').strip()
    source = str(raw.get('source') or (reg_entry or {}).get('source') or '').strip()
    source_meta = SOURCE_CATALOG.get(source, {})
    source_label = str(
        raw.get('source_short')
        or raw.get('source_label')
        or source_meta.get('short')
        or source_meta.get('label')
        or ('本地' if raw.get('rel_path') else source)
    ).strip()

    song_id = str(
        raw.get('song_id')
        or getattr(song_obj, 'identifier', '')
        or ''
    ).strip()
    ext = str(raw.get('ext') or getattr(song_obj, 'ext', 'mp3') or 'mp3').lower().lstrip('.')
    duration = str(raw.get('duration') or getattr(song_obj, 'duration', '') or '').strip()
    file_size = str(raw.get('file_size') or getattr(song_obj, 'file_size', '') or '').strip()
    cover_url = str(raw.get('cover_url') or getattr(song_obj, 'cover_url', '') or '').strip()
    lossless = 1 if (raw.get('lossless') or ext in {'flac', 'wav', 'ape', 'alac'}) else 0

    rel_path = str(raw.get('rel_path') or '').strip()
    if rel_paths is not None and stem_map is not None:
        matched = _match_local_rel_path(rel_path, singers, song_name, rel_paths, stem_map)
        if matched:
            rel_path = matched

    if rel_path and not source:
        source = 'local'
        source_label = '本地'

    if source and source != 'local' and song_id:
        track_key = f"src:{source}:{song_id}"
    elif rel_path and source in ('', 'local'):
        track_key = f"local:{rel_path}"
    else:
        track_key = f"meta:{_norm_text(singers)}::{_norm_text(song_name)}::{_norm_text(album)}"

    return {
        'track_key': track_key,
        'rel_path': rel_path,
        'source': source,
        'source_label': source_label,
        'song_id': song_id,
        'song_name': song_name[:200],
        'singers': singers[:200],
        'album': album[:200],
        'ext': ext[:16] or 'mp3',
        'duration': duration[:32],
        'file_size': file_size[:32],
        'cover_url': cover_url[:1000],
        'lossless': lossless,
    }


def _track_row_to_dict(
    row: Any,
    rel_paths: Set[str],
    stem_map: Dict[str, str],
    rebind_updates: Optional[List[Tuple[str, int]]] = None,
) -> Dict[str, Any]:
    stored_rel = row['rel_path'] or ''
    effective_rel = _match_local_rel_path(
        stored_rel,
        row['singers'],
        row['song_name'],
        rel_paths,
        stem_map,
    )
    if effective_rel and effective_rel != stored_rel and rebind_updates is not None:
        rebind_updates.append((effective_rel, int(row['id'])))

    is_local = bool(effective_rel)
    cover_url = row['cover_url'] or ''
    has_cover = bool(cover_url or is_local)

    return {
        'item_id': int(row['id']),
        'playlist_id': row['playlist_id'],
        'position': int(row['position']),
        'track_key': row['track_key'],
        'rel_path': effective_rel,
        'is_local': is_local,
        'has_cover': has_cover,
        'source': row['source'],
        'source_label': row['source_label'] or ('本地' if is_local else row['source']),
        'source_short': row['source_label'] or ('本地' if is_local else row['source']),
        'song_id': row['song_id'],
        'song_name': row['song_name'],
        'singers': row['singers'],
        'album': row['album'],
        'ext': row['ext'],
        'duration': row['duration'],
        'file_size': row['file_size'],
        'cover_url': cover_url,
        'lossless': bool(row['lossless']),
        'added_by': row['added_by'],
        'added_at': row['added_at'],
    }


def _get_playlist_notify_users(conn: Any, playlist_row: Any) -> Set[int]:
    if playlist_row['visibility'] == 'public':
        rows = conn.execute('SELECT id FROM users').fetchall()
        return {int(r['id']) for r in rows}

    uids = {int(playlist_row['owner_id'])}
    mrows = conn.execute(
        'SELECT user_id FROM playlist_members WHERE playlist_id = ?',
        (playlist_row['id'],),
    ).fetchall()
    for mr in mrows:
        uids.add(int(mr['user_id']))
    return uids


def _notify_playlist(
    conn: Any,
    playlist_row: Any,
    action: str,
    actor_id: int,
    client_id: str = '',
    extra_users: Optional[Set[int]] = None,
) -> None:
    targets = _get_playlist_notify_users(conn, playlist_row)
    if extra_users:
        targets |= set(extra_users)
    EVENTS.publish_users(
        targets,
        'playlist_changed',
        {
            'playlist_id': playlist_row['id'],
            'action': action,
            'actor_id': int(actor_id),
            'client_id': client_id or '',
        },
    )


def _compute_access(conn: Any, pl_row: Any, user: Dict[str, Any]) -> Dict[str, Any]:
    uid = int(user['id'])
    is_admin = user.get('role') == 'admin'
    is_owner = int(pl_row['owner_id']) == uid

    member_row = conn.execute(
        'SELECT permission FROM playlist_members WHERE playlist_id = ? AND user_id = ?',
        (pl_row['id'], uid),
    ).fetchone()
    member_perm = member_row['permission'] if member_row else None

    is_public = pl_row['visibility'] == 'public'
    public_editable = bool(pl_row['public_editable'])

    if is_owner:
        access_role = 'owner'
    elif member_perm == 'editor':
        access_role = 'editor'
    elif member_perm == 'viewer':
        access_role = 'viewer'
    elif is_public:
        access_role = 'public'
    elif is_admin:
        access_role = 'admin'
    else:
        access_role = 'none'

    can_manage = is_owner or is_admin
    can_edit = can_manage or member_perm == 'editor' or (is_public and public_editable)
    can_view = can_edit or member_perm == 'viewer' or is_public

    return {
        'access_role': access_role,
        'is_member': member_row is not None,
        'member_permission': member_perm,
        'can_view': can_view,
        'can_edit': can_edit,
        'can_manage': can_manage,
    }


def _serialize_playlist_summary(
    conn: Any,
    pl_row: Any,
    user: Dict[str, Any],
    rel_paths: Set[str],
    stem_map: Dict[str, str],
) -> Dict[str, Any]:
    access = _compute_access(conn, pl_row, user)
    owner = conn.execute(
        'SELECT username, display_name FROM users WHERE id = ?',
        (pl_row['owner_id'],),
    ).fetchone()

    members_rows = conn.execute(
        """
        SELECT pm.user_id, pm.permission, u.username, u.display_name
        FROM playlist_members pm
        JOIN users u ON u.id = pm.user_id
        WHERE pm.playlist_id = ?
        ORDER BY u.display_name COLLATE NOCASE ASC
        """,
        (pl_row['id'],),
    ).fetchall()

    trows = conn.execute(
        """
        SELECT id, rel_path, singers, song_name, cover_url
        FROM playlist_tracks
        WHERE playlist_id = ?
        ORDER BY position ASC, id ASC
        """,
        (pl_row['id'],),
    ).fetchall()

    track_count = len(trows)
    offline_count = 0
    cover_url = ''

    for idx, tr in enumerate(trows):
        eff_rel = _match_local_rel_path(tr['rel_path'] or '', tr['singers'], tr['song_name'], rel_paths, stem_map)
        if eff_rel:
            offline_count += 1
        if not cover_url:
            if tr['cover_url']:
                cover_url = tr['cover_url']
            elif eff_rel:
                from urllib.parse import quote
                cover_url = f"/api/library/cover/{quote(eff_rel)}"

    return {
        'id': pl_row['id'],
        'name': pl_row['name'],
        'description': pl_row['description'],
        'owner_id': int(pl_row['owner_id']),
        'owner_username': owner['username'] if owner else '',
        'owner_name': owner['display_name'] if owner else '未知用户',
        'created_by': pl_row['created_by'],
        'visibility': pl_row['visibility'],
        'public_editable': bool(pl_row['public_editable']),
        'source_playlist_id': pl_row['source_playlist_id'],
        'created_at': pl_row['created_at'],
        'updated_at': pl_row['updated_at'],
        'track_count': track_count,
        'offline_count': offline_count,
        'cover_url': cover_url,
        'members': [
            {
                'user_id': int(m['user_id']),
                'username': m['username'],
                'display_name': m['display_name'],
                'permission': m['permission'],
            }
            for m in members_rows
        ],
        **access,
    }


def list_playlists_for_user(user: Dict[str, Any]) -> List[Dict[str, Any]]:
    uid = int(user['id'])
    rel_paths, stem_map = _build_local_file_index()

    with DB.connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT p.*
            FROM playlists p
            LEFT JOIN playlist_members pm ON pm.playlist_id = p.id AND pm.user_id = ?
            WHERE p.owner_id = ?
               OR pm.user_id IS NOT NULL
               OR p.visibility = 'public'
            ORDER BY p.updated_at DESC, p.created_at DESC
            """,
            (uid, uid),
        ).fetchall()

        return [_serialize_playlist_summary(conn, r, user, rel_paths, stem_map) for r in rows]


def get_playlist_detail(playlist_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
    rel_paths, stem_map = _build_local_file_index()
    rebind_updates: List[Tuple[str, int]] = []

    with DB.connection() as conn:
        pl_row = conn.execute('SELECT * FROM playlists WHERE id = ?', (playlist_id,)).fetchone()
        if not pl_row:
            raise PlaylistError('找不到该歌单', 404)

        access = _compute_access(conn, pl_row, user)
        if not access['can_view']:
            raise PlaylistError('无权查看该私有歌单', 403)

        summary = _serialize_playlist_summary(conn, pl_row, user, rel_paths, stem_map)
        trows = conn.execute(
            'SELECT * FROM playlist_tracks WHERE playlist_id = ? ORDER BY position ASC, id ASC',
            (playlist_id,),
        ).fetchall()
        tracks = [_track_row_to_dict(r, rel_paths, stem_map, rebind_updates) for r in trows]

        if rebind_updates:
            conn.executemany(
                'UPDATE playlist_tracks SET rel_path = ? WHERE id = ?',
                rebind_updates,
            )

        return {'playlist': summary, 'tracks': tracks}


def create_playlist(
    actor: Dict[str, Any],
    name: str,
    description: str = '',
    visibility: str = 'private',
    public_editable: bool = False,
    owner_id: Optional[int] = None,
    members: Optional[List[Dict[str, Any]]] = None,
    initial_tracks: Optional[List[Dict[str, Any]]] = None,
    client_id: str = '',
) -> Dict[str, Any]:
    clean_name = (name or '').strip()
    if not clean_name or len(clean_name) > 80:
        raise PlaylistError('歌单名称需为 1–80 个字符', 400)

    clean_desc = (description or '').strip()[:300]
    vis = 'public' if visibility == 'public' else 'private'
    pub_edit = 1 if (vis == 'public' and public_editable) else 0

    actor_id = int(actor['id'])
    target_owner_id = int(owner_id) if owner_id is not None else actor_id
    if target_owner_id != actor_id and actor.get('role') != 'admin':
        raise PlaylistError('仅管理员可直接指定其他用户为歌单所有者', 403)

    rel_paths, stem_map = _build_local_file_index()
    pl_id = uuid.uuid4().hex[:12]
    now = time.time()

    with DB.connection() as conn:
        owner_row = conn.execute('SELECT id FROM users WHERE id = ?', (target_owner_id,)).fetchone()
        if not owner_row:
            raise PlaylistError('指定的目标用户不存在', 404)

        conn.execute(
            """
            INSERT INTO playlists (
                id, owner_id, created_by, name, description,
                visibility, public_editable, source_playlist_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (pl_id, target_owner_id, actor_id, clean_name, clean_desc, vis, pub_edit, now, now),
        )

        # If admin created playlist for someone else, keep admin or creator informed if included in members
        if members:
            _apply_members(conn, pl_id, target_owner_id, actor_id, members, now)

        if initial_tracks:
            _insert_tracks_batch(conn, pl_id, actor_id, initial_tracks, rel_paths, stem_map, now)

        pl_row = conn.execute('SELECT * FROM playlists WHERE id = ?', (pl_id,)).fetchone()
        _notify_playlist(conn, pl_row, 'created', actor_id, client_id, extra_users={actor_id, target_owner_id})
        return _serialize_playlist_summary(conn, pl_row, actor, rel_paths, stem_map)


def _apply_members(
    conn: Any,
    playlist_id: str,
    owner_id: int,
    actor_id: int,
    members: List[Dict[str, Any]],
    now: float,
) -> None:
    conn.execute('DELETE FROM playlist_members WHERE playlist_id = ?', (playlist_id,))
    seen_uids = set()
    for m in members:
        if not isinstance(m, dict) or 'user_id' not in m:
            continue
        try:
            uid = int(m['user_id'])
        except (TypeError, ValueError):
            continue
        if uid == owner_id or uid in seen_uids:
            continue
        perm = 'editor' if m.get('permission') == 'editor' else 'viewer'
        exists = conn.execute('SELECT id FROM users WHERE id = ?', (uid,)).fetchone()
        if not exists:
            continue
        seen_uids.add(uid)
        conn.execute(
            """
            INSERT INTO playlist_members (playlist_id, user_id, permission, added_by, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (playlist_id, uid, perm, actor_id, now),
        )


def _insert_tracks_batch(
    conn: Any,
    playlist_id: str,
    actor_id: int,
    raw_tracks: List[Dict[str, Any]],
    rel_paths: Set[str],
    stem_map: Dict[str, str],
    now: float,
) -> Tuple[int, int]:
    existing_keys = {
        r['track_key']
        for r in conn.execute(
            'SELECT track_key FROM playlist_tracks WHERE playlist_id = ?',
            (playlist_id,),
        ).fetchall()
    }
    max_pos_row = conn.execute(
        'SELECT COALESCE(MAX(position), -1) AS mp FROM playlist_tracks WHERE playlist_id = ?',
        (playlist_id,),
    ).fetchone()
    next_pos = int(max_pos_row['mp']) + 1

    added = 0
    skipped = 0
    for rt in raw_tracks:
        norm = normalize_track_input(rt, rel_paths, stem_map)
        if norm['track_key'] in existing_keys:
            skipped += 1
            continue
        existing_keys.add(norm['track_key'])
        conn.execute(
            """
            INSERT INTO playlist_tracks (
                playlist_id, position, track_key, rel_path, source, source_label,
                song_id, song_name, singers, album, ext, duration, file_size,
                cover_url, lossless, added_by, added_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                playlist_id,
                next_pos,
                norm['track_key'],
                norm['rel_path'],
                norm['source'],
                norm['source_label'],
                norm['song_id'],
                norm['song_name'],
                norm['singers'],
                norm['album'],
                norm['ext'],
                norm['duration'],
                norm['file_size'],
                norm['cover_url'],
                norm['lossless'],
                actor_id,
                now,
            ),
        )
        next_pos += 1
        added += 1

    return added, skipped


def update_playlist(
    playlist_id: str,
    actor: Dict[str, Any],
    data: Dict[str, Any],
    client_id: str = '',
) -> Dict[str, Any]:
    rel_paths, stem_map = _build_local_file_index()
    now = time.time()

    with DB.connection() as conn:
        pl_row = conn.execute('SELECT * FROM playlists WHERE id = ?', (playlist_id,)).fetchone()
        if not pl_row:
            raise PlaylistError('找不到该歌单', 404)

        access = _compute_access(conn, pl_row, actor)
        if not access['can_manage']:
            raise PlaylistError('只有歌单创建者或管理员可以修改歌单信息', 403)

        name = pl_row['name']
        if 'name' in data:
            clean_name = (data.get('name') or '').strip()
            if not clean_name or len(clean_name) > 80:
                raise PlaylistError('歌单名称需为 1–80 个字符', 400)
            name = clean_name

        desc = pl_row['description']
        if 'description' in data:
            desc = (data.get('description') or '').strip()[:300]

        vis = pl_row['visibility']
        if 'visibility' in data:
            vis = 'public' if data.get('visibility') == 'public' else 'private'

        pub_edit = int(pl_row['public_editable'])
        if 'public_editable' in data:
            pub_edit = 1 if data.get('public_editable') else 0
        if vis != 'public':
            pub_edit = 0

        owner_id = int(pl_row['owner_id'])
        if 'owner_id' in data and data['owner_id'] is not None:
            new_owner = int(data['owner_id'])
            if new_owner != owner_id:
                if actor.get('role') != 'admin':
                    raise PlaylistError('仅管理员可转移歌单所有者', 403)
                if not conn.execute('SELECT id FROM users WHERE id = ?', (new_owner,)).fetchone():
                    raise PlaylistError('目标所有者不存在', 404)
                owner_id = new_owner
                conn.execute(
                    'DELETE FROM playlist_members WHERE playlist_id = ? AND user_id = ?',
                    (playlist_id, owner_id),
                )

        old_users = _get_playlist_notify_users(conn, pl_row)
        conn.execute(
            """
            UPDATE playlists
            SET name = ?, description = ?, visibility = ?, public_editable = ?, owner_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (name, desc, vis, pub_edit, owner_id, now, playlist_id),
        )
        updated_row = conn.execute('SELECT * FROM playlists WHERE id = ?', (playlist_id,)).fetchone()
        _notify_playlist(conn, updated_row, 'updated', int(actor['id']), client_id, extra_users=old_users)
        return _serialize_playlist_summary(conn, updated_row, actor, rel_paths, stem_map)


def update_playlist_sharing(
    playlist_id: str,
    actor: Dict[str, Any],
    visibility: str,
    public_editable: bool,
    members: List[Dict[str, Any]],
    client_id: str = '',
) -> Dict[str, Any]:
    rel_paths, stem_map = _build_local_file_index()
    now = time.time()

    with DB.connection() as conn:
        pl_row = conn.execute('SELECT * FROM playlists WHERE id = ?', (playlist_id,)).fetchone()
        if not pl_row:
            raise PlaylistError('找不到该歌单', 404)

        access = _compute_access(conn, pl_row, actor)
        if not access['can_manage']:
            raise PlaylistError('只有歌单创建者或管理员可以管理共享设置', 403)

        old_users = _get_playlist_notify_users(conn, pl_row)
        vis = 'public' if visibility == 'public' else 'private'
        pub_edit = 1 if (vis == 'public' and public_editable) else 0

        conn.execute(
            'UPDATE playlists SET visibility = ?, public_editable = ?, updated_at = ? WHERE id = ?',
            (vis, pub_edit, now, playlist_id),
        )
        if isinstance(members, list):
            _apply_members(conn, playlist_id, int(pl_row['owner_id']), int(actor['id']), members, now)

        updated_row = conn.execute('SELECT * FROM playlists WHERE id = ?', (playlist_id,)).fetchone()
        _notify_playlist(conn, updated_row, 'shared', int(actor['id']), client_id, extra_users=old_users)
        return _serialize_playlist_summary(conn, updated_row, actor, rel_paths, stem_map)


def delete_playlist(playlist_id: str, actor: Dict[str, Any], client_id: str = '') -> None:
    with DB.connection() as conn:
        pl_row = conn.execute('SELECT * FROM playlists WHERE id = ?', (playlist_id,)).fetchone()
        if not pl_row:
            raise PlaylistError('找不到该歌单', 404)

        access = _compute_access(conn, pl_row, actor)
        if not access['can_manage']:
            raise PlaylistError('只有歌单创建者或管理员可以删除该歌单', 403)

        notify_users = _get_playlist_notify_users(conn, pl_row)
        conn.execute('DELETE FROM playlists WHERE id = ?', (playlist_id,))

    EVENTS.publish_users(
        notify_users,
        'playlist_changed',
        {
            'playlist_id': playlist_id,
            'action': 'deleted',
            'actor_id': int(actor['id']),
            'client_id': client_id or '',
        },
    )


def leave_shared_playlist(playlist_id: str, user: Dict[str, Any], client_id: str = '') -> None:
    uid = int(user['id'])
    with DB.connection() as conn:
        pl_row = conn.execute('SELECT * FROM playlists WHERE id = ?', (playlist_id,)).fetchone()
        if not pl_row:
            raise PlaylistError('找不到该歌单', 404)
        if int(pl_row['owner_id']) == uid:
            raise PlaylistError('创建者不能退出自己的歌单，请直接删除歌单', 400)
        conn.execute(
            'DELETE FROM playlist_members WHERE playlist_id = ? AND user_id = ?',
            (playlist_id, uid),
        )
        _notify_playlist(conn, pl_row, 'member_left', uid, client_id, extra_users={uid})


def add_tracks_to_playlist(
    playlist_id: str,
    actor: Dict[str, Any],
    raw_tracks: List[Dict[str, Any]],
    client_id: str = '',
) -> Dict[str, Any]:
    if not raw_tracks:
        raise PlaylistError('请提供要添加的曲目', 400)

    rel_paths, stem_map = _build_local_file_index()
    now = time.time()

    with DB.connection() as conn:
        pl_row = conn.execute('SELECT * FROM playlists WHERE id = ?', (playlist_id,)).fetchone()
        if not pl_row:
            raise PlaylistError('找不到该歌单', 404)

        access = _compute_access(conn, pl_row, actor)
        if not access['can_edit']:
            raise PlaylistError('没有权限向该歌单添加曲目', 403)

        added, skipped = _insert_tracks_batch(
            conn, playlist_id, int(actor['id']), raw_tracks, rel_paths, stem_map, now
        )
        if added > 0:
            conn.execute('UPDATE playlists SET updated_at = ? WHERE id = ?', (now, playlist_id))
            pl_row = conn.execute('SELECT * FROM playlists WHERE id = ?', (playlist_id,)).fetchone()
            _notify_playlist(conn, pl_row, 'tracks_added', int(actor['id']), client_id)

        return {'added': added, 'skipped': skipped}


def remove_track_from_playlist(
    playlist_id: str,
    item_id: int,
    actor: Dict[str, Any],
    client_id: str = '',
) -> None:
    now = time.time()
    with DB.connection() as conn:
        pl_row = conn.execute('SELECT * FROM playlists WHERE id = ?', (playlist_id,)).fetchone()
        if not pl_row:
            raise PlaylistError('找不到该歌单', 404)

        access = _compute_access(conn, pl_row, actor)
        if not access['can_edit']:
            raise PlaylistError('没有权限移除该歌单中的曲目', 403)

        cur = conn.execute(
            'DELETE FROM playlist_tracks WHERE id = ? AND playlist_id = ?',
            (int(item_id), playlist_id),
        )
        if cur.rowcount == 0:
            raise PlaylistError('未找到该歌单曲目', 404)

        rem = conn.execute(
            'SELECT id FROM playlist_tracks WHERE playlist_id = ? ORDER BY position ASC, id ASC',
            (playlist_id,),
        ).fetchall()
        for pos, r in enumerate(rem):
            conn.execute('UPDATE playlist_tracks SET position = ? WHERE id = ?', (pos, r['id']))

        conn.execute('UPDATE playlists SET updated_at = ? WHERE id = ?', (now, playlist_id))
        _notify_playlist(conn, pl_row, 'tracks_removed', int(actor['id']), client_id)


def reorder_playlist_tracks(
    playlist_id: str,
    item_ids: List[int],
    actor: Dict[str, Any],
    client_id: str = '',
) -> None:
    now = time.time()
    with DB.connection() as conn:
        pl_row = conn.execute('SELECT * FROM playlists WHERE id = ?', (playlist_id,)).fetchone()
        if not pl_row:
            raise PlaylistError('找不到该歌单', 404)

        access = _compute_access(conn, pl_row, actor)
        if not access['can_edit']:
            raise PlaylistError('没有权限调整歌单排序', 403)

        rows = conn.execute(
            'SELECT id FROM playlist_tracks WHERE playlist_id = ? ORDER BY position ASC, id ASC',
            (playlist_id,),
        ).fetchall()
        existing_ids = [int(r['id']) for r in rows]
        existing_set = set(existing_ids)

        ordered: List[int] = []
        seen = set()
        for raw_id in item_ids or []:
            iid = int(raw_id)
            if iid in existing_set and iid not in seen:
                ordered.append(iid)
                seen.add(iid)

        for iid in existing_ids:
            if iid not in seen:
                ordered.append(iid)

        for pos, iid in enumerate(ordered):
            conn.execute('UPDATE playlist_tracks SET position = ? WHERE id = ?', (pos, iid))

        conn.execute('UPDATE playlists SET updated_at = ? WHERE id = ?', (now, playlist_id))
        _notify_playlist(conn, pl_row, 'tracks_reordered', int(actor['id']), client_id)


def distribute_playlist(
    playlist_id: str,
    target_user_ids: List[int],
    actor: Dict[str, Any],
    mode: str = 'sync',
    client_id: str = '',
) -> Dict[str, Any]:
    """Create or sync independent copies of a playlist into multiple target users' accounts."""
    if not target_user_ids:
        raise PlaylistError('请至少选择一位目标用户', 400)

    actor_id = int(actor['id'])
    is_admin = actor.get('role') == 'admin'
    now = time.time()

    created_list = []
    synced_list = []
    notified_users: Set[int] = {actor_id}

    with DB.connection() as conn:
        src_pl = conn.execute('SELECT * FROM playlists WHERE id = ?', (playlist_id,)).fetchone()
        if not src_pl:
            raise PlaylistError('找不到源歌单', 404)

        access = _compute_access(conn, src_pl, actor)
        if not access['can_view']:
            raise PlaylistError('无权访问源歌单', 403)

        src_tracks = conn.execute(
            'SELECT * FROM playlist_tracks WHERE playlist_id = ? ORDER BY position ASC, id ASC',
            (playlist_id,),
        ).fetchall()

        clean_targets = []
        seen_t = set()
        for raw_uid in target_user_ids:
            uid = int(raw_uid)
            if uid not in seen_t:
                seen_t.add(uid)
                clean_targets.append(uid)

        for target_uid in clean_targets:
            u_row = conn.execute(
                'SELECT id, username, display_name FROM users WHERE id = ?',
                (target_uid,),
            ).fetchone()
            if not u_row:
                continue

            existing_copy = None
            if mode != 'copy':
                existing_copy = conn.execute(
                    """
                    SELECT * FROM playlists
                    WHERE source_playlist_id = ? AND owner_id = ?
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (playlist_id, target_uid),
                ).fetchone()

            if existing_copy and (
                is_admin
                or int(src_pl['owner_id']) == actor_id
                or existing_copy['created_by'] == actor_id
                or target_uid == actor_id
            ):
                target_pl_id = existing_copy['id']
                conn.execute(
                    'UPDATE playlists SET name = ?, description = ?, updated_at = ? WHERE id = ?',
                    (src_pl['name'], src_pl['description'], now, target_pl_id),
                )
                conn.execute('DELETE FROM playlist_tracks WHERE playlist_id = ?', (target_pl_id,))
                synced_list.append({
                    'user_id': target_uid,
                    'display_name': u_row['display_name'],
                    'playlist_id': target_pl_id,
                })
            else:
                target_pl_id = uuid.uuid4().hex[:12]
                conn.execute(
                    """
                    INSERT INTO playlists (
                        id, owner_id, created_by, name, description,
                        visibility, public_editable, source_playlist_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'private', 0, ?, ?, ?)
                    """,
                    (
                        target_pl_id,
                        target_uid,
                        actor_id,
                        src_pl['name'],
                        src_pl['description'],
                        playlist_id,
                        now,
                        now,
                    ),
                )
                created_list.append({
                    'user_id': target_uid,
                    'display_name': u_row['display_name'],
                    'playlist_id': target_pl_id,
                })

            for pos, tr in enumerate(src_tracks):
                conn.execute(
                    """
                    INSERT INTO playlist_tracks (
                        playlist_id, position, track_key, rel_path, source, source_label,
                        song_id, song_name, singers, album, ext, duration, file_size,
                        cover_url, lossless, added_by, added_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        target_pl_id,
                        pos,
                        tr['track_key'],
                        tr['rel_path'],
                        tr['source'],
                        tr['source_label'],
                        tr['song_id'],
                        tr['song_name'],
                        tr['singers'],
                        tr['album'],
                        tr['ext'],
                        tr['duration'],
                        tr['file_size'],
                        tr['cover_url'],
                        tr['lossless'],
                        actor_id,
                        now,
                    ),
                )
            notified_users.add(target_uid)

    EVENTS.publish_users(
        notified_users,
        'playlist_changed',
        {
            'playlist_id': playlist_id,
            'action': 'distributed',
            'actor_id': actor_id,
            'client_id': client_id or '',
        },
    )

    return {'created': created_list, 'synced': synced_list}


def bind_downloaded_file(rel_path: str, song_name: str, singers: str) -> None:
    """Link newly downloaded local audio file to any matching playlist tracks."""
    if not rel_path:
        return
    clean_singers = _norm_text(sanitize_filename(singers or ''))
    clean_song = _norm_text(sanitize_filename(song_name or ''))
    raw_singers = _norm_text(singers or '')
    raw_song = _norm_text(song_name or '')

    affected_playlists: Set[str] = set()
    notify_users: Set[int] = set()

    with DB.connection() as conn:
        rows = conn.execute(
            "SELECT id, playlist_id, singers, song_name FROM playlist_tracks WHERE rel_path = '' OR rel_path IS NULL"
        ).fetchall()
        matched_ids = []
        for r in rows:
            rs = _norm_text(r['singers'])
            rn = _norm_text(r['song_name'])
            cs = _norm_text(sanitize_filename(r['singers'] or ''))
            cn = _norm_text(sanitize_filename(r['song_name'] or ''))
            if (rn == raw_song and rs == raw_singers) or (cn == clean_song and cs == clean_singers):
                matched_ids.append(int(r['id']))
                affected_playlists.add(r['playlist_id'])

        for mid in matched_ids:
            conn.execute('UPDATE playlist_tracks SET rel_path = ? WHERE id = ?', (rel_path, mid))

        for pid in affected_playlists:
            pl_row = conn.execute('SELECT * FROM playlists WHERE id = ?', (pid,)).fetchone()
            if pl_row:
                notify_users |= _get_playlist_notify_users(conn, pl_row)

    EVENTS.publish_all('library_changed', {'rel_path': rel_path, 'action': 'downloaded'})
    if notify_users:
        for pid in affected_playlists:
            EVENTS.publish_users(
                notify_users,
                'playlist_changed',
                {'playlist_id': pid, 'action': 'track_downloaded', 'actor_id': 0, 'client_id': ''},
            )


def _search_single_source_best_match(
    source: str,
    song_name: str,
    singers: str,
    song_id: str = '',
) -> Optional[Tuple[Any, str]]:
    if source not in SOURCE_CATALOG:
        return None
    client = MANAGER.get_client(source)
    if not client:
        return None

    keyword = f"{singers} {song_name}".strip() if singers and singers != '未知艺人' else song_name
    progress = _NullProgress()
    try:
        search_urls = client._constructsearchurls(keyword=keyword, rule={}, request_overrides={})
    except Exception:
        return None

    bucket: list = []
    for url in search_urls[:2]:
        try:
            client._search(
                keyword=keyword,
                search_url=url,
                request_overrides={},
                song_infos=bucket,
                progress=progress,
            )
        except Exception:
            continue
        if bucket:
            break

    if not bucket:
        return None

    target_name = _norm_text(song_name)
    target_singer = _norm_text(singers)
    best = None
    best_score = -1

    for cand in bucket:
        dl_url = getattr(cand, 'download_url', None)
        if not isinstance(dl_url, str) or not dl_url.startswith('http'):
            continue
        score = 1
        cand_id = str(getattr(cand, 'identifier', '') or '')
        if song_id and cand_id and cand_id == song_id:
            score += 100
        cn = _norm_text(str(getattr(cand, 'song_name', '') or ''))
        cs = _norm_text(str(getattr(cand, 'singers', '') or ''))
        if cn == target_name:
            score += 20
        elif target_name and target_name in cn:
            score += 10
        if target_singer and target_singer != '未知艺人':
            if cs == target_singer:
                score += 15
            elif target_singer in cs or cs in target_singer:
                score += 8
        ext = str(getattr(cand, 'ext', '') or '').lower().lstrip('.')
        if ext in {'flac', 'wav', 'ape'}:
            score += 2

        if score > best_score:
            best_score = score
            best = cand

    return (best, source) if best else None


def resolve_online_track(track_data: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve a playable local path or fresh upstream token for a saved playlist/queue track."""
    song_name = str(track_data.get('song_name') or '').strip()
    singers = str(track_data.get('singers') or '').strip()
    rel_path = str(track_data.get('rel_path') or '').strip()
    source = str(track_data.get('source') or '').strip()
    song_id = str(track_data.get('song_id') or '').strip()
    token = str(track_data.get('token') or '').strip()

    rel_paths, stem_map = _build_local_file_index()
    matched_rel = _match_local_rel_path(rel_path, singers, song_name, rel_paths, stem_map)
    if matched_rel:
        return {
            'is_local': True,
            'rel_path': matched_rel,
            'has_cover': True,
            'song_name': song_name,
            'singers': singers or '未知艺人',
            'album': str(track_data.get('album') or ''),
            'ext': os.path.splitext(matched_rel)[1].lstrip('.').lower() or 'mp3',
            'source': 'local',
            'source_label': '本地',
            'source_short': '本地',
        }

    if token:
        entry = REGISTRY.get(token)
        if entry:
            song_info = entry['song_info']
            dl_url = getattr(song_info, 'download_url', None)
            if isinstance(dl_url, str) and dl_url.startswith('http'):
                return track_to_payload(song_info, token, entry['source'])

    if not song_name:
        raise PlaylistError('缺少曲目名称，无法解析音源', 400)

    candidate_sources: List[str] = []
    if source and source in SOURCE_CATALOG:
        candidate_sources.append(source)
    for s in CONFIG.get('active_sources', []):
        if s in SOURCE_CATALOG and s not in candidate_sources:
            candidate_sources.append(s)
    if not candidate_sources:
        candidate_sources = [s for s in SOURCE_ORDER if SOURCE_CATALOG[s].get('default')]

    for src in candidate_sources[:4]:
        found = _search_single_source_best_match(src, song_name, singers, song_id if src == source else '')
        if found:
            song_obj, matched_src = found
            fresh_token = REGISTRY.add(song_obj, matched_src)
            return track_to_payload(song_obj, fresh_token, matched_src)

    raise PlaylistError(f'未能重新解析曲目「{song_name}」，请检查音源或代理配置', 404)


def queue_playlist_downloads(playlist_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
    """Queue background downloads for all non-local tracks in a playlist."""
    detail = get_playlist_detail(playlist_id, user)
    tracks = detail['tracks']

    pending_tracks = [t for t in tracks if not t.get('is_local')]
    already_local = len(tracks) - len(pending_tracks)
    if not pending_tracks:
        return {'queued': 0, 'already_local': already_local, 'download_ids': []}

    jobs = []
    for t in pending_tracks:
        dl_id = uuid.uuid4().hex[:16]
        display_name = f"{t.get('singers') or '未知艺人'} - {t.get('song_name') or 'track'}"
        init_pending_download(dl_id, display_name)
        jobs.append((dl_id, t))

    def _worker(download_id: str, track_item: Dict[str, Any]):
        try:
            resolved = resolve_online_track(track_item)
            if resolved.get('is_local') and resolved.get('rel_path'):
                bind_downloaded_file(
                    resolved['rel_path'],
                    track_item.get('song_name', ''),
                    track_item.get('singers', ''),
                )
                from backend.downloader import mark_download_already_exists
                mark_download_already_exists(download_id, resolved['rel_path'])
                return
            tok = resolved.get('token')
            if not tok:
                from backend.downloader import mark_download_failed
                mark_download_failed(download_id, '无法解析有效下载直链')
                return
            run_download(download_id, tok)
        except Exception as err:
            from backend.downloader import mark_download_failed
            mark_download_failed(download_id, str(err))

    for dl_id, t in jobs:
        PLAYLIST_DL_EXECUTOR.submit(_worker, dl_id, t)

    return {
        'queued': len(jobs),
        'already_local': already_local,
        'download_ids': [dl_id for dl_id, _ in jobs],
    }


# ---------------------------------------------------------------------------
# Cross-Device User Playback Queue & State Sync
# ---------------------------------------------------------------------------
def get_playback_state(user_id: int) -> Dict[str, Any]:
    rel_paths, stem_map = _build_local_file_index()
    with DB.connection() as conn:
        row = conn.execute(
            'SELECT * FROM user_playback_state WHERE user_id = ?',
            (int(user_id),),
        ).fetchone()
        if not row:
            return {
                'queue': [],
                'current_index': -1,
                'play_mode': 'loop',
                'position_sec': 0.0,
                'updated_at': 0,
            }

        try:
            raw_queue = json.loads(row['queue_json'] or '[]')
            if not isinstance(raw_queue, list):
                raw_queue = []
        except Exception:
            raw_queue = []

        # Reconcile local paths so queue items downloaded on server play locally
        hydrated_queue = []
        for item in raw_queue[:500]:
            if not isinstance(item, dict):
                continue
            eff_rel = _match_local_rel_path(
                str(item.get('rel_path') or ''),
                str(item.get('singers') or ''),
                str(item.get('song_name') or ''),
                rel_paths,
                stem_map,
            )
            cloned = dict(item)
            if eff_rel:
                cloned['rel_path'] = eff_rel
                cloned['is_local'] = True
                cloned['has_cover'] = True
            else:
                cloned['rel_path'] = ''
                cloned['is_local'] = False
            hydrated_queue.append(cloned)

        return {
            'queue': hydrated_queue,
            'current_index': int(row['current_index']),
            'play_mode': row['play_mode'] if row['play_mode'] in ('loop', 'single', 'shuffle') else 'loop',
            'position_sec': float(row['position_sec'] or 0.0),
            'client_id': row['client_id'] or '',
            'updated_at': float(row['updated_at'] or 0.0),
        }


def save_playback_state(user_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    uid = int(user_id)
    raw_queue = data.get('queue')
    if not isinstance(raw_queue, list):
        raw_queue = []

    sanitized_queue = []
    for t in raw_queue[:500]:
        if not isinstance(t, dict) or not t.get('song_name'):
            continue
        sanitized_queue.append({
            'token': str(t.get('token') or ''),
            'rel_path': str(t.get('rel_path') or ''),
            'has_cover': bool(t.get('has_cover')),
            'source': str(t.get('source') or ''),
            'source_label': str(t.get('source_label') or ''),
            'source_short': str(t.get('source_short') or ''),
            'song_id': str(t.get('song_id') or ''),
            'song_name': str(t.get('song_name') or '')[:200],
            'singers': str(t.get('singers') or '未知艺人')[:200],
            'album': str(t.get('album') or '')[:200],
            'ext': str(t.get('ext') or 'mp3')[:16],
            'duration': str(t.get('duration') or '')[:32],
            'file_size': str(t.get('file_size') or '')[:32],
            'cover_url': str(t.get('cover_url') or '')[:1000],
            'lossless': bool(t.get('lossless')),
        })

    current_index = int(data.get('current_index', -1))
    if not sanitized_queue:
        current_index = -1
    elif current_index >= len(sanitized_queue):
        current_index = len(sanitized_queue) - 1

    play_mode = str(data.get('play_mode') or 'loop')
    if play_mode not in ('loop', 'single', 'shuffle'):
        play_mode = 'loop'

    try:
        position_sec = max(0.0, float(data.get('position_sec') or 0.0))
    except (TypeError, ValueError):
        position_sec = 0.0

    client_id = str(data.get('client_id') or '')[:64]
    now = time.time()
    queue_json = json.dumps(sanitized_queue, ensure_ascii=False)

    with DB.connection() as conn:
        conn.execute(
            """
            INSERT INTO user_playback_state (
                user_id, queue_json, current_index, play_mode, position_sec, client_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                queue_json = excluded.queue_json,
                current_index = excluded.current_index,
                play_mode = excluded.play_mode,
                position_sec = excluded.position_sec,
                client_id = excluded.client_id,
                updated_at = excluded.updated_at
            """,
            (uid, queue_json, current_index, play_mode, position_sec, client_id, now),
        )

    state = get_playback_state(uid)
    if data.get('broadcast', True):
        EVENTS.publish_users(
            {uid},
            'queue_changed',
            {'state': state, 'client_id': client_id},
            exclude_client_id=client_id,
        )
    return state
