// ── UI Rendering & Component Helpers for musicdl-web ──
const UI = {
  showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;

    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 3000);
  },

  formatTime(seconds) {
    if (!seconds || isNaN(seconds)) return '00:00';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  },

  formatBytes(bytes) {
    if (!bytes || bytes <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    while (bytes >= 1024 && i < units.length - 1) {
      bytes /= 1024;
      i++;
    }
    return `${bytes.toFixed(1)} ${units[i]}`;
  },

  createTrackRow(track, options = {}) {
    const row = document.createElement('div');
    row.className = 'track-row';
    row.dataset.token = track.token || '';
    row.dataset.path = track.rel_path || '';

    // Cover image
    let coverSrc = track.cover_url || '';
    if (!coverSrc && track.rel_path && track.has_cover) {
      coverSrc = `/api/library/cover/${encodeURIComponent(track.rel_path)}`;
    }
    if (!coverSrc) {
      coverSrc = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="%234b5563"%3E%3Cpath d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/%3E%3C/svg%3E';
    }

    const isLossless = track.lossless || ['flac', 'wav', 'ape'].includes((track.ext || '').toLowerCase());
    const qualityTag = isLossless ? '<span class="badge-tag lossless">FLAC 无损</span>' : `<span class="badge-tag">${(track.ext || 'MP3').toUpperCase()}</span>`;

    row.innerHTML = `
      <div class="track-title-col">
        <img class="track-cover-mini" src="${coverSrc}" alt="" loading="lazy" onerror="this.src='data:image/svg+xml,%3Csvg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'40\\' height=\\'40\\' viewBox=\\'0 0 24 24\\' fill=\\'%234b5563\\'%3E%3Cpath d=\\'M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z\\'/%3E%3C/svg%3E'">
        <div class="track-meta-wrap">
          <span class="track-name" title="${track.song_name}">${track.song_name}</span>
          <span class="track-singers" title="${track.singers}">${track.singers}</span>
        </div>
      </div>
      <div class="track-album" title="${track.album || ''}">${track.album || '—'}</div>
      <div class="track-duration">${track.duration || '—'}</div>
      <div class="track-size">${qualityTag}</div>
      <div class="track-source">
        <span class="badge-tag source-tag">${track.source_short || track.source_label || track.source || '本地'}</span>
      </div>
      <div class="track-actions">
        <button class="btn-icon-action btn-play-track" title="播放">
          <svg viewBox="0 0 24 24" width="16" height="16"><path d="M8 5v14l11-7z" fill="currentColor"/></svg>
        </button>
        ${options.isLibrary ? `
          <button class="btn-icon-action btn-download-file" title="下载到电脑">
            <svg viewBox="0 0 24 24" width="16" height="16"><path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" stroke="currentColor" stroke-width="2" fill="none"/></svg>
          </button>
          <button class="btn-icon-action btn-delete-track text-danger" title="删除">
            <svg viewBox="0 0 24 24" width="16" height="16"><path d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" stroke="currentColor" stroke-width="2" fill="none"/></svg>
          </button>
        ` : `
          <button class="btn-icon-action btn-queue-add" title="加入播放列表">
            <svg viewBox="0 0 24 24" width="16" height="16"><path d="M12 4v16m8-8H4" stroke="currentColor" stroke-width="2"/></svg>
          </button>
          <button class="btn-icon-action btn-dl-track" title="下载并内嵌封面">
            <svg viewBox="0 0 24 24" width="16" height="16"><path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" stroke="currentColor" stroke-width="2" fill="none"/></svg>
          </button>
        `}
      </div>
    `;

    // Row click play
    row.addEventListener('dblclick', () => {
      if (options.onPlay) options.onPlay(track);
    });

    row.querySelector('.btn-play-track').addEventListener('click', (e) => {
      e.stopPropagation();
      if (options.onPlay) options.onPlay(track);
    });

    if (options.isLibrary) {
      row.querySelector('.btn-download-file').addEventListener('click', (e) => {
        e.stopPropagation();
        window.open(`/api/library/download/${encodeURIComponent(track.rel_path)}`, '_blank');
      });
      row.querySelector('.btn-delete-track').addEventListener('click', (e) => {
        e.stopPropagation();
        if (options.onDelete) options.onDelete(track);
      });
    } else {
      row.querySelector('.btn-queue-add').addEventListener('click', (e) => {
        e.stopPropagation();
        if (options.onAddToQueue) options.onAddToQueue(track);
      });
      row.querySelector('.btn-dl-track').addEventListener('click', (e) => {
        e.stopPropagation();
        if (options.onDownload) options.onDownload(track);
      });
    }

    return row;
  },

  renderDownloadCard(dl, onCancel) {
    const card = document.createElement('div');
    card.className = 'dl-card';
    card.id = `dl-card-${dl.id}`;

    const percent = dl.total > 0 ? Math.min(100, Math.round((dl.downloaded / dl.total) * 100)) : 0;
    const speedStr = dl.speed > 0 ? `${(dl.speed / (1024 * 1024)).toFixed(2)} MB/s` : '';

    let statusLabel = '正在下载...';
    let statusColor = '#38bdf8';
    if (dl.status === 'tagging') {
      statusLabel = '写入封面与标签 (Mutagen)...';
      statusColor = '#a855f7';
    } else if (dl.status === 'done') {
      statusLabel = '下载完成';
      statusColor = '#22c55e';
    } else if (dl.status === 'error') {
      statusLabel = `失败: ${dl.message || '未知错误'}`;
      statusColor = '#ef4444';
    } else if (dl.status === 'cancelled') {
      statusLabel = '已取消';
      statusColor = '#94a3b8';
    }

    card.innerHTML = `
      <div class="dl-card-header">
        <span class="dl-title" title="${dl.name}">${dl.name || '未命名音频'}</span>
        <span class="dl-status-badge" style="color: ${statusColor}; font-size: 12px;">${statusLabel}</span>
      </div>
      <div class="dl-progress-bar">
        <div class="dl-progress-fill" style="width: ${percent}%;"></div>
      </div>
      <div class="dl-card-footer">
        <span>${UI.formatBytes(dl.downloaded)} / ${UI.formatBytes(dl.total)} (${percent}%)</span>
        <span>${speedStr}</span>
        ${dl.status === 'downloading' || dl.status === 'pending' ? `
          <button class="btn-text text-danger btn-cancel-dl">取消</button>
        ` : ''}
      </div>
    `;

    const cancelBtn = card.querySelector('.btn-cancel-dl');
    if (cancelBtn) {
      cancelBtn.addEventListener('click', () => onCancel(dl.id));
    }

    return card;
  }
};
