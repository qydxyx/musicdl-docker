// ── Full-Featured Audio Player with Web Audio Visualizer, Auto-Resolve & Sync ──
class AudioPlayer {
  constructor(audioEl, visualizerCanvas) {
    this.audio = audioEl;
    this.canvas = visualizerCanvas;
    this.ctx = visualizerCanvas ? visualizerCanvas.getContext('2d') : null;

    this.queue = [];
    this.currentIndex = -1;
    this.modes = ['loop', 'single', 'shuffle'];
    this.modeIndex = 0;

    this.audioCtx = null;
    this.analyser = null;
    this.audioSource = null;
    this.isVisualizerInit = false;

    this.onTrackChange = null;
    this.onTimeUpdate = null;
    this.onStateMutate = null;
    this._loadSeq = 0;

    this.initAudioEvents();
    this.initKeyboardShortcuts();
    this.initVolume();
  }

  get playMode() {
    return this.modes[this.modeIndex] || 'loop';
  }

  setPlayMode(mode, silent = false) {
    const idx = this.modes.indexOf(mode);
    if (idx === -1) return;
    this.modeIndex = idx;
    const btn = document.getElementById('btnMode');
    if (btn) {
      const titles = { loop: '列表循环', single: '单曲循环', shuffle: '随机播放' };
      btn.title = `播放模式: ${titles[mode]}`;
      if (!silent) UI.showToast(`切换为: ${titles[mode]}`, 'info');
    }
  }

  notifyStateMutate() {
    if (typeof this.onStateMutate === 'function') {
      this.onStateMutate(this.serializeState());
    }
  }

  serializeState() {
    return {
      queue: this.queue.map((t) => ({
        token: t.token || '',
        rel_path: t.rel_path || '',
        has_cover: Boolean(t.has_cover),
        source: t.source || '',
        source_label: t.source_label || '',
        source_short: t.source_short || '',
        song_id: t.song_id || '',
        song_name: t.song_name || '',
        singers: t.singers || '',
        album: t.album || '',
        ext: t.ext || 'mp3',
        duration: t.duration || '',
        file_size: t.file_size || '',
        cover_url: t.cover_url || '',
        lossless: Boolean(t.lossless),
      })),
      current_index: this.currentIndex,
      play_mode: this.playMode,
      position_sec: Number.isFinite(this.audio.currentTime) ? Math.floor(this.audio.currentTime) : 0,
    };
  }

  initAudioEvents() {
    this.audio.addEventListener('timeupdate', () => {
      if (this.onTimeUpdate) {
        this.onTimeUpdate(this.audio.currentTime, this.audio.duration || 0);
      }
    });

    this.audio.addEventListener('ended', () => {
      this.handleTrackEnded();
    });

    this.audio.addEventListener('play', () => {
      this.initVisualizer();
      if (this.audioCtx && this.audioCtx.state === 'suspended') {
        this.audioCtx.resume();
      }
      this.updatePlayStateUI(true);
      this.updateMediaSessionState('playing');
    });

    this.audio.addEventListener('pause', () => {
      this.updatePlayStateUI(false);
      this.updateMediaSessionState('paused');
      this.notifyStateMutate();
    });

    this.audio.addEventListener('error', async (e) => {
      if (!this.audio.getAttribute('src')) return;
      const track = this.queue[this.currentIndex];
      if (track && !track.rel_path && !track._retriedResolve) {
        track._retriedResolve = true;
        track.token = '';
        try {
          const resolved = await API.resolveTrack(track);
          Object.assign(track, resolved);
          await this.loadCurrentTrack(true, { skipMutate: true });
          return;
        } catch (resolveErr) {
          console.warn('Auto re-resolve failed:', resolveErr);
        }
      }
      console.error('Audio playback error:', e);
      UI.showToast('播放失败，音频地址可能已失效', 'error');
    });
  }

  initVisualizer() {
    if (this.isVisualizerInit || !this.ctx) return;
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) return;

      this.audioCtx = new AudioContext();
      this.analyser = this.audioCtx.createAnalyser();
      this.analyser.fftSize = 64;

      this.audioSource = this.audioCtx.createMediaElementSource(this.audio);
      this.audioSource.connect(this.analyser);
      this.analyser.connect(this.audioCtx.destination);

      this.isVisualizerInit = true;
      this.renderVisualizer();
    } catch (err) {
      console.warn('Web Audio API not supported or error:', err);
    }
  }

  renderVisualizer() {
    if (!this.analyser || !this.ctx) return;
    const bufferLength = this.analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    const draw = () => {
      requestAnimationFrame(draw);
      if (this.audio.paused) {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        return;
      }

      this.analyser.getByteFrequencyData(dataArray);
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

      const barWidth = (this.canvas.width / (bufferLength / 2)) * 1.5;
      let x = 0;

      for (let i = 0; i < bufferLength / 2; i++) {
        const barHeight = (dataArray[i] / 255) * this.canvas.height;
        const grad = this.ctx.createLinearGradient(0, this.canvas.height, 0, 0);
        grad.addColorStop(0, 'rgba(212, 160, 92, 0.28)');
        grad.addColorStop(1, 'rgba(212, 160, 92, 0.92)');

        this.ctx.fillStyle = grad;
        this.ctx.fillRect(x, this.canvas.height - barHeight, barWidth - 2, barHeight);
        x += barWidth;
      }
    };
    draw();
  }

  initVolume() {
    const saved = localStorage.getItem('musicdl_volume');
    const vol = saved !== null ? parseFloat(saved) : 0.8;
    this.setVolume(vol);
  }

  setVolume(val) {
    val = Math.max(0, Math.min(1, val));
    this.audio.volume = val;
    localStorage.setItem('musicdl_volume', val);
    const slider = document.getElementById('volumeSlider');
    if (slider) slider.value = val;
  }

  _isSameTrack(a, b) {
    if (!a || !b) return false;
    if (a.rel_path && b.rel_path && a.rel_path === b.rel_path) return true;
    if (a.token && b.token && a.token === b.token) return true;
    if (a.item_id && b.item_id && a.item_id === b.item_id) return true;
    if (a.song_name && b.song_name && a.song_name === b.song_name && (a.singers || '') === (b.singers || '') && !a.token && !b.token) {
      return true;
    }
    return false;
  }

  playTrack(track) {
    let idx = this.queue.findIndex((t) => this._isSameTrack(t, track));
    if (idx === -1) {
      this.queue.push(Object.assign({}, track));
      idx = this.queue.length - 1;
    } else {
      Object.assign(this.queue[idx], track);
    }
    this.currentIndex = idx;
    this.loadCurrentTrack(true);
  }

  replaceQueue(tracks, startIndex = 0, autoPlay = true) {
    this.queue = (tracks || []).map((t) => Object.assign({}, t));
    if (this.queue.length === 0) {
      this.currentIndex = -1;
      this.audio.pause();
      this.audio.removeAttribute('src');
      this.notifyStateMutate();
      return;
    }
    this.currentIndex = Math.max(0, Math.min(startIndex, this.queue.length - 1));
    this.loadCurrentTrack(autoPlay);
  }

  async loadCurrentTrack(autoPlay = true, opts = {}) {
    if (this.currentIndex < 0 || this.currentIndex >= this.queue.length) return;
    const seq = ++this._loadSeq;
    const track = this.queue[this.currentIndex];
    track._retriedResolve = false;

    if (this.onTrackChange) this.onTrackChange(track, this.currentIndex);

    if (!track.rel_path && !track.token) {
      try {
        const resolved = await API.resolveTrack(track);
        if (seq !== this._loadSeq) return;
        Object.assign(track, resolved);
        if (this.onTrackChange) this.onTrackChange(track, this.currentIndex);
      } catch (err) {
        if (seq !== this._loadSeq) return;
        UI.showToast(err.message || '无法解析该在线曲目', 'error');
        return;
      }
    }

    if (track.rel_path) {
      this.audio.src = `/api/library/stream/${encodeURIComponent(track.rel_path)}`;
    } else if (track.token) {
      this.audio.src = `/api/stream/${track.token}`;
    } else {
      return;
    }

    if (typeof opts.resumeSec === 'number' && opts.resumeSec > 0) {
      const targetSec = opts.resumeSec;
      const onLoaded = () => {
        if (this.audio.duration && targetSec < this.audio.duration) {
          this.audio.currentTime = targetSec;
        }
      };
      this.audio.addEventListener('loadedmetadata', onLoaded, { once: true });
    }

    if (autoPlay) {
      this.audio.play().catch((e) => console.warn('AutoPlay blocked:', e));
    }

    this.updateMediaSession(track);
    if (!opts.skipMutate) {
      this.notifyStateMutate();
    }
  }

  togglePlay() {
    if (this.audio.paused) {
      if (!this.audio.getAttribute('src') && this.queue.length > 0) {
        if (this.currentIndex < 0) this.currentIndex = 0;
        this.loadCurrentTrack(true);
      } else if (this.audio.getAttribute('src')) {
        this.audio.play();
      }
    } else {
      this.audio.pause();
    }
  }

  prev() {
    if (this.queue.length === 0) return;
    if (this.modes[this.modeIndex] === 'shuffle') {
      this.currentIndex = Math.floor(Math.random() * this.queue.length);
    } else {
      this.currentIndex = (this.currentIndex - 1 + this.queue.length) % this.queue.length;
    }
    this.loadCurrentTrack(true);
  }

  next() {
    if (this.queue.length === 0) return;
    if (this.modes[this.modeIndex] === 'shuffle') {
      this.currentIndex = Math.floor(Math.random() * this.queue.length);
    } else {
      this.currentIndex = (this.currentIndex + 1) % this.queue.length;
    }
    this.loadCurrentTrack(true);
  }

  handleTrackEnded() {
    const mode = this.modes[this.modeIndex];
    if (mode === 'single') {
      this.audio.currentTime = 0;
      this.audio.play();
    } else {
      this.next();
    }
  }

  toggleMode() {
    this.modeIndex = (this.modeIndex + 1) % this.modes.length;
    const mode = this.modes[this.modeIndex];
    this.setPlayMode(mode, false);
    this.notifyStateMutate();
    return mode;
  }

  seek(seconds) {
    if (this.audio.duration) {
      this.audio.currentTime = Math.max(0, Math.min(seconds, this.audio.duration));
    }
  }

  updatePlayStateUI(isPlaying) {
    const playIcon = document.querySelector('.icon-play');
    const pauseIcon = document.querySelector('.icon-pause');
    const coverWrap = document.getElementById('playerCoverWrapper');

    if (playIcon) playIcon.style.display = isPlaying ? 'none' : 'block';
    if (pauseIcon) pauseIcon.style.display = isPlaying ? 'block' : 'none';
    if (coverWrap) {
      if (isPlaying) coverWrap.classList.add('playing');
      else coverWrap.classList.remove('playing');
    }
  }

  // ── macOS & Browser MediaSession API ──
  updateMediaSession(track) {
    if (!('mediaSession' in navigator)) return;

    let artworkSrc = track.cover_url || '';
    if (track.rel_path && track.has_cover) {
      artworkSrc = `/api/library/cover/${encodeURIComponent(track.rel_path)}`;
    }

    navigator.mediaSession.metadata = new MediaMetadata({
      title: track.song_name || '未知曲目',
      artist: track.singers || '未知艺人',
      album: track.album || '',
      artwork: artworkSrc ? [{ src: artworkSrc, sizes: '300x300', type: 'image/jpeg' }] : []
    });

    navigator.mediaSession.setActionHandler('play', () => this.audio.play());
    navigator.mediaSession.setActionHandler('pause', () => this.audio.pause());
    navigator.mediaSession.setActionHandler('previoustrack', () => this.prev());
    navigator.mediaSession.setActionHandler('nexttrack', () => this.next());
    navigator.mediaSession.setActionHandler('seekto', (details) => {
      if (details.seekTime) this.seek(details.seekTime);
    });
  }

  updateMediaSessionState(state) {
    if ('mediaSession' in navigator) {
      navigator.mediaSession.playbackState = state;
    }
  }

  // ── Keyboard Shortcuts ──
  initKeyboardShortcuts() {
    window.addEventListener('keydown', (e) => {
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
        return;
      }
      if (document.querySelector('dialog[open]') || !document.getElementById('authOverlay')?.hidden) {
        return;
      }

      if (e.code === 'Space') {
        e.preventDefault();
        this.togglePlay();
      } else if (e.code === 'ArrowLeft') {
        e.preventDefault();
        this.seek(this.audio.currentTime - 5);
      } else if (e.code === 'ArrowRight') {
        e.preventDefault();
        this.seek(this.audio.currentTime + 5);
      } else if (e.code === 'ArrowUp') {
        e.preventDefault();
        this.setVolume(this.audio.volume + 0.05);
      } else if (e.code === 'ArrowDown') {
        e.preventDefault();
        this.setVolume(this.audio.volume - 0.05);
      } else if (e.code === 'BracketLeft') {
        this.prev();
      } else if (e.code === 'BracketRight') {
        this.next();
      } else if (e.code === 'KeyL') {
        const toggleBtn = document.getElementById('toggleLyricsBtn');
        if (toggleBtn) toggleBtn.click();
      }
    });
  }
}
