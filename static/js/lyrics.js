// ── Dynamic Synchronized Lyrics Engine for musicdl-web ──
class LyricsEngine {
  constructor(containerEl, onSeekCallback) {
    this.container = containerEl;
    this.onSeek = onSeekCallback;
    this.lines = []; // [{ time: 12.34, text: "xxx" }, ...]
    this.currentIndex = -1;
  }

  loadLRC(lrcText) {
    this.lines = [];
    this.currentIndex = -1;
    this.container.innerHTML = '';

    if (!lrcText || typeof lrcText !== 'string' || !lrcText.trim()) {
      this.container.innerHTML = '<div class="lyrics-empty">暂无同步歌词</div>';
      return;
    }

    const rawLines = lrcText.split(/\r?\n/);
    const timeReg = /\[(\d{1,2}):(\d{1,2})(?:\.(\d{1,3}))?\]/g;

    for (const raw of rawLines) {
      const text = raw.replace(timeReg, '').trim();
      let match;
      timeReg.lastIndex = 0;

      while ((match = timeReg.exec(raw)) !== null) {
        const mins = parseInt(match[1], 10);
        const secs = parseInt(match[2], 10);
        const msStr = match[3] || '0';
        const ms = msStr.length === 2 ? parseInt(msStr, 10) / 100 : parseInt(msStr, 10) / 1000;
        const totalSec = mins * 60 + secs + ms;

        if (text) {
          this.lines.push({ time: totalSec, text });
        }
      }
    }

    this.lines.sort((a, b) => a.time - b.time);

    if (this.lines.length === 0) {
      this.container.innerHTML = '<div class="lyrics-empty">纯音乐 / 暂无歌词文本</div>';
      return;
    }

    // Render DOM elements
    const frag = document.createDocumentFragment();
    this.lines.forEach((item, idx) => {
      const div = document.createElement('div');
      div.className = 'lyric-line';
      div.dataset.index = idx;
      div.dataset.time = item.time;
      div.textContent = item.text;
      div.addEventListener('click', () => {
        if (this.onSeek) this.onSeek(item.time);
      });
      frag.appendChild(div);
    });

    this.container.appendChild(frag);
  }

  sync(currentTime) {
    if (this.lines.length === 0) return;

    // Binary search for the active line index
    let low = 0;
    let high = this.lines.length - 1;
    let target = -1;

    while (low <= high) {
      const mid = Math.floor((low + high) / 2);
      if (this.lines[mid].time <= currentTime) {
        target = mid;
        low = mid + 1;
      } else {
        high = mid - 1;
      }
    }

    if (target === this.currentIndex) return;
    this.currentIndex = target;

    // Update active class
    const prevActive = this.container.querySelector('.lyric-line.active');
    if (prevActive) prevActive.classList.remove('active');

    if (target >= 0) {
      const activeEl = this.container.children[target];
      if (activeEl) {
        activeEl.classList.add('active');

        // Center scroll
        const containerHeight = this.container.clientHeight;
        const targetTop = activeEl.offsetTop - this.container.offsetTop;
        const scrollTop = targetTop - containerHeight / 2 + activeEl.clientHeight / 2;

        this.container.scrollTo({
          top: Math.max(0, scrollTop),
          behavior: 'smooth'
        });
      }
    }
  }

  clear() {
    this.lines = [];
    this.currentIndex = -1;
    this.container.innerHTML = '<div class="lyrics-empty">暂无歌词</div>';
  }
}
