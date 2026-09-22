import threading
from typing import Dict, Any, List, Optional
from musicdl import musicdl
from musicdl.modules.sources.base import BaseMusicClient
from backend.config import CONFIG

CATEGORY_LABELS = {
    'cn_major': '国内主流',
    'global': '国际平台',
    'aggregator': '聚合源',
    'audiobook': '有声电台',
}

SOURCE_CATALOG: Dict[str, Dict[str, Any]] = {
    # ── 国内主流平台 ──
    'MiguMusicClient': {
        'label': '咪咕音乐', 'short': 'Migu', 'category': 'cn_major', 'default': True,
        'desc': '官方直链高音质，解析速度极快，免会员'
    },
    'KuwoMusicClient': {
        'label': '酷我音乐', 'short': 'Kuwo', 'category': 'cn_major', 'default': True,
        'desc': '资源丰富，支持无损 FLAC，解析稳定'
    },
    'NeteaseMusicClient': {
        'label': '网易云音乐', 'short': 'Netease', 'category': 'cn_major', 'default': True,
        'desc': '涵盖热门流行与独立曲目，支持歌单解析'
    },
    'QQMusicClient': {
        'label': 'QQ音乐', 'short': 'QQ', 'category': 'cn_major', 'default': False,
        'desc': '曲库庞大，支持歌单解析与无损音质'
    },
    'KugouMusicClient': {
        'label': '酷狗音乐', 'short': 'Kugou', 'category': 'cn_major', 'default': False,
        'desc': '大众流行与网络热歌，支持歌单解析'
    },
    'SodaMusicClient': {
        'label': '汽水音乐', 'short': 'Soda', 'category': 'cn_major', 'default': False,
        'desc': '抖音官方音乐平台，热歌潮流榜单'
    },
    'BilibiliMusicClient': {
        'label': 'B站音频', 'short': 'Bili', 'category': 'cn_major', 'default': False,
        'desc': 'B站音乐区、翻唱、二次元与衍生曲目'
    },
    'QianqianMusicClient': {
        'label': '千千静听', 'short': 'Qianqian', 'category': 'cn_major', 'default': False,
        'desc': '经典百度音乐/千千静听曲库'
    },
    'StreetVoiceMusicClient': {
        'label': '街声', 'short': 'StreetVoice', 'category': 'cn_major', 'default': False,
        'desc': '独立原创音乐与青年音乐人作品'
    },
    'FiveSingMusicClient': {
        'label': '5sing 原创', 'short': '5sing', 'category': 'cn_major', 'default': False,
        'desc': '古风、翻唱与网络原创基地'
    },

    # ── 国际与独立平台 ──
    'YouTubeMusicClient': {
        'label': 'YouTube', 'short': 'YT', 'category': 'global', 'default': False,
        'desc': '全球最大视频音频平台（大陆网络需代理）'
    },
    'SoundCloudMusicClient': {
        'label': 'SoundCloud', 'short': 'SoundCloud', 'category': 'global', 'default': False,
        'desc': '全球独立电音、混音与创作平台'
    },
    'SpotifyMusicClient': {
        'label': 'Spotify', 'short': 'Spotify', 'category': 'global', 'default': False,
        'desc': '全球流媒体平台（需代理）'
    },
    'DeezerMusicClient': {
        'label': 'Deezer', 'short': 'Deezer', 'category': 'global', 'default': False,
        'desc': '法国流媒体巨头，欧美曲库全面'
    },
    'TIDALMusicClient': {
        'label': 'TIDAL', 'short': 'TIDAL', 'category': 'global', 'default': False,
        'desc': '高保真无损流媒体平台'
    },
    'AppleMusicClient': {
        'label': 'Apple Music', 'short': 'Apple', 'category': 'global', 'default': False,
        'desc': '苹果音乐官方平台（支持预览及部分音频）'
    },
    'JamendoMusicClient': {
        'label': 'Jamendo', 'short': 'Jamendo', 'category': 'global', 'default': False,
        'desc': '免费商用与自由版权独立音乐'
    },
    'AudiusMusicClient': {
        'label': 'Audius', 'short': 'Audius', 'category': 'global', 'default': False,
        'desc': '去中心化 Web3 独立音乐平台'
    },
    'SunoMusicClient': {
        'label': 'Suno AI', 'short': 'Suno', 'category': 'global', 'default': False,
        'desc': '热门 AI 生成音乐平台搜索'
    },

    # ── 聚合与第三方源 ──
    'GequbaoMusicClient': {
        'label': '歌曲宝', 'short': 'Gequbao', 'category': 'aggregator', 'default': False,
        'desc': '第三方免登录快速下载源'
    },
    'TuneHubMusicClient': {
        'label': 'TuneHub', 'short': 'TuneHub', 'category': 'aggregator', 'default': False,
        'desc': '多平台汇聚综合音乐源'
    },
    'GDStudioMusicClient': {
        'label': 'GDStudio', 'short': 'GDStudio', 'category': 'aggregator', 'default': False,
        'desc': '聚合第三方解析引擎'
    },
    'MyFreeMP3MusicClient': {
        'label': 'MyFreeMP3', 'short': 'MyFreeMP3', 'category': 'aggregator', 'default': False,
        'desc': '经典多源搜索下载聚合'
    },

    # ── 有声电台 ──
    'XimalayaMusicClient': {
        'label': '喜马拉雅', 'short': 'Ximalaya', 'category': 'audiobook', 'default': False,
        'desc': '国内最大音频读物、相声播客平台'
    },
    'LizhiMusicClient': {
        'label': '荔枝 FM', 'short': 'Lizhi', 'category': 'audiobook', 'default': False,
        'desc': '情感电台、播客与语音节目'
    },
    'QingtingMusicClient': {
        'label': '蜻蜓 FM', 'short': 'Qingting', 'category': 'audiobook', 'default': False,
        'desc': '网络电台与有声小说'
    },
}

SOURCE_ORDER = list(SOURCE_CATALOG.keys())


class ClientManager:
    """Manages musicdl instances, with lazy creation, proxy, and cookie injection."""
    def __init__(self):
        self._lock = threading.Lock()
        self._clients: Dict[str, Any] = {}

    def get_client(self, source_name: str) -> Optional[Any]:
        if source_name not in SOURCE_CATALOG:
            return None

        with self._lock:
            if source_name in self._clients:
                return self._clients[source_name]

            search_size = int(CONFIG.get('search_size_per_source', 8))
            cookies = CONFIG.get('cookies', {}).get(source_name, {})
            proxy = CONFIG.get('proxy', '').strip()

            client_cfg = {
                source_name: {
                    'search_size_per_source': search_size,
                    'disable_print': True,
                }
            }

            if cookies:
                client_cfg[source_name]['default_search_cookies'] = cookies
                client_cfg[source_name]['default_download_cookies'] = cookies

            try:
                mc = musicdl.MusicClient(
                    music_sources=[source_name],
                    init_music_clients_cfg=client_cfg
                )
                client = mc.music_clients[source_name]

                if proxy:
                    proxies = {'http': proxy, 'https': proxy}
                    if hasattr(client, 'session') and hasattr(client.session, 'proxies'):
                        client.session.proxies.update(proxies)

                self._clients[source_name] = client
                return client
            except Exception as e:
                print(f"[ClientManager] Warning: failed to init {source_name}: {e}")
                return None

    def reset(self):
        with self._lock:
            self._clients.clear()


MANAGER = ClientManager()


def get_catalog_info() -> List[Dict[str, Any]]:
    """Return catalog structured with categories for frontend."""
    from musicdl.modules.sources import MusicClientBuilder
    active_sources = set(CONFIG.get('active_sources', []))
    res = []
    for sid in SOURCE_ORDER:
        info = SOURCE_CATALOG[sid]
        cls = MusicClientBuilder.REGISTERED_MODULES.get(sid)
        supports_playlist = hasattr(cls, 'parseplaylist') and (
            getattr(cls, 'parseplaylist', None) is not BaseMusicClient.parseplaylist
        ) if cls else False

        res.append({
            'id': sid,
            'label': info['label'],
            'short': info['short'],
            'category': info['category'],
            'category_label': CATEGORY_LABELS.get(info['category'], '其他'),
            'desc': info['desc'],
            'active': sid in active_sources,
            'supports_playlist': bool(supports_playlist),
        })
    return res
