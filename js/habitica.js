// ── Habitica API client ──────────────────────────────────────
// Habitica's API is CORS-open (access-control-allow-origin: *) and accepts
// x-api-user / x-api-key / x-client from a browser, which is the whole reason
// this site needs no backend and no proxy. It allows 30 requests per minute and
// exposes the remaining budget through access-control-expose-headers.
//
// Every call in the app goes through ONE limiter instance so the budget is
// shared. Two independent limiters would each believe they had 30.

export const API_BASE = 'https://habitica.com/api/v3';
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export class RateLimiter {
  #calls = [];
  #chain = Promise.resolve();

  constructor({ maxPerWindow = 30, windowMs = 60000 } = {}) {
    this.maxPerWindow = maxPerWindow;
    this.windowMs = windowMs;
    this.throttled = 0;
    this.totalSleptMs = 0;
  }

  #evict(now) {
    while (this.#calls.length && now - this.#calls[0] >= this.windowMs) this.#calls.shift();
  }

  async #acquire() {
    this.#evict(Date.now());
    if (this.#calls.length >= this.maxPerWindow) {
      const wait = this.windowMs - (Date.now() - this.#calls[0]);
      if (wait > 0) {
        this.throttled += 1;
        this.totalSleptMs += wait;
        await sleep(wait);
        this.#evict(Date.now());
      }
    }
    this.#calls.push(Date.now());
  }

  /** Serialised: concurrent callers queue rather than all reading an empty window. */
  acquire() {
    const next = this.#chain.then(() => this.#acquire());
    this.#chain = next.catch(() => {});
    return next;
  }

  async pauseFor(ms) {
    if (ms > 0) {
      this.throttled += 1;
      this.totalSleptMs += ms;
      await sleep(ms);
    }
    this.#calls.length = 0;
  }

  get inWindow() {
    this.#evict(Date.now());
    return this.#calls.length;
  }
}

export class ApiError extends Error {
  constructor(status, message, path) {
    super(`${status} ${path}: ${message}`);
    this.status = status;
    this.path = path;
  }
}

export class HabiticaClient {
  #token;

  constructor({ userId, apiToken, appName = 'Overworld', baseUrl = API_BASE, limiter }) {
    this.userId = userId;
    this.#token = apiToken;
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.limiter = limiter || new RateLimiter();
    // Habitica's third-party guideline: "<UserID>-<AppName>".
    this.clientHeader = `${userId}-${appName}`;
    this.rateRemaining = null;
  }

  async request(method, path, { params, body, retries = 1 } = {}) {
    let url = this.baseUrl + path;
    if (params) {
      const query = new URLSearchParams(
        Object.entries(params).filter(([, v]) => v !== undefined && v !== null),
      );
      if (String(query)) url += `?${query}`;
    }

    await this.limiter.acquire();
    const response = await fetch(url, {
      method,
      headers: {
        'x-api-user': this.userId,
        'x-api-key': this.#token,
        'x-client': this.clientHeader,
        'content-type': 'application/json',
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });

    const remaining = response.headers.get('X-RateLimit-Remaining');
    if (remaining !== null) this.rateRemaining = Number(remaining);

    if (response.status === 429 && retries > 0) {
      const retryAfter = Number(response.headers.get('Retry-After') || 60);
      await this.limiter.pauseFor(retryAfter * 1000);
      return this.request(method, path, { params, body, retries: retries - 1 });
    }

    let payload = null;
    try { payload = await response.json(); } catch { /* empty body */ }

    if (!response.ok) {
      throw new ApiError(response.status, payload?.message || response.statusText, path);
    }
    if (payload && payload.success === false) {
      throw new ApiError(200, payload.message || 'request reported failure', path);
    }
    return payload && 'data' in payload ? payload.data : payload;
  }

  // -- reads --
  getUser() { return this.request('GET', '/user'); }

  /** All types except completed to-dos, which Habitica requires be asked for separately. */
  getTasks({ withHistory = true } = {}) {
    return this.request('GET', '/tasks/user', { params: { history: String(withHistory) } });
  }

  /** Everything still inside Habitica's 30-day retention window, newest first. */
  getCompletedTodos() {
    return this.request('GET', '/tasks/user', { params: { type: 'completedTodos' } });
  }

  getTags() { return this.request('GET', '/tags'); }

  // -- writes --
  createTag(name) { return this.request('POST', '/tags', { body: { name } }); }

  addTagToTask(taskId, tagId) {
    return this.request('POST', `/tasks/${taskId}/tags/${tagId}`);
  }

  removeTagFromTask(taskId, tagId) {
    return this.request('DELETE', `/tasks/${taskId}/tags/${tagId}`);
  }

  updateTask(taskId, patch) {
    return this.request('PUT', `/tasks/${taskId}`, { body: patch });
  }

  scoreTask(taskId, direction = 'up') {
    return this.request('POST', `/tasks/${taskId}/score/${direction}`);
  }

  createTodo({ text, notes = '', tags = [], date = null, priority = null }) {
    const body = { type: 'todo', text, notes };
    if (tags.length) body.tags = tags;
    if (date) body.date = date;
    if (priority) body.priority = priority;
    return this.request('POST', '/tasks/user', { body });
  }
}

/** One request, used by the Connect screen to prove the credentials work. */
export async function verifyCredentials({ userId, apiToken }) {
  const client = new HabiticaClient({ userId, apiToken });
  const user = await client.getUser();
  return {
    name: user?.profile?.name || '(no display name)',
    level: user?.stats?.lvl ?? 0,
    className: user?.stats?.class || 'warrior',
  };
}
