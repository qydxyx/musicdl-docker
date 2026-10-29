// ── Main Application Controller for musicdl-web ──
document.addEventListener('DOMContentLoaded', async () => {
  // ── Core Elements ──
  const audioEl = document.getElementById('mainAudio');
  const canvasEl = document.getElementById('audioVisualizer');
  const lyricsScrollEl = document.getElementById('lyricsScroll');

  const player = new AudioPlayer(audioEl, canvasEl);
  const lyrics = new LyricsEngine(lyricsScrollEl, (time) => player.seek(time));

  const COVER_FALLBACK = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='64' height='64' viewBox='0 0 24 24' fill='%236b6258'%3E%3Cpath d='M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z'/%3E%3C/svg%3E";

  // ── Runtime State ──
  let currentUser = null;
  let authState = { needsSetup: false, allowRegistration: false, mode: 'login' };
  let appConfig = {};
  let allSources = [];
  let allUsersCache = [];
  let playlistsCache = [];
  let activePlaylistFilter = 'all';
  let currentPlaylistId = null;
  let currentPlaylistDetail = null;
  let currentSearchSSE = null;
  let downloadsSSE = null;
  let userEventsSSE = null;
  let activePlaylistTracks = [];
  let selectedSearchSources = new Set();

  let _applyingRemoteState = false;
  let _playbackSaveTimer = null;

  // ── Theme Toggle ──
  const themeToggle = document.getElementById('themeToggle');

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('musicdl_theme', theme);
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', theme === 'light' ? '#f3eee4' : '#12110f');
    if (themeToggle) {
      const light = theme === 'light';
      themeToggle.setAttribute('aria-pressed', light ? 'true' : 'false');
      themeToggle.setAttribute('aria-label', light ? '切换到暗色主题' : '切换到明亮主题');
    }
  }

  applyTheme(document.documentElement.dataset.theme === 'light' ? 'light' : 'dark');
  themeToggle?.addEventListener('click', () => {
    applyTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light');
  });

  // ── Helpers ──
  function esc(val) {
    return UI.esc(val);
  }

  function openDialog(dlg) {
    if (!dlg) return;
    if (typeof dlg.showModal === 'function') {
      if (!dlg.open) dlg.showModal();
    } else {
      dlg.setAttribute('open', '');
    }
  }

  function closeDialog(dlg) {
    if (!dlg) return;
    if (typeof dlg.close === 'function') {
      if (dlg.open) dlg.close();
    } else {
      dlg.removeAttribute('open');
    }
  }

  // Click backdrop to close <dialog>
  document.querySelectorAll('dialog.app-dialog').forEach((dlg) => {
    dlg.addEventListener('click', (e) => {
      if (e.target === dlg) closeDialog(dlg);
    });
  });

  function markPlayingRow() {
    const track = player.queue[player.currentIndex];
    document.querySelectorAll('.track-row.playing').forEach((el) => el.classList.remove('playing'));
    if (!track) return;
    document.querySelectorAll('.track-row').forEach((row) => {
      const sameToken = track.token && row.dataset.token === track.token;
      const samePath = track.rel_path && row.dataset.path === track.rel_path;
      const sameItem = track.item_id && row.dataset.itemId === String(track.item_id);
      if (sameToken || samePath || sameItem) row.classList.add('playing');
    });
  }

  // ── Tab Navigation ──
  const navItems = document.querySelectorAll('.nav-item');
  const panels = document.querySelectorAll('.tab-panel');

  function switchTab(tabId) {
    navItems.forEach((item) => {
      const on = item.dataset.tab === tabId;
      item.classList.toggle('active', on);
      if (on) item.setAttribute('aria-current', 'page');
      else item.removeAttribute('aria-current');
    });
    panels.forEach((p) => {
      p.classList.toggle('active', p.id === `panel-${tabId}`);
    });

    if (!currentUser) return;
    if (tabId === 'playlist') {
      loadPlaylists();
      if (currentPlaylistId) {
        openPlaylistDetail(currentPlaylistId, { silent: true });
      }
    } else if (tabId === 'library') {
      loadLibrary();
    } else if (tabId === 'settings') {
      loadSettings();
    }
  }

  navItems.forEach((item) => {
    item.addEventListener('click', () => switchTab(item.dataset.tab));
  });

  // ── Auth Overlay & Account Management ──
  const authOverlay = document.getElementById('authOverlay');
  const authModeTabs = document.getElementById('authModeTabs');
  const authTabLogin = document.getElementById('authTabLogin');
  const authTabRegister = document.getElementById('authTabRegister');
  const authHeading = document.getElementById('authHeading');
  const authSubtext = document.getElementById('authSubtext');
  const authForm = document.getElementById('authForm');
  const authUsername = document.getElementById('authUsername');
  const authDisplayNameGroup = document.getElementById('authDisplayNameGroup');
  const authDisplayName = document.getElementById('authDisplayName');
  const authPassword = document.getElementById('authPassword');
  const authErrorMsg = document.getElementById('authErrorMsg');
  const authSubmitBtn = document.getElementById('authSubmitBtn');

  const userMenuBtn = document.getElementById('userMenuBtn');
  const userAvatarText = document.getElementById('userAvatarText');
  const userDisplayNameEl = document.getElementById('userDisplayName');
  const userRoleBadge = document.getElementById('userRoleBadge');
  const syncStatusDot = document.getElementById('syncStatusDot');

  function setAuthMode(mode) {
    authState.mode = mode;
    authErrorMsg.hidden = true;
    authErrorMsg.textContent = '';

    if (mode === 'setup') {
      authModeTabs.hidden = true;
      authHeading.textContent = '创建管理员账号';
      authSubtext.textContent = '首次运行请创建管理员账号，完成后即可管理成员与系统设置。';
      authDisplayNameGroup.hidden = false;
      authPassword.setAttribute('autocomplete', 'new-password');
      authSubmitBtn.textContent = '完成初始化并进入';
    } else if (mode === 'register') {
      authModeTabs.hidden = !authState.allowRegistration;
      authTabLogin.classList.remove('active');
      authTabRegister.classList.add('active');
      authHeading.textContent = '注册新账号';
      authSubtext.textContent = '创建属于您的独立账号，个人歌单与播放状态会自动跨端同步。';
      authDisplayNameGroup.hidden = false;
      authPassword.setAttribute('autocomplete', 'new-password');
      authSubmitBtn.textContent = '注册并登录';
    } else {
      authModeTabs.hidden = !authState.allowRegistration;
      authTabLogin.classList.add('active');
      authTabRegister.classList.remove('active');
      authHeading.textContent = '登录账号';
      authSubtext.textContent = '登录后即可访问您的个人歌单、共享协作歌单与共享曲库。';
      authDisplayNameGroup.hidden = true;
      authPassword.setAttribute('autocomplete', 'current-password');
      authSubmitBtn.textContent = '登录';
    }
  }

  authTabLogin.addEventListener('click', () => setAuthMode('login'));
  authTabRegister.addEventListener('click', () => setAuthMode('register'));

  function showAuthOverlay(opts = {}) {
    if (opts.needsSetup !== undefined) authState.needsSetup = opts.needsSetup;
    if (opts.allowRegistration !== undefined) authState.allowRegistration = opts.allowRegistration;
    setAuthMode(authState.needsSetup ? 'setup' : 'login');
    authOverlay.hidden = false;
    document.body.classList.add('auth-locked');
    userMenuBtn.hidden = true;
    setTimeout(() => authUsername.focus(), 50);
  }

  function updateUserHeaderUI() {
    if (!currentUser) {
      userMenuBtn.hidden = true;
      return;
    }
    const name = currentUser.display_name || currentUser.username || 'U';
    userAvatarText.textContent = Array.from(name)[0].toUpperCase();
    userDisplayNameEl.textContent = name;
    userRoleBadge.hidden = currentUser.role !== 'admin';
    userMenuBtn.hidden = false;
  }

  function teardownRealtimeStreams() {
    if (currentSearchSSE) {
      currentSearchSSE.close();
      currentSearchSSE = null;
    }
    if (downloadsSSE) {
      downloadsSSE.close();
      downloadsSSE = null;
    }
    if (userEventsSSE) {
      userEventsSSE.close();
      userEventsSSE = null;
    }
    syncStatusDot.classList.remove('is-online');
  }

  API.onUnauthorized = () => {
    if (!currentUser) return;
    currentUser = null;
    teardownRealtimeStreams();
    player.audio.pause();
    closeAddToPlaylistPopover();
    document.querySelectorAll('dialog[open]').forEach((d) => closeDialog(d));
    showAuthOverlay({ needsSetup: false });
  };

  authForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    authErrorMsg.hidden = true;
    const uname = authUsername.value.trim();
    const pwd = authPassword.value;
    const dname = authDisplayName.value.trim();

    authSubmitBtn.disabled = true;
    try {
      let res;
      if (authState.mode === 'setup') {
        res = await API.setupAdmin(uname, pwd, dname);
      } else if (authState.mode === 'register') {
        res = await API.register(uname, pwd, dname);
      } else {
        res = await API.login(uname, pwd);
      }
      authPassword.value = '';
      await enterAuthenticatedApp(res.user);
      UI.showToast(`欢迎回来，${res.user.display_name}`, 'success');
    } catch (err) {
      authErrorMsg.textContent = err.message || '验证失败，请重试';
      authErrorMsg.hidden = false;
    } finally {
      authSubmitBtn.disabled = false;
    }
  });

  // ── Account Dialog ──
  const accountDialog = document.getElementById('accountDialog');
  const acctUsernameLabel = document.getElementById('acctUsernameLabel');
  const acctRoleLabel = document.getElementById('acctRoleLabel');
  const acctSyncStatus = document.getElementById('acctSyncStatus');
  const acctDisplayNameInput = document.getElementById('acctDisplayNameInput');

  function openAccountModal() {
    if (!currentUser) return;
    acctUsernameLabel.textContent = `@${currentUser.username}`;
    acctRoleLabel.textContent = currentUser.role === 'admin' ? '管理员' : '普通成员';
    acctDisplayNameInput.value = currentUser.display_name || '';
    document.getElementById('acctCurrentPwd').value = '';
    document.getElementById('acctNewPwd').value = '';
    openDialog(accountDialog);
  }

  userMenuBtn.addEventListener('click', openAccountModal);
  document.getElementById('memberOpenAccountBtn').addEventListener('click', openAccountModal);
  document.getElementById('closeAccountDialogBtn').addEventListener('click', () => closeDialog(accountDialog));

  document.getElementById('acctProfileForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const res = await API.updateOwnProfile(acctDisplayNameInput.value.trim());
      currentUser = res.user;
      updateUserHeaderUI();
      if (currentUser.role === 'admin') loadAdminUsers();
      UI.showToast('显示昵称已更新', 'success');
    } catch (err) {
      UI.showToast(err.message || '更新失败', 'error');
    }
  });

  document.getElementById('acctPasswordForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const curPwd = document.getElementById('acctCurrentPwd').value;
    const newPwd = document.getElementById('acctNewPwd').value;
    try {
      await API.changeOwnPassword(curPwd, newPwd);
      document.getElementById('acctCurrentPwd').value = '';
      document.getElementById('acctNewPwd').value = '';
      UI.showToast('密码已更新', 'success');
    } catch (err) {
      UI.showToast(err.message || '密码修改失败', 'error');
    }
  });

  document.getElementById('logoutBtn').addEventListener('click', async () => {
    closeDialog(accountDialog);
    try {
      await API.logout();
    } catch (_) {}
    currentUser = null;
    teardownRealtimeStreams();
    resetPlayerUI();
    currentPlaylistId = null;
    currentPlaylistDetail = null;
    const me = await API.getAuthMe().catch(() => ({ needs_setup: false, allow_registration: false }));
    showAuthOverlay({
      needsSetup: Boolean(me.needs_setup),
      allowRegistration: Boolean(me.allow_registration),
    });
    UI.showToast('已退出登录', 'info');
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
  const saveQueueAsPlaylistBtn = document.getElementById('saveQueueAsPlaylistBtn');
  const queueList = document.getElementById('queueList');
  const queueCount = document.getElementById('queueCount');
  const queueBadge = document.getElementById('queueBadge');

  const stageCoverImg = document.getElementById('stageCoverImg');
  const stageBackdrop = document.getElementById('stageBackdrop');

  btnPlayPause.addEventListener('click', () => player.togglePlay());
  btnPrev.addEventListener('click', () => player.prev());
  btnNext.addEventListener('click', () => player.next());
  btnMode.addEventListener('click', () => player.toggleMode());

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

  function setCover(src, alt) {
    playerCoverImg.src = src;
    playerCoverImg.alt = alt;
    stageCoverImg.src = src;
    stageCoverImg.alt = alt;
    stageBackdrop.src = src;
  }

  function resetPlayerUI() {
    player.queue = [];
    player.currentIndex = -1;
    player.audio.pause();
    player.audio.removeAttribute('src');
    playerTitle.textContent = '未在播放';
    playerArtist.textContent = '从列表点一首歌';
    document.getElementById('lyricsTitle').textContent = '未在播放';
    document.getElementById('lyricsArtist').textContent = '从列表点一首歌';
    document.getElementById('stageAlbum').textContent = '';
    progressFill.style.width = '0%';
    progressThumb.style.left = '0%';
    timeCurrent.textContent = '00:00';
    timeDuration.textContent = '00:00';
    setCover(COVER_FALLBACK, '专辑封面');
    markPlayingRow();
    lyrics.clear();
    updateQueueUI();
  }

  function renderActiveTrackMeta(track) {
    if (!track) return;
    playerTitle.textContent = track.song_name || '未知曲目';
    playerArtist.textContent = track.singers || '未知艺人';

    let coverSrc = track.cover_url || '';
    if (!coverSrc && track.rel_path && (track.has_cover || track.is_local)) {
      coverSrc = `/api/library/cover/${encodeURIComponent(track.rel_path)}`;
    }
    const coverAlt = track.song_name ? `${track.song_name} 的封面` : '专辑封面';
    setCover(coverSrc || COVER_FALLBACK, coverAlt);
    markPlayingRow();

    document.getElementById('lyricsTitle').textContent = track.song_name || '未知曲目';
    document.getElementById('lyricsArtist').textContent = track.singers || '未知艺人';
    document.getElementById('stageAlbum').textContent = track.album || '';
  }

  player.onTrackChange = async (track) => {
    renderActiveTrackMeta(track);
    updateQueueUI();

    lyrics.clear();
    let lrc = '';
    if (track.rel_path) {
      lrc = await API.getLocalLyric(track.rel_path);
    } else if (track.token) {
      lrc = await API.getLyric(track.token);
    }
    lyrics.loadLRC(lrc);
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

  // Debounced cross-device playback state sync
  function scheduleSavePlaybackState() {
    if (!currentUser || _applyingRemoteState) return;
    if (_playbackSaveTimer) clearTimeout(_playbackSaveTimer);
    _playbackSaveTimer = setTimeout(() => {
      if (!currentUser) return;
      API.savePlaybackState(player.serializeState()).catch(() => {});
    }, 700);
  }

  player.onStateMutate = () => {
    scheduleSavePlaybackState();
  };

  // Periodic progress sync when actively playing
  setInterval(() => {
    if (currentUser && !player.audio.paused && player.queue.length > 0) {
      API.savePlaybackState(Object.assign(player.serializeState(), { broadcast: false })).catch(() => {});
    }
  }, 15000);

  async function restorePlaybackState() {
    try {
      const state = await API.getPlaybackState();
      applyRemotePlaybackState(state, true);
    } catch (_) {}
  }

  function applyRemotePlaybackState(state, isInitial = false) {
    if (!state || !Array.isArray(state.queue)) return;
    _applyingRemoteState = true;
    try {
      player.setPlayMode(state.play_mode || 'loop', true);

      // If currently playing audio on this device, only update queue items without interrupting playback
      if (!isInitial && !player.audio.paused) {
        const curTrack = player.queue[player.currentIndex];
        player.queue = state.queue.map((t) => Object.assign({}, t));
        if (curTrack) {
          const foundIdx = player.queue.findIndex((t) => player._isSameTrack(t, curTrack));
          if (foundIdx !== -1) player.currentIndex = foundIdx;
        }
        updateQueueUI();
        markPlayingRow();
        return;
      }

      player.queue = state.queue.map((t) => Object.assign({}, t));
      player.currentIndex = state.current_index ?? -1;
      if (player.currentIndex >= player.queue.length) {
        player.currentIndex = player.queue.length - 1;
      }
      updateQueueUI();

      if (player.currentIndex >= 0 && player.queue[player.currentIndex]) {
        const active = player.queue[player.currentIndex];
        renderActiveTrackMeta(active);
        if (active.rel_path) {
          player.audio.src = `/api/library/stream/${encodeURIComponent(active.rel_path)}`;
          if (state.position_sec > 0) {
            player.audio.addEventListener('loadedmetadata', () => {
              if (player.audio.duration && state.position_sec < player.audio.duration) {
                player.audio.currentTime = state.position_sec;
              }
            }, { once: true });
          }
        }
      }
    } finally {
      _applyingRemoteState = false;
    }
  }

  function openStage() {
    lyricsModal.classList.add('active');
    lyricsModal.setAttribute('aria-hidden', 'false');
    toggleLyricsBtn.classList.add('active');
    lyrics.currentIndex = -1;
    requestAnimationFrame(() => lyrics.sync(player.audio.currentTime || 0));
  }

  function closeStage() {
    lyricsModal.classList.remove('active');
    lyricsModal.setAttribute('aria-hidden', 'true');
    toggleLyricsBtn.classList.remove('active');
  }

  toggleLyricsBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (lyricsModal.classList.contains('active')) closeStage();
    else openStage();
  });
  closeLyricsBtn.addEventListener('click', closeStage);
  document.getElementById('playerCoverWrapper').addEventListener('click', openStage);
  document.querySelector('.player-info').addEventListener('click', openStage);
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (!addToPlaylistPopover.hidden) {
        closeAddToPlaylistPopover();
        return;
      }
      if (lyricsModal.classList.contains('active')) closeStage();
    }
  });
  stageCoverImg.addEventListener('error', () => setCover(COVER_FALLBACK, '专辑封面'));

  // Queue Drawer Toggle & Actions
  openQueueBtn.addEventListener('click', () => {
    queueDrawer.classList.toggle('active');
    updateQueueUI();
  });
  closeQueueBtn.addEventListener('click', () => {
    queueDrawer.classList.remove('active');
  });
  clearQueueBtn.addEventListener('click', () => {
    resetPlayerUI();
    scheduleSavePlaybackState();
    UI.showToast('播放队列已清空', 'info');
  });
  saveQueueAsPlaylistBtn.addEventListener('click', (e) => {
    if (player.queue.length === 0) {
      UI.showToast('当前播放队列为空', 'warning');
      return;
    }
    openAddToPlaylistPopover(player.queue, e.currentTarget);
  });

  function updateQueueUI() {
    queueCount.textContent = player.queue.length;
    queueBadge.textContent = player.queue.length;
    queueBadge.style.display = player.queue.length ? 'inline-block' : 'none';
    queueList.innerHTML = '';

    player.queue.forEach((t, idx) => {
      const item = document.createElement('div');
      item.className = `queue-item ${idx === player.currentIndex ? 'active' : ''}`;
      item.innerHTML = `
        <span class="queue-item-title">${esc(t.song_name)} <span class="queue-item-artist">${esc(t.singers)}</span></span>
        <button class="btn-text text-danger queue-remove" type="button" title="移除" aria-label="从播放队列移除">移除</button>
      `;
      item.addEventListener('click', () => {
        player.currentIndex = idx;
        player.loadCurrentTrack(true);
      });
      item.querySelector('button').addEventListener('click', (e) => {
        e.stopPropagation();
        player.queue.splice(idx, 1);
        if (player.queue.length === 0) {
          resetPlayerUI();
        } else if (player.currentIndex === idx) {
          player.currentIndex = Math.min(idx, player.queue.length - 1);
          player.loadCurrentTrack(true);
        } else if (player.currentIndex > idx) {
          player.currentIndex--;
          updateQueueUI();
        } else {
          updateQueueUI();
        }
        scheduleSavePlaybackState();
      });
      queueList.appendChild(item);
    });
  }

  function appendTrackToQueue(track) {
    player.queue.push(Object.assign({}, track));
    updateQueueUI();
    scheduleSavePlaybackState();
    UI.showToast(`已加入队列: ${track.song_name}`, 'success');
  }

  // ── Quick Add-to-Playlist Popover ──
  const addToPlaylistPopover = document.getElementById('addToPlaylistPopover');
  const popoverTitleText = document.getElementById('popoverTitleText');
  const popoverPlaylistList = document.getElementById('popoverPlaylistList');
  const popoverQuickCreateForm = document.getElementById('popoverQuickCreateForm');
  const popoverNewPlaylistInput = document.getElementById('popoverNewPlaylistInput');
  let _popoverTracks = [];

  function closeAddToPlaylistPopover() {
    addToPlaylistPopover.hidden = true;
    _popoverTracks = [];
  }

  document.getElementById('closePlaylistPopoverBtn').addEventListener('click', closeAddToPlaylistPopover);
  document.addEventListener('click', (e) => {
    if (!addToPlaylistPopover.hidden && !addToPlaylistPopover.contains(e.target)) {
      closeAddToPlaylistPopover();
    }
  });

  async function openAddToPlaylistPopover(tracksOrSingle, anchorEl) {
    const list = Array.isArray(tracksOrSingle) ? tracksOrSingle : [tracksOrSingle];
    if (!list.length) return;
    _popoverTracks = list;
    popoverTitleText.textContent = list.length > 1
      ? `收藏 ${list.length} 首曲目到歌单`
      : '收藏到歌单';
    popoverNewPlaylistInput.value = '';

    if (playlistsCache.length === 0) {
      await loadPlaylists();
    }
    const editable = playlistsCache.filter((p) => p.can_edit);
    popoverPlaylistList.innerHTML = '';

    if (editable.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'popover-empty';
      empty.textContent = '暂无可编辑歌单，在下方输入名称直接新建';
      popoverPlaylistList.appendChild(empty);
    } else {
      editable.forEach((pl) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'popover-item';
        const roleNote = pl.access_role === 'owner' ? `${pl.track_count} 首` : `协作 · ${pl.track_count} 首`;
        btn.innerHTML = `
          <span class="popover-item-name">${esc(pl.name)}</span>
          <span class="popover-item-meta">${esc(roleNote)}</span>
        `;
        btn.addEventListener('click', async () => {
          const toAdd = _popoverTracks.slice();
          closeAddToPlaylistPopover();
          try {
            const res = await API.addTracksToPlaylist(pl.id, toAdd);
            const msg = res.skipped > 0
              ? `已加入「${pl.name}」${res.added} 首（跳过重复 ${res.skipped} 首）`
              : `已加入「${pl.name}」（${res.added} 首）`;
            UI.showToast(msg, 'success');
            loadPlaylists();
            if (currentPlaylistId === pl.id) {
              openPlaylistDetail(pl.id, { silent: true });
            }
          } catch (err) {
            UI.showToast(err.message || '添加失败', 'error');
          }
        });
        popoverPlaylistList.appendChild(btn);
      });
    }

    addToPlaylistPopover.hidden = false;
    const rect = anchorEl ? anchorEl.getBoundingClientRect() : { left: window.innerWidth / 2 - 130, bottom: 140, top: 120 };
    const popWidth = 268;
    const popHeight = Math.min(340, addToPlaylistPopover.offsetHeight || 260);
    let left = Math.min(window.innerWidth - popWidth - 12, Math.max(12, rect.right ? rect.right - popWidth : rect.left));
    let top = rect.bottom + 6;
    if (top + popHeight > window.innerHeight - 16) {
      top = Math.max(12, rect.top - popHeight - 6);
    }
    addToPlaylistPopover.style.left = `${left}px`;
    addToPlaylistPopover.style.top = `${top}px`;
  }

  popoverQuickCreateForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = popoverNewPlaylistInput.value.trim();
    if (!name) {
      popoverNewPlaylistInput.focus();
      return;
    }
    const tracksToSave = _popoverTracks.slice();
    closeAddToPlaylistPopover();
    try {
      const res = await API.createPlaylist({
        name,
        visibility: 'private',
        tracks: tracksToSave,
      });
      UI.showToast(`已创建歌单「${res.playlist.name}」并加入 ${tracksToSave.length} 首曲目`, 'success');
      await loadPlaylists();
    } catch (err) {
      UI.showToast(err.message || '创建歌单失败', 'error');
    }
  });

  // ── Playlists Hub & Detail View ──
  const playlistCountBadge = document.getElementById('playlistCount');
  const playlistCollectionView = document.getElementById('playlistCollectionView');
  const playlistDetailView = document.getElementById('playlistDetailView');
  const playlistsGrid = document.getElementById('playlistsGrid');
  const playlistsEmptyState = document.getElementById('playlistsEmptyState');
  const externalParserSection = document.getElementById('externalParserSection');
  const toggleUrlParserBtn = document.getElementById('toggleUrlParserBtn');

  function setUrlParserOpen(open) {
    externalParserSection.hidden = !open;
    toggleUrlParserBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) {
      document.getElementById('playlistUrlInput').focus();
    }
  }

  toggleUrlParserBtn.addEventListener('click', () => setUrlParserOpen(externalParserSection.hidden));
  document.getElementById('closeUrlParserBtn').addEventListener('click', () => setUrlParserOpen(false));
  document.getElementById('emptyOpenParserBtn').addEventListener('click', () => setUrlParserOpen(true));

  document.querySelectorAll('#playlistFilterBar .filter-pill').forEach((btn) => {
    btn.addEventListener('click', () => {
      activePlaylistFilter = btn.dataset.plFilter;
      document.querySelectorAll('#playlistFilterBar .filter-pill').forEach((b) => {
        const active = b === btn;
        b.classList.toggle('active', active);
        b.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      renderPlaylistsGrid();
    });
  });

  async function loadPlaylists() {
    if (!currentUser) return;
    try {
      const data = await API.getPlaylists();
      playlistsCache = data.playlists || [];
      playlistCountBadge.textContent = playlistsCache.length;
      renderPlaylistsGrid();
    } catch (err) {
      console.error('Failed to load playlists:', err);
    }
  }

  function getFilteredPlaylists() {
    return playlistsCache.filter((p) => {
      if (activePlaylistFilter === 'mine') return p.access_role === 'owner';
      if (activePlaylistFilter === 'shared') return p.is_member || (p.access_role === 'owner' && p.members && p.members.length > 0);
      if (activePlaylistFilter === 'public') return p.visibility === 'public';
      return true;
    });
  }

  function formatPlaylistRoleLabel(pl) {
    if (pl.access_role === 'owner') {
      if (pl.visibility === 'public') return pl.public_editable ? '我创建 · 公开协作' : '我创建 · 公开';
      if (pl.members && pl.members.length > 0) return `我创建 · 共享 ${pl.members.length} 人`;
      if (pl.source_playlist_id) return '同步副本';
      return '私有';
    }
    if (pl.access_role === 'editor') return `${pl.owner_name} · 可协作`;
    if (pl.access_role === 'viewer') return `${pl.owner_name} · 只读共享`;
    return `${pl.owner_name} · 公开`;
  }

  function renderPlaylistsGrid() {
    const list = getFilteredPlaylists();
    playlistsGrid.innerHTML = '';

    if (list.length === 0) {
      playlistsEmptyState.style.display = 'flex';
      return;
    }

    playlistsEmptyState.style.display = 'none';
    list.forEach((pl) => {
      const tile = document.createElement('article');
      tile.className = 'playlist-tile';
      const cover = pl.cover_url || COVER_FALLBACK;
      const offlineNote = pl.offline_count > 0 ? ` · 已缓存 ${pl.offline_count}` : '';
      const roleNote = formatPlaylistRoleLabel(pl);

      tile.innerHTML = `
        <div class="playlist-tile-art">
          <img src="${esc(cover)}" alt="" loading="lazy">
          <button class="playlist-tile-play" type="button" title="直接播放整张歌单" aria-label="播放 ${esc(pl.name)}">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M8 5v14l11-7z" fill="currentColor"/></svg>
          </button>
        </div>
        <div class="playlist-tile-info">
          <h3 title="${esc(pl.name)}">${esc(pl.name)}</h3>
          <p class="playlist-tile-meta">${pl.track_count} 首${esc(offlineNote)} · ${esc(roleNote)}</p>
        </div>
      `;

      const img = tile.querySelector('img');
      img.addEventListener('error', () => { img.src = COVER_FALLBACK; }, { once: true });

      tile.querySelector('.playlist-tile-play').addEventListener('click', async (e) => {
        e.stopPropagation();
        try {
          const detail = await API.getPlaylistDetail(pl.id);
          if (!detail.tracks || detail.tracks.length === 0) {
            UI.showToast('这张歌单里还没有曲目', 'warning');
            return;
          }
          player.replaceQueue(detail.tracks, 0, true);
          UI.showToast(`开始播放「${pl.name}」`, 'success');
        } catch (err) {
          UI.showToast(err.message || '加载歌单失败', 'error');
        }
      });

      tile.addEventListener('click', () => openPlaylistDetail(pl.id));
      playlistsGrid.appendChild(tile);
    });
  }

  function showPlaylistCollectionView() {
    currentPlaylistId = null;
    currentPlaylistDetail = null;
    playlistDetailView.hidden = true;
    playlistCollectionView.hidden = false;
    loadPlaylists();
  }

  document.getElementById('backToPlaylistsBtn').addEventListener('click', showPlaylistCollectionView);

  async function openPlaylistDetail(playlistId, opts = {}) {
    try {
      const detail = await API.getPlaylistDetail(playlistId);
      currentPlaylistId = playlistId;
      currentPlaylistDetail = detail;
      playlistCollectionView.hidden = true;
      playlistDetailView.hidden = false;
      renderPlaylistDetail(detail);
    } catch (err) {
      if (!opts.silent) {
        UI.showToast(err.message || '无法打开歌单', 'error');
      }
      showPlaylistCollectionView();
    }
  }

  function renderPlaylistDetail(detail) {
    const pl = detail.playlist;
    const tracks = detail.tracks || [];

    const coverEl = document.getElementById('plDetailCover');
    coverEl.src = pl.cover_url || COVER_FALLBACK;
    coverEl.onerror = () => { coverEl.src = COVER_FALLBACK; };

    document.getElementById('plDetailTitle').textContent = pl.name;
    const descEl = document.getElementById('plDetailDesc');
    descEl.textContent = pl.description || '';
    descEl.hidden = !pl.description;

    const badgesEl = document.getElementById('plDetailBadges');
    badgesEl.innerHTML = '';
    const badges = [];
    if (pl.visibility === 'public') {
      badges.push(pl.public_editable ? '全员公开 · 可协作' : '全员公开');
    } else {
      badges.push('私有');
    }
    if (pl.members && pl.members.length > 0) {
      badges.push(`共享 ${pl.members.length} 人`);
    }
    if (pl.access_role === 'editor') badges.push('协作权限');
    else if (pl.access_role === 'viewer') badges.push('只读订阅');
    if (pl.source_playlist_id) badges.push('分发关联歌单');

    badges.forEach((b) => {
      const span = document.createElement('span');
      span.className = 'badge-tag';
      span.textContent = b;
      badgesEl.appendChild(span);
    });

    const memberNames = (pl.members || []).map((m) => m.display_name).slice(0, 4).join('、');
    const sharedSuffix = memberNames ? ` · 协作成员：${memberNames}${pl.members.length > 4 ? ' 等' : ''}` : '';
    document.getElementById('plDetailMeta').textContent =
      `创建者：${pl.owner_name} · 共 ${tracks.length} 首（本地已缓存 ${pl.offline_count} 首）${sharedSuffix}`;

    document.getElementById('plEditMetaBtn').hidden = !pl.can_manage;
    document.getElementById('plDeleteBtn').hidden = !pl.can_manage;
    document.getElementById('plLeaveBtn').hidden = !(pl.is_member && !pl.can_manage);

    const listEl = document.getElementById('plDetailTracksList');
    const headerEl = document.getElementById('plDetailTableHeader');
    const emptyEl = document.getElementById('plDetailEmptyState');
    listEl.innerHTML = '';

    if (tracks.length === 0) {
      headerEl.style.display = 'none';
      emptyEl.style.display = 'flex';
      return;
    }

    headerEl.style.display = 'grid';
    emptyEl.style.display = 'none';

    tracks.forEach((track, idx) => {
      const row = UI.createTrackRow(track, {
        isPlaylist: true,
        canEditPlaylist: pl.can_edit,
        onPlay: () => {
          player.replaceQueue(tracks, idx, true);
        },
        onAddToPlaylist: (t, btn) => openAddToPlaylistPopover(t, btn),
        onDownload: (t) => triggerDownload(t),
        onMoveUp: idx > 0 ? () => movePlaylistTrack(pl.id, tracks, idx, -1) : null,
        onMoveDown: idx < tracks.length - 1 ? () => movePlaylistTrack(pl.id, tracks, idx, 1) : null,
        onRemoveFromPlaylist: async (t) => {
          try {
            await API.removeTrackFromPlaylist(pl.id, t.item_id);
            await openPlaylistDetail(pl.id, { silent: true });
            loadPlaylists();
          } catch (err) {
            UI.showToast(err.message || '移除失败', 'error');
          }
        },
      });
      listEl.appendChild(row);
    });
    markPlayingRow();
  }

  async function movePlaylistTrack(playlistId, tracks, index, delta) {
    const targetIdx = index + delta;
    if (targetIdx < 0 || targetIdx >= tracks.length) return;
    const ids = tracks.map((t) => t.item_id);
    const [moved] = ids.splice(index, 1);
    ids.splice(targetIdx, 0, moved);
    try {
      await API.reorderPlaylistTracks(playlistId, ids);
      await openPlaylistDetail(playlistId, { silent: true });
    } catch (err) {
      UI.showToast(err.message || '排序更新失败', 'error');
    }
  }

  document.getElementById('plPlayAllBtn').addEventListener('click', () => {
    const tracks = currentPlaylistDetail?.tracks || [];
    if (tracks.length === 0) {
      UI.showToast('歌单中还没有曲目', 'warning');
      return;
    }
    player.replaceQueue(tracks, 0, true);
    UI.showToast(`开始播放「${currentPlaylistDetail.playlist.name}」`, 'success');
  });

  document.getElementById('plAppendQueueBtn').addEventListener('click', () => {
    const tracks = currentPlaylistDetail?.tracks || [];
    if (tracks.length === 0) {
      UI.showToast('歌单中还没有曲目', 'warning');
      return;
    }
    tracks.forEach((t) => player.queue.push(Object.assign({}, t)));
    updateQueueUI();
    scheduleSavePlaybackState();
    UI.showToast(`已将 ${tracks.length} 首曲目追加到播放队列`, 'success');
  });

  document.getElementById('plDownloadOfflineBtn').addEventListener('click', async () => {
    if (!currentPlaylistDetail) return;
    try {
      const res = await API.downloadWholePlaylist(currentPlaylistDetail.playlist.id);
      if (res.queued === 0) {
        UI.showToast('歌单内所有曲目均已在本地曲库缓存', 'info');
      } else {
        UI.showToast(`已为 ${res.queued} 首未缓存曲目发起后台下载`, 'success');
        switchTab('downloads');
      }
    } catch (err) {
      UI.showToast(err.message || '批量离线下载失败', 'error');
    }
  });

  document.getElementById('plDeleteBtn').addEventListener('click', async () => {
    if (!currentPlaylistDetail) return;
    const pl = currentPlaylistDetail.playlist;
    if (!confirm(`确定要删除歌单「${pl.name}」吗？（不会删除已下载到本地曲库的音频文件）`)) return;
    try {
      await API.deletePlaylist(pl.id);
      UI.showToast(`已删除歌单「${pl.name}」`, 'info');
      showPlaylistCollectionView();
    } catch (err) {
      UI.showToast(err.message || '删除歌单失败', 'error');
    }
  });

  document.getElementById('plLeaveBtn').addEventListener('click', async () => {
    if (!currentPlaylistDetail) return;
    const pl = currentPlaylistDetail.playlist;
    if (!confirm(`确定退出共享歌单「${pl.name}」吗？`)) return;
    try {
      await API.leavePlaylist(pl.id);
      UI.showToast('已退出共享歌单', 'info');
      showPlaylistCollectionView();
    } catch (err) {
      UI.showToast(err.message || '操作失败', 'error');
    }
  });

  // ── Create / Edit Playlist Dialog ──
  const playlistEditDialog = document.getElementById('playlistEditDialog');
  const plEditForm = document.getElementById('plEditForm');
  const plDialogTitle = document.getElementById('plDialogTitle');
  const plFormName = document.getElementById('plFormName');
  const plFormDesc = document.getElementById('plFormDesc');
  const plFormOwnerGroup = document.getElementById('plFormOwnerGroup');
  const plFormOwnerSelect = document.getElementById('plFormOwnerSelect');
  const plFormVisibility = document.getElementById('plFormVisibility');
  const plFormPublicEditWrap = document.getElementById('plFormPublicEditWrap');
  const plFormPublicEditable = document.getElementById('plFormPublicEditable');

  let _editingPlaylistId = null;

  plFormVisibility.addEventListener('change', () => {
    plFormPublicEditWrap.hidden = plFormVisibility.value !== 'public';
  });

  async function ensureUsersLoaded() {
    try {
      const data = await API.getUsers();
      allUsersCache = data.users || [];
    } catch (_) {}
    return allUsersCache;
  }

  async function openPlaylistEditor({ playlist = null, presetOwnerId = null } = {}) {
    _editingPlaylistId = playlist ? playlist.id : null;
    plDialogTitle.textContent = playlist ? '编辑歌单信息' : '新建歌单';
    plFormName.value = playlist ? playlist.name : '';
    plFormDesc.value = playlist ? (playlist.description || '') : '';
    plFormVisibility.value = playlist ? playlist.visibility : 'private';
    plFormPublicEditable.checked = playlist ? Boolean(playlist.public_editable) : false;
    plFormPublicEditWrap.hidden = plFormVisibility.value !== 'public';

    if (currentUser?.role === 'admin') {
      const users = await ensureUsersLoaded();
      plFormOwnerSelect.innerHTML = '';
      users.forEach((u) => {
        const opt = document.createElement('option');
        opt.value = String(u.id);
        opt.textContent = `${u.display_name} (@${u.username})${u.id === currentUser.id ? ' · 我自己' : ''}`;
        plFormOwnerSelect.appendChild(opt);
      });
      const targetOwner = presetOwnerId || (playlist ? playlist.owner_id : currentUser.id);
      plFormOwnerSelect.value = String(targetOwner);
      plFormOwnerGroup.hidden = false;
    } else {
      plFormOwnerGroup.hidden = true;
    }

    openDialog(playlistEditDialog);
    setTimeout(() => plFormName.focus(), 40);
  }

  document.getElementById('openCreatePlaylistBtn').addEventListener('click', () => openPlaylistEditor());
  document.getElementById('emptyCreatePlaylistBtn').addEventListener('click', () => openPlaylistEditor());
  document.getElementById('plEditMetaBtn').addEventListener('click', () => {
    if (currentPlaylistDetail) {
      openPlaylistEditor({ playlist: currentPlaylistDetail.playlist });
    }
  });
  document.getElementById('closePlEditDialogBtn').addEventListener('click', () => closeDialog(playlistEditDialog));
  document.getElementById('cancelPlEditBtn').addEventListener('click', () => closeDialog(playlistEditDialog));

  plEditForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
      name: plFormName.value.trim(),
      description: plFormDesc.value.trim(),
      visibility: plFormVisibility.value,
      public_editable: plFormVisibility.value === 'public' && plFormPublicEditable.checked,
    };
    if (currentUser?.role === 'admin' && plFormOwnerSelect.value) {
      payload.owner_id = parseInt(plFormOwnerSelect.value, 10);
    }

    try {
      if (_editingPlaylistId) {
        await API.updatePlaylist(_editingPlaylistId, payload);
        UI.showToast('歌单信息已保存', 'success');
        closeDialog(playlistEditDialog);
        await loadPlaylists();
        if (currentPlaylistId === _editingPlaylistId) {
          await openPlaylistDetail(_editingPlaylistId, { silent: true });
        }
      } else {
        const res = await API.createPlaylist(payload);
        closeDialog(playlistEditDialog);
        await loadPlaylists();
        if (res.playlist.owner_id === currentUser.id || currentUser.role === 'admin') {
          UI.showToast(`已创建歌单「${res.playlist.name}」`, 'success');
          if (res.playlist.owner_id === currentUser.id) {
            openPlaylistDetail(res.playlist.id);
          }
        }
      }
    } catch (err) {
      UI.showToast(err.message || '保存失败', 'error');
    }
  });

  // ── Share & Multi-User Distribute Dialog ──
  const playlistShareDialog = document.getElementById('playlistShareDialog');
  const shareModeLiveBtn = document.getElementById('shareModeLiveBtn');
  const shareModeDistributeBtn = document.getElementById('shareModeDistributeBtn');
  const shareLivePane = document.getElementById('shareLivePane');
  const shareDistributePane = document.getElementById('shareDistributePane');
  const shareVisibilitySelect = document.getElementById('shareVisibilitySelect');
  const sharePubEditWrap = document.getElementById('sharePubEditWrap');
  const sharePubEditCheck = document.getElementById('sharePubEditCheck');
  const shareMembersList = document.getElementById('shareMembersList');
  const distributeUsersList = document.getElementById('distributeUsersList');
  const distributeModeSelect = document.getElementById('distributeModeSelect');

  function setShareDialogTab(tab) {
    const isLive = tab === 'live';
    shareModeLiveBtn.classList.toggle('active', isLive);
    shareModeLiveBtn.setAttribute('aria-selected', isLive ? 'true' : 'false');
    shareModeDistributeBtn.classList.toggle('active', !isLive);
    shareModeDistributeBtn.setAttribute('aria-selected', !isLive ? 'true' : 'false');
    shareLivePane.hidden = !isLive;
    shareDistributePane.hidden = isLive;
  }

  shareModeLiveBtn.addEventListener('click', () => setShareDialogTab('live'));
  shareModeDistributeBtn.addEventListener('click', () => setShareDialogTab('distribute'));
  document.getElementById('closePlShareDialogBtn').addEventListener('click', () => closeDialog(playlistShareDialog));

  shareVisibilitySelect.addEventListener('change', () => {
    sharePubEditWrap.hidden = shareVisibilitySelect.value !== 'public';
  });

  document.getElementById('plShareSyncBtn').addEventListener('click', async () => {
    if (!currentPlaylistDetail) return;
    const pl = currentPlaylistDetail.playlist;
    const users = await ensureUsersLoaded();

    // Live Share Pane setup
    shareModeLiveBtn.hidden = !pl.can_manage;
    shareVisibilitySelect.value = pl.visibility || 'private';
    sharePubEditCheck.checked = Boolean(pl.public_editable);
    sharePubEditWrap.hidden = shareVisibilitySelect.value !== 'public';

    const existingMemberMap = new Map((pl.members || []).map((m) => [m.user_id, m.permission]));
    shareMembersList.innerHTML = '';
    const candidateMembers = users.filter((u) => u.id !== pl.owner_id);

    if (candidateMembers.length === 0) {
      shareMembersList.innerHTML = '<div class="share-empty-note">当前还没有其他成员账号，管理员可在「设置」中添加用户。</div>';
    } else {
      candidateMembers.forEach((u) => {
        const perm = existingMemberMap.get(u.id) || '';
        const row = document.createElement('div');
        row.className = 'share-user-row';
        row.dataset.userId = String(u.id);
        row.innerHTML = `
          <label class="checkbox-label share-user-check">
            <input type="checkbox" class="member-enable-cb" ${perm ? 'checked' : ''}>
            <span class="share-user-name">${esc(u.display_name)} <small>@${esc(u.username)}</small></span>
          </label>
          <select class="form-control form-control-sm member-perm-select" aria-label="${esc(u.display_name)} 的共享权限">
            <option value="viewer" ${perm !== 'editor' ? 'selected' : ''}>只读订阅</option>
            <option value="editor" ${perm === 'editor' ? 'selected' : ''}>协作编辑</option>
          </select>
        `;
        shareMembersList.appendChild(row);
      });
    }

    // Distribute Pane setup
    distributeUsersList.innerHTML = '';
    const distTargets = users.filter((u) => u.id !== currentUser.id || users.length === 1);
    if (distTargets.length === 0) {
      distributeUsersList.innerHTML = '<div class="share-empty-note">暂无其他用户可分发。</div>';
    } else {
      users.forEach((u) => {
        const isSelf = u.id === currentUser.id;
        const row = document.createElement('label');
        row.className = 'share-user-row checkbox-label';
        row.innerHTML = `
          <input type="checkbox" class="dist-user-cb" value="${u.id}" ${!isSelf && users.length === 2 ? 'checked' : ''}>
          <span class="share-user-name">${esc(u.display_name)} <small>@${esc(u.username)}${isSelf ? ' · 我自己（复制备份）' : ''}</small></span>
        `;
        distributeUsersList.appendChild(row);
      });
    }

    setShareDialogTab(pl.can_manage ? 'live' : 'distribute');
    openDialog(playlistShareDialog);
  });

  document.getElementById('distributeSelectAllBtn').addEventListener('click', () => {
    distributeUsersList.querySelectorAll('.dist-user-cb').forEach((cb) => {
      if (parseInt(cb.value, 10) !== currentUser.id) {
        cb.checked = true;
      }
    });
  });

  document.getElementById('saveShareSettingsBtn').addEventListener('click', async () => {
    if (!currentPlaylistDetail) return;
    const pl = currentPlaylistDetail.playlist;
    const members = [];
    shareMembersList.querySelectorAll('.share-user-row').forEach((row) => {
      const cb = row.querySelector('.member-enable-cb');
      const sel = row.querySelector('.member-perm-select');
      if (cb && cb.checked) {
        members.push({
          user_id: parseInt(row.dataset.userId, 10),
          permission: sel ? sel.value : 'viewer',
        });
      }
    });

    try {
      await API.updatePlaylistSharing(pl.id, {
        visibility: shareVisibilitySelect.value,
        public_editable: shareVisibilitySelect.value === 'public' && sharePubEditCheck.checked,
        members,
      });
      closeDialog(playlistShareDialog);
      UI.showToast('共享权限已更新并实时同步', 'success');
      await openPlaylistDetail(pl.id, { silent: true });
      loadPlaylists();
    } catch (err) {
      UI.showToast(err.message || '保存共享设置失败', 'error');
    }
  });

  document.getElementById('runDistributeBtn').addEventListener('click', async () => {
    if (!currentPlaylistDetail) return;
    const pl = currentPlaylistDetail.playlist;
    const targetIds = Array.from(distributeUsersList.querySelectorAll('.dist-user-cb:checked'))
      .map((cb) => parseInt(cb.value, 10));

    if (targetIds.length === 0) {
      UI.showToast('请至少勾选一位接收用户', 'warning');
      return;
    }

    try {
      const res = await API.distributePlaylist(pl.id, targetIds, distributeModeSelect.value);
      closeDialog(playlistShareDialog);
      const cLen = (res.created || []).length;
      const sLen = (res.synced || []).length;
      UI.showToast(`分发完成：新建 ${cLen} 份歌单，同步更新 ${sLen} 份歌单`, 'success');
      loadPlaylists();
    } catch (err) {
      UI.showToast(err.message || '分发歌单失败', 'error');
    }
  });

  // ── Source Filter Chips ──
  const searchSourceChips = document.getElementById('searchSourceChips');

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
    allSources.forEach((s) => {
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
    allSources.forEach((s) => selectedSearchSources.add(s.id));
    renderSourceChips();
  });
  document.getElementById('clearAllSources').addEventListener('click', () => {
    selectedSearchSources.clear();
    renderSourceChips();
  });
  document.getElementById('presetDefaultSources').addEventListener('click', () => {
    selectedSearchSources.clear();
    ['MiguMusicClient', 'KuwoMusicClient', 'NeteaseMusicClient'].forEach((id) => selectedSearchSources.add(id));
    renderSourceChips();
  });

  // ── Search Logic (SSE) ──
  const globalSearchInput = document.getElementById('globalSearchInput');
  const searchResultsList = document.getElementById('searchResultsList');
  const searchAlbumStrip = document.getElementById('searchAlbumStrip');
  const searchTableHeader = document.getElementById('searchTableHeader');
  const searchEmptyState = document.getElementById('searchEmptyState');
  const searchProgressBar = document.getElementById('searchProgressBar');
  const searchProgressText = document.getElementById('searchProgressText');

  document.getElementById('globalSearchForm').addEventListener('submit', (e) => {
    e.preventDefault();
    doSearch();
  });

  function doSearch() {
    const query = globalSearchInput.value.trim();
    if (!query) {
      UI.showToast('请输入搜索关键词或歌名', 'warning');
      return;
    }

    if (query.startsWith('http://') || query.startsWith('https://')) {
      const albumLink = albumTargetFromUrl(query);
      if (albumLink) {
        downloadWholeAlbum(albumLink.source, albumLink.albumId, '这张专辑');
        return;
      }
      document.getElementById('playlistUrlInput').value = query;
      showPlaylistCollectionView();
      switchTab('playlist');
      setUrlParserOpen(true);
      startParsePlaylist();
      return;
    }

    switchTab('search');

    if (currentSearchSSE) {
      currentSearchSSE.close();
      currentSearchSSE = null;
    }

    searchResultsList.innerHTML = '';
    searchAlbumStrip.innerHTML = '';
    searchAlbumStrip.hidden = true;
    searchEmptyState.style.display = 'none';
    searchTableHeader.style.display = 'grid';
    searchProgressBar.style.display = 'flex';
    searchProgressText.textContent = `正在从 ${selectedSearchSources.size} 个音源并发搜索 "${query}"...`;

    const sourcesArr = Array.from(selectedSearchSources);
    let resultCount = 0;
    const seenAlbums = new Map();

    currentSearchSSE = API.searchStream(query, sourcesArr, {
      onSourceStart(data) {
        searchProgressText.textContent = `音源 [${data.label}] 已发起搜索...`;
      },
      onResult(track) {
        resultCount++;
        const row = UI.createTrackRow(track, {
          onPlay: (t) => player.playTrack(t),
          onAddToPlaylist: (t, btn) => openAddToPlaylistPopover(t, btn),
          onAddToQueue: (t) => appendTrackToQueue(t),
          onDownload: (t) => triggerDownload(t),
        });
        searchResultsList.appendChild(row);
        noteSearchAlbum(track, seenAlbums);
        markPlayingRow();
      },
      onSourceDone(data) {
        if (data.timed_out) {
          console.warn(`Source ${data.source} timed out.`);
        }
      },
      onDone() {
        searchProgressBar.style.display = 'none';
        if (resultCount === 0) {
          searchEmptyState.style.display = 'flex';
          searchTableHeader.style.display = 'none';
          searchEmptyState.querySelector('h2').textContent = '没有找到这首歌';
          searchEmptyState.querySelector('p').textContent = '请尝试更换关键词或勾选更多音源。';
        } else {
          UI.showToast(`搜索完成，共检索到 ${resultCount} 首曲目`, 'success');
        }
      },
      onError() {
        searchProgressBar.style.display = 'none';
        UI.showToast('搜索连接断开或超时', 'error');
      }
    });
  }

  function albumTargetFromUrl(raw) {
    let url;
    try { url = new URL(raw); } catch (_) { return null; }
    const host = url.hostname.toLowerCase();
    const blob = `${url.pathname} ${url.hash}`;
    if (host.includes('163.com') && blob.includes('album')) {
      const fromQuery = url.searchParams.get('id') || new URLSearchParams(url.hash.split('?')[1] || '').get('id');
      const fromPath = (url.pathname.match(/album\/(\d+)/) || [])[1];
      const albumId = fromQuery || fromPath;
      if (albumId) return { source: 'NeteaseMusicClient', albumId };
    }
    if (host.includes('qq.com') && /album/i.test(blob)) {
      const parts = url.pathname.split('/').filter(Boolean);
      const albumId = parts[parts.length - 1];
      if (albumId && !/album/i.test(albumId)) return { source: 'QQMusicClient', albumId };
    }
    if (host.includes('kuwo.cn') && url.pathname.includes('album')) {
      const parts = url.pathname.split('/').filter(Boolean);
      const albumId = parts[parts.length - 1];
      if (/^\d+$/.test(albumId)) return { source: 'KuwoMusicClient', albumId };
    }
    if (host.includes('kugou.com') && url.pathname.includes('album')) {
      const parts = url.pathname.split('/').filter(Boolean);
      const albumId = (parts[parts.length - 1] || '').replace(/\..*$/, '');
      if (/^\d+$/.test(albumId)) return { source: 'KugouMusicClient', albumId };
    }
    if (host.includes('migu.cn') && /album/i.test(blob)) {
      const albumId = url.searchParams.get('albumId') || url.searchParams.get('id');
      if (albumId) return { source: 'MiguMusicClient', albumId };
    }
    return null;
  }

  function noteSearchAlbum(track, seenAlbums) {
    if (!track.album) return;
    const key = track.album_id
      ? `${track.source}:${track.album_id}`
      : `name:${track.source}:${track.album}:${track.singers || ''}`;
    let card = seenAlbums.get(key);
    if (!card) {
      card = document.createElement('article');
      card.className = 'album-card';
      const cover = track.cover_url || COVER_FALLBACK;
      const canDownload = Boolean(track.album_downloadable && track.album_id);
      card.innerHTML = `
        <img src="${esc(cover)}" alt="" loading="lazy">
        <div>
          <h3 title="${esc(track.album)}">${esc(track.album)}</h3>
          <p>${esc(track.singers)} · ${esc(track.source_short || track.source_label || '')}</p>
          ${canDownload ? '<button class="btn" type="button">下载整张专辑</button>' : '<p>没有专辑编号，不能整张下载</p>'}
        </div>
      `;
      if (canDownload) {
        card.querySelector('button').addEventListener('click', () => {
          downloadWholeAlbum(track.source, track.album_id, track.album);
        });
      }
      seenAlbums.set(key, card);
      searchAlbumStrip.hidden = false;
      searchAlbumStrip.appendChild(card);
    }
  }

  function downloadWholeAlbum(source, albumId, name) {
    let saved = 0;
    UI.showToast(`正在解析专辑「${name}」`, 'info');
    API.parseAlbumStream(source, albumId, {
      onStart(data) {
        UI.showToast(`专辑共 ${data.count} 首，开始加入下载`, 'info');
      },
      onTrack(track) {
        saved += 1;
        API.startDownload(track.token).catch(() => {});
      },
      onDone(data) {
        UI.showToast(`已加入 ${data.count || saved} 首`, 'success');
        switchTab('downloads');
      },
      onError(err) {
        UI.showToast(err.message || '整张专辑解析失败', 'error');
      },
    });
  }

  // ── External Playlist URL Parser ──
  const startParsePlaylistBtn = document.getElementById('startParsePlaylistBtn');
  const playlistUrlInput = document.getElementById('playlistUrlInput');
  const playlistSourceSelect = document.getElementById('playlistSourceSelect');
  const playlistResultsList = document.getElementById('playlistResultsList');
  const playlistActionsBar = document.getElementById('playlistActionsBar');
  const playlistStatsText = document.getElementById('playlistStatsText');
  const playlistBatchDownloadBtn = document.getElementById('playlistBatchDownloadBtn');
  const saveParsedAsPlaylistBtn = document.getElementById('saveParsedAsPlaylistBtn');

  startParsePlaylistBtn.addEventListener('click', startParsePlaylist);

  function startParsePlaylist() {
    const url = playlistUrlInput.value.trim();
    if (!url) {
      UI.showToast('请输入歌单或分享链接', 'warning');
      return;
    }

    playlistResultsList.innerHTML = '';
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
          onAddToPlaylist: (t, btn) => openAddToPlaylistPopover(t, btn),
          onAddToQueue: (t) => appendTrackToQueue(t),
          onDownload: (t) => triggerDownload(t),
        });
        playlistResultsList.appendChild(row);
        markPlayingRow();
      },
      onDone() {
        playlistStatsText.textContent = `歌单解析完成，共 ${activePlaylistTracks.length} 首`;
        UI.showToast(`歌单解析成功 (${activePlaylistTracks.length} 首)`, 'success');
      },
      onError(err) {
        UI.showToast(err.message || '歌单解析失败，请检查链接或 Cookie', 'error');
      }
    });
  }

  saveParsedAsPlaylistBtn.addEventListener('click', (e) => {
    if (activePlaylistTracks.length === 0) {
      UI.showToast('当前没有解析出的曲目', 'warning');
      return;
    }
    openAddToPlaylistPopover(activePlaylistTracks, e.currentTarget);
  });

  playlistBatchDownloadBtn.addEventListener('click', async () => {
    if (activePlaylistTracks.length === 0) {
      UI.showToast('当前没有解析出的曲目', 'warning');
      return;
    }
    UI.showToast(`已为 ${activePlaylistTracks.length} 首歌曲发起批量下载`, 'info');
    for (const t of activePlaylistTracks) {
      await API.startDownload(t.token).catch(() => {});
    }
    switchTab('downloads');
  });

  // ── Download Trigger & Progress Stream ──
  async function triggerDownload(track) {
    let token = track.token;
    if (!token) {
      try {
        UI.showToast(`正在解析「${track.song_name}」下载地址…`, 'info');
        const resolved = await API.resolveTrack(track);
        if (resolved.is_local) {
          UI.showToast('该曲目已存在于本地曲库中', 'info');
          if (currentPlaylistId) openPlaylistDetail(currentPlaylistId, { silent: true });
          return;
        }
        token = resolved.token;
        track.token = token;
      } catch (err) {
        UI.showToast(err.message || '无法解析下载地址', 'error');
        return;
      }
    }

    try {
      const res = await API.startDownload(token);
      if (res.download_id) {
        UI.showToast(`已添加下载任务: ${track.song_name}`, 'success');
        const badge = document.getElementById('downloadBadge');
        badge.style.display = 'inline-block';
      }
    } catch (err) {
      UI.showToast(err.message || '发起下载失败', 'error');
    }
  }

  const downloadsActiveList = document.getElementById('downloadsActiveList');
  const downloadsEmptyState = document.getElementById('downloadsEmptyState');
  const downloadsCountText = document.getElementById('downloadsCountText');
  const downloadBadge = document.getElementById('downloadBadge');

  function connectDownloadsStream() {
    if (downloadsSSE) downloadsSSE.close();
    downloadsSSE = API.listenDownloads((tasks) => {
      downloadsCountText.textContent = `${tasks.length} 个任务`;
      const running = tasks.filter((t) => ['pending', 'downloading', 'tagging'].includes(t.status));

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

      tasks.forEach((dl) => {
        const card = UI.renderDownloadCard(dl, async (id) => {
          await API.cancelDownload(id).catch(() => {});
          UI.showToast('已取消下载', 'info');
        });
        downloadsActiveList.appendChild(card);
      });
    });
  }

  function connectUserEventsStream() {
    if (userEventsSSE) userEventsSSE.close();
    userEventsSSE = API.listenEvents({
      onConnected() {
        syncStatusDot.classList.add('is-online');
        acctSyncStatus.textContent = '实时同步已连接';
      },
      onError() {
        syncStatusDot.classList.remove('is-online');
        acctSyncStatus.textContent = '同步重连中…';
      },
      onPlaylistChanged(evt) {
        loadPlaylists();
        if (!currentPlaylistId) return;
        if (evt.action === 'deleted' && evt.playlist_id === currentPlaylistId) {
          UI.showToast('当前歌单已被删除', 'info');
          showPlaylistCollectionView();
        } else if (
          evt.playlist_id === currentPlaylistId &&
          (evt.client_id !== API.clientId || evt.action === 'track_downloaded')
        ) {
          openPlaylistDetail(currentPlaylistId, { silent: true });
        }
      },
      onQueueChanged(evt) {
        if (evt.client_id !== API.clientId && evt.state) {
          applyRemotePlaybackState(evt.state, false);
        }
      },
      onLibraryChanged() {
        loadLibrary();
        loadPlaylists();
        if (currentPlaylistId) {
          openPlaylistDetail(currentPlaylistId, { silent: true });
        }
      },
    });
  }

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
    rows.forEach((r) => {
      const text = r.textContent.toLowerCase();
      r.style.display = text.includes(q) ? 'grid' : 'none';
    });
  });

  async function loadLibrary() {
    if (!currentUser) return;
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
      const isAdmin = currentUser?.role === 'admin';

      tracks.forEach((track) => {
        const row = UI.createTrackRow(track, {
          isLibrary: true,
          canDeleteFile: isAdmin,
          onPlay: (t) => player.playTrack(t),
          onAddToPlaylist: (t, btn) => openAddToPlaylistPopover(t, btn),
          onAddToQueue: (t) => appendTrackToQueue(t),
          onDelete: async (t) => {
            if (confirm(`确定要从服务器磁盘彻底删除 "${t.song_name}" 吗？`)) {
              await API.deleteLibraryTrack(t.rel_path);
              UI.showToast('文件已删除', 'info');
              loadLibrary();
            }
          }
        });
        libraryTracksList.appendChild(row);
      });
      markPlayingRow();
    } catch (e) {
      console.error('Failed to load library:', e);
    }
  }

  // ── Settings & Admin User Management ──
  const cfgDownloadDir = document.getElementById('cfgDownloadDir');
  const cfgSearchSize = document.getElementById('cfgSearchSize');
  const cfgTimeout = document.getElementById('cfgTimeout');
  const cfgEmbedCover = document.getElementById('cfgEmbedCover');
  const cfgEmbedLyrics = document.getElementById('cfgEmbedLyrics');
  const cfgProxy = document.getElementById('cfgProxy');
  const cfgAllowRegistration = document.getElementById('cfgAllowRegistration');
  const saveSettingsBtn = document.getElementById('saveSettingsBtn');
  const settingsSourcesMatrix = document.getElementById('settingsSourcesMatrix');
  const adminUsersCard = document.getElementById('adminUsersCard');
  const adminUsersList = document.getElementById('adminUsersList');
  const memberAccountCard = document.getElementById('memberAccountCard');
  const adminStorageCard = document.getElementById('adminStorageCard');
  const adminNetworkCard = document.getElementById('adminNetworkCard');
  const adminSourcesCard = document.getElementById('adminSourcesCard');
  const adminSettingsActions = document.getElementById('adminSettingsActions');

  function renderSettingsSourcesMatrix() {
    settingsSourcesMatrix.innerHTML = '';
    allSources.forEach((s) => {
      const card = document.createElement('label');
      card.className = 'source-checkbox-card';
      const isChecked = selectedSearchSources.has(s.id);

      card.innerHTML = `
        <input type="checkbox" value="${esc(s.id)}" ${isChecked ? 'checked' : ''}>
        <div class="source-card-info">
          <h4>${esc(s.label)} <small class="source-cat">${esc(s.category_label)}</small></h4>
          <p>${esc(s.desc)}</p>
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

  async function loadAdminUsers() {
    if (currentUser?.role !== 'admin') return;
    try {
      const data = await API.getUsers();
      allUsersCache = data.users || [];
      adminUsersList.innerHTML = '';

      allUsersCache.forEach((u) => {
        const row = document.createElement('div');
        row.className = 'user-admin-row';
        const initial = Array.from(u.display_name || u.username || 'U')[0].toUpperCase();
        const isSelf = u.id === currentUser.id;
        row.innerHTML = `
          <div class="user-admin-main">
            <span class="user-avatar" aria-hidden="true">${esc(initial)}</span>
            <div class="user-admin-meta">
              <div class="user-admin-title">
                <strong>${esc(u.display_name)}</strong>
                <span class="user-handle">@${esc(u.username)}</span>
                <span class="badge-tag ${u.role === 'admin' ? 'role-admin-tag' : ''}">${u.role === 'admin' ? '管理员' : '成员'}</span>
              </div>
              <span class="user-submeta">${u.playlist_count ?? 0} 张自建歌单${isSelf ? ' · 当前登录' : ''}</span>
            </div>
          </div>
          <div class="user-admin-actions">
            <button class="btn btn-sm btn-create-pl-for" type="button">代建歌单</button>
            <button class="btn btn-sm btn-edit-user" type="button">编辑</button>
            ${!isSelf ? '<button class="btn btn-sm btn-danger-outline btn-del-user" type="button">删除</button>' : ''}
          </div>
        `;

        row.querySelector('.btn-create-pl-for').addEventListener('click', () => {
          openPlaylistEditor({ presetOwnerId: u.id });
        });
        row.querySelector('.btn-edit-user').addEventListener('click', () => {
          openUserAdminDialog(u);
        });
        row.querySelector('.btn-del-user')?.addEventListener('click', async () => {
          if (!confirm(`确定要删除用户 "${u.display_name} (@${u.username})" 及其名下私有歌单吗？`)) return;
          try {
            await API.deleteUser(u.id);
            UI.showToast(`已删除用户 @${u.username}`, 'info');
            loadAdminUsers();
            loadPlaylists();
          } catch (err) {
            UI.showToast(err.message || '删除用户失败', 'error');
          }
        });

        adminUsersList.appendChild(row);
      });
    } catch (err) {
      console.error('Failed to load users:', err);
    }
  }

  cfgAllowRegistration.addEventListener('change', async () => {
    try {
      await API.saveConfig({ allow_registration: cfgAllowRegistration.checked });
      UI.showToast(
        cfgAllowRegistration.checked ? '已开启登录页自助注册' : '已关闭登录页自助注册',
        'success'
      );
    } catch (err) {
      cfgAllowRegistration.checked = !cfgAllowRegistration.checked;
      UI.showToast(err.message || '保存失败', 'error');
    }
  });

  // Admin User Create/Edit Dialog
  const userFormDialog = document.getElementById('userFormDialog');
  const userDialogTitle = document.getElementById('userDialogTitle');
  const userFormUsernameGroup = document.getElementById('userFormUsernameGroup');
  const userFormUsername = document.getElementById('userFormUsername');
  const userFormDisplayName = document.getElementById('userFormDisplayName');
  const userFormRole = document.getElementById('userFormRole');
  const userFormPassword = document.getElementById('userFormPassword');
  const userFormPasswordHint = document.getElementById('userFormPasswordHint');
  let _editingUserId = null;

  function openUserAdminDialog(user = null) {
    _editingUserId = user ? user.id : null;
    userDialogTitle.textContent = user ? `管理用户 @${user.username}` : '添加新成员';
    userFormUsernameGroup.hidden = Boolean(user);
    userFormUsername.required = !user;
    userFormUsername.value = user ? user.username : '';
    userFormDisplayName.value = user ? user.display_name : '';
    userFormRole.value = user ? user.role : 'user';
    userFormPassword.value = '';
    userFormPassword.required = !user;
    userFormPasswordHint.hidden = !user;
    openDialog(userFormDialog);
    setTimeout(() => (user ? userFormDisplayName : userFormUsername).focus(), 40);
  }

  document.getElementById('openCreateUserBtn').addEventListener('click', () => openUserAdminDialog(null));
  document.getElementById('closeUserDialogBtn').addEventListener('click', () => closeDialog(userFormDialog));
  document.getElementById('cancelUserDialogBtn').addEventListener('click', () => closeDialog(userFormDialog));

  document.getElementById('userAdminForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      if (_editingUserId) {
        const payload = {
          display_name: userFormDisplayName.value.trim(),
          role: userFormRole.value,
        };
        if (userFormPassword.value) {
          payload.password = userFormPassword.value;
        }
        const res = await API.updateUser(_editingUserId, payload);
        if (_editingUserId === currentUser.id) {
          currentUser = res.user;
          updateUserHeaderUI();
        }
        UI.showToast('用户信息已更新', 'success');
      } else {
        await API.createUser({
          username: userFormUsername.value.trim(),
          display_name: userFormDisplayName.value.trim(),
          role: userFormRole.value,
          password: userFormPassword.value,
        });
        UI.showToast('新用户已创建', 'success');
      }
      closeDialog(userFormDialog);
      loadAdminUsers();
    } catch (err) {
      UI.showToast(err.message || '保存用户失败', 'error');
    }
  });

  async function loadSettings() {
    if (!currentUser) return;
    const isAdmin = currentUser.role === 'admin';
    adminUsersCard.hidden = !isAdmin;
    memberAccountCard.hidden = isAdmin;
    adminStorageCard.hidden = !isAdmin;
    adminNetworkCard.hidden = !isAdmin;
    adminSourcesCard.hidden = !isAdmin;
    adminSettingsActions.hidden = !isAdmin;
    document.getElementById('settingsIntroDesc').textContent = isAdmin
      ? '管理用户账号、下载存储、网络代理与默认检索音源。'
      : '管理个人账号信息与多设备同步状态。';

    appConfig = await API.getConfig();
    if (isAdmin) {
      cfgDownloadDir.value = appConfig.download_dir || '';
      cfgSearchSize.value = appConfig.search_size_per_source || 8;
      cfgTimeout.value = appConfig.per_source_timeout || 25;
      cfgEmbedCover.checked = appConfig.embed_cover !== false;
      cfgEmbedLyrics.checked = appConfig.embed_lyrics !== false;
      cfgProxy.value = appConfig.proxy || '';
      cfgAllowRegistration.checked = Boolean(appConfig.allow_registration);
      loadAdminUsers();
    }

    const sys = await API.getSystemInfo();
    if (sys.version) {
      document.getElementById('appVersion').textContent = `v${sys.version}`;
    }
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
      allow_registration: cfgAllowRegistration.checked,
      active_sources: Array.from(selectedSearchSources),
    };

    try {
      await API.saveConfig(updated);
      UI.showToast('系统配置已保存并生效', 'success');
    } catch (err) {
      UI.showToast(err.message || '保存配置失败', 'error');
    }
  });

  // ── Enter Authenticated Session ──
  async function enterAuthenticatedApp(user) {
    currentUser = user;
    authOverlay.hidden = true;
    document.body.classList.remove('auth-locked');
    updateUserHeaderUI();

    connectDownloadsStream();
    connectUserEventsStream();

    await Promise.all([
      initSources(),
      loadPlaylists(),
      loadLibrary(),
      loadSettings(),
      restorePlaybackState(),
    ]);
  }

  // ── Boot ──
  try {
    const me = await API.getAuthMe();
    authState.needsSetup = Boolean(me.needs_setup);
    authState.allowRegistration = Boolean(me.allow_registration);
    if (me.authenticated && me.user) {
      await enterAuthenticatedApp(me.user);
    } else {
      showAuthOverlay({
        needsSetup: authState.needsSetup,
        allowRegistration: authState.allowRegistration,
      });
    }
  } catch (err) {
    console.error('Boot check failed:', err);
    showAuthOverlay({ needsSetup: false, allowRegistration: false });
  }
});
