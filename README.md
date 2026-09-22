# musicdl Web UI

<div align="center">

🎵 **现代化、全功能的跨平台音乐解析、播放与下载管理 Web UI**  
基于 [CharlesPikachu/musicdl](https://github.com/CharlesPikachu/musicdl) 构建 · 适用于 **macOS** 与 **Linux**

[三种部署方式](#部署与启动指南) · [功能特性](#核心特性) · [配置指南](#进阶配置) · [API 文档](#api-概览)

</div>

---

## 核心特性

- ⚡ **多源并发流式搜索 (SSE)**：驱动 `musicdl` 底层解析引擎，每解析成功一首歌曲立即通过 Server-Sent Events (SSE) 实时推向前端，多音源并发、独立看门狗超时保护，彻底告别整页等待与冻结卡死。
- 📋 **歌单 / 专辑一键解析**：支持粘贴主流平台（网易云音乐、QQ音乐、酷我、酷狗、咪咕、B站音频、Spotify 等）的公开歌单或分享链接，自动解析出全部单曲并支持一键批量勾选下载。
- 🎧 **音频代理与 Range 拖拽寻道**：内建防盗链代理及 HTTP 206 Partial Content 支持，无需整首下载即可在浏览器中即点即播，进度条任意拖拽跳转。
- 🏷️ **自动内嵌高清封面与标签 (Mutagen)**：下载时自动向 MP3 / FLAC / M4A 文件中写入 ID3 / FLAC Vorbis 标签（歌曲名、艺术家、专辑名）并嵌入高清专辑封面，同时提取生成同名 `.lrc` 歌词文件，与 Apple Music、车机及 Navidrome / Plex / Jellyfin 完美兼容。
- 📁 **本地离线音乐库**：已下载音乐独立界面管理，支持离线秒播、下载到浏览器本地、安全删除与存储空间概览。
- 🎼 **全功能播放器**：
  - 动态同步滚动歌词（LRC 解析、逐行高亮发光、点击任意歌词跳播）
  - HTML5 Web Audio API 实时音频频谱可视化动画
  - 播放模式切换（列表循环、单曲循环、随机播放）
  - 实时播放队列抽屉管理
  - 原生系统集成：支持 macOS 控制中心、Touch Bar、锁屏界面及键盘多媒体按键（`MediaSession` API）
  - 快捷键支持：空格播放/暂停、左右方向键快进/快退 5 秒、上下键调节音量、`[` / `]` 切歌、`L` 开关歌词。
- 🌐 **多源分类管理与设置**：30+ 音源（国内主流、国际平台、聚合站点、有声电台），支持全局设置下载路径、检索深度、代理服务器（HTTP/SOCKS5）及 VIP Cookie。

---

## 部署与启动指南

本项目提供三种分发与部署方式，满足不同场景需求：

### 方式一：预编译二进制单文件 (推荐：最简单、零依赖)

无需安装 Python 或 Docker，下载即可直接运行：

#### 1. 一键安装 (macOS / Linux)
```bash
curl -fsSL https://raw.githubusercontent.com/CharlesPikachu/musicdl/master/install.sh | bash
```

#### 2. 或手动下载解压运行
从 GitHub Releases 下载对应系统的压缩包：
- **macOS (Apple Silicon M1/M2/M3/M4)**: `musicdl-web-macos-aarch64.tar.gz`
- **macOS (Intel)**: `musicdl-web-macos-x86_64.tar.gz`
- **Linux (x86_64)**: `musicdl-web-linux-x86_64.tar.gz`
- **Linux (ARM64 / 树莓派)**: `musicdl-web-linux-aarch64.tar.gz`

```bash
tar -xzf musicdl-web-*.tar.gz
./musicdl-web
# 浏览器打开 http://127.0.0.1:8080
```

---

### 方式二：Docker / Docker Compose 容器部署 (推荐：Linux 服务器 / NAS)

非常适合群晖 (Synology)、QNAP、Unraid 及云服务器部署。

#### 使用 Docker Compose (最简单)
在本项目根目录下直接执行：
```bash
docker compose up -d
```

或使用自定义参数启动：
```bash
PORT=8080 docker compose up -d
```

#### 单容器命令启动
```bash
docker run -d \
  --name musicdl-web \
  --restart unless-stopped \
  -p 8080:8080 \
  -v $(pwd)/downloads:/app/downloads \
  -v $(pwd)/data:/app/data \
  -e TZ=Asia/Shanghai \
  musicdl-web:latest
```

> **持久化目录说明**：
> - `./downloads`：存放下载的音乐文件、内嵌封面与歌词
> - `./data`：存放系统配置（音源选择、Cookie、代理设置等）

---

### 方式三：源码一键运行 (开发者 / 自定义修改)

需要本地 Python 3.10+ 环境（优先使用 `uv` 极速运行）：

```bash
# 克隆仓库
git clone https://github.com/CharlesPikachu/musicdl.git
cd musicdl-docker

# 一键运行（自动创建虚拟环境并安装依赖，自动在 Mac/Linux 打开浏览器）
./run.sh start
```

管理命令：
```bash
./run.sh status    # 查看运行状态
./run.sh stop      # 停止服务
./run.sh restart   # 重启服务
```

---

## Makefile 快捷命令汇总

```bash
make run          # 本地源码启动服务 (执行 run.sh)
make stop         # 停止本地运行的服务
make docker       # 构建并后台启动 Docker 容器
make docker-stop  # 停止并移除 Docker 容器
make binary       # 使用 PyInstaller 打包当前平台的独立二进制文件
make test         # 运行后端全套自动化测试
make clean        # 清理打包产生的 build/dist 临时文件
```

---

## 进阶配置

在 Web 界面点击侧边栏 **系统设置**，或直接编辑 `data/config.json`：

```json
{
  "download_dir": "./downloads",
  "search_size_per_source": 8,
  "per_source_timeout": 25,
  "active_sources": [
    "MiguMusicClient",
    "KuwoMusicClient",
    "NeteaseMusicClient"
  ],
  "proxy": "http://127.0.0.1:7890",
  "embed_cover": true,
  "embed_lyrics": true,
  "host": "127.0.0.1",
  "port": 8080
}
```

### 1. 代理配置 (使用国际音乐源)
若需搜索与下载 YouTube、SoundCloud、Spotify 等国际平台，请在系统设置的「网络代理」填入您的代理地址，如 `http://127.0.0.1:7890` 或 `socks5://127.0.0.1:1080`。

### 2. 外部访问安全性
- 本地使用（二进制/源码模式）默认监听 `127.0.0.1`，保障本地主机网络安全。
- 如需局域网其他设备访问，可在启动前设置环境变量 `HOST=0.0.0.0 ./run.sh start`。
- Docker 容器镜像默认监听 `0.0.0.0`，由宿主机端口映射负责网络路由。

---

## API 概览

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/sources` | GET | 获取全部 30+ 音乐源分类目录与激活状态 |
| `/api/search?q={keyword}&sources={src1,src2}` | GET | SSE 长连接实时流式搜索 |
| `/api/parse_playlist` | POST | SSE 长连接歌单/专辑链接批量解析 |
| `/api/stream/{token}` | GET | 带 HTTP 206 Range 支持的音频播放流代理 |
| `/api/cover/{token}` | GET | 封面图片反防盗链代理 |
| `/api/lyric/{token}` | GET | 获取曲目同步歌词文本 |
| `/api/download` | POST | 提交后台异步下载任务 |
| `/api/download/progress` | GET | SSE 长连接实时推送全部任务下载进度与网速 |
| `/api/library/tracks` | GET | 扫描并列出本地已下载音乐库 |
| `/api/library/stream/{path}` | GET | 本地离线音频播放流 (支持 Range 拖动) |
| `/api/library/download/{path}` | GET | 将本地文件直接下载至客户端浏览器 |
| `/api/library/track/{path}` | DELETE | 删除本地音频及同名 `.lrc` 文件 |
| `/api/config` | GET / PUT | 查询与更新系统设置 |
| `/api/system_info` | GET | 获取操作系统、架构、存储剩余空间等信息 |

---

## 许可证与免责声明

本项目仅用于个人学习、音乐管理和编程技术研究。所有音频资源与版权均归各自音乐平台所有，请支持正版音乐。
