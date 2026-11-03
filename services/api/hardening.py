"""Defence-in-depth request integrity, injection screening and detection.

This module is deliberately dependency-free and independent of
``services.api.security`` so it can be unit-tested on its own. It implements
the controls that sit *below* authentication:

* HTTP request-integrity checks: duplicate framing headers, conflicting
  ``Content-Length``/``Transfer-Encoding`` (request smuggling), header
  injection, oversized headers and a DNS-rebinding-safe ``Host`` allowlist.
* Framing and content-type enforcement for JSON API writes.
* High-confidence signatures for injection families (SQL injection, XSS,
  command injection, path traversal, SSTI, XXE, NoSQL/LDAP injection,
  unsafe deserialization, prototype pollution, CRLF injection, SSRF).
* An SSRF guard that resolves a name and rejects every non-public address.
* A per-caller egress budget that limits bulk data exfiltration.
* A machine-readable coverage matrix for the 50 attack classes in
  ``security/ATTACK_COVERAGE.md``.

Detection never echoes the matched value: reports contain the field name, rule
name and category only, so they are safe to audit and show in a UI.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import threading
import time
from collections import Counter, deque
from pathlib import Path
from urllib.parse import urlsplit

WRITE_METHODS = {"POST", "PUT", "PATCH"}
ALLOWED_CONTENT_TYPES = {"application/json"}
MAX_HEADERS = 100
MAX_HEADER_BYTES = 32 * 1024
MAX_HEADER_VALUE = 8 * 1024
MAX_INSPECT_BODY = 256 * 1024
MAX_FINDINGS = 50
_EGRESS_LOCK = threading.RLock()
_EGRESS: dict[str, deque[tuple[float, int]]] = {}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}
_SINGLETON_HEADERS = {
    "content-length", "transfer-encoding", "host", "authorization",
    "x-agent-token", "x-agent-totp", "x-agent-session",
}
_TOKEN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_HOST = re.compile(r"^[A-Za-z0-9._\-\[\]:]+$")

# Free-text fields are code, prompts or chat and legitimately contain strings
# such as "<script>" or "SELECT". They are stored with parameterized queries and
# rendered as text, so signature matches there are not treated as attacks.
FREE_TEXT_FIELDS = {
    "message", "content", "code", "text", "diff", "html", "prompt", "query",
    "question", "instruction", "source", "body", "answer", "stdout", "stderr",
    "summary", "reason", "description", "notes",
}

# category, rule name, severity, pattern
INJECTION_RULES: list[tuple[str, str, str, re.Pattern]] = [
    ("sqli", "union_select", "critical",
     re.compile(r"(?is)\bunion\b[\s(]{1,10}\bselect\b")),
    ("sqli", "stacked_query", "critical",
     re.compile(r"(?is);\s*(?:drop|alter|truncate|delete|insert|update|create)\b")),
    ("sqli", "boolean_tautology", "high",
     re.compile(r"(?is)(?:'|\"|`)\s*(?:or|and)\s*(?:'|\")?\s*\d+\s*(?:'|\")?\s*=\s*(?:'|\")?\s*\d+")),
    ("sqli", "time_delay", "high",
     re.compile(r"(?i)\b(?:sleep|pg_sleep|benchmark|waitfor\s+delay)\s*\(")),
    ("sqli", "comment_terminator", "medium",
     re.compile(r"(?s)['\"]\s*(?:--|#|/\*)")),
    ("sqli", "system_catalog", "high",
     re.compile(r"(?i)\b(?:information_schema|pg_catalog|sysobjects|xp_cmdshell)\b")),
    ("xss", "script_tag", "critical",
     re.compile(r"(?is)<\s*/?\s*script\b")),
    ("xss", "event_handler", "high",
     re.compile(r"(?is)\bon(?:error|load|click|mouseover|focus|submit|toggle)\s*=")),
    ("xss", "javascript_uri", "high",
     re.compile(r"(?i)\bjavascript\s*:")),
    ("xss", "dangerous_tag", "high",
     re.compile(r"(?is)<\s*(?:iframe|object|embed|svg|img)\b[^>]{0,200}\b(?:src|onerror|onload)\s*=")),
    ("xss", "dom_sink", "medium",
     re.compile(r"(?i)\bdocument\.(?:cookie|domain|write)\b")),
    ("command_injection", "shell_metachar", "critical",
     re.compile(r"(?:;|&&|\|\||\$\()\s*(?:/bin/)?(?:sh|bash|zsh|powershell|cmd|curl|wget|nc|netcat|rm|chmod|chown|python|perl)\b", re.I)),
    ("command_injection", "backtick_exec", "high",
     re.compile(r"`[^`\n]{1,200}`")),
    ("command_injection", "powershell_encoded", "high",
     re.compile(r"(?i)\bpowershell(?:\.exe)?\b[^\n]{0,40}-(?:enc|encodedcommand)\b")),
    ("path_traversal", "parent_segments", "critical",
     re.compile(r"(?:^|[\\/])\.\.(?:[\\/]|$)")),
    ("path_traversal", "encoded_parent", "critical",
     re.compile(r"(?i)%(?:2e|252e){2}")),
    ("path_traversal", "sensitive_file", "high",
     re.compile(r"(?i)(?:^|[\\/])(?:etc/(?:passwd|shadow)|proc/self|windows/win\.ini|boot\.ini|\.ssh/(?:id_rsa|authorized_keys))")),
    ("ssti", "template_expression", "high",
     re.compile(r"(?s)(?:\{\{.{0,200}\}\}|\$\{.{0,200}\}|<%.{0,200}%>|#\{.{0,200}\})")),
    ("xxe", "doctype_entity", "high",
     re.compile(r"(?is)<!DOCTYPE[^>]{0,200}<!ENTITY|<!ENTITY\s+\w+\s+SYSTEM")),
    ("nosql_injection", "operator", "high",
     re.compile(r"(?i)\$(?:where|ne|gt|gte|lt|lte|regex|nin|exists)\b")),
    ("ldap_injection", "filter_injection", "medium",
     re.compile(r"(?:\)\s*\(\s*(?:uid|cn|objectclass)\s*=|\*\)\s*\()", re.I)),
    ("deserialization", "java_serialized", "high",
     re.compile(r"\brO0AB[A-Za-z0-9+/=]{8,}")),
    ("deserialization", "php_object", "high",
     re.compile(r"\bO:\d{1,4}:\"[A-Za-z0-9_\\\\]{1,120}\":")),
    ("deserialization", "python_object", "high",
     re.compile(r"!!python/(?:object|module)")),
    ("prototype_pollution", "proto_key", "high",
     re.compile(r"(?i)(?:__proto__|\[\s*[\"']?prototype[\"']?\s*\]|constructor\s*\[\s*[\"']?prototype)")),
    ("crlf_injection", "encoded_crlf", "high",
     re.compile(r"(?i)%0d%0a|%0a%0d")),
    ("ssrf", "internal_target", "critical",
     re.compile(r"(?i)^(?:https?|gopher|file|dict|ftp)://(?:127\.|10\.|192\.168\.|169\.254\.|172\.(?:1[6-9]|2\d|3[01])\.|\[?::1\]?|localhost)")),
]

SEVERITY_WEIGHT = {"low": 1, "medium": 2, "high": 3, "critical": 4}
BLOCKING_SEVERITIES = {"high", "critical"}

# Resolved outbound addresses that must never be reachable from server-side
# fetches. ``ipaddress`` covers most of these; the explicit list keeps the
# intent readable and guards new Python versions.
_BLOCKED_NETWORKS = [
    ipaddress.ip_network(net) for net in (
        "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
        "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.168.0.0/16",
        "198.18.0.0/15", "224.0.0.0/4", "240.0.0.0/4",
        "::1/128", "fc00::/7", "fe80::/10", "ff00::/8",
    )
]


def enabled() -> bool:
    return os.getenv("SECURITY_ENABLED", "1") != "0" and os.getenv("HARDENING_ENABLED", "1") != "0"


def blocking_enabled() -> bool:
    return os.getenv("SECURITY_BLOCK_SUSPICIOUS_INPUT", "1") != "0"


def _int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def reset() -> None:
    """Clear in-memory egress state. Test-only."""
    with _EGRESS_LOCK:
        _EGRESS.clear()


# ---------------------------------------------------------------------------
# HTTP request integrity
# ---------------------------------------------------------------------------

def request_integrity(request) -> str | None:
    """Return a reason when framing/headers are ambiguous or malformed.

    Ambiguous framing is the precondition for HTTP request smuggling; rejecting
    it at the application edge is defensive even when the server also rejects
    it. Header names are validated so CR/LF cannot be smuggled into responses.
    """
    raw = list(request.headers.raw)
    if len(raw) > MAX_HEADERS:
        return "too many headers"
    total = 0
    seen: set[str] = set()
    for name, value in raw:
        total += len(name) + len(value) + 4
        if total > MAX_HEADER_BYTES:
            return "header block too large"
        if len(name) > 256 or len(value) > MAX_HEADER_VALUE:
            return "header line too large"
        if b"\r" in value or b"\n" in value or b"\x00" in value:
            return "control character in header value"
        try:
            decoded_name = name.decode("ascii")
        except UnicodeDecodeError:
            return "non-ASCII header name"
        if not _TOKEN.fullmatch(decoded_name):
            return "invalid header name"
        lowered = decoded_name.lower()
        if lowered in _SINGLETON_HEADERS:
            if lowered in seen:
                return "duplicate " + lowered + " header"
            seen.add(lowered)
    if "transfer-encoding" in seen and "content-length" in seen:
        return "conflicting framing headers"
    if "transfer-encoding" in seen:
        values = [value.strip().lower() for name, value in raw if name.lower() == b"transfer-encoding"]
        if len(values) != 1 or values[0] != b"chunked":
            return "unsupported transfer-encoding"
    if "content-length" in seen:
        value = next(value for name, value in raw if name.lower() == b"content-length")
        if not value.isdigit():
            return "invalid content-length"
    return None


def _normalize_host(host: str) -> str:
    host = (host or "").strip().lower().rstrip(".")
    if host.startswith("["):
        end = host.find("]")
        if end == -1:
            return ""
        return host[1:end]
    if host.count(":") == 1:
        name, _, port = host.partition(":")
        if port.isdigit():
            return name
    return host


def _host_matches(host: str, pattern: str) -> bool:
    pattern = pattern.strip().lower().rstrip(".")
    if not pattern:
        return False
    if pattern.startswith("*."):
        suffix = pattern[1:]
        return host.endswith(suffix) and host != suffix[1:]
    return host == pattern


def host_allowed(host: str) -> bool:
    """DNS-rebinding defence: only loopback and explicitly configured hosts."""
    if os.getenv("SECURITY_ENFORCE_HOST", "1") == "0":
        return True
    normalized = _normalize_host(host)
    if not normalized:
        return True
    if not _HOST.fullmatch(normalized):
        return False
    if normalized in LOOPBACK_HOSTS:
        return True
    configured = [item for item in os.getenv("SECURITY_ALLOWED_HOSTS", "").split(",") if item.strip()]
    return any(_host_matches(normalized, item) for item in configured)


def request_host_problem(request) -> str | None:
    host = request.headers.get("host", "")
    if host_allowed(host):
        return None
    return "host is not in the allowlist"


def fetch_metadata_problem(request) -> str | None:
    """Reject browser-issued cross-site writes (defence in depth for CSRF)."""
    if request.method not in WRITE_METHODS:
        return None
    site = (request.headers.get("sec-fetch-site") or "").strip().lower()
    if site == "cross-site":
        return "cross-site browser write"
    return None


def framing_problem(request) -> str | None:
    """Chunked writes are refused so body size limits cannot be bypassed."""
    if request.method not in WRITE_METHODS or not request.url.path.startswith("/api/"):
        return None
    if request.headers.get("transfer-encoding"):
        return "Chunked request bodies are not accepted"
    if os.getenv("SECURITY_REQUIRE_CONTENT_LENGTH", "1") == "1":
        if request.headers.get("content-length") is None:
            return "Content-Length required"
    return None


def content_type_problem(request) -> str | None:
    if request.method not in WRITE_METHODS or not request.url.path.startswith("/api/"):
        return None
    length = request.headers.get("content-length")
    if length in (None, "0"):
        return None
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype in ALLOWED_CONTENT_TYPES:
        return None
    if ctype.startswith("application/") and ctype.endswith("+json"):
        return None
    return "Unsupported content type"


# ---------------------------------------------------------------------------
# Injection signature detection
# ---------------------------------------------------------------------------

def _iter_strings(value, prefix: str = "", depth: int = 0):
    if depth > 6:
        return
    if isinstance(value, dict):
        for key, item in list(value.items())[:200]:
            name = f"{prefix}.{key}" if prefix else str(key)
            yield name, "key", str(key)
            yield from _iter_strings(item, name, depth + 1)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value[:50]):
            yield from _iter_strings(item, f"{prefix}[{index}]", depth + 1)
    elif isinstance(value, str) and len(value) <= 4096:
        yield prefix, "value", value


def inspect_text(text: str, field: str = "value") -> list[dict]:
    """Return non-echoing findings for one untrusted scalar."""
    findings = []
    for category, rule, severity, pattern in INJECTION_RULES:
        if pattern.search(text):
            findings.append({"category": category, "rule": rule,
                             "severity": severity, "field": field})
    return findings


def _structured_field(field: str) -> bool:
    leaf = field.rsplit(".", 1)[-1].split("[", 1)[0].strip().lower()
    return leaf not in FREE_TEXT_FIELDS


async def inspect_request(request) -> dict:
    """Inspect path segments, query values and structured JSON body fields.

    Free-text fields (chat messages, code, diffs) are skipped: this is a coding
    assistant, so those fields legitimately contain SQL and HTML. They are
    stored with parameterized queries and never rendered as markup.
    """
    findings: list[dict] = []

    for segment in request.url.path.split("/"):
        if segment:
            findings.extend(inspect_text(segment, "path"))

    for key, value in request.query_params.multi_items():
        findings.extend(inspect_text(value, f"query.{key}"))

    if request.method in WRITE_METHODS:
        ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        is_json = ctype in ALLOWED_CONTENT_TYPES or (
            ctype.startswith("application/") and ctype.endswith("+json"))
        if is_json:
            try:
                raw = await request.body()
            except Exception:
                raw = b""
            if raw and len(raw) <= MAX_INSPECT_BODY:
                try:
                    data = json.loads(raw)
                except (ValueError, UnicodeError):
                    data = None
                if data is not None:
                    for field, kind, text in _iter_strings(data, "body"):
                        if kind == "key":
                            findings.extend(inspect_text(text, field + "[key]"))
                        elif _structured_field(field):
                            findings.extend(inspect_text(text, field))

    # Free-text body fields were skipped above; everything left (path, query
    # and structured body fields) is inspected, including a query parameter
    # whose name happens to be "query" or "message".
    deduped: dict[tuple[str, str, str], dict] = {}
    for finding in findings:
        deduped.setdefault(
            (finding["category"], finding["rule"], finding["field"]), finding)
    ordered = list(deduped.values())[:MAX_FINDINGS]
    score = sum(SEVERITY_WEIGHT.get(item["severity"], 1) for item in ordered)
    blocked = bool(blocking_enabled() and any(
        item["severity"] in BLOCKING_SEVERITIES for item in ordered))
    return {
        "findings": ordered,
        "categories": sorted({item["category"] for item in ordered}),
        "score": score,
        "blocked": blocked,
    }


# ---------------------------------------------------------------------------
# SSRF guard
# ---------------------------------------------------------------------------

def _address_problem(address: ipaddress._BaseAddress) -> str | None:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if address.is_loopback:
        return "loopback address"
    if address.is_link_local:
        return "link-local address"
    if address.is_multicast or address.is_reserved or address.is_unspecified:
        return "reserved address"
    for network in _BLOCKED_NETWORKS:
        if address.version == network.version and address in network:
            return "private or special-use address"
    return None


def url_problem(url: str, *, allow_loopback: bool = False,
                allowed_hosts: set[str] | tuple[str, ...] = ()) -> str | None:
    """Validate a server-side outbound URL. Returns a reason or ``None``.

    Every address returned by the resolver is checked, so a name that resolves
    to both a public and a private address is refused. Resolution happens twice
    (here and at connect time), so re-checking the connected peer is still
    required for a fully rebinding-proof client.
    """
    if not isinstance(url, str) or not url or len(url) > 2048:
        return "invalid URL"
    if any(character.isspace() for character in url):
        return "whitespace in URL"
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        return "unsupported scheme"
    if parsed.username or parsed.password:
        return "URL credentials are not allowed"
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return "missing host"
    if host in {item.lower() for item in allowed_hosts}:
        return None
    if host.endswith(".internal") or host.endswith(".local") or host.endswith(".localhost"):
        return "internal hostname"
    if "." not in host and ":" not in host and host not in LOOPBACK_HOSTS:
        return "single-label hostname"
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return "invalid port"
    if not 1 <= port <= 65535:
        return "invalid port"
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(
            host, port, type=socket.SOCK_STREAM)}
    except (socket.gaierror, UnicodeError, OSError):
        return "host does not resolve"
    if not addresses:
        return "host does not resolve"
    for raw_address in addresses:
        try:
            address = ipaddress.ip_address(raw_address.split("%", 1)[0])
        except ValueError:
            return "unparseable address"
        if address.is_loopback and allow_loopback:
            continue
        problem = _address_problem(address)
        if problem:
            return problem
    return None


# ---------------------------------------------------------------------------
# Egress (data-exfiltration) budget
# ---------------------------------------------------------------------------

def egress_limit() -> int:
    return _int("SECURITY_EGRESS_BYTES_PER_MINUTE", 64 * 1024 * 1024, 1024, 10 * 1024 ** 3)


def egress_window() -> int:
    return _int("SECURITY_EGRESS_WINDOW_SECONDS", 60, 1, 3600)


def large_response_threshold() -> int:
    return _int("SECURITY_LARGE_RESPONSE_BYTES", 4 * 1024 * 1024, 1024, 1024 ** 3)


def note_egress(identifier: str, size: int) -> None:
    if size <= 0:
        return
    now = time.monotonic()
    window = egress_window()
    with _EGRESS_LOCK:
        queue = _EGRESS.setdefault(identifier, deque())
        queue.append((now, int(size)))
        while queue and now - queue[0][0] > window:
            queue.popleft()
        if len(_EGRESS) > 10000:
            for stale in [key for key, value in _EGRESS.items()
                          if not value or now - value[-1][0] > window]:
                _EGRESS.pop(stale, None)


def egress_used(identifier: str) -> int:
    now = time.monotonic()
    window = egress_window()
    with _EGRESS_LOCK:
        queue = _EGRESS.get(identifier)
        if not queue:
            return 0
        while queue and now - queue[0][0] > window:
            queue.popleft()
        return sum(size for _at, size in queue)


def egress_retry(identifier: str) -> int:
    used = egress_used(identifier)
    limit = egress_limit()
    if used < limit:
        return 0
    return egress_window()


def response_size_bytes(response) -> int:
    try:
        return max(0, int(response.headers.get("content-length", "0")))
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Static exposure
# ---------------------------------------------------------------------------

def static_mount_problems(app) -> list[dict]:
    """Flag static mounts that would serve secrets, databases or repository metadata."""
    from starlette.routing import Mount

    issues = []
    protected_names = {".git", ".ssh", ".aws", ".gnupg", "database"}
    for route in getattr(app, "routes", []):
        if not isinstance(route, Mount):
            continue
        directory = getattr(route.app, "directory", None)
        if not directory:
            continue
        try:
            resolved = Path(directory).resolve()
        except (OSError, RuntimeError):
            continue
        names = {part.name for part in resolved.parents} | {resolved.name}
        reason = None
        if names & protected_names:
            reason = "mount is inside a protected directory"
        elif (resolved / ".env").is_file() or (resolved / ".git").exists() \
                or (resolved / "database").is_dir():
            reason = "mount exposes repository secrets or data"
        if reason:
            issues.append({"mount": route.path, "directory": str(resolved),
                           "problem": reason})
    return issues


# ---------------------------------------------------------------------------
# Threat coverage matrix (50 classes)
# ---------------------------------------------------------------------------

def _threat(number: int, category: str, name: str, status: str,
            controls: list[str]) -> dict:
    return {"id": number, "category": category, "name": name,
            "status": status, "controls": controls}


THREATS = [
    _threat(1, "Network", "DDoS", "partial", [
        "Per-address sliding-window limits with Retry-After",
        "Header and body ceilings; bounded request parsing",
        "Volumetric absorption still requires an edge/proxy"]),
    _threat(2, "Network", "Man-in-the-middle", "partial", [
        "HSTS on HTTPS; no secrets in caches or logs",
        "Token kept in page memory; TLS termination required"]),
    _threat(3, "Network", "DNS spoofing", "delegated", [
        "TLS plus HSTS mitigate impersonation",
        "Resolver and DNSSEC policy are platform responsibilities"]),
    _threat(4, "Network", "ARP spoofing", "delegated", [
        "Application traffic integrity depends on TLS",
        "Requires network segmentation or port security"]),
    _threat(5, "Network", "Packet sniffing", "partial", [
        "No plaintext token persistence; no-store responses",
        "TLS at the proxy is required for on-wire confidentiality"]),
    _threat(6, "Application", "SQL injection", "mitigated", [
        "All SQL uses bound parameters",
        "Structured-field SQLi signatures block at the edge",
        "Static audit flags string-built SQL"]),
    _threat(7, "Application", "Cross-site scripting", "partial", [
        "CSP, nosniff, frame denial and JSON-only API",
        "Sandboxed preview iframe; escaping on render",
        "Bundled editor requires unsafe-inline/unsafe-eval"]),
    _threat(8, "Application", "CSRF", "mitigated", [
        "Header-token authentication, no ambient cookies",
        "Origin allowlist and Sec-Fetch-Site rejection"]),
    _threat(9, "Application", "Remote code execution", "partial", [
        "Host execution disabled by default; no shell",
        "Allowlisted networkless Docker with cap-drop",
        "Command-injection and deserialization signatures"]),
    _threat(10, "Application", "SSRF", "mitigated", [
        "Model and delegation endpoints restricted to loopback",
        "DNS-safe guard rejects private and metadata addresses",
        "Redirects disabled on outbound clients"]),
    _threat(11, "Identity", "Credential stuffing", "partial", [
        "Per-address lockouts plus global failure cooldown",
        "Distributed guessing degrades to a service-wide pause"]),
    _threat(12, "Identity", "Brute force", "mitigated", [
        "Constant-time digest comparison",
        "Exponential lockout with capped escalation",
        "Optional TOTP second factor"]),
    _threat(13, "Identity", "Password spraying", "partial", [
        "Global failure-rate cooldown across addresses",
        "Generic error messages and no account enumeration"]),
    _threat(14, "Identity", "Session hijacking", "partial", [
        "No cookie sessions; per-request bearer token",
        "No token in local storage; HSTS when TLS is present"]),
    _threat(15, "Identity", "MFA fatigue", "partial", [
        "TOTP rather than push approval",
        "MFA failures feed the lockout and global cooldown",
        "Failed MFA attempts are audited"]),
    _threat(16, "Malware", "Ransomware", "partial", [
        "Diff approval, atomic writes and reversible checkpoints",
        "Read-only container root; database on an isolated volume",
        "Bulk-write and egress limits raise the cost of mass theft"]),
    _threat(17, "Malware", "Trojan horse", "delegated", [
        "Pinned dependencies and license verification",
        "Endpoint malware protection is outside this process"]),
    _threat(18, "Malware", "Rootkit", "delegated", [
        "Container runs non-root with all capabilities dropped",
        "Host integrity monitoring is a platform control"]),
    _threat(19, "Malware", "Spyware", "delegated", [
        "No telemetry; outbound inference is operator-configured",
        "Endpoint scanning is outside this process"]),
    _threat(20, "Malware", "Worm", "delegated", [
        "No inbound peer-to-peer surface; networkless execution",
        "Network egress policy is a platform control"]),
    _threat(21, "Cloud", "Cloud storage exposure", "mitigated", [
        "No cloud object storage binding in this build",
        "Static-mount audit rejects protected directories",
        "No directory listing or path-joined file serving"]),
    _threat(22, "Cloud", "IAM privilege escalation", "partial", [
        "Single administrator role; no cloud IAM in-app",
        "Non-root container with capabilities dropped"]),
    _threat(23, "Cloud", "Cloud API key theft", "partial", [
        "Keys read from environment only, never logged",
        "Secret redaction before prompts and excerpts",
        "Audit records events, never credential values"]),
    _threat(24, "Cloud", "Container escape", "partial", [
        "cap-drop ALL, no-new-privileges, read-only rootfs",
        "No Docker socket; networkless execution container",
        "Containers are not a hard security boundary"]),
    _threat(25, "Cloud", "Kubernetes cluster compromise", "partial", [
        "Hardened manifests with dropped capabilities",
        "Cluster RBAC and admission control are platform controls"]),
    _threat(26, "Financial", "Account takeover", "partial", [
        "Digest-compared token plus optional TOTP",
        "Lockout, global cooldown and rate limits"]),
    _threat(27, "Financial", "Payment fraud", "not_applicable", [
        "No payment processing or card data in this build"]),
    _threat(28, "Financial", "Business email compromise", "delegated", [
        "No mail transport in this build",
        "Email authentication is a provider control"]),
    _threat(29, "Financial", "Transaction manipulation", "mitigated", [
        "Human approval header on every write",
        "SHA-256 conflict check before apply/restore",
        "Atomic replace with a reversible checkpoint"]),
    _threat(30, "Financial", "API abuse", "mitigated", [
        "Authentication on every route except /health",
        "Per-route rate buckets, body caps and egress budget",
        "Generic errors and request IDs for correlation"]),
    _threat(31, "Social engineering", "Phishing", "delegated", [
        "No credential-collection UI beyond the operator token",
        "Operator training and mail filtering are external"]),
    _threat(32, "Social engineering", "Spear phishing", "delegated", [
        "Out of scope for the application; user awareness required"]),
    _threat(33, "Social engineering", "Whaling", "delegated", [
        "Out of scope for the application; organizational control"]),
    _threat(34, "Social engineering", "Vishing", "delegated", [
        "Out of scope for the application; organizational control"]),
    _threat(35, "Social engineering", "Deepfake impersonation", "delegated", [
        "Out of scope; out-of-band verification is an organizational control"]),
    _threat(36, "Database and data", "Data exfiltration", "partial", [
        "Per-caller egress budget with 429 and Retry-After",
        "Large responses audited; no bulk export endpoint",
        "Execution container has no network"]),
    _threat(37, "Database and data", "Insider data theft", "partial", [
        "Tamper-evident HMAC audit chain",
        "Single-operator model lacks per-user least privilege"]),
    _threat(38, "Database and data", "Database misconfiguration", "mitigated", [
        "Embedded SQLite; no network listener or default credentials",
        "Bound parameters and foreign keys enabled",
        "Database and audit files are gitignored"]),
    _threat(39, "Database and data", "Insecure deserialization", "mitigated", [
        "JSON-only request parsing; no pickle or unsafe YAML",
        "Deserialization signatures blocked on structured fields"]),
    _threat(40, "Database and data", "Backup data exposure", "partial", [
        "No backup endpoint; database files are gitignored",
        "Static-mount audit; full-disk encryption recommended"]),
    _threat(41, "Supply chain", "Dependency confusion", "mitigated", [
        "Lockfiles pin resolved versions; scoped package registry",
        "security_audit.py checks pins and lockfile presence"]),
    _threat(42, "Supply chain", "Malicious software update", "partial", [
        "No auto-update channel; pinned base images recommended",
        "Release artifacts must be verified before rollout"]),
    _threat(43, "Supply chain", "CI/CD pipeline compromise", "partial", [
        "Read-only workflow permissions and no production secrets",
        "Action pinning checked by the audit script"]),
    _threat(44, "Supply chain", "Open-source package poisoning", "partial", [
        "Registered permissive dependencies with notices",
        "Transitive dependency risk remains; review before upgrade"]),
    _threat(45, "Supply chain", "Repository secret exposure", "mitigated", [
        "Secret scan in CI and pre-commit workflow",
        "Redaction before prompts; .env gitignored"]),
    _threat(46, "Advanced", "Zero-day exploitation", "partial", [
        "Minimal dependency surface and fail-closed authentication",
        "Audit trail and anomaly limits contain blast radius"]),
    _threat(47, "Advanced", "Advanced persistent threat", "partial", [
        "Tamper-evident audit chain and global anomaly cooldown",
        "Long-dwell detection needs external SIEM"]),
    _threat(48, "Advanced", "Firmware compromise", "delegated", [
        "Secure boot and firmware attestation are platform controls"]),
    _threat(49, "Advanced", "Active Directory compromise", "not_applicable", [
        "No Active Directory integration in this build"]),
    _threat(50, "Advanced", "Hypervisor escape", "delegated", [
        "VM isolation and hypervisor patching are platform controls"]),
]


def coverage_counts() -> dict[str, int]:
    return dict(Counter(item["status"] for item in THREATS))


def summary() -> dict:
    return {
        "enabled": enabled(),
        "blocking_input_inspection": blocking_enabled(),
        "request_integrity": True,
        "host_allowlist_enforced": os.getenv("SECURITY_ENFORCE_HOST", "1") != "0",
        "host_allowlist": [
            item.strip() for item in os.getenv("SECURITY_ALLOWED_HOSTS", "").split(",")
            if item.strip()],
        "content_type_enforcement": True,
        "content_length_required": os.getenv("SECURITY_REQUIRE_CONTENT_LENGTH", "1") != "0",
        "injection_rules": len(INJECTION_RULES),
        "egress_bytes_per_minute": egress_limit(),
        "large_response_threshold": large_response_threshold(),
        "threats_tracked": len(THREATS),
        "threat_status_counts": coverage_counts(),
    }
