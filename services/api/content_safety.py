"""Secret and prompt-injection screening for untrusted repository text.

Retrieved code and docs are untrusted data. Before any excerpt is placed in a
model prompt it is scanned for credentials and instruction-injection patterns;
secrets are replaced with typed placeholders. Findings never include the
matched secret itself, so the scan report is safe to show in the UI and write to
logs.

Detection combines explicit provider patterns with a Shannon-entropy check for
opaque tokens. It is deliberately conservative: hexadecimal commit hashes are
not treated as secrets, and normal code identifiers are not redacted.
"""
from __future__ import annotations

import math
import re

MAX_SCAN_CHARS = 200_000
HIGH_ENTROPY_MIN_LENGTH = 32
HIGH_ENTROPY_THRESHOLD = 3.8

# kind, pattern, replacement strategy
SECRET_RULES = [
    ("private_key", re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]{0,4000}?-----END [A-Z0-9 ]*PRIVATE KEY-----"), "whole"),
    ("jwt", re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "whole"),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "whole"),
    ("provider_token", re.compile(
        r"\b(?:sk|rk|ghp|gho|ghu|ghs|github_pat|xox[abprs])[-_][A-Za-z0-9_-]{16,}\b"), "whole"),
    ("slack_webhook", re.compile(
        r"https://hooks\.slack\.com/services/[A-Za-z0-9/]{20,}"), "whole"),
    ("uri_credentials", re.compile(
        r"\b([a-z][a-z0-9+.-]*://)[^\s:/@]{1,64}:[^\s@/]{1,128}@", re.IGNORECASE), "uri"),
    ("bearer_token", re.compile(
        r"(?i)\b(bearer)(\s+)[A-Za-z0-9\-._~+/]{20,}=*"), "bearer"),
    ("env_secret", re.compile(
        r"(?im)^(\s*[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY|ACCESS_KEY)[A-Z0-9_]*\s*=\s*)(['\"]?)(?!\[REDACTED:)([^\s'\"]{6,})\2"),
     "env"),
]

INJECTION_RULES = [
    ("override_instructions", re.compile(
        r"(?i)\b(?:ignore|disregard|forget)\b[^.\n]{0,40}\b(?:previous|prior|above|earlier)\b"
        r"[^.\n]{0,30}\b(?:instruction|prompt|rule|message)s?\b")),
    ("reveal_system_prompt", re.compile(
        r"(?i)\b(?:reveal|print|show|repeat|dump)\b[^.\n]{0,30}\b(?:system|developer)\b"
        r"[^.\n]{0,20}\b(?:prompt|instruction|message)s?\b")),
    ("role_override", re.compile(
        r"(?i)\byou are now\b|\bact as (?:an?|the) (?:system|developer|admin)\b")),
    ("chat_markup", re.compile(
        r"(?i)<\|(?:im_start|im_end|endoftext|system|assistant)\|>|</?(?:system|assistant|tool_call|function_call)[^>]{0,40}>")),
    ("exfiltration", re.compile(
        r"(?i)\b(?:exfiltrate|upload|send|post|leak)\b[^.\n]{0,40}"
        r"\b(?:secret|token|api[_ ]?key|credential|password|\.env)\b")),
    ("forced_execution", re.compile(
        r"(?i)\b(?:execute|run|eval)\b[^.\n]{0,20}\b(?:this|the following)\b"
        r"[^.\n]{0,20}\b(?:command|code|script|payload)\b")),
    ("encoded_payload", re.compile(r"(?i)\bbase64\s*:\s*[A-Za-z0-9+/=]{80,}")),
]

ENTROPY_TOKEN = re.compile(r"[A-Za-z0-9+/=_-]{%d,}" % HIGH_ENTROPY_MIN_LENGTH)
HEX_ONLY = re.compile(r"[0-9a-fA-F]+")


def _entropy(value: str) -> float:
    counts: dict[str, int] = {}
    for character in value:
        counts[character] = counts.get(character, 0) + 1
    total = len(value)
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _mask(kind: str, strategy: str, match: re.Match) -> str:
    if strategy == "env":
        return match.group(1) + match.group(2) + f"[REDACTED:{kind}]" + match.group(2)
    if strategy == "uri":
        return match.group(1) + f"[REDACTED:{kind}]@"
    if strategy == "bearer":
        return match.group(1) + match.group(2) + f"[REDACTED:{kind}]"
    return f"[REDACTED:{kind}]"


def _high_entropy_tokens(text: str) -> list[tuple[int, str]]:
    found = []
    for match in ENTROPY_TOKEN.finditer(text):
        token = match.group(0)
        if HEX_ONLY.fullmatch(token):
            continue
        classes = sum((
            any(character.islower() for character in token),
            any(character.isupper() for character in token),
            any(character.isdigit() for character in token),
            any(character in "+/=_-" for character in token),
        ))
        if classes >= 3 and _entropy(token) >= HIGH_ENTROPY_THRESHOLD:
            found.append((match.start(), token))
    return found


def scan(text: str) -> dict:
    """Report secret and injection findings without echoing sensitive values."""
    sample = (text or "")[:MAX_SCAN_CHARS]
    findings = []
    secrets = 0
    injection = 0
    for kind, pattern, _strategy in SECRET_RULES:
        for match in pattern.finditer(sample):
            findings.append({"category": "secret", "kind": kind,
                             "line": _line_of(sample, match.start())})
            secrets += 1
    for start, _token in _high_entropy_tokens(sample):
        findings.append({"category": "secret", "kind": "high_entropy",
                         "line": _line_of(sample, start)})
        secrets += 1
    for kind, pattern in INJECTION_RULES:
        for match in pattern.finditer(sample):
            findings.append({"category": "injection", "kind": kind,
                             "line": _line_of(sample, match.start())})
            injection += 1
    if secrets:
        risk = "high"
    elif injection:
        risk = "medium"
    else:
        risk = "none"
    return {
        "risk": risk,
        "secrets": secrets,
        "injection": injection,
        "findings": findings[:100],
        "truncated": len(text or "") > MAX_SCAN_CHARS,
    }


def redact(text: str) -> tuple[str, dict]:
    """Return redacted text plus a findings report for the original input."""
    sample = (text or "")[:MAX_SCAN_CHARS]
    report = scan(sample)
    redacted = sample
    for kind, pattern, strategy in SECRET_RULES:
        redacted = pattern.sub(lambda match, k=kind, s=strategy: _mask(k, s, match), redacted)
    for start, token in _high_entropy_tokens(sample):
        redacted = redacted.replace(token, "[REDACTED:high_entropy]")
    return redacted, report


def scan_and_redact(text: str) -> dict:
    redacted, report = redact(text)
    return {"text": redacted, "safety": report}
