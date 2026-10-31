/**
 * Lightweight local API client. Never exposes a remote execution API.
 * Node.js 20+ required (native fetch and AbortSignal.timeout).
 */
export class AgenticClient {
  constructor({ baseUrl = "http://127.0.0.1:8000", token, timeoutMs = 30000 } = {}) {
    const url = new URL(baseUrl);
    if (url.protocol !== "http:" || !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname) || url.username || url.password || url.search || url.hash || url.pathname !== "/") {
      throw new TypeError("AgenticClient requires a loopback HTTP server URL");
    }
    if (typeof token !== "string" || token.length < 8) throw new TypeError("An administrator token is required");
    this.baseUrl = url.origin;
    this.token = token;
    this.timeoutMs = timeoutMs;
  }
  async request(path, { method = "GET", body } = {}) {
    if (!/^\/api\/[a-zA-Z0-9/_-]*$/.test(path)) throw new TypeError("Invalid API path");
    const response = await fetch(this.baseUrl + path, {
      method,
      headers: { Authorization: `Bearer ${this.token}`, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      signal: AbortSignal.timeout(this.timeoutMs),
      redirect: "error"
    });
    const content = await response.text();
    let result;
    try { result = JSON.parse(content); } catch { result = { message: content.slice(0, 1000) }; }
    if (!response.ok) throw new Error(`Agentic API HTTP ${response.status}: ${JSON.stringify(result).slice(0, 300)}`);
    return result;
  }
  listProjects() { return this.request("/api/projects"); }
  createProject(slug, title) { return this.request("/api/projects", { method: "POST", body: { slug, title } }); }
  listLanguages() { return this.request("/api/languages"); }
}
