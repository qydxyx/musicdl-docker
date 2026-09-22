import os
import re
import time
import uuid
import threading
from typing import Dict, Any, Optional
import requests

from backend.config import CONFIG
from backend.streamer import REGISTRY
from backend.sources_registry import SOURCE_CATALOG

DOWNLOADS: Dict[str, Dict[str, Any]] = {}
DL_LOCK = threading.Lock()
CANCEL_EVENTS: Dict[str, threading.Event] = {}


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """Sanitize string to be safe for filenames across Linux and macOS."""
    clean = re.sub(r'[\\/:*?"<>|\r\n\t]', '_', name or 'track').strip()
    clean = re.sub(r'\s+', ' ', clean)
    return clean[:max_len].strip('. ') or 'track'


def tag_audio_file(filepath: str, song_info: Any, cover_url: Optional[str] = None):
    """Embed ID3 / FLAC tags and cover art into the downloaded audio file."""
    ext = os.path.splitext(filepath)[1].lower()

    cover_bytes = None
    if cover_url and cover_url.startswith('http'):
        try:
            resp = requests.get(cover_url, timeout=10)
            if resp.status_code == 200:
                cover_bytes = resp.content
        except Exception:
            pass

    title = str(getattr(song_info, 'song_name', '') or '')
    artist = str(getattr(song_info, 'singers', '') or '')
    album = str(getattr(song_info, 'album', '') or '')

    try:
        if ext == '.mp3':
            import mutagen.id3 as id3
            try:
                tags = id3.ID3(filepath)
            except id3.ID3NoHeaderError:
                tags = id3.ID3()

            if title:
                tags.add(id3.TIT2(encoding=3, text=title))
            if artist:
                tags.add(id3.TPE1(encoding=3, text=artist))
            if album:
                tags.add(id3.TALB(encoding=3, text=album))
            if cover_bytes:
                tags.add(id3.APIC(
                    encoding=3,
                    mime='image/jpeg',
                    type=3,  # Front cover
                    desc='Cover',
                    data=cover_bytes
                ))
            tags.save(filepath, v2_version=3)

        elif ext == '.flac':
            from mutagen.flac import FLAC, Picture
            audio = FLAC(filepath)
            if title:
                audio['title'] = title
            if artist:
                audio['artist'] = artist
            if album:
                audio['album'] = album
            if cover_bytes:
                pic = Picture()
                pic.type = 3
                pic.mime = 'image/jpeg'
                pic.desc = 'Cover'
                pic.data = cover_bytes
                audio.add_picture(pic)
            audio.save()

        elif ext in ('.m4a', '.mp4'):
            from mutagen.mp4 import MP4, MP4Cover
            audio = MP4(filepath)
            if title:
                audio['\xa9nam'] = [title]
            if artist:
                audio['\xa9ART'] = [artist]
            if album:
                audio['\xa9alb'] = [album]
            if cover_bytes:
                audio['covr'] = [MP4Cover(cover_bytes, imageformat=MP4Cover.FORMAT_JPEG)]
            audio.save()

    except Exception as e:
        print(f"[Mutagen] Warning: failed to tag {filepath}: {e}")


def run_download(download_id: str, token: str):
    """Background download worker."""
    cancel_evt = threading.Event()
    with DL_LOCK:
        CANCEL_EVENTS[download_id] = cancel_evt

    entry = REGISTRY.get(token)
    if not entry:
        _update_dl(download_id, status='error', message='曲目已过期，请重新搜索')
        return

    song_info = entry['song_info']
    url = getattr(song_info, 'download_url', None)
    if not isinstance(url, str) or not url.startswith('http'):
        _update_dl(download_id, status='error', message='该曲目没有有效的下载直链')
        return

    source = entry['source']
    source_label = SOURCE_CATALOG.get(source, {}).get('short', source)
    download_root = CONFIG.get('download_dir', os.path.join(os.getcwd(), 'downloads'))
    save_dir = os.path.join(download_root, source_label)
    os.makedirs(save_dir, exist_ok=True)

    ext = (str(getattr(song_info, 'ext', 'mp3')) or 'mp3').lower().lstrip('.')
    song_name = sanitize_filename(str(getattr(song_info, 'song_name', 'track')))
    singers = sanitize_filename(str(getattr(song_info, 'singers', 'unknown')))
    base_filename = f"{singers} - {song_name}"
    audio_path = os.path.join(save_dir, f"{base_filename}.{ext}")
    part_path = audio_path + '.part'

    headers = dict(entry['headers'])
    cookies = dict(entry['cookies'])

    try:
        with requests.get(url, headers=headers, cookies=cookies,
                          stream=True, timeout=(10, 30), verify=False) as resp:
            resp.raise_for_status()
            total_bytes = int(resp.headers.get('Content-Length', 0) or 0)
            if total_bytes <= 0:
                total_bytes = int(getattr(song_info, 'file_size_bytes', 0) or 0)

            _update_dl(
                download_id,
                status='downloading',
                total=total_bytes,
                downloaded=0,
                speed=0,
                name=f"{base_filename}.{ext}",
                path=audio_path,
                start_time=time.time(),
            )

            done = 0
            last_time = time.time()
            last_bytes = 0

            with open(part_path, 'wb') as fp:
                for chunk in resp.iter_content(chunk_size=256 * 1024):
                    if cancel_evt.is_set():
                        fp.close()
                        if os.path.exists(part_path):
                            os.remove(part_path)
                        _update_dl(download_id, status='cancelled', message='下载已取消')
                        return

                    if not chunk:
                        continue
                    fp.write(chunk)
                    done += len(chunk)

                    now = time.time()
                    if now - last_time >= 0.25:
                        speed = (done - last_bytes) / (now - last_time)
                        _update_dl(download_id, downloaded=done, total=total_bytes, speed=speed)
                        last_time, last_bytes = now, done

            os.replace(part_path, audio_path)

        # ── Tagging with mutagen ──
        if CONFIG.get('embed_cover', True):
            _update_dl(download_id, status='tagging', speed=0)
            tag_audio_file(
                audio_path,
                song_info,
                cover_url=getattr(song_info, 'cover_url', None)
            )

        # ── Save .lrc lyric file ──
        if CONFIG.get('embed_lyrics', True):
            lyric_text = getattr(song_info, 'lyric', '')
            if lyric_text and isinstance(lyric_text, str) and len(lyric_text.strip()) > 0:
                lrc_path = os.path.join(save_dir, f"{base_filename}.lrc")
                try:
                    with open(lrc_path, 'w', encoding='utf-8') as lrc_f:
                        lrc_f.write(lyric_text.strip())
                except Exception as lrc_err:
                    print(f"[LRC] Warning: failed to save {lrc_path}: {lrc_err}")

        _update_dl(
            download_id,
            status='done',
            downloaded=done,
            total=total_bytes or done,
            speed=0,
            path=audio_path,
            name=f"{base_filename}.{ext}"
        )

    except Exception as err:
        if os.path.exists(part_path):
            try: os.remove(part_path)
            except: pass
        _update_dl(download_id, status='error', message=str(err))


def cancel_download(download_id: str) -> bool:
    with DL_LOCK:
        if download_id in CANCEL_EVENTS:
            CANCEL_EVENTS[download_id].set()
            return True
    return False


def _update_dl(download_id: str, **fields):
    with DL_LOCK:
        rec = DOWNLOADS.setdefault(download_id, {
            'id': download_id,
            'status': 'pending',
            'downloaded': 0,
            'total': 0,
            'speed': 0,
            'name': '',
            'message': '',
            'path': '',
            'updated_at': time.time(),
        })
        rec.update(fields)
        rec['updated_at'] = time.time()


def get_download_status(download_id: str) -> Optional[Dict[str, Any]]:
    with DL_LOCK:
        rec = DOWNLOADS.get(download_id)
        return dict(rec) if rec else None


def get_all_downloads() -> list:
    with DL_LOCK:
        return [dict(v) for v in sorted(DOWNLOADS.values(), key=lambda x: x.get('updated_at', 0), reverse=True)]
