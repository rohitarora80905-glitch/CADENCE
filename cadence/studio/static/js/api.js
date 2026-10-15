/* The HTTP client for the Studio's own FastAPI server. */

async function request(method, path, body = null, headers = {}) {
  const opts = { method, headers: { ...headers } };
  if (body !== null) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const type = res.headers.get('content-type') || '';
  const data = type.includes('application/json') ? await res.json() : await res.text();
  if (!res.ok) {
    const msg = (data && (data.message || data.detail)) || res.statusText || 'request failed';
    const err = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

export const api = {
  health: () => request('GET', '/api/health'),
  compile: (source, { name = 'score.cad', level = 2, articulate = false, midi = true } = {}) =>
    request('POST', '/api/compile', { source, name, level, articulate, midi }),
  examples: () => request('GET', '/api/examples'),
  presets: () => request('GET', '/api/presets'),
  toolchain: () => request('GET', '/api/toolchain'),
  core: () => request('GET', '/api/core'),
  coreSource: (group, file) => request('GET', `/api/core/${encodeURIComponent(group)}/${encodeURIComponent(file)}`),
  readme: () => request('GET', '/api/core/readme'),
  aiModels: (key) => request('GET', '/api/ai/models', null, key ? { 'X-Groq-Key': key } : {}),
  arrange: (chart) => request('POST', '/api/arrange', { chart }),
  importMidi: async (file) => {
    const fd = new FormData();
    fd.append('file', file, file.name);
    const res = await fetch('/api/import/midi', { method: 'POST', body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { const err = new Error(data.detail || data.message || res.statusText); err.status = res.status; throw err; }
    return data;
  },
  aiCompose: (payload, key) => request('POST', '/api/ai/compose', payload, key ? { 'X-Groq-Key': key } : {}),
  /* The streaming variant: progress lines arrive while the model works, with no time
     limit on the browser side; resolves with the final result. */
  aiComposeStream: async (payload, key, onProgress) => {
    const headers = { 'Content-Type': 'application/json' };
    if (key) headers['X-Groq-Key'] = key;
    const res = await fetch('/api/ai/compose/stream', { method: 'POST', headers, body: JSON.stringify(payload) });
    if (!res.ok || !res.body) {
      const data = await res.json().catch(() => ({}));
      const err = new Error(data.message || data.detail || res.statusText || 'request failed');
      err.status = res.status;
      throw err;
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    let result = null;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, i).trim();
        buf = buf.slice(i + 1);
        if (!line) continue;
        const msg = JSON.parse(line);
        if (msg.event === 'progress') onProgress && onProgress(msg.message);
        else if (msg.event === 'result') result = msg;
        else if (msg.event === 'error') { const err = new Error(msg.message); err.status = msg.status; throw err; }
      }
    }
    if (!result) throw new Error('the composer stream ended without a result');
    return result;
  },
};
