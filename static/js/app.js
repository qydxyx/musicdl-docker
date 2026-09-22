// ── Main Application Controller for musicdl-web ──
document.addEventListener('DOMContentLoaded', async () => {
  // ── Core Elements ──
  const audioEl = document.getElementById('mainAudio');
  const canvasEl = document.getElementById('audioVisualizer');
  const lyricsScrollEl = document.getElementById('lyricsScroll');

  const player = new AudioPlayer(audioEl, canvasEl);
  const lyrics = new LyricsEngine(lyricsScrollEl, (time) => player.seek(time));

  let appConfig = {};
  let allSources = [];
  let currentSearchSSE = null;
  let activePlaylistTracks = [];

  // ── Tab Navigation ──
  const navItems = document.querySelectorAll('.nav-item');
  const panels = document.querySelectorAll('.tab-panel');

  function switchTab(tabId) {
    navItems.forEach(item => {
      if (item.dataset.tab === tabId) item.classList.add('active');
      else item.classList.remove('active');
    });
    panels.forEach(p => {
      if (p.id === `panel-${tabId}`) p.classList.add('active');
      else p.classList.remove('active');
    });

    if (tabId === 'library') loadLibrary();
    if (tabId === 'settings') loadSettings();
  }

  navItems.forEach(item => {
    item.addEventListener('click', () => switchTab(item.dataset.tab));
  });

  // ── Bottom Player UI Binding ──
  const playerCoverImg = document.getElementById('playerCoverImg');
  const playerTitle = document.getElementById('playerTitle');
  const playerArtist = document.getElementById('playerArtist');
  const btnPlayPause = document.getElementById('btnPlayPause');
  const btnPrev = document.getElementById('btnPrev');
  const btnNext = document.getElementById('btnNext');
  const btnMode = document.getElementById('btnMode');
  const progressBarWrap = document.getElementById('progressBarWrap');
  const progressFill = document.getElementById('progressFill');
  const progressThumb = document.getElementById('progressThumb');
  const timeCurrent = document.getElementById('timeCurrent');
  const timeDuration = document.getElementById('timeDuration');
  const volumeSlider = document.getElementById('volumeSlider');
  const btnMute = document.getElementById('btnMute');
  const toggleLyricsBtn = document.getElementById('toggleLyricsBtn');
  const closeLyricsBtn = document.getElementById('closeLyricsBtn');
  const lyricsModal = document.getElementById('lyricsModal');
  const openQueueBtn = document.getElementById('openQueueBtn');
  const closeQueueBtn = document.getElementById('closeQueueBtn');
  const queueDrawer = document.getElementById('queueDrawer');
  const clearQueueBtn = document.getElementById('clearQueueBtn');
  const queueList = document.getElementById('queueList');
  const queueCount = document.getElementById('queueCount');
  const queueBadge = document.getElementById('queueBadge');

  btnPlayPause.addEventListener('click', () => player.togglePlay());
  btnPrev.addEventListener('click', () => player.prev());
  btnNext.addEventListener('click', () => player.next());
  btnMode.addEventListener('click', () => player.toggleMode());

  // Seek bar interaction
  let isSeeking = false;
  progressBarWrap.addEventListener('mousedown', (e) => {
    isSeeking = true;
    handleSeek(e);
  });
  window.addEventListener('mousemove', (e) => {
    if (isSeeking) handleSeek(e);
  });
  window.addEventListener('mouseup', () => {
    isSeeking = false;
  });

  function handleSeek(e) {
    const rect = progressBarWrap.getBoundingClientRect();
    const percent = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    if (player.audio.duration) {
      player.seek(percent * player.audio.duration);
    }
  }

  // Volume slider
  volumeSlider.addEventListener('input', (e) => {
    player.setVolume(parseFloat(e.target.value));
  });

  let prevVol = 0.8;
  btnMute.addEventListener('click', () => {
    if (player.audio.volume > 0) {
      prevVol = player.audio.volume;
      player.setVolume(0);
    } else {
      player.setVolume(prevVol || 0.8);
    }
  });

  // Track & Time update callbacks
  player.onTrackChange = async (track) => {
    playerTitle.textContent = track.song_name || '未知曲目';
    playerArtist.textContent = track.singers || '未知艺人';

    let coverSrc = track.cover_url || '';
    if (!coverSrc && track.rel_path && track.has_cover) {
      coverSrc = `/api/library/cover/${encodeURIComponent(track.rel_path)}`;
    }
    playerCoverImg.src = coverSrc || 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="%236366f1"%3E%3Cpath d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/%3E%3C/svg%3E';

    // Update Lyrics Info
    document.getElementById('lyricsTitle').textContent = track.song_name || '歌词';
    document.getElementById('lyricsArtist').textContent = track.singers || '';

    // Fetch and load lyrics
    lyrics.clear();
    let lrc = '';
    if (track.rel_path) {
      lrc = await API.getLocalLyric(track.rel_path);
    } else if (track.token) {
      lrc = await API.getLyric(track.token);
    }
    lyrics.loadLRC(lrc);

    updateQueueUI();
  };

  player.onTimeUpdate = (currentTime, duration) => {
    if (!isSeeking && duration > 0) {
      const pct = (currentTime / duration) * 100;
      progressFill.style.width = `${pct}%`;
      progressThumb.style.left = `${pct}%`;
    }
    timeCurrent.textContent = UI.formatTime(currentTime);
    timeDuration.textContent = UI.formatTime(duration);
    lyrics.sync(currentTime);
  };

  // Lyrics Drawer Toggle
  toggleLyricsBtn.addEventListener('click', () => {
    lyricsModal.classList.toggle('active');
    toggleLyricsBtn.classList.toggle('active');
  });
  closeLyricsBtn.addEventListener('click', () => {
    lyricsModal.classList.remove('active');
    toggleLyricsBtn.classList.remove('active');
  });

  // Queue Drawer Toggle
  openQueueBtn.addEventListener('click', () => {
    queueDrawer.classList.toggle('active');
    updateQueueUI();
  });
  closeQueueBtn.addEventListener('click', () => {
    queueDrawer.classList.remove('active');
  });
  clearQueueBtn.addEventListener('click', () => {
    player.queue = [];
    player.currentIndex = -1;
    player.audio.pause();
    player.audio.src = '';
    playerTitle.textContent = '未在播放';
    playerArtist.textContent = '从列表点击播放歌曲';
    lyrics.clear();
    updateQueueUI();
    UI.showToast('播放列表已清空', 'info');
  });

  function updateQueueUI() {
    queueCount.textContent = player.queue.length;
    queueBadge.textContent = player.queue.length;
    queueList.innerHTML = '';

    player.queue.forEach((t, idx) => {
      const item = document.createElement('div');
      item.className = `queue-item ${idx === player.currentIndex ? 'active' : ''}`;
      item.innerHTML = `
        <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1;">
          ${t.song_name} - <small style="color:var(--text-muted);">${t.singers}</small>
        </span>
        <button class="btn-text text-danger" style="margin-left:8px;" title="移除">✕</button>
      `;
      item.addEventListener('click', () => {
        player.currentIndex = idx;
        player.loadCurrentTrack(true);
      });
      item.querySelector('button').addEventListener('click', (e) => {
        e.stopPropagation();
        player.queue.splice(idx, 1);
        if (player.currentIndex === idx) {
          player.loadCurrentTrack(true);
        } else if (player.currentIndex > idx) {
          player.currentIndex--;
        }
        updateQueueUI();
      });
      queueList.appendChild(item);
    });
  }

  // ── Source Filter Chips ──
  const searchSourceChips = document.getElementById('searchSourceChips');
  let selectedSearchSources = new Set();

  async function initSources() {
    const data = await API.getSources();
    allSources = data.sources || [];
    const active = data.active || [];

    selectedSearchSources = new Set(active);
    renderSourceChips();
    renderSettingsSourcesMatrix();
  }

  function renderSourceChips() {
    searchSourceChips.innerHTML = '';
    allSources.forEach(s => {
      const chip = document.createElement('div');
      chip.className = `source-chip ${selectedSearchSources.has(s.id) ? 'active' : ''}`;
      chip.textContent = s.label;
      chip.title = `${s.desc} [${s.category_label}]`;
      chip.addEventListener('click', () => {
        if (selectedSearchSources.has(s.id)) {
          selectedSearchSources.delete(s.id);
          chip.classList.remove('active');
        } else {
          selectedSearchSources.add(s.id);
          chip.classList.add('active');
        }
      });
      searchSourceChips.appendChild(chip);
    });
  }

  document.getElementById('selectAllSources').addEventListener('click', () => {
    allSources.forEach(s => selectedSearchSources.add(s.id));
    renderSourceChips();
  });
  document.getElementById('clearAllSources').addEventListener('click', () => {
    selectedSearchSources.clear();
    renderSourceChips();
  });
  document.getElementById('presetDefaultSources').addEventListener('click', () => {
    selectedSearchSources.clear();
    ['MiguMusicClient', 'KuwoMusicClient', 'NeteaseMusicClient'].forEach(id => selectedSearchSources.add(id));
    renderSourceChips();
  });

  // ── Search Logic (SSE) ──
  const globalSearchInput = document.getElementById('globalSearchInput');
  const searchSubmitBtn = document.getElementById('searchSubmitBtn');
  const searchResultsList = document.getElementById('searchResultsList');
  const searchTableHeader = document.getElementById('searchTableHeader');
  const searchEmptyState = document.getElementById('searchEmptyState');
  const searchProgressBar = document.getElementById('searchProgressBar');
  const searchProgressText = document.getElementById('searchProgressText');

  searchSubmitBtn.addEventListener('click', doSearch);
  globalSearchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') doSearch();
  });

  function doSearch() {
    const query = globalSearchInput.value.trim();
    if (!query) {
      UI.showToast('请输入搜索关键词或歌名', 'warning');
      return;
    }

    // Smart detection: If user pastes URL, automatically redirect to playlist parser
    if (query.startsWith('http://') || query.startsWith('https://')) {
      document.getElementById('playlistUrlInput').value = query;
      switchTab('playlist');
      startParsePlaylist();
      return;
    }

    if (currentSearchSSE) {
      currentSearchSSE.close();
      currentSearchSSE = null;
    }

    searchResultsList.innerHTML = '';
    searchEmptyState.style.display = 'none';
    searchTableHeader.style.display = 'grid';
    searchProgressBar.style.display = 'flex';
    searchProgressText.textContent = `正在从 ${selectedSearchSources.size} 个音源并发搜索 "${query}"...`;

    const sourcesArr = Array.from(selectedSearchSources);
    let resultCount = 0;

    currentSearchSSE = API.searchStream(query, sourcesArr, {
      onSourceStart(data) {
        searchProgressText.textContent = `音源 [${data.label}] 已发起搜索...`;
      },
      onResult(track) {
        resultCount++;
        const row = UI.createTrackRow(track, {
          onPlay: (t) => player.playTrack(t),
          onAddToQueue: (t) => {
            player.queue.push(t);
            updateQueueUI();
            UI.showToast(`已添加: ${t.song_name}`, 'success');
          },
          onDownload: (t) => triggerDownload(t),
        });
        searchResultsList.appendChild(row);
      },
      onSourceDone(data) {
        if (data.timed_out) {
          console.warn(`Source ${data.source} timed out.`);
        }
      },
      onDone(data) {
        searchProgressBar.style.display = 'none';
        if (resultCount === 0) {
          searchEmptyState.style.display = 'flex';
          searchTableHeader.style.display = 'none';
          searchEmptyState.querySelector('h3').textContent = '未检索到相关曲目';
          searchEmptyState.querySelector('p').textContent = '请尝试更换关键词或勾选更多音源。';
        } else {
          UI.showToast(`搜索完成，共检索到 ${resultCount} 首曲目`, 'success');
        }
      },
      onError(err) {
        searchProgressBar.style.display = 'none';
        UI.showToast('搜索连接断开或超时', 'error');
      }
    });
  }

  // ── Playlist Parsing Tab ──
  const startParsePlaylistBtn = document.getElementById('startParsePlaylistBtn');
  const playlistUrlInput = document.getElementById('playlistUrlInput');
  const playlistSourceSelect = document.getElementById('playlistSourceSelect');
  const playlistResultsList = document.getElementById('playlistResultsList');
  const playlistEmptyState = document.getElementById('playlistEmptyState');
  const playlistActionsBar = document.getElementById('playlistActionsBar');
  const playlistStatsText = document.getElementById('playlistStatsText');
  const playlistSelectAllBtn = document.getElementById('playlistSelectAllBtn');
  const playlistBatchDownloadBtn = document.getElementById('playlistBatchDownloadBtn');

  startParsePlaylistBtn.addEventListener('click', startParsePlaylist);

  function startParsePlaylist() {
    const url = playlistUrlInput.value.trim();
    if (!url) {
      UI.showToast('请输入歌单或分享链接', 'warning');
      return;
    }

    playlistResultsList.innerHTML = '';
    playlistEmptyState.style.display = 'none';
    playlistActionsBar.style.display = 'flex';
    playlistStatsText.textContent = '正在连接目标平台并解析歌单信息...';
    activePlaylistTracks = [];

    API.parsePlaylistStream(url, playlistSourceSelect.value || null, {
      onStart(data) {
        playlistStatsText.textContent = `正在从 [${data.label}] 解析歌单...`;
      },
      onTrack(track) {
        activePlaylistTracks.push(track);
        playlistStatsText.textContent = `已解析 ${activePlaylistTracks.length} 首`;

        const row = UI.createTrackRow(track, {
          onPlay: (t) => player.playTrack(t),
          onAddToQueue: (t) => {
            player.queue.push(t);
            updateQueueUI();
            UI.showToast(`已加入播放列表: ${t.song_name}`, 'success');
          },
          onDownload: (t) => triggerDownload(t),
        });
        playlistResultsList.appendChild(row);
      },
      onDone(data) {
        playlistStatsText.textContent = `歌单解析完成，共 ${activePlaylistTracks.length} 首`;
        UI.showToast(`歌单解析成功 (${activePlaylistTracks.length} 首)`, 'success');
      },
      onError(err) {
        UI.showToast(err.message || '歌单解析失败，请检查链接或 Cookie', 'error');
      }
    });
  }

  playlistBatchDownloadBtn.addEventListener('click', async () => {
    if (activePlaylistTracks.length === 0) {
      UI.showToast('当前没有解析出的曲目', 'warning');
      return;
    }
    UI.showToast(`已为 ${activePlaylistTracks.length} 首歌曲发起批量下载`, 'info');
    for (const t of activePlaylistTracks) {
      await API.startDownload(t.token);
    }
    switchTab('downloads');
  });

  // ── Download Trigger & Listen ──
  async function triggerDownload(track) {
    if (!track.token) {
      UI.showToast('无法下载无有效 Token 的曲目', 'error');
      return;
    }
    try {
      const res = await API.startDownload(track.token);
      if (res.download_id) {
        UI.showToast(`已添加下载任务: ${track.song_name}`, 'success');
        const badge = document.getElementById('downloadBadge');
        badge.style.display = 'inline-block';
      }
    } catch (e) {
      UI.showToast('发起下载失败', 'error');
    }
  }

  // Listen to background downloads SSE
  const downloadsActiveList = document.getElementById('downloadsActiveList');
  const downloadsEmptyState = document.getElementById('downloadsEmptyState');
  const downloadsCountText = document.getElementById('downloadsCountText');
  const downloadBadge = document.getElementById('downloadBadge');

  API.listenDownloads((tasks) => {
    downloadsCountText.textContent = `${tasks.length} 个任务`;
    const running = tasks.filter(t => ['pending', 'downloading', 'tagging'].includes(t.status));

    if (running.length > 0) {
      downloadBadge.textContent = running.length;
      downloadBadge.style.display = 'inline-block';
    } else {
      downloadBadge.style.display = 'none';
    }

    if (tasks.length === 0) {
      downloadsEmptyState.style.display = 'flex';
      downloadsActiveList.innerHTML = '';
      return;
    }

    downloadsEmptyState.style.display = 'none';
    downloadsActiveList.innerHTML = '';

    tasks.forEach(dl => {
      const card = UI.renderDownloadCard(dl, async (id) => {
        await API.cancelDownload(id);
        UI.showToast('已取消下载', 'info');
      });
      downloadsActiveList.appendChild(card);
    });
  });

  // ── Local Library Tab ──
  const libraryTracksList = document.getElementById('libraryTracksList');
  const libraryEmptyState = document.getElementById('libraryEmptyState');
  const libraryCountBadge = document.getElementById('libraryCount');
  const libraryFilterInput = document.getElementById('libraryFilterInput');
  const refreshLibraryBtn = document.getElementById('refreshLibraryBtn');

  refreshLibraryBtn.addEventListener('click', loadLibrary);
  libraryFilterInput.addEventListener('input', (e) => {
    const q = e.target.value.toLowerCase().trim();
    const rows = libraryTracksList.querySelectorAll('.track-row');
    rows.forEach(r => {
      const text = r.textContent.toLowerCase();
      r.style.display = text.includes(q) ? 'grid' : 'none';
    });
  });

  async function loadLibrary() {
    try {
      const data = await API.getLibraryTracks();
      const tracks = data.tracks || [];
      libraryCountBadge.textContent = tracks.length;

      if (tracks.length === 0) {
        libraryEmptyState.style.display = 'flex';
        libraryTracksList.innerHTML = '';
        return;
      }

      libraryEmptyState.style.display = 'none';
      libraryTracksList.innerHTML = '';

      tracks.forEach(track => {
        const row = UI.createTrackRow(track, {
          isLibrary: true,
          onPlay: (t) => player.playTrack(t),
          onDelete: async (t) => {
            if (confirm(`确定要彻底删除音频文件 "${t.song_name}" 吗？`)) {
              await API.deleteLibraryTrack(t.rel_path);
              UI.showToast('文件已删除', 'info');
              loadLibrary();
            }
          }
        });
        libraryTracksList.appendChild(row);
      });
    } catch (e) {
      console.error('Failed to load library:', e);
    }
  }

  // ── Settings Tab ──
  const cfgDownloadDir = document.getElementById('cfgDownloadDir');
  const cfgSearchSize = document.getElementById('cfgSearchSize');
  const cfgTimeout = document.getElementById('cfgTimeout');
  const cfgEmbedCover = document.getElementById('cfgEmbedCover');
  const cfgEmbedLyrics = document.getElementById('cfgEmbedLyrics');
  const cfgProxy = document.getElementById('cfgProxy');
  const saveSettingsBtn = document.getElementById('saveSettingsBtn');
  const settingsSourcesMatrix = document.getElementById('settingsSourcesMatrix');

  function renderSettingsSourcesMatrix() {
    settingsSourcesMatrix.innerHTML = '';
    allSources.forEach(s => {
      const card = document.createElement('label');
      card.className = 'source-checkbox-card';
      const isChecked = selectedSearchSources.has(s.id);

      card.innerHTML = `
        <input type="checkbox" value="${s.id}" ${isChecked ? 'checked' : ''}>
        <div class="source-card-info">
          <h4>${s.label} <small style="color:var(--text-muted);">(${s.category_label})</small></h4>
          <p>${s.desc}</p>
        </div>
      `;

      card.querySelector('input').addEventListener('change', (e) => {
        if (e.target.checked) selectedSearchSources.add(s.id);
        else selectedSearchSources.delete(s.id);
        renderSourceChips();
      });

      settingsSourcesMatrix.appendChild(card);
    });
  }

  async function loadSettings() {
    appConfig = await API.getConfig();
    cfgDownloadDir.value = appConfig.download_dir || '';
    cfgSearchSize.value = appConfig.search_size_per_source || 8;
    cfgTimeout.value = appConfig.per_source_timeout || 25;
    cfgEmbedCover.checked = appConfig.embed_cover !== false;
    cfgEmbedLyrics.checked = appConfig.embed_lyrics !== false;
    cfgProxy.value = appConfig.proxy || '';

    // Load disk usage
    const sys = await API.getSystemInfo();
    if (sys.disk_total_gb) {
      const usedGb = sys.disk_total_gb - sys.disk_free_gb;
      const pct = Math.round((usedGb / sys.disk_total_gb) * 100);
      document.getElementById('diskFreeText').textContent = `${sys.disk_free_gb} GB 可用`;
      document.getElementById('diskFill').style.width = `${pct}%`;
    }
  }

  saveSettingsBtn.addEventListener('click', async () => {
    const updated = {
      download_dir: cfgDownloadDir.value.trim(),
      search_size_per_source: parseInt(cfgSearchSize.value, 10) || 8,
      per_source_timeout: parseInt(cfgTimeout.value, 10) || 25,
      embed_cover: cfgEmbedCover.checked,
      embed_lyrics: cfgEmbedLyrics.checked,
      proxy: cfgProxy.value.trim(),
      active_sources: Array.from(selectedSearchSources),
    };

    await API.saveConfig(updated);
    UI.showToast('配置已保存并生效', 'success');
  });

  // ── Init App ──
  await initSources();
  await loadLibrary();
  await loadSettings();
});
