'use strict';

/** SSE framing works across arbitrary UTF-8 network chunk boundaries. */
const MAX_PENDING = 512_000;
function parseFrame(raw) {
  const lines = raw.split(/\r?\n/);
  const eventLine = lines.find(line => line.startsWith('event:'));
  const data = lines.filter(line => line.startsWith('data:'))
    .map(line => line.slice(5).trimStart()).join('\n');
  if (!eventLine || !data) return null;
  const kind = eventLine.slice(6).trim();
  if (!['delta', 'done', 'error'].includes(kind)) return null;
  const payload = JSON.parse(data);
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error('Invalid SSE event payload');
  }
  return {kind, payload};
}
function parseAvailable(buffer) {
  const events = [];
  while (true) {
    const match = /\r?\n\r?\n/.exec(buffer);
    if (!match) break;
    const raw = buffer.slice(0, match.index);
    buffer = buffer.slice(match.index + match[0].length);
    const event = parseFrame(raw);
    if (event) events.push(event);
  }
  if (buffer.length > MAX_PENDING) throw new Error('SSE receive buffer exceeded');
  return {events, rest:buffer};
}
function localEndpoint(input) {
  const url = new URL(input);
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
      || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('Local AI endpoint must be an unqualified loopback HTTP URL');
  }
  return url.origin;
}
function validProject(project) {return typeof project === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(project);}
module.exports = {parseAvailable, parseFrame, localEndpoint, validProject};
