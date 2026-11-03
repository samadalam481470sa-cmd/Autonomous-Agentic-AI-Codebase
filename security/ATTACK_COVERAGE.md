# Attack coverage matrix

This file is generated from `services/api/hardening.py` (the same data is
served by the authenticated `GET /api/security/coverage` endpoint). Status
values are deliberately honest:

- `mitigated` - an application-layer control blocks or contains the class.
- `partial` - meaningful controls exist, but a platform control, product
  scope limit, or residual risk remains.
- `delegated` - the attack is outside this process's trust boundary
  (network, endpoint, mail, hypervisor) and needs a platform control.
- `not_applicable` - the feature does not exist in this build.

No software is unhackable. This matrix documents what is actually
implemented, not a guarantee of immunity.

## Coverage at a glance

| Status | Count |
| --- | --- |
| mitigated | 11 |
| partial | 23 |
| delegated | 14 |
| not_applicable | 2 |
| **total** | **50** |

## Controls by threat

| # | Category | Attack | Status | Implemented controls |
| --- | --- | --- | --- | --- |
| 1 | Network | DDoS | `partial` | Per-address sliding-window limits with Retry-After; Header and body ceilings; bounded request parsing; Volumetric absorption still requires an edge/proxy |
| 2 | Network | Man-in-the-middle | `partial` | HSTS on HTTPS; no secrets in caches or logs; Token kept in page memory; TLS termination required |
| 3 | Network | DNS spoofing | `delegated` | TLS plus HSTS mitigate impersonation; Resolver and DNSSEC policy are platform responsibilities |
| 4 | Network | ARP spoofing | `delegated` | Application traffic integrity depends on TLS; Requires network segmentation or port security |
| 5 | Network | Packet sniffing | `partial` | No plaintext token persistence; no-store responses; TLS at the proxy is required for on-wire confidentiality |
| 6 | Application | SQL injection | `mitigated` | All SQL uses bound parameters; Structured-field SQLi signatures block at the edge; Static audit flags string-built SQL |
| 7 | Application | Cross-site scripting | `partial` | CSP, nosniff, frame denial and JSON-only API; Sandboxed preview iframe; escaping on render; Bundled editor requires unsafe-inline/unsafe-eval |
| 8 | Application | CSRF | `mitigated` | Header-token authentication, no ambient cookies; Origin allowlist and Sec-Fetch-Site rejection |
| 9 | Application | Remote code execution | `partial` | Host execution disabled by default; no shell; Allowlisted networkless Docker with cap-drop; Command-injection and deserialization signatures |
| 10 | Application | SSRF | `mitigated` | Model and delegation endpoints restricted to loopback; DNS-safe guard rejects private and metadata addresses; Redirects disabled on outbound clients |
| 11 | Identity | Credential stuffing | `partial` | Per-address lockouts plus global failure cooldown; Distributed guessing degrades to a service-wide pause |
| 12 | Identity | Brute force | `mitigated` | Constant-time digest comparison; Exponential lockout with capped escalation; Optional TOTP second factor |
| 13 | Identity | Password spraying | `partial` | Global failure-rate cooldown across addresses; Generic error messages and no account enumeration |
| 14 | Identity | Session hijacking | `partial` | No cookie sessions; per-request bearer token; No token in local storage; HSTS when TLS is present |
| 15 | Identity | MFA fatigue | `partial` | TOTP rather than push approval; MFA failures feed the lockout and global cooldown; Failed MFA attempts are audited |
| 16 | Malware | Ransomware | `partial` | Diff approval, atomic writes and reversible checkpoints; Read-only container root; database on an isolated volume; Bulk-write and egress limits raise the cost of mass theft |
| 17 | Malware | Trojan horse | `delegated` | Pinned dependencies and license verification; Endpoint malware protection is outside this process |
| 18 | Malware | Rootkit | `delegated` | Container runs non-root with all capabilities dropped; Host integrity monitoring is a platform control |
| 19 | Malware | Spyware | `delegated` | No telemetry; outbound inference is operator-configured; Endpoint scanning is outside this process |
| 20 | Malware | Worm | `delegated` | No inbound peer-to-peer surface; networkless execution; Network egress policy is a platform control |
| 21 | Cloud | Cloud storage exposure | `mitigated` | No cloud object storage binding in this build; Static-mount audit rejects protected directories; No directory listing or path-joined file serving |
| 22 | Cloud | IAM privilege escalation | `partial` | Single administrator role; no cloud IAM in-app; Non-root container with capabilities dropped |
| 23 | Cloud | Cloud API key theft | `partial` | Keys read from environment only, never logged; Secret redaction before prompts and excerpts; Audit records events, never credential values |
| 24 | Cloud | Container escape | `partial` | cap-drop ALL, no-new-privileges, read-only rootfs; No Docker socket; networkless execution container; Containers are not a hard security boundary |
| 25 | Cloud | Kubernetes cluster compromise | `partial` | Hardened manifests with dropped capabilities; Cluster RBAC and admission control are platform controls |
| 26 | Financial | Account takeover | `partial` | Digest-compared token plus optional TOTP; Lockout, global cooldown and rate limits |
| 27 | Financial | Payment fraud | `not_applicable` | No payment processing or card data in this build |
| 28 | Financial | Business email compromise | `delegated` | No mail transport in this build; Email authentication is a provider control |
| 29 | Financial | Transaction manipulation | `mitigated` | Human approval header on every write; SHA-256 conflict check before apply/restore; Atomic replace with a reversible checkpoint |
| 30 | Financial | API abuse | `mitigated` | Authentication on every route except /health; Per-route rate buckets, body caps and egress budget; Generic errors and request IDs for correlation |
| 31 | Social engineering | Phishing | `delegated` | No credential-collection UI beyond the operator token; Operator training and mail filtering are external |
| 32 | Social engineering | Spear phishing | `delegated` | Out of scope for the application; user awareness required |
| 33 | Social engineering | Whaling | `delegated` | Out of scope for the application; organizational control |
| 34 | Social engineering | Vishing | `delegated` | Out of scope for the application; organizational control |
| 35 | Social engineering | Deepfake impersonation | `delegated` | Out of scope; out-of-band verification is an organizational control |
| 36 | Database and data | Data exfiltration | `partial` | Per-caller egress budget with 429 and Retry-After; Large responses audited; no bulk export endpoint; Execution container has no network |
| 37 | Database and data | Insider data theft | `partial` | Tamper-evident HMAC audit chain; Single-operator model lacks per-user least privilege |
| 38 | Database and data | Database misconfiguration | `mitigated` | Embedded SQLite; no network listener or default credentials; Bound parameters and foreign keys enabled; Database and audit files are gitignored |
| 39 | Database and data | Insecure deserialization | `mitigated` | JSON-only request parsing; no pickle or unsafe YAML; Deserialization signatures blocked on structured fields |
| 40 | Database and data | Backup data exposure | `partial` | No backup endpoint; database files are gitignored; Static-mount audit; full-disk encryption recommended |
| 41 | Supply chain | Dependency confusion | `mitigated` | Lockfiles pin resolved versions; scoped package registry; security_audit.py checks pins and lockfile presence |
| 42 | Supply chain | Malicious software update | `partial` | No auto-update channel; pinned base images recommended; Release artifacts must be verified before rollout |
| 43 | Supply chain | CI/CD pipeline compromise | `partial` | Read-only workflow permissions and no production secrets; Action pinning checked by the audit script |
| 44 | Supply chain | Open-source package poisoning | `partial` | Registered permissive dependencies with notices; Transitive dependency risk remains; review before upgrade |
| 45 | Supply chain | Repository secret exposure | `mitigated` | Secret scan in CI and pre-commit workflow; Redaction before prompts; .env gitignored |
| 46 | Advanced | Zero-day exploitation | `partial` | Minimal dependency surface and fail-closed authentication; Audit trail and anomaly limits contain blast radius |
| 47 | Advanced | Advanced persistent threat | `partial` | Tamper-evident audit chain and global anomaly cooldown; Long-dwell detection needs external SIEM |
| 48 | Advanced | Firmware compromise | `delegated` | Secure boot and firmware attestation are platform controls |
| 49 | Advanced | Active Directory compromise | `not_applicable` | No Active Directory integration in this build |
| 50 | Advanced | Hypervisor escape | `delegated` | VM isolation and hypervisor patching are platform controls |

## Verify

```bash
AGENT_ADMIN_TOKEN=test-token python -m pytest -q tests/test_hardening.py
python scripts/security_audit.py --fail-on high
```

The runtime matrix covers {rules} injection rules, a per-caller egress budget
of 67108864 bytes/minute and an HMAC-chained audit trail.

