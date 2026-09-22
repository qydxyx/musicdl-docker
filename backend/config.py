import os
import sys
import json
import threading
from typing import Any, Dict


def get_bundle_dir() -> str:
    """Return directory where static assets and bundled code live."""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_working_dir() -> str:
    """Return directory where user data (downloads, data) should be stored."""
    return os.getcwd()


DEFAULT_CONFIG: Dict[str, Any] = {
    'download_dir': os.path.join(get_working_dir(), 'downloads'),
    'search_size_per_source': 8,
    'per_source_timeout': 25,
    'active_sources': [
        'MiguMusicClient',
        'KuwoMusicClient',
        'NeteaseMusicClient'
    ],
    'cookies': {},
    'proxy': '',
    'embed_cover': True,
    'embed_lyrics': True,
    'host': '127.0.0.1',
    'port': 8080,
}


class ConfigManager:
    """Thread-safe configuration manager."""
    def __init__(self):
        self._lock = threading.Lock()
        self._data_dir = os.environ.get(
            'MUSICDL_DATA_DIR',
            os.path.join(get_working_dir(), 'data')
        )
        os.makedirs(self._data_dir, exist_ok=True)
        self._config_file = os.path.join(self._data_dir, 'config.json')
        self._config = dict(DEFAULT_CONFIG)
        self._load()

    def _load(self):
        with self._lock:
            if os.path.exists(self._config_file):
                try:
                    with open(self._config_file, 'r', encoding='utf-8') as f:
                        loaded = json.load(f)
                        if isinstance(loaded, dict):
                            self._config.update(loaded)
                except Exception as e:
                    print(f"[Config] Failed to load {self._config_file}: {e}")

            # Apply environment overrides
            if 'HOST' in os.environ:
                self._config['host'] = os.environ['HOST']
            if 'PORT' in os.environ:
                try:
                    self._config['port'] = int(os.environ['PORT'])
                except ValueError:
                    pass
            if 'MUSICDL_DOWNLOAD_DIR' in os.environ:
                self._config['download_dir'] = os.environ['MUSICDL_DOWNLOAD_DIR']
            if 'MUSICDL_PROXY' in os.environ:
                self._config['proxy'] = os.environ['MUSICDL_PROXY']

            # Ensure download dir exists
            os.makedirs(self._config['download_dir'], exist_ok=True)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._config.get(key, default)

    def get_all(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._config)

    def update(self, new_data: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            for k, v in new_data.items():
                if k in self._config:
                    self._config[k] = v
            # Ensure download directory exists if modified
            if 'download_dir' in new_data:
                os.makedirs(self._config['download_dir'], exist_ok=True)
            try:
                with open(self._config_file, 'w', encoding='utf-8') as f:
                    json.dump(self._config, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"[Config] Failed to save {self._config_file}: {e}")
            return dict(self._config)


CONFIG = ConfigManager()
