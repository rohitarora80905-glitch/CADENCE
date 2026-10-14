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
  aiCompose: (payload, key) => request('POST', '/api/ai/compose', payload, key ? { 'X-Groq-Key': key } : {}),
};
