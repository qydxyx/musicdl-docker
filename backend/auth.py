import hashlib
import re
import secrets
import time
from functools import wraps
from typing import Any, Callable, Dict, List, Optional

from flask import g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from backend.db import DB

SESSION_COOKIE = 'musicdl_session'
SESSION_TTL_SECONDS = 30 * 24 * 3600
SESSION_RENEW_THRESHOLD = 20 * 24 * 3600

USERNAME_RE = re.compile(r'^[^\s/\\<>:"|?*\x00-\x1f]{2,32}$')


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()


def _row_to_user(row: Any) -> Dict[str, Any]:
    return {
        'id': int(row['id']),
        'username': row['username'],
        'display_name': row['display_name'],
        'role': row['role'],
        'created_at': row['created_at'],
        'updated_at': row['updated_at'],
    }


def validate_username(username: str) -> str:
    clean = (username or '').strip()
    if not USERNAME_RE.match(clean):
        raise AuthError('用户名需为 2–32 个字符，且不能包含空格或特殊路径符号', 400)
    return clean


def validate_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 6:
        raise AuthError('密码长度至少需要 6 位', 400)
    if len(password) > 128:
        raise AuthError('密码长度不能超过 128 位', 400)
    return password


def count_users() -> int:
    with DB.connection() as conn:
        row = conn.execute('SELECT COUNT(*) AS cnt FROM users').fetchone()
        return int(row['cnt']) if row else 0


def setup_initial_admin(username: str, password: str, display_name: str = '') -> Dict[str, Any]:
    uname = validate_username(username)
    pwd = validate_password(password)
    dname = (display_name or '').strip() or uname
    now = time.time()
    pwd_hash = generate_password_hash(pwd)

    with DB.connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        existing = conn.execute('SELECT COUNT(*) AS cnt FROM users').fetchone()['cnt']
        if existing > 0:
            raise AuthError('系统已完成初始化，请直接登录', 409)

        cur = conn.execute(
            """
            INSERT INTO users (username, display_name, password_hash, role, created_at, updated_at)
            VALUES (?, ?, ?, 'admin', ?, ?)
            """,
            (uname, dname[:48], pwd_hash, now, now),
        )
        row = conn.execute('SELECT * FROM users WHERE id = ?', (cur.lastrowid,)).fetchone()
        return _row_to_user(row)


def create_user(
    username: str,
    password: str,
    display_name: str = '',
    role: str = 'user',
) -> Dict[str, Any]:
    uname = validate_username(username)
    pwd = validate_password(password)
    dname = (display_name or '').strip() or uname
    if role not in ('user', 'admin'):
        role = 'user'
    now = time.time()
    pwd_hash = generate_password_hash(pwd)

    with DB.connection() as conn:
        dup = conn.execute('SELECT id FROM users WHERE username = ?', (uname,)).fetchone()
        if dup:
            raise AuthError(f'用户名 "{uname}" 已存在', 409)

        cur = conn.execute(
            """
            INSERT INTO users (username, display_name, password_hash, role, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (uname, dname[:48], pwd_hash, role, now, now),
        )
        row = conn.execute('SELECT * FROM users WHERE id = ?', (cur.lastrowid,)).fetchone()
        return _row_to_user(row)


def authenticate_user(username: str, password: str) -> Dict[str, Any]:
    uname = (username or '').strip()
    pwd = password or ''
    if not uname or not pwd:
        raise AuthError('请输入用户名和密码', 400)

    with DB.connection() as conn:
        row = conn.execute('SELECT * FROM users WHERE username = ?', (uname,)).fetchone()
        if not row or not check_password_hash(row['password_hash'], pwd):
            raise AuthError('用户名或密码不正确', 401)
        return _row_to_user(row)


def create_session(user_id: int, user_agent: str = '') -> str:
    raw_token = secrets.token_hex(32)
    token_hash = _hash_token(raw_token)
    now = time.time()
    expires_at = now + SESSION_TTL_SECONDS

    with DB.connection() as conn:
        conn.execute('DELETE FROM sessions WHERE expires_at < ?', (now,))
        conn.execute(
            """
            INSERT INTO sessions (token_hash, user_id, user_agent, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (token_hash, int(user_id), (user_agent or '')[:255], now, expires_at),
        )
    return raw_token


def revoke_session(raw_token: str) -> None:
    if not raw_token:
        return
    token_hash = _hash_token(raw_token)
    with DB.connection() as conn:
        conn.execute('DELETE FROM sessions WHERE token_hash = ?', (token_hash,))


def get_user_by_token(raw_token: str) -> Optional[Dict[str, Any]]:
    if not raw_token:
        return None
    token_hash = _hash_token(raw_token)
    now = time.time()

    with DB.connection() as conn:
        row = conn.execute(
            """
            SELECT u.*, s.expires_at
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if not row:
            return None
        if row['expires_at'] <= now:
            conn.execute('DELETE FROM sessions WHERE token_hash = ?', (token_hash,))
            return None
        if row['expires_at'] - now < SESSION_RENEW_THRESHOLD:
            conn.execute(
                'UPDATE sessions SET expires_at = ? WHERE token_hash = ?',
                (now + SESSION_TTL_SECONDS, token_hash),
            )
        return _row_to_user(row)


def get_request_token() -> str:
    cookie_tok = request.cookies.get(SESSION_COOKIE, '').strip()
    if cookie_tok:
        return cookie_tok
    auth_header = request.headers.get('Authorization', '').strip()
    if auth_header.lower().startswith('bearer '):
        return auth_header[7:].strip()
    return ''


def get_current_user() -> Optional[Dict[str, Any]]:
    if hasattr(g, '_current_user_loaded'):
        return g.current_user
    token = get_request_token()
    user = get_user_by_token(token) if token else None
    g.current_user = user
    g._current_user_loaded = True
    return user


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    with DB.connection() as conn:
        row = conn.execute('SELECT * FROM users WHERE id = ?', (int(user_id),)).fetchone()
        return _row_to_user(row) if row else None


def list_users(include_admin_details: bool = False) -> List[Dict[str, Any]]:
    with DB.connection() as conn:
        if include_admin_details:
            rows = conn.execute(
                """
                SELECT u.*,
                       (SELECT COUNT(*) FROM playlists p WHERE p.owner_id = u.id) AS playlist_count
                FROM users u
                ORDER BY CASE WHEN u.role = 'admin' THEN 0 ELSE 1 END, u.id ASC
                """
            ).fetchall()
            result = []
            for r in rows:
                u = _row_to_user(r)
                u['playlist_count'] = int(r['playlist_count'] or 0)
                result.append(u)
            return result

        rows = conn.execute(
            """
            SELECT id, username, display_name, role
            FROM users
            ORDER BY display_name COLLATE NOCASE ASC, id ASC
            """
        ).fetchall()
        return [
            {
                'id': int(r['id']),
                'username': r['username'],
                'display_name': r['display_name'],
                'role': r['role'],
            }
            for r in rows
        ]


def update_own_profile(user_id: int, display_name: str) -> Dict[str, Any]:
    dname = (display_name or '').strip()
    if not dname or len(dname) > 48:
        raise AuthError('显示昵称需为 1–48 个字符', 400)
    now = time.time()
    with DB.connection() as conn:
        conn.execute(
            'UPDATE users SET display_name = ?, updated_at = ? WHERE id = ?',
            (dname, now, int(user_id)),
        )
        row = conn.execute('SELECT * FROM users WHERE id = ?', (int(user_id),)).fetchone()
        if not row:
            raise AuthError('用户不存在', 404)
        return _row_to_user(row)


def change_own_password(user_id: int, current_password: str, new_password: str) -> None:
    new_pwd = validate_password(new_password)
    now = time.time()
    with DB.connection() as conn:
        row = conn.execute('SELECT * FROM users WHERE id = ?', (int(user_id),)).fetchone()
        if not row:
            raise AuthError('用户不存在', 404)
        if not check_password_hash(row['password_hash'], current_password or ''):
            raise AuthError('当前密码不正确', 400)
        conn.execute(
            'UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?',
            (generate_password_hash(new_pwd), now, int(user_id)),
        )


def update_user_by_admin(
    user_id: int,
    display_name: Optional[str] = None,
    role: Optional[str] = None,
    password: Optional[str] = None,
) -> Dict[str, Any]:
    uid = int(user_id)
    now = time.time()
    with DB.connection() as conn:
        target = conn.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()
        if not target:
            raise AuthError('目标用户不存在', 404)

        if role is not None:
            if role not in ('user', 'admin'):
                raise AuthError('无效的用户角色', 400)
            if target['role'] == 'admin' and role != 'admin':
                admin_cnt = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM users WHERE role = 'admin'"
                ).fetchone()['cnt']
                if admin_cnt <= 1:
                    raise AuthError('必须至少保留一位管理员账号', 400)
            conn.execute('UPDATE users SET role = ?, updated_at = ? WHERE id = ?', (role, now, uid))

        if display_name is not None:
            clean_name = display_name.strip()
            if not clean_name or len(clean_name) > 48:
                raise AuthError('显示昵称需为 1–48 个字符', 400)
            conn.execute(
                'UPDATE users SET display_name = ?, updated_at = ? WHERE id = ?',
                (clean_name, now, uid),
            )

        if password:
            pwd = validate_password(password)
            conn.execute(
                'UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?',
                (generate_password_hash(pwd), now, uid),
            )

        updated = conn.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()
        return _row_to_user(updated)


def delete_user_by_admin(user_id: int, actor_id: int) -> None:
    uid = int(user_id)
    if uid == int(actor_id):
        raise AuthError('不能删除当前正在登录的管理员自己', 400)

    with DB.connection() as conn:
        target = conn.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()
        if not target:
            raise AuthError('目标用户不存在', 404)
        if target['role'] == 'admin':
            admin_cnt = conn.execute(
                "SELECT COUNT(*) AS cnt FROM users WHERE role = 'admin'"
            ).fetchone()['cnt']
            if admin_cnt <= 1:
                raise AuthError('必须至少保留一位管理员账号', 400)
        conn.execute('DELETE FROM users WHERE id = ?', (uid,))


def require_auth(fn: Callable) -> Callable:
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': '请先登录账号'}), 401
        return fn(*args, **kwargs)

    return wrapper


def require_admin(fn: Callable) -> Callable:
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': '请先登录账号'}), 401
        if user.get('role') != 'admin':
            return jsonify({'error': '需要管理员权限'}), 403
        return fn(*args, **kwargs)

    return wrapper
