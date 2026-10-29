// ── API and SSE Client for musicdl-web ──
const CLIENT_ID = (typeof crypto !== 'undefined' && crypto.randomUUID)
  ? crypto.randomUUID()
  : `cid_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;

const API = {
  clientId: CLIENT_ID,
  onUnauthorized: null,

  async _request(url, options = {}) {
    const headers = Object.assign({ 'X-Client-ID': CLIENT_ID }, options.headers || {});
    if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(options.body);
    }
    const res = await fetch(url, Object.assign({}, options, { headers }));
    if (res.status === 401 && !url.startsWith('/api/auth/')) {
      if (typeof API.onUnauthorized === 'function') {
        API.onUnauthorized();
      }
      const errData = await res.json().catch(() => ({}));
      const err = new Error(errData.error || '登录已过期，请重新登录');
      err.status = 401;
      throw err;
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(data.error || `请求失败 (${res.status})`);
      err.status = res.status;
      throw err;
    }
    return data;
  },

  // ── Auth & Users ──
  async getAuthMe() {
    return await this._request('/api/auth/me');
  },

  async setupAdmin(username, password, displayName) {
    return await this._request('/api/auth/setup', {
      method: 'POST',
      body: { username, password, display_name: displayName },
    });
  },

  async login(username, password) {
    return await this._request('/api/auth/login', {
      method: 'POST',
      body: { username, password },
    });
  },

  async register(username, password, displayName) {
    return await this._request('/api/auth/register', {
      method: 'POST',
      body: { username, password, display_name: displayName },
    });
  },

  async logout() {
    return await this._request('/api/auth/logout', { method: 'POST' });
  },

  async updateOwnProfile(displayName) {
    return await this._request('/api/auth/profile', {
      method: 'PUT',
      body: { display_name: displayName },
    });
  },

  async changeOwnPassword(currentPassword, newPassword) {
    return await this._request('/api/auth/password', {
      method: 'PUT',
      body: { current_password: currentPassword, new_password: newPassword },
    });
  },

  async getUsers() {
    return await this._request('/api/users');
  },

  async createUser(payload) {
    return await this._request('/api/users', {
      method: 'POST',
      body: payload,
    });
  },

  async updateUser(userId, payload) {
    return await this._request(`/api/users/${userId}`, {
      method: 'PUT',
      body: payload,
    });
  },

  async deleteUser(userId) {
    return await this._request(`/api/users/${userId}`, {
      method: 'DELETE',
    });
  },

  // ── Playlists & Sync ──
  async getPlaylists() {
    return await this._request('/api/playlists');
  },

  async getPlaylistDetail(playlistId) {
    return await this._request(`/api/playlists/${encodeURIComponent(playlistId)}`);
  },

  async createPlaylist(payload) {
    return await this._request('/api/playlists', {
      method: 'POST',
      body: payload,
    });
  },

  async updatePlaylist(playlistId, payload) {
    return await this._request(`/api/playlists/${encodeURIComponent(playlistId)}`, {
      method: 'PUT',
      body: payload,
    });
  },

  async deletePlaylist(playlistId) {
    return await this._request(`/api/playlists/${encodeURIComponent(playlistId)}`, {
      method: 'DELETE',
    });
  },

  async leavePlaylist(playlistId) {
    return await this._request(`/api/playlists/${encodeURIComponent(playlistId)}/members/me`, {
      method: 'DELETE',
    });
  },

  async addTracksToPlaylist(playlistId, tracks) {
    const arr = Array.isArray(tracks) ? tracks : [tracks];
    return await this._request(`/api/playlists/${encodeURIComponent(playlistId)}/tracks`, {
      method: 'POST',
      body: { tracks: arr },
    });
  },

  async removeTrackFromPlaylist(playlistId, itemId) {
    return await this._request(`/api/playlists/${encodeURIComponent(playlistId)}/tracks/${itemId}`, {
      method: 'DELETE',
    });
  },

  async reorderPlaylistTracks(playlistId, itemIds) {
    return await this._request(`/api/playlists/${encodeURIComponent(playlistId)}/tracks/reorder`, {
      method: 'PUT',
      body: { item_ids: itemIds },
    });
  },

  async updatePlaylistSharing(playlistId, payload) {
    return await this._request(`/api/playlists/${encodeURIComponent(playlistId)}/share`, {
      method: 'PUT',
      body: payload,
    });
  },

  async distributePlaylist(playlistId, targetUserIds, mode = 'sync') {
    return await this._request(`/api/playlists/${encodeURIComponent(playlistId)}/distribute`, {
      method: 'POST',
      body: { target_user_ids: targetUserIds, mode },
    });
  },

  async downloadWholePlaylist(playlistId) {
    return await this._request(`/api/playlists/${encodeURIComponent(playlistId)}/download`, {
      method: 'POST',
    });
  },

  async resolveTrack(track) {
    return await this._request('/api/tracks/resolve', {
      method: 'POST',
      body: track,
    });
  },

  async getPlaybackState() {
    return await this._request('/api/me/playback');
  },

  async savePlaybackState(state) {
    return await this._request('/api/me/playback', {
      method: 'PUT',
      body: Object.assign({ client_id: CLIENT_ID }, state),
    });
  },

  listenEvents(handlers = {}) {
    const es = new EventSource(`/api/events?client_id=${encodeURIComponent(CLIENT_ID)}`);
    es.addEventListener('connected', (e) => {
      handlers.onConnected && handlers.onConnected(JSON.parse(e.data));
    });
    es.addEventListener('playlist_changed', (e) => {
      try {
        handlers.onPlaylistChanged && handlers.onPlaylistChanged(JSON.parse(e.data));
      } catch (_) {}
    });
    es.addEventListener('queue_changed', (e) => {
      try {
        handlers.onQueueChanged && handlers.onQueueChanged(JSON.parse(e.data));
      } catch (_) {}
    });
    es.addEventListener('library_changed', (e) => {
      try {
        handlers.onLibraryChanged && handlers.onLibraryChanged(JSON.parse(e.data));
      } catch (_) {}
    });
    es.onerror = (err) => {
      handlers.onError && handlers.onError(err);
    };
    return es;
  },

  // ── Core Music & Config Endpoints ──
  async getSources() {
    return await this._request('/api/sources');
  },

  async getConfig() {
    return await this._request('/api/config');
  },

  async saveConfig(cfg) {
    return await this._request('/api/config', {
      method: 'PUT',
      body: cfg,
    });
  },

  async getSystemInfo() {
    return await this._request('/api/system_info');
  },

  async getLibraryTracks() {
    return await this._request('/api/library/tracks');
  },

  async deleteLibraryTrack(relPath) {
    return await this._request(`/api/library/track/${encodeURIComponent(relPath)}`, {
      method: 'DELETE',
    });
  },

  async getLyric(token) {
    try {
      const data = await this._request(`/api/lyric/${token}`);
      return data.lyric || '';
    } catch (_) {
      return '';
    }
  },

  async getLocalLyric(relPath) {
    try {
      const data = await this._request(`/api/library/lyric/${encodeURIComponent(relPath)}`);
      return data.lyric || '';
    } catch (_) {
      return '';
    }
  },

  async startDownload(token) {
    return await this._request('/api/download', {
      method: 'POST',
      body: { token },
    });
  },

  async cancelDownload(downloadId) {
    return await this._request(`/api/download/cancel/${downloadId}`, {
      method: 'POST',
    });
  },

  // ── Streaming Search SSE ──
  searchStream(keyword, sources, callbacks) {
    const sourceParam = sources.length ? encodeURIComponent(sources.join(',')) : '';
    const url = `/api/search?q=${encodeURIComponent(keyword)}&sources=${sourceParam}`;
    const es = new EventSource(url);

    es.addEventListener('source_start', (e) => {
      callbacks.onSourceStart && callbacks.onSourceStart(JSON.parse(e.data));
    });

    es.addEventListener('result', (e) => {
      callbacks.onResult && callbacks.onResult(JSON.parse(e.data));
    });

    es.addEventListener('source_done', (e) => {
      callbacks.onSourceDone && callbacks.onSourceDone(JSON.parse(e.data));
    });

    es.addEventListener('source_error', (e) => {
      callbacks.onSourceError && callbacks.onSourceError(JSON.parse(e.data));
    });

    es.addEventListener('done', (e) => {
      callbacks.onDone && callbacks.onDone(JSON.parse(e.data));
      es.close();
    });

    es.onerror = (err) => {
      callbacks.onError && callbacks.onError(err);
      es.close();
    };

    return es;
  },

  // ── Playlist Parsing SSE ──
  parsePlaylistStream(playlistUrl, sourceHint, callbacks) {
    const controller = new AbortController();

    fetch('/api/parse_playlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Client-ID': CLIENT_ID },
      body: JSON.stringify({ url: playlistUrl, source: sourceHint }),
      signal: controller.signal,
    }).then(async (response) => {
      if (response.status === 401) {
        API.onUnauthorized && API.onUnauthorized();
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop();

        for (const evt of events) {
          const lines = evt.split('\n');
          let eventType = 'message';
          let dataStr = '';

          for (const line of lines) {
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith('data: ')) {
              dataStr = line.slice(6).trim();
            }
          }

          if (dataStr) {
            try {
              const data = JSON.parse(dataStr);
              if (eventType === 'playlist_start') callbacks.onStart && callbacks.onStart(data);
              else if (eventType === 'playlist_track') callbacks.onTrack && callbacks.onTrack(data);
              else if (eventType === 'playlist_done') callbacks.onDone && callbacks.onDone(data);
              else if (eventType === 'playlist_error') callbacks.onError && callbacks.onError(data);
              else if (eventType === 'playlist_empty') callbacks.onError && callbacks.onError(data);
            } catch (_) {}
          }
        }
      }
    }).catch((err) => {
      if (err.name !== 'AbortError') {
        callbacks.onError && callbacks.onError(err);
      }
    });

    return controller;
  },

  parseAlbumStream(source, albumId, callbacks) {
    const controller = new AbortController();
    fetch('/api/parse_album', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Client-ID': CLIENT_ID },
      body: JSON.stringify({ source, album_id: albumId }),
      signal: controller.signal,
    }).then(async (response) => {
      if (response.status === 401) {
        API.onUnauthorized && API.onUnauthorized();
        return;
      }
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        callbacks.onError && callbacks.onError(err);
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop();
        for (const evt of events) {
          const lines = evt.split('\n');
          let eventType = 'message';
          let dataStr = '';
          for (const line of lines) {
            if (line.startsWith('event: ')) eventType = line.slice(7).trim();
            else if (line.startsWith('data: ')) dataStr = line.slice(6).trim();
          }
          if (!dataStr) continue;
          try {
            const data = JSON.parse(dataStr);
            if (eventType === 'album_start') callbacks.onStart && callbacks.onStart(data);
            else if (eventType === 'album_track') callbacks.onTrack && callbacks.onTrack(data);
            else if (eventType === 'album_done') callbacks.onDone && callbacks.onDone(data);
            else if (eventType === 'album_error') callbacks.onError && callbacks.onError(data);
          } catch (_) {}
        }
      }
    }).catch((err) => {
      if (err.name !== 'AbortError') callbacks.onError && callbacks.onError(err);
    });
    return controller;
  },

  // ── Downloads Progress SSE ──
  listenDownloads(onUpdate) {
    const es = new EventSource('/api/download/progress');
    es.addEventListener('downloads', (e) => {
      try {
        const list = JSON.parse(e.data);
        onUpdate(list);
      } catch (_) {}
    });
    return es;
  }
};
