# Secure Microservice Architecture

## JWT Auth · CORS Policy · Rate Limiting · Audit Logging

> **Audience**: Architects and developers building production-grade microservices.
> **Scope**: Four interdependent security layers that protect every request from edge to data.
> **Prior art**: See [`docs/auth-architecture.md`](./auth-architecture.md) for detailed JWT token design
> and rate-limiting algorithms. This document unifies those with CORS and audit logging into a single architecture.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Layer 1 — CORS Policy (Edge Gateway)](#2-layer-1--cors-policy-edge-gateway)
3. [Layer 2 — JWT Authentication (Identity)](#3-layer-2--jwt-authentication-identity)
4. [Layer 3 — Rate Limiting (Traffic Control)](#4-layer-3--rate-limiting-traffic-control)
5. [Layer 4 — Audit Logging (Observability)](#5-layer-4--audit-logging-observability)
6. [Integration: Request Lifecycle](#6-integration-request-lifecycle)
7. [Implementation Guide](#7-implementation-guide)
8. [Security Checklist](#8-security-checklist)

---

## 1. Architecture Overview

```
                          ┌──────────────────────────────────────┐
                          │          Internet / Clients          │
                          └────────────────┬─────────────────────┘
                                           │
                                    ╔══════╧══════╗
                                    ║  Layer 1    ║
                                    ║  CORS       ║  ← Origin validation, preflight
                                    ║  Gateway    ║     Security headers (HSTS, CSP)
                                    ╚══════╤══════╝
                                           │
                                    ╔══════╧══════╗
                                    ║  Layer 2    ║
                                    ║  JWT Auth   ║  ← Token validation, scope check
                                    ║  Service    ║     Refresh rotation, revocation
                                    ╚══════╤══════╝
                                           │
                                    ╔══════╧══════╗
                                    ║  Layer 3    ║
                                    ║  Rate       ║  ← Global / per-user / per-endpoint
                                    ║  Limiter    ║     Token bucket + sliding window
                                    ╚══════╤══════╝
                                           │
                              ┌────────────┼────────────┐
                              │            │            │
                         ┌────┴────┐ ┌────┴────┐ ┌────┴────┐
                         │Service A│ │Service B│ │Service C│
                         │(API)    │ │(Auth)   │ │(Data)   │
                         └────┬────┘ └────┬────┘ └────┬────┘
                              │            │            │
                              └────────────┼────────────┘
                                           │
                                    ╔══════╧══════╗
                                    ║  Layer 4    ║
                                    ║  Audit      ║  ← Structured logs, tamper chain
                                    ║  Pipeline   ║     SIEM forward, alert rules
                                    ╚═════════════╝
```

### Layered Defense Principle

| Layer | Protection | Stateless? | Failure Mode |
|-------|-----------|------------|-------------|
| **1. CORS** | Prevents cross-origin abuse from browsers | ✅ Yes | Reject with 403 |
| **2. JWT** | Verifies identity and permissions | ✅ Yes (AT) | Reject with 401/403 |
| **3. Rate Limit** | Prevents abuse and DoS | ❌ No (Redis) | Delay with 429 |
| **4. Audit** | Records everything for forensics | ❌ No (DB/Log) | Fail-open (async) |

---

## 2. Layer 1 — CORS Policy (Edge Gateway)

### 2.1 Why CORS Matters in Microservices

CORS (Cross-Origin Resource Sharing) is the browser's gatekeeper. Without it, any
website can make authenticated requests to your API on behalf of a logged-in user.
In a microservice architecture, CORS must be:

- **Per-service granular**: Different origins for public API vs. admin panel
- **Environment-aware**: Strict in production, permissive in development
- **Audit-compatible**: Every rejected cross-origin request is logged

### 2.2 Policy Model

```python
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CORSOrigin:
    """A single allowed origin with its specific policy."""
    origin: str
    allow_credentials: bool = True
    max_age: int = 7200
    expose_headers: tuple[str, ...] = ("X-Request-Id", "X-RateLimit-Remaining")


@dataclass(frozen=True)
class CORSPolicy:
    """Complete CORS policy for one service."""
    allowed_origins: tuple[CORSOrigin, ...] = ()
    allow_methods: tuple[str, ...] = (
        "GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"
    )
    allow_headers: tuple[str, ...] = (
        "Content-Type",
        "Authorization",
        "X-Request-Id",
        "X-CSRF-Token",
    )
    deny_empty_origin: bool = True

    def match(self, origin: str | None) -> CORSOrigin | None:
        """Match an incoming Origin against the allowed list."""
        if not origin:
            return None
        for allowed in self.allowed_origins:
            if allowed.origin == origin:
                return allowed
        return None
```

### 2.3 Environment Profiles

```yaml
# config/cors.yaml
environments:
  development:
    mode: permissive
    allowed_origins:
      - "http://localhost:3000"
      - "http://localhost:5173"      # Vite dev
      - "http://127.0.0.1:4173"     # Vite preview
      - "http://127.0.0.1:8765"     # API server itself
    allow_credentials: true
    allow_methods: ["*"]

  staging:
    mode: strict
    allowed_origins:
      - "https://staging.app.example.com"
      - "https://staging-api.example.com"
    preflight_max_age: 300

  production:
    mode: strictest
    allowed_origins:
      - "https://app.example.com"
      - "https://admin.example.com"
    preflight_max_age: 7200
    deny_empty_origin: true
```

### 2.4 CORS Middleware (FastAPI)

```python
from fastapi import Request, Response
from starlette.types import ASGIApp


class SecureCORSMiddleware:
    """CORS middleware with audit logging and security headers."""

    def __init__(self, app: ASGIApp, policy: CORSPolicy, audit=None):
        self.app = app
        self.policy = policy
        self.audit = audit

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        origin = request.headers.get("origin")

        if origin and origin != "null":
            matched = self.policy.match(origin)
            if not matched:
                if self.audit:
                    await self.audit.log(
                        event_type="cors_violation",
                        metadata={
                            "origin": origin,
                            "path": request.url.path,
                            "method": request.method,
                        },
                    )
                response = Response(
                    status_code=403,
                    content='{"error":"origin_not_allowed"}',
                    media_type="application/json",
                )
                await response(scope, receive, send)
                return

        if request.method == "OPTIONS":
            response = Response(status_code=204)
            self._apply_cors_headers(response, origin, matched)
            await response(scope, receive, send)
            return

        async def send_with_cors(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                response = Response(status_code=message["status"])
                response.headers.update(
                    (k.decode(), v.decode()) for k, v in headers.items()
                )
                self._apply_cors_headers(response, origin, matched)
                response.headers["X-Content-Type-Options"] = "nosniff"
                response.headers["X-Frame-Options"] = "DENY"
                response.headers["X-XSS-Protection"] = "1; mode=block"
                response.headers["Strict-Transport-Security"] = (
                    "max-age=31536000; includeSubDomains"
                )
                message["headers"] = list(response.headers.items())
            await send(message)

        await self.app(scope, receive, send_with_cors)

    def _apply_cors_headers(self, response, origin, matched):
        if matched:
            response.headers["Access-Control-Allow-Origin"] = matched.origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = ", ".join(
                self.policy.allow_methods
            )
            response.headers["Access-Control-Allow-Headers"] = ", ".join(
                self.policy.allow_headers
            )
            if matched.expose_headers:
                response.headers["Access-Control-Expose-Headers"] = ", ".join(
                    matched.expose_headers
                )
            response.headers["Access-Control-Max-Age"] = str(matched.max_age)
```

### 2.5 Harden CORS Against Common Attacks

| Attack | Mitigation |
|--------|-----------|
| **`null` origin injection** | Reject `Origin: null` unless explicitly needed |
| **Wildcard + credentials** | Never use `Access-Control-Allow-Origin: *` with credentials |
| **Preflight cache poisoning** | Set `max-age` conservatively (≤ 2 hours) |
| **Reflected origin** | Never echo back the request Origin verbatim |
| **Internal DNS rebinding** | Validate `Host` header matches expected domain |

> **Golden rule**: If the request has an `Origin` header that doesn't match,
> **reject at the gateway** before any auth or business logic runs.

---

## 3. Layer 2 — JWT Authentication (Identity)

> **Full design**: See [`docs/auth-architecture.md`](./auth-architecture.md) for:
> - Dual-token model (Access + Refresh)
> - Refresh Token Rotation with reuse detection
> - Token blacklist (JTI revocation)
> - Key rotation and management
> - Password hashing (bcrypt cost=12)

### 3.1 Integration Summary

```
┌──────────┐         ┌──────────────┐         ┌──────────────┐
│  Client  │  ───►   │  API Gateway │  ───►   │  Auth        │
│          │  AT+RT  │  (Validate   │         │  Service     │
│          │  ◄───   │   JWT, CORS) │  ◄───   │  (Issue/     │
│          │         │              │         │   Rotate)    │
└──────────┘         └──────────────┘         └──────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │  Redis       │
                    │  (JTI black- │
                    │   list cache)│
                    └──────────────┘
```

### 3.2 Service-to-Service Auth

For internal microservice communication, use a **separate JWT with a shorter TTL**
and a different audience:

```python
def create_service_token(
    service_name: str,
    target_service: str,
    ttl_seconds: int = 60,
) -> str:
    """Short-lived JWT for service-to-service auth."""
    now = int(time.time())
    payload = {
        "sub": f"svc:{service_name}",
        "aud": target_service,
        "iss": "api-gateway",
        "iat": now,
        "exp": now + ttl_seconds,
        "jti": uuid.uuid4().hex,
        "type": "service",
    }
    return jwt.encode(payload, SERVICE_SIGNING_KEY, algorithm="HS256")
```

Internal tokens are:
- **Short-lived** (60 seconds) — no refresh needed
- **Scoped** to specific target services via `aud` claim
- **Not rate-limited** (bypass Layer 3)

---

## 4. Layer 3 — Rate Limiting (Traffic Control)

> **Full design**: See [`docs/auth-architecture.md`](./auth-architecture.md) for:
> - Three-layer architecture (Global → Per-User → Per-Endpoint)
> - Sliding Window Log algorithm
> - Redis key structure
> - Account lockout for login endpoints

### 4.1 Distributed Rate Limiting with Redis

```
         ┌────────────┐
         │   Client   │
         └─────┬──────┘
               │
         ┌─────▼──────┐
         │  API GW    │
         │  (Layer 1) │  ← Global limit: 10,000 req/min
         └─────┬──────┘
               │
         ┌─────▼──────┐
         │  Auth MW   │
         │  (Layer 2) │  ← Per-user: 30 req/min
         └─────┬──────┘
               │
         ┌─────▼──────┐
         │  Business  │
         │  (Layer 3) │  ← Per-endpoint: 5 req/min (/auth/login)
         └────────────┘
               │
         ┌─────▼──────┐
         │   Redis    │
         │  (Backend) │
         └────────────┘
```

### 4.2 Rate Limit Response Headers

Every response must carry the current rate limit state:

```python
@dataclass
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_at: int        # Unix timestamp
    retry_after: int = 0 # Seconds (only for 429)


def apply_rate_limit_headers(response, result: RateLimitResult) -> None:
    response.headers["X-RateLimit-Limit"] = str(result.limit)
    response.headers["X-RateLimit-Remaining"] = str(result.remaining)
    response.headers["X-RateLimit-Reset"] = str(result.reset_at)
    if not result.allowed:
        response.status_code = 429
        response.headers["Retry-After"] = str(result.retry_after)
```

### 4.3 Redis Cluster Configuration

```python
RATE_LIMIT_CONFIG = {
    "cluster_nodes": [
        {"host": "redis-1.internal", "port": 6379},
        {"host": "redis-2.internal", "port": 6379},
        {"host": "redis-3.internal", "port": 6379},
    ],
    "key_prefix": "rl:",
    "default_ttl": 300,
    "sliding_window_size": 60,
    "max_pipeline_calls": 100,
    "fallback_mode": "allow",  # Fail-open on Redis failure
}
```

> **Fail-open vs fail-close**: Rate limiting should **fail-open** (allow requests
> when Redis is down) to avoid killing the service. Auth should **fail-close**
> (deny when DB is down).

---

## 5. Layer 4 — Audit Logging (Observability)

### 5.1 Audit Event Model

Every auditable event is a structured record:

```python
from dataclasses import dataclass, field, asdict
from typing import Any
import json
import hashlib


@dataclass
class AuditEvent:
    """Immutable audit event — never modified after creation."""
    event_type: str
    timestamp: str                       # ISO 8601, set at creation
    service: str                         # Originating service
    trace_id: str                        # Distributed tracing ID
    user_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    resource: str | None = None          # e.g., "/api/orders"
    action: str | None = None            # e.g., "CREATE", "DELETE"
    status: str = "success"              # success, failure, blocked
    metadata: dict[str, Any] = field(default_factory=dict)
    previous_hash: str = ""              # Tamper-evident chain

    def serialize(self) -> str:
        """Deterministic JSON (sorted keys)."""
        return json.dumps(
            asdict(self), sort_keys=True, default=str, ensure_ascii=False
        )

    @property
    def hash(self) -> str:
        """SHA-256 digest of the serialized event."""
        return hashlib.sha256(self.serialize().encode()).hexdigest()
```

### 5.2 Event Types

| Event Type | When Triggered | Who |
|-----------|---------------|-----|
| `cors_violation` | Origin not in allow-list | Gateway/CORS MW |
| `login` | Successful password verification | Auth Service |
| `login_failure` | Wrong password or MFA failure | Auth Service |
| `login_blocked` | Account locked (5 failures) | Auth Service |
| `token_refresh` | Refresh token rotated | Auth Service |
| `token_reuse` | Token reuse detected (theft) | Auth Service |
| `token_revoke` | Manual session revocation | Auth Service |
| `logout` | User-initiated logout | Auth Service |
| `rate_limit_exceeded` | Request denied by rate limiter | Rate Limit MW |
| `api_access` | Successful API request | Each service |
| `api_denied` | Forbidden by scope/permission | Authorization MW |
| `user_created` | New user registration | User Service |
| `user_deleted` | Account deletion | User Service |
| `config_change` | Security configuration modified | Admin Service |

### 5.3 Tamper-Evident Audit Chain

Each audit event contains the hash of the previous event:

```
┌────────────┐     ┌────────────┐     ┌────────────┐
│ Event #1   │     │ Event #2   │     │ Event #3   │
│            │     │            │     │            │
│ hash=H1    │────►│ prev=H1    │────►│ prev=H2    │
│ prev=""    │     │ hash=H2    │     │ hash=H3    │
└────────────┘     └────────────┘     └────────────┘
```

```python
class AuditChain:
    """Append-only audit chain with tamper detection."""

    def __init__(self, storage):
        self.storage = storage

    async def append(self, event: AuditEvent) -> str:
        """Append event, return its hash."""
        last = await self.storage.get_last()
        event.previous_hash = last.hash if last else ""
        event_hash = event.hash
        await self.storage.insert(event_hash,
                                   event.serialize(),
                                   event.previous_hash)
        return event_hash

    async def verify_integrity(self) -> list[str]:
        """Walk chain, verify hashes. Return broken links."""
        broken = []
        current = await self.storage.get_last()
        while current and current.previous_hash:
            expected = hashlib.sha256(
                current.serialize().encode()
            ).hexdigest()
            if expected != current.hash:
                broken.append(f"Hash mismatch at {current.timestamp}")
            previous = await self.storage.get_by_hash(
                current.previous_hash
            )
            if not previous:
                broken.append(
                    f"Missing predecessor: {current.previous_hash}"
                )
                break
            current = previous
        return broken
```

### 5.4 Audit Pipeline (Log → Store → Forward)

```
   Service
   ┌────────────┐
   │  Generate  │
   │  Event     │───┐
   └────────────┘   │
                    ▼
           ┌────────────────┐
           │  Buffer        │  ← In-memory ring buffer (async)
           │  (RingBuffer)  │     512 events per service
           └───────┬────────┘
                   │ flush (batch every 1s or 100 events)
                   ▼
           ┌────────────────┐
           │  Storage       │  ← PostgreSQL (JSONB)
           │  (Audit DB)    │     Redis cache (recent 1000)
           └───────┬────────┘
                   │ stream
                   ▼
           ┌────────────────┐
           │  Forwarder     │  ← Kafka topic "audit"
           │  (Kafka/S3)    │     S3 Parquet (hourly)
           └───────┬────────┘
                   │
                   ▼
           ┌────────────────┐
           │  SIEM          │  ← Elasticsearch / Splunk
           │  (Search +     │     Alert rules, dashboards
           │   Alerts)      │
           └────────────────┘
```

```python
import asyncio
from collections import deque


class AuditBuffer:
    """Async ring buffer for audit events.

    Flushes at capacity (size=N) or interval (T).
    """

    def __init__(self, storage, max_size: int = 100,
                 flush_interval: float = 1.0):
        self.storage = storage
        self.buffer: deque[AuditEvent] = deque(maxlen=max_size * 2)
        self.max_size = max_size
        self.flush_interval = flush_interval
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    async def emit(self, event: AuditEvent) -> None:
        async with self._lock:
            self.buffer.append(event)
            if len(self.buffer) >= self.max_size:
                await self._flush()

    async def _flush(self) -> None:
        events = list(self.buffer)
        self.buffer.clear()
        if events:
            await self.storage.batch_insert(events)

    async def start(self) -> None:
        async def _loop():
            while True:
                await asyncio.sleep(self.flush_interval)
                async with self._lock:
                    if self.buffer:
                        await self._flush()

        self._task = asyncio.create_task(_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        await self._flush()
```

### 5.5 Audit Log Storage Schema

```sql
CREATE TABLE audit_events (
    id              BIGSERIAL PRIMARY KEY,
    event_hash      TEXT NOT NULL UNIQUE,
    previous_hash   TEXT NOT NULL DEFAULT '',
    event_type      TEXT NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL,
    service         TEXT NOT NULL,
    trace_id        TEXT NOT NULL,
    user_id         TEXT,
    ip_address      INET,
    user_agent      TEXT,
    resource        TEXT,
    action          TEXT,
    status          TEXT NOT NULL DEFAULT 'success',
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT fk_previous_hash
        FOREIGN KEY (previous_hash) REFERENCES audit_events(event_hash)
);

CREATE INDEX idx_audit_event_type  ON audit_events(event_type, timestamp);
CREATE INDEX idx_audit_user        ON audit_events(user_id, timestamp);
CREATE INDEX idx_audit_trace       ON audit_events(trace_id);
CREATE INDEX idx_audit_timestamp   ON audit_events(timestamp DESC);

-- Partition by month
CREATE TABLE audit_events_y2024m01 PARTITION OF audit_events
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
CREATE TABLE audit_events_y2024m02 PARTITION OF audit_events
    FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');
```

### 5.6 Alert Rules (SIEM)

```yaml
# config/alert-rules.yaml
alerts:
  - name: brute_force_login
    description: "> 10 login failures in 5 minutes from one IP"
    query: >
      SELECT COUNT(*) FROM audit_events
      WHERE event_type = 'login_failure'
        AND timestamp > now() - interval '5 minutes'
        AND ip_address = $ip
    threshold: 10
    severity: high
    action: notify_security

  - name: token_reuse_theft
    description: "Refresh token reuse detected"
    query: >
      SELECT COUNT(*) FROM audit_events
      WHERE event_type = 'token_reuse'
        AND timestamp > now() - interval '1 hour'
    threshold: 1
    severity: critical
    action: revoke_family + notify_user

  - name: cors_scanning
    description: "> 50 CORS violations in 1 minute"
    query: >
      SELECT COUNT(*) FROM audit_events
      WHERE event_type = 'cors_violation'
        AND timestamp > now() - interval '1 minute'
    threshold: 50
    severity: medium
    action: rate_block_origin

  - name: audit_chain_break
    description: "Tamper-evident chain integrity check failed"
    query: >
      SELECT COUNT(*) FROM verify_audit_chain()
      WHERE broken_links > 0
    threshold: 0
    severity: critical
    action: incident_response
```

---

## 6. Integration: Request Lifecycle

Every request passes through all four layers in order:

```
Request: POST /api/orders
Origin: https://app.example.com
Authorization: Bearer eyJ...

Step 1: CORS Gateway
├── Origin matches policy?      ✅ → Allow
├── Preflight (OPTIONS)?        ❌ → Continue
├── Security headers applied    ✅ → HSTS, X-Frame-Options
└── Audit: —                    (no event — allowed)

Step 2: JWT Auth Middleware
├── Authorization header?       ✅ → Bearer eyJ...
├── Signature valid?            ✅ → HS256 verified
├── Token expired?              ❌ → exp check passed
├── JTI blacklisted?            ❌ → Not revoked
├── Scope sufficient?           ✅ → "api:write"
├── Inject user context         ✅ → user_id = "user_abc123"
└── Audit: "api_access"         ✅ → Written to buffer

Step 3: Rate Limiter
├── Global (10,000/min)         ✅ → Remaining: 9,871
├── Per-user (300/min)          ✅ → Remaining: 287
├── Per-endpoint (100/min)      ✅ → Remaining: 94
├── Headers applied             ✅ → X-RateLimit-Remaining: 94
└── Audit: —                    (no event — allowed)

Step 4: Business Logic (Service)
├── Create order in database    ✅ → Order #ORD-001
├── Return 201 Created          ✅
└── Audit: "api_access"         ✅ → status=success

Response: 201 Created
Headers:
  Access-Control-Allow-Origin: https://app.example.com
  X-Content-Type-Options: nosniff
  Strict-Transport-Security: max-age=31536000
  X-RateLimit-Remaining: 287, 94, 9871
  X-Request-Id: trace_uuid
```

### Failure Scenarios

| Failure | CORS | JWT | Rate Limit | Audit |
|---------|------|-----|------------|-------|
| Unknown origin `evil.com` | **403** ❌ | — | — | `cors_violation` |
| Expired access token | ✅ Pass | **401** ❌ | — | `api_denied` |
| Theft: reused refresh token | ✅ Pass | Detected in rotation | — | `token_reuse` **critical** |
| 1000 req/min from one IP | ✅ Pass | ✅ Pass | **429** ❌ | `rate_limit_exceeded` |
| Redis cluster down | ✅ Pass | ✅ Pass | **Fail-open** | — |
| Audit DB unavailable | ✅ Pass | ✅ Pass | ✅ Pass | **Fail-open** |

---

## 7. Implementation Guide

### 7.1 Adding to `gui_server.py`

The current `GUIRequestHandler` in `src/next_agent/gui_server.py` already has
basic CORS headers (lines 386-388). Retrofitting all four layers:

```python
# ── Step 1: Import security modules ─────────────────────────────
from .cors_policy import CORSPolicy, CORSOrigin, SecureCORSMiddleware
from .rate_limiter import RateLimiter, RateLimitResult
from .audit_logger import AuditLogger, AuditBuffer, AuditEvent


# ── Step 2: Create secure server factory ────────────────────────
def create_secure_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    workdir: str | None = None,
    static_dir: str | Path | None = None,
    environment: str = "development",
) -> ThreadingHTTPServer:
    store = SessionStore(workdir or os.getcwd())

    # Load CORS policy from config
    cors_config = load_cors_config(environment)
    cors_policy = CORSPolicy(
        allowed_origins=tuple(
            CORSOrigin(origin=o["origin"])
            for o in cors_config["allowed_origins"]
        ),
        deny_empty_origin=cors_config.get("deny_empty_origin", True),
    )

    # Initialize audit logger
    audit_logger = AuditLogger(
        service="next-agent-core",
        db_url=os.environ.get("AUDIT_DB_URL", "sqlite:///audit.db"),
    )

    # Initialize rate limiter
    rate_limiter = RateLimiter(
        redis_url=os.environ.get("REDIS_URL",
                                 "redis://localhost:6379/0"),
        config=RATE_LIMIT_CONFIG,
    )

    # Create handler with security dependencies
    handler = type(
        "SecureGUIRequestHandler",
        (GUIRequestHandler,),
        {
            "store": store,
            "static_dir": Path(static_dir).resolve()
                          if static_dir else None,
            "cors_policy": cors_policy,
            "audit_logger": audit_logger,
            "rate_limiter": rate_limiter,
        },
    )
    return ThreadingHTTPServer((host, port), handler)
```

### 7.2 Rate Limiter Integration

```python
async def _check_rate_limits(self) -> bool:
    """Check all rate limit layers. Return True if allowed."""
    client_ip = self.client_address[0]
    user_id = getattr(self, "user_id", None)
    endpoint = urlparse(self.path).path

    # Layer 1: Global
    global_result = await self.rate_limiter.check(
        key="global", limit=10000, window=60,
    )
    if not global_result.allowed:
        await self._send_rate_limited(global_result)
        return False

    # Layer 2: Per-user (if authenticated)
    if user_id:
        user_result = await self.rate_limiter.check(
            key=f"user:{user_id}", limit=300, window=60,
        )
        if not user_result.allowed:
            await self._send_rate_limited(user_result)
            return False

    # Layer 3: Per-endpoint
    if endpoint in ("/auth/login",):
        ep_result = await self.rate_limiter.check(
            key=f"endpoint:{endpoint}:{client_ip}",
            limit=5, window=60,
        )
        if not ep_result.allowed:
            await self._send_rate_limited(ep_result)
            return False

    return True
```

### 7.3 Audit Logger Integration

```python
async def _log_api_access(
    self, event_type: str, status: str = "success", **metadata
) -> None:
    """Emit an audit event asynchronously."""
    event = AuditEvent(
        event_type=event_type,
        timestamp=datetime.utcnow().isoformat() + "Z",
        service="next-agent-core",
        trace_id=self.headers.get("X-Request-Id",
                                   uuid.uuid4().hex),
        user_id=getattr(self, "user_id", None),
        ip_address=self.client_address[0],
        user_agent=self.headers.get("User-Agent"),
        resource=urlparse(self.path).path,
        action=self.command,
        status=status,
        metadata=metadata,
    )
    await self.audit_logger.buffer.emit(event)
```

### 7.4 Refactoring the Current CORS Headers

Replace the hardcoded CORS in `_send()` with policy-driven headers:

```python
# Current (gui_server.py:386-388):
self.send_header("Access-Control-Allow-Origin",
                 "http://127.0.0.1:4173")

# Refactored:
def _send(self, status: int, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False,
                      default=str).encode("utf-8")
    self.send_response(status)
    self.send_header("Content-Type",
                     "application/json; charset=utf-8")
    self.send_header("Content-Length", str(len(body)))

    # Apply CORS from policy
    origin = self.headers.get("origin")
    matched = self.cors_policy.match(origin) if origin else None
    if matched:
        self.send_header("Access-Control-Allow-Origin",
                         matched.origin)
        self.send_header("Access-Control-Allow-Credentials",
                         "true")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods",
                         "GET, POST, OPTIONS")

    # Security headers
    self.send_header("X-Content-Type-Options", "nosniff")
    self.send_header("X-Frame-Options", "DENY")

    self.end_headers()
    self.wfile.write(body)
```

---

## 8. Security Checklist

Use this checklist when deploying to production:

### CORS
- [ ] Allowed origins are explicit (no wildcard `*` with credentials)
- [ ] `OPTIONS` preflight returns correct headers
- [ ] `Origin` header is validated, not echoed
- [ ] `null` origin is blocked unless explicitly needed
- [ ] Preflight `max-age` ≤ 7200 seconds
- [ ] Security headers: `X-Content-Type-Options: nosniff`,
      `X-Frame-Options: DENY`, `Strict-Transport-Security`

### JWT
- [ ] Access Token expiry ≤ 15 minutes
- [ ] Refresh Token rotation is implemented
- [ ] Token reuse detection activates on refresh
- [ ] JTI blacklist cache is populated on revocation
- [ ] Signing key is rotated every 90 days
- [ ] Service-to-service tokens have separate key and 60s TTL

### Rate Limiting
- [ ] Three-layer limits: Global, Per-User, Per-Endpoint
- [ ] Standard rate limit headers on every response
- [ ] Login endpoint has strict limits (≤ 5 req/min)
- [ ] Account lockout on >5 failed login attempts
- [ ] Redis cluster configured with fail-open fallback
- [ ] Internal service tokens bypass rate limits

### Audit Logging
- [ ] All security events are logged with structured schema
- [ ] Tamper-evident chain is verified on each append
- [ ] Audit buffer flushes within 1 second or 100 events
- [ ] Database is partitioned by month for retention
- [ ] SIEM alerts configured for critical events
- [ ] Chain integrity verified hourly (cron job)
- [ ] Audit events are immutable (append-only)

### Deployment
- [ ] All secrets in env vars or Vault (never in code)
- [ ] HTTPS enforced with TLS 1.3
- [ ] API Gateway validates all headers before forwarding
- [ ] Health check endpoint excluded from rate limiting
- [ ] Security headers at the gateway level
- [ ] Logging level is `INFO` or higher in production
