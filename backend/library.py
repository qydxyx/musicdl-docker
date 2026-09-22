import os
import io
import base64
from typing import List, Dict, Any, Optional
from mutagen import File as MutagenFile

from backend.config import CONFIG

AUDIO_EXTENSIONS = {'.mp3', '.flac', '.wav', '.m4a', '.aac', '.ogg', '.ape', '.opus', '.wma'}


def scan_local_library() -> List[Dict[str, Any]]:
    """Scan download directory and extract metadata for all audio files."""
    download_root = CONFIG.get('download_dir', os.path.join(os.getcwd(), 'downloads'))
    if not os.path.exists(download_root):
        return []

    tracks: List[Dict[str, Any]] = []

    for root, _, files in os.walk(download_root):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in AUDIO_EXTENSIONS:
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, download_root)

                stat = os.stat(full_path)
                size_mb = f"{stat.st_size / (1024 * 1024):.2f} MB"

                track_info = {
                    'rel_path': rel_path,
                    'filename': f,
                    'ext': ext.lstrip('.'),
                    'file_size': size_mb,
                    'file_size_bytes': stat.st_size,
                    'mtime': stat.st_mtime,
                    'song_name': os.path.splitext(f)[0],
                    'singers': '未知艺人',
                    'album': '',
                    'duration': '',
                    'duration_s': 0,
                    'bitrate': 0,
                    'has_lyric': False,
                    'has_cover': False,
                }

                # Check companion .lrc
                lrc_path = os.path.splitext(full_path)[0] + '.lrc'
                track_info['has_lyric'] = os.path.exists(lrc_path)

                # Read mutagen tags
                try:
                    meta = MutagenFile(full_path)
                    if meta is not None:
                        if meta.info:
                            d_sec = int(getattr(meta.info, 'length', 0) or 0)
                            if d_sec > 0:
                                track_info['duration_s'] = d_sec
                                mins, secs = divmod(d_sec, 60)
                                track_info['duration'] = f"{mins:02d}:{secs:02d}"
                            br = int(getattr(meta.info, 'bitrate', 0) or 0)
                            if br > 0:
                                track_info['bitrate'] = br // 1000  # in kbps

                        tags = meta.tags or {}
                        # MP3 tags
                        if hasattr(tags, 'getall'):
                            if tags.get('TIT2'):
                                track_info['song_name'] = str(tags['TIT2'])
                            if tags.get('TPE1'):
                                track_info['singers'] = str(tags['TPE1'])
                            if tags.get('TALB'):
                                track_info['album'] = str(tags['TALB'])
                            if tags.getall('APIC'):
                                track_info['has_cover'] = True
                        # Vorbis comments (FLAC, OGG)
                        elif isinstance(tags, dict):
                            if 'title' in tags and tags['title']:
                                track_info['song_name'] = str(tags['title'][0])
                            if 'artist' in tags and tags['artist']:
                                track_info['singers'] = str(tags['artist'][0])
                            if 'album' in tags and tags['album']:
                                track_info['album'] = str(tags['album'][0])
                            if hasattr(meta, 'pictures') and meta.pictures:
                                track_info['has_cover'] = True

                        # Parse artist from filename fallback: "Artist - Title"
                        if track_info['singers'] == '未知艺人' and ' - ' in f:
                            parts = os.path.splitext(f)[0].split(' - ', 1)
                            track_info['singers'] = parts[0].strip()
                            track_info['song_name'] = parts[1].strip()

                except Exception as e:
                    pass

                tracks.append(track_info)

    # Sort descending by mtime (newest downloads first)
    tracks.sort(key=lambda x: x['mtime'], reverse=True)
    return tracks


def get_library_cover(rel_path: str) -> Optional[bytes]:
    """Extract embedded cover image from audio file."""
    download_root = CONFIG.get('download_dir', os.path.join(os.getcwd(), 'downloads'))
    full_path = os.path.abspath(os.path.join(download_root, rel_path))

    # Security path check
    if not full_path.startswith(os.path.abspath(download_root)) or not os.path.exists(full_path):
        return None

    try:
        meta = MutagenFile(full_path)
        if meta is None:
            return None

        # ID3 APIC
        if hasattr(meta, 'tags') and hasattr(meta.tags, 'getall'):
            apics = meta.tags.getall('APIC')
            if apics:
                return apics[0].data

        # FLAC pictures
        if hasattr(meta, 'pictures') and meta.pictures:
            return meta.pictures[0].data

        # MP4 covr
        if hasattr(meta, 'tags') and 'covr' in meta.tags:
            covr = meta.tags['covr']
            if covr:
                return bytes(covr[0])
    except Exception:
        pass

    return None


def get_library_lyric(rel_path: str) -> str:
    """Read companion or embedded lyric."""
    download_root = CONFIG.get('download_dir', os.path.join(os.getcwd(), 'downloads'))
    full_path = os.path.abspath(os.path.join(download_root, rel_path))
    lrc_path = os.path.splitext(full_path)[0] + '.lrc'

    if os.path.exists(lrc_path):
        try:
            with open(lrc_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception:
            pass

    return ''


def delete_library_track(rel_path: str) -> bool:
    """Delete an audio file and its companion .lrc."""
    download_root = CONFIG.get('download_dir', os.path.join(os.getcwd(), 'downloads'))
    full_path = os.path.abspath(os.path.join(download_root, rel_path))

    # Security check: must be inside download directory
    if not full_path.startswith(os.path.abspath(download_root)):
        return False

    if os.path.exists(full_path):
        try:
            os.remove(full_path)
            lrc_path = os.path.splitext(full_path)[0] + '.lrc'
            if os.path.exists(lrc_path):
                os.remove(lrc_path)
            return True
        except Exception:
            return False
    return False
