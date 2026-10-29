import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator

from backend.config import CONFIG

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_agent TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS playlists (
    id TEXT PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'private',
    public_editable INTEGER NOT NULL DEFAULT 0,
    source_playlist_id TEXT REFERENCES playlists(id) ON DELETE SET NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_playlists_owner ON playlists(owner_id);
CREATE INDEX IF NOT EXISTS idx_playlists_visibility ON playlists(visibility);
CREATE INDEX IF NOT EXISTS idx_playlists_source ON playlists(source_playlist_id);

CREATE TABLE IF NOT EXISTS playlist_members (
    playlist_id TEXT NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    permission TEXT NOT NULL DEFAULT 'viewer',
    added_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (playlist_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_playlist_members_user ON playlist_members(user_id);

CREATE TABLE IF NOT EXISTS playlist_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id TEXT NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    track_key TEXT NOT NULL,
    rel_path TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    source_label TEXT NOT NULL DEFAULT '',
    song_id TEXT NOT NULL DEFAULT '',
    song_name TEXT NOT NULL,
    singers TEXT NOT NULL DEFAULT '未知艺人',
    album TEXT NOT NULL DEFAULT '',
    ext TEXT NOT NULL DEFAULT 'mp3',
    duration TEXT NOT NULL DEFAULT '',
    file_size TEXT NOT NULL DEFAULT '',
    cover_url TEXT NOT NULL DEFAULT '',
    lossless INTEGER NOT NULL DEFAULT 0,
    added_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    added_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_playlist_tracks_pl_pos ON playlist_tracks(playlist_id, position);
CREATE INDEX IF NOT EXISTS idx_playlist_tracks_rel_path ON playlist_tracks(rel_path);

CREATE TABLE IF NOT EXISTS user_playback_state (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    queue_json TEXT NOT NULL DEFAULT '[]',
    current_index INTEGER NOT NULL DEFAULT -1,
    play_mode TEXT NOT NULL DEFAULT 'loop',
    position_sec REAL NOT NULL DEFAULT 0,
    client_id TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
);
"""


class Database:
    """Thread-safe SQLite database connection helper with WAL mode."""

    def __init__(self):
        self._init_lock = threading.Lock()
        self._initialized_paths = set()

    def get_db_path(self) -> str:
        data_dir = CONFIG.data_dir
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, 'musicdl.db')

    def _connect(self, db_path: str) -> sqlite3.Connection:
        conn = sqlite3.connect(db_path, timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        conn.execute('PRAGMA busy_timeout = 5000')
        return conn

    def ensure_initialized(self) -> str:
        db_path = os.path.abspath(self.get_db_path())
        if db_path in self._initialized_paths and os.path.exists(db_path):
            return db_path

        with self._init_lock:
            if db_path not in self._initialized_paths or not os.path.exists(db_path):
                conn = self._connect(db_path)
                try:
                    conn.execute('PRAGMA journal_mode = WAL')
                    conn.executescript(SCHEMA_SQL)
                    conn.commit()
                    self._initialized_paths.add(db_path)
                finally:
                    conn.close()
        return db_path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db_path = self.ensure_initialized()
        conn = self._connect(db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


DB = Database()
