// ── UI Rendering & Component Helpers for musicdl-web ──
const UI = {
  esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[ch]));
  },

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
      toast.style.transition = 'opacity 0.22s ease, transform 0.22s ease';
      setTimeout(() => toast.remove(), 250);
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
    if (track.item_id) row.dataset.itemId = String(track.item_id);

    const fallbackSvg = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='44' height='44' viewBox='0 0 24 24' fill='%236b6258'%3E%3Cpath d='M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z'/%3E%3C/svg%3E";
    let coverSrc = track.cover_url || '';
    if (!coverSrc && track.rel_path && (track.has_cover || track.is_local)) {
      coverSrc = `/api/library/cover/${encodeURIComponent(track.rel_path)}`;
    }
    if (!coverSrc) coverSrc = fallbackSvg;

    const isLossless = track.lossless || ['flac', 'wav', 'ape'].includes((track.ext || '').toLowerCase());
    const qualityTag = isLossless
      ? '<span class="badge-tag lossless">FLAC 无损</span>'
      : `<span class="badge-tag">${UI.esc((track.ext || 'MP3').toUpperCase())}</span>`;

    const isLocalTrack = Boolean(options.isLibrary || track.is_local || track.rel_path);
    const sourceText = UI.esc(track.source_short || track.source_label || track.source || '本地');
    const sourceBadge = isLocalTrack && options.isPlaylist
      ? `<span class="badge-tag local-tag">本地已缓存</span>`
      : `<span class="badge-tag source-tag">${sourceText}</span>`;

    let actionButtonsHtml = `
      <button class="btn-icon-action btn-play-track" type="button" title="播放" aria-label="播放">
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M8 5v14l11-7z" fill="currentColor"/></svg>
      </button>
    `;

    if (options.onAddToPlaylist) {
      actionButtonsHtml += `
        <button class="btn-icon-action btn-fav-playlist" type="button" title="收藏到歌单" aria-label="收藏到歌单">
          <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z" stroke="currentColor" stroke-width="1.75" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>
      `;
    }

    if (options.isPlaylist) {
      if (isLocalTrack) {
        actionButtonsHtml += `
          <button class="btn-icon-action btn-download-file" type="button" title="导出音频到电脑" aria-label="导出音频到电脑">
            <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" stroke="currentColor" stroke-width="1.75" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
        `;
      } else if (options.onDownload) {
        actionButtonsHtml += `
          <button class="btn-icon-action btn-dl-track" type="button" title="下载到服务器曲库" aria-label="下载到服务器曲库">
            <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" stroke="currentColor" stroke-width="1.75" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
        `;
      }
      if (options.canEditPlaylist) {
        if (options.onMoveUp) {
          actionButtonsHtml += `
            <button class="btn-icon-action btn-move-up" type="button" title="上移" aria-label="上移">
              <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path d="M18 15l-6-6-6 6" stroke="currentColor" stroke-width="1.75" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </button>
          `;
        }
        if (options.onMoveDown) {
          actionButtonsHtml += `
            <button class="btn-icon-action btn-move-down" type="button" title="下移" aria-label="下移">
              <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path d="M6 9l6 6 6-6" stroke="currentColor" stroke-width="1.75" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </button>
          `;
        }
        if (options.onRemoveFromPlaylist) {
          actionButtonsHtml += `
            <button class="btn-icon-action btn-remove-pl-track text-danger" type="button" title="从歌单移除" aria-label="从歌单移除">
              <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="1.75" fill="none" stroke-linecap="round"/></svg>
            </button>
          `;
        }
      }
    } else if (options.isLibrary) {
      actionButtonsHtml += `
        <button class="btn-icon-action btn-queue-add" type="button" title="加入播放队列" aria-label="加入播放队列">
          <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="1.75" fill="none" stroke-linecap="round"/></svg>
        </button>
        <button class="btn-icon-action btn-download-file" type="button" title="下载到电脑" aria-label="下载到电脑">
          <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" stroke="currentColor" stroke-width="1.75" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>
      `;
      if (options.canDeleteFile) {
        actionButtonsHtml += `
          <button class="btn-icon-action btn-delete-track text-danger" type="button" title="从磁盘删除" aria-label="从磁盘删除">
            <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" stroke="currentColor" stroke-width="1.75" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
        `;
      }
    } else {
      actionButtonsHtml += `
        <button class="btn-icon-action btn-queue-add" type="button" title="加入播放队列" aria-label="加入播放队列">
          <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="1.75" fill="none" stroke-linecap="round"/></svg>
        </button>
        <button class="btn-icon-action btn-dl-track" type="button" title="下载并内嵌封面" aria-label="下载并内嵌封面">
          <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" stroke="currentColor" stroke-width="1.75" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>
      `;
    }

    row.innerHTML = `
      <div class="track-title-col">
        <img class="track-cover-mini" src="${UI.esc(coverSrc)}" alt="" loading="lazy">
        <div class="track-meta-wrap">
          <span class="track-name" title="${UI.esc(track.song_name)}">${UI.esc(track.song_name)}</span>
          <span class="track-singers" title="${UI.esc(track.singers)}">${UI.esc(track.singers)}</span>
        </div>
      </div>
      <div class="track-album" title="${UI.esc(track.album || '')}">${UI.esc(track.album || '—')}</div>
      <div class="track-duration">${UI.esc(track.duration || '—')}</div>
      <div class="track-size">${qualityTag}</div>
      <div class="track-source">${sourceBadge}</div>
      <div class="track-actions">${actionButtonsHtml}</div>
    `;

    const imgEl = row.querySelector('.track-cover-mini');
    imgEl.addEventListener('error', () => { imgEl.src = fallbackSvg; }, { once: true });

    row.addEventListener('dblclick', () => {
      if (options.onPlay) options.onPlay(track);
    });

    row.querySelector('.btn-play-track')?.addEventListener('click', (e) => {
      e.stopPropagation();
      if (options.onPlay) options.onPlay(track);
    });

    row.querySelector('.btn-fav-playlist')?.addEventListener('click', (e) => {
      e.stopPropagation();
      if (options.onAddToPlaylist) options.onAddToPlaylist(track, e.currentTarget);
    });

    row.querySelector('.btn-queue-add')?.addEventListener('click', (e) => {
      e.stopPropagation();
      if (options.onAddToQueue) options.onAddToQueue(track);
    });

    row.querySelector('.btn-dl-track')?.addEventListener('click', (e) => {
      e.stopPropagation();
      if (options.onDownload) options.onDownload(track);
    });

    row.querySelector('.btn-download-file')?.addEventListener('click', (e) => {
      e.stopPropagation();
      if (track.rel_path) {
        window.open(`/api/library/download/${encodeURIComponent(track.rel_path)}`, '_blank');
      }
    });

    row.querySelector('.btn-delete-track')?.addEventListener('click', (e) => {
      e.stopPropagation();
      if (options.onDelete) options.onDelete(track);
    });

    row.querySelector('.btn-move-up')?.addEventListener('click', (e) => {
      e.stopPropagation();
      if (options.onMoveUp) options.onMoveUp(track);
    });

    row.querySelector('.btn-move-down')?.addEventListener('click', (e) => {
      e.stopPropagation();
      if (options.onMoveDown) options.onMoveDown(track);
    });

    row.querySelector('.btn-remove-pl-track')?.addEventListener('click', (e) => {
      e.stopPropagation();
      if (options.onRemoveFromPlaylist) options.onRemoveFromPlaylist(track);
    });

    return row;
  },

  renderDownloadCard(dl, onCancel) {
    const card = document.createElement('div');
    card.className = 'dl-card';
    card.id = `dl-card-${dl.id}`;

    const percent = dl.total > 0 ? Math.min(100, Math.round((dl.downloaded / dl.total) * 100)) : 0;
    const speedStr = dl.speed > 0 ? `${(dl.speed / (1024 * 1024)).toFixed(2)} MB/s` : '';

    let statusLabel = '正在下载';
    if (dl.status === 'tagging') statusLabel = '写入封面与标签';
    else if (dl.status === 'done') statusLabel = dl.message || '下载完成';
    else if (dl.status === 'error') statusLabel = `失败：${dl.message || '未知错误'}`;
    else if (dl.status === 'cancelled') statusLabel = '已取消';
    else if (dl.status === 'pending') statusLabel = dl.message || '等待中';

    card.classList.add(`is-${dl.status || 'downloading'}`);
    card.innerHTML = `
      <div class="dl-card-header">
        <span class="dl-title" title="${UI.esc(dl.name)}">${UI.esc(dl.name || '未命名音频')}</span>
        <span class="dl-status-badge">${UI.esc(statusLabel)}</span>
      </div>
      <div class="dl-progress-bar">
        <div class="dl-progress-fill" style="width: ${percent}%;"></div>
      </div>
      <div class="dl-card-footer">
        <span>${UI.formatBytes(dl.downloaded)} / ${UI.formatBytes(dl.total)} (${percent}%)</span>
        <span>${speedStr}</span>
        ${dl.status === 'downloading' || dl.status === 'pending' ? `
          <button class="btn-text text-danger btn-cancel-dl" type="button">取消</button>
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
