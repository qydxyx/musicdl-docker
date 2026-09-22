// ── API and SSE Client for musicdl-web ──
const API = {
  async getSources() {
    const res = await fetch('/api/sources');
    return await res.json();
  },

  async getConfig() {
    const res = await fetch('/api/config');
    return await res.json();
  },

  async saveConfig(cfg) {
    const res = await fetch('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cfg),
    });
    return await res.json();
  },

  async getSystemInfo() {
    const res = await fetch('/api/system_info');
    return await res.json();
  },

  async getLibraryTracks() {
    const res = await fetch('/api/library/tracks');
    return await res.json();
  },

  async deleteLibraryTrack(relPath) {
    const res = await fetch(`/api/library/track/${encodeURIComponent(relPath)}`, {
      method: 'DELETE',
    });
    return await res.json();
  },

  async getLyric(token) {
    const res = await fetch(`/api/lyric/${token}`);
    const data = await res.json();
    return data.lyric || '';
  },

  async getLocalLyric(relPath) {
    const res = await fetch(`/api/library/lyric/${encodeURIComponent(relPath)}`);
    const data = await res.json();
    return data.lyric || '';
  },

  async startDownload(token) {
    const res = await fetch('/api/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    });
    return await res.json();
  },

  async cancelDownload(downloadId) {
    const res = await fetch(`/api/download/cancel/${downloadId}`, {
      method: 'POST',
    });
    return await res.json();
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
    // We send a POST request with EventSource-like fetch or use POST endpoint
    // To support SSE via POST, we use fetch stream
    const controller = new AbortController();

    fetch('/api/parse_playlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: playlistUrl, source: sourceHint }),
      signal: controller.signal,
    }).then(async (response) => {
      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop(); // keep partial

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
            } catch (err) {}
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

  // ── Downloads Progress SSE ──
  listenDownloads(onUpdate) {
    const es = new EventSource('/api/download/progress');
    es.addEventListener('downloads', (e) => {
      try {
        const list = JSON.parse(e.data);
        onUpdate(list);
      } catch (err) {}
    });
    return es;
  }
};
