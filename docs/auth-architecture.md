# Secure Authentication Architecture

## JWT · Rate Limiting · Refresh Token Rotation

---

## 目录

1. [设计原则](#1-设计原则)
2. [令牌体系](#2-令牌体系)
3. [Refresh Token Rotation](#3-refresh-token-rotation)
4. [速率限制](#4-速率限制)
5. [存储层](#5-存储层)
6. [API 接口](#6-api-接口)
7. [安全加固](#7-安全加固)
8. [攻击面分析](#8-攻击面分析)
9. [部署清单](#9-部署清单)

---

## 1. 设计原则

| 原则 | 含义 |
|------|------|
| **最小权限** | 每个令牌只携带所需 claim，scope 粒度为 endpoint 级别 |
| **零信任** | 每个请求都验证令牌、来源、速率，不信任内网/IP |
| **防御深度** | 即使令牌泄露，rotation + 短过期时间 + 黑名单 提供多层保护 |
| **无状态优先** | Access Token 完全自包含（JWT），无需查 DB |
| **有状态兜底** | Refresh Token + 黑名单，支持显式撤销 |
| **审计完备** | 每次令牌颁发、刷新、撤销、速率触发都有日志 |

---

## 2. 令牌体系

### 2.1 双令牌模型

```
┌──────────────────────────────┐
│        Authorization         │
│  ┌─────────┐  ┌───────────┐ │
│  │ Access  │  │  Refresh  │ │
│  │  Token  │  │   Token   │ │
│  ├─────────┤  ├───────────┤ │
│  │ JWT     │  │ Opaque /  │ │
│  │ self-   │  │ DB-backed │ │
│  │contained│  │           │ │
│  ├─────────┤  ├───────────┤ │
│  │ 15 min  │  │  7 days   │ │
│  │ expiry  │  │  + rotation│ │
│  └─────────┘  └───────────┘ │
└──────────────────────────────┘
```

### 2.2 Access Token (JWT)

```json
{
  "sub": "user_abc123",
  "sid": "session_def456",
  "scope": ["api:read", "api:write"],
  "iss": "next-agent",
  "aud": "next-agent-api",
  "iat": 1718000000,
  "exp": 1718000900,
  "jti": "unique-token-id-001"
}
```

| Claim | 含义 | 说明 |
|-------|------|------|
| `sub` | 用户 ID | 不可变标识符 |
| `sid` | 会话 ID | 关联 refresh token 家族 |
| `scope` | 权限范围 | 字符串数组，控制访问权限 |
| `jti` | JWT ID | 唯一标识，用于黑名单/日志追踪 |
| `iat` / `exp` | 签发/过期 | 过期时间 **≤ 15 分钟** |

**签名算法**: `HS256`（对称，单服务）或 `ES256`（非对称，多服务）

### 2.3 Refresh Token

不是 JWT，而是一个 **不透明令牌**（opaque token）：

| 属性 | 值 |
|------|-----|
| 格式 | `rt_<64-byte- hex>` (crypto/rand) |
| 存储 | 数据库表中，bcrypt 哈希存储 |
| 过期 | 7 天 |
| 家族 | `family_id` 关联同一个用户/设备 |
| 轮换 | **每次使用都轮换**（见 §3） |

```sql
-- Refresh Tokens 表
CREATE TABLE refresh_tokens (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash    TEXT NOT NULL,           -- bcrypt(token)
    family_id     UUID NOT NULL,           -- 令牌家族
    user_id       TEXT NOT NULL,
    device_info   TEXT,                    -- user-agent / fingerprint
    ip_address    INET,
    expires_at    TIMESTAMPTZ NOT NULL,
    revoked_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE(token_hash)
);

CREATE INDEX idx_refresh_family ON refresh_tokens(family_id);
CREATE INDEX idx_refresh_user ON refresh_tokens(user_id);
```

---

## 3. Refresh Token Rotation

### 3.1 核心逻辑

每次使用 Refresh Token 获取新 Access Token 时：

1. 验证当前 refresh token 的哈希在 DB 中存在且未过期/撤销
2. **立即撤销** 当前 refresh token（`revoked_at = now()`）
3. **颁发新** refresh token（新的随机值，**同一 family_id**）
4. 返回新的 access token + 新的 refresh token

```
时间线 t₀:   RT₁ 颁发        AT₁ 颁发（15min）
                │                │
                ▼                ▼
时间线 t₁:   使用 RT₁  →  撤销 RT₁  →  颁发 RT₂ + AT₂
                                          │
                                          ▼
时间线 t₂:                       使用 RT₂  →  撤销 RT₂  →  颁发 RT₃ + AT₃
```

### 3.2 令牌重用检测（Token Reuse Detection）

如果攻击者窃取了 RT₁，受害者也在同一时间使用 RT₁：

| 场景 | 检测 | 动作 |
|------|------|------|
| 正常刷新 | RT₁ 存在，未被撤销 → 轮换 | 撤销 RT₁，颁发 RT₂ |
| **重用攻击** | RT₁ 已被撤销（RT₂ 已颁发） | **整个 family 的所有令牌立即撤销** |

```python
async def rotate_refresh_token(current_rt: str) -> tuple[str, str, str]:
    """返回 (new_access_token, new_refresh_token, family_id)"""

    row = await db.fetchrow(
        "SELECT * FROM refresh_tokens WHERE token_hash = bcrypt($1)",
        current_rt,
    )
    if not row or row["revoked_at"] or row["expires_at"] < now():
        raise AuthError("invalid or expired refresh token")

    if row.get("reuse_detected"):  # 已经被重用标记
        await revoke_family(row["family_id"])
        raise AuthError("token family revoked — possible theft")

    # 标记为可能要被重用（先标记，再轮换）
    await db.execute(
        "UPDATE refresh_tokens SET reuse_detected = TRUE WHERE id = $1",
        row["id"],
    )

    # 颁发新令牌（同一 family）
    new_rt = generate_opaque_token()
    new_family_id = row["family_id"]
    new_at = create_access_token(user_id=row["user_id"], sid=row["id"])

    await db.execute("BEGIN")
    # 撤销旧令牌
    await db.execute(
        "UPDATE refresh_tokens SET revoked_at = now() WHERE id = $1",
        row["id"],
    )
    # 插入新令牌
    await db.execute(
        """INSERT INTO refresh_tokens
           (token_hash, family_id, user_id, device_info, ip_address, expires_at)
           VALUES (bcrypt($1), $2, $3, $4, $5, now() + interval '7 days')""",
        new_rt, new_family_id, row["user_id"], row["device_info"], row["ip_address"],
    )
    await db.execute("COMMIT")

    return new_at, new_rt, new_family_id
```

### 3.3 令牌撤销

```python
async def revoke_family(family_id: str) -> int:
    """撤销整个令牌家族。返回撤销的令牌数。"""
    result = await db.execute(
        "UPDATE refresh_tokens SET revoked_at = now() "
        "WHERE family_id = $1 AND revoked_at IS NULL",
        family_id,
    )
    return result.rowcount

async def revoke_all_user_sessions(user_id: str) -> int:
    """撤销用户所有会话（修改密码、账户被盗时调用）。"""
    result = await db.execute(
        "UPDATE refresh_tokens SET revoked_at = now() "
        "WHERE user_id = $1 AND revoked_at IS NULL",
        user_id,
    )
    # 可选：将当前 access token 的 jti 加入黑名单
    return result.rowcount
```

---

## 4. 速率限制

### 4.1 三层架构

```
                    ┌──────────────────────────┐
                    │    Layer 1: Global       │
                    │  (所有请求)               │
                    │  10,000 req/min          │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │    Layer 2: Per-User      │
                    │  (by user_id / IP)        │
                    │  Auth:      30 req/min    │
                    │  API Read:  300 req/min   │
                    │  API Write: 100 req/min   │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │    Layer 3: Per-Endpoint  │
                    │  /auth/login    5 req/min │
                    │  /auth/refresh  10 req/min│
                    │  /auth/logout   10 req/min│
                    │  /api/register  3 req/min │
                    └──────────────────────────┘
```

### 4.2 算法选择

**推荐的算法**: **滑动窗口日志**（Sliding Window Log）

| 算法 | 优点 | 缺点 | 推荐场景 |
|------|------|------|----------|
| Token Bucket | 实现简单，允许突发 | 窗口边界精度不足 | 全局限制 |
| Fixed Window | 最简单 | 窗口边界双倍流量 | 不推荐单独使用 |
| **Sliding Window Log** | **精确到毫秒，无边界问题** | 存储开销略高 | **推荐主方案** |
| Sliding Window Counter | 内存效率好 | 近似精度 | 高并发替代方案 |

### 4.3 存储后端

```python
# ---------- Redis (推荐) ----------
# Key 结构:
#   ratelimit:<type>:<key>:<window>
#
# 类型:
#   global       — ratelimit:global:1718000000
#   user:<id>    — ratelimit:user:user_abc123:1718000000
#   endpoint:<p> — ratelimit:endpoint:auth.login:1718000000
#   ip:<addr>    — ratelimit:ip:192.168.1.1:1718000000

async def check_rate_limit(
    key: str,           # 如 "user:user_abc123"
    max_requests: int,  # 如 30
    window_sec: int,    # 如 60
) -> RateLimitResult:
    """滑动窗口日志实现。"""
    now = time.time()
    window_start = now - window_sec

    # 移除窗口外的旧记录
    await redis.zremrangebyscore(f"ratelimit:{key}", "-inf", window_start)

    # 当前窗口请求数
    count = await redis.zcard(f"ratelimit:{key}")

    if count >= max_requests:
        oldest = await redis.zrange(f"ratelimit:{key}", 0, 0, withscores=True)
        retry_after = int(oldest[0][1]) + window_sec - now if oldest else window_sec
        return RateLimitResult(allowed=False, retry_after=retry_after)

    # 记录当前请求
    await redis.zadd(f"ratelimit:{key}", {str(now): now})
    await redis.expire(f"ratelimit:{key}", window_sec * 2)  # TTL 自动清理

    return RateLimitResult(allowed=True, remaining=max_requests - count - 1)
```

### 4.4 响应头

所有被限流的请求返回 `429 Too Many Requests`：

```http
HTTP/1.1 429 Too Many Requests
Content-Type: application/json
Retry-After: 42
X-RateLimit-Limit: 30
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1718000100

{
  "error": "rate_limit_exceeded",
  "message": "Too many requests. Try again in 42 seconds.",
  "retry_after": 42
}
```

### 4.5 特殊处理

| 场景 | 策略 |
|------|------|
| **登录端点** | 额外实施 **基于 account lockout**：5 次失败 → 15 分钟锁定 |
| **注册端点** | 每 IP 每 24h 最多 3 次 + CAPTCHA（reCAPTCHA v3） |
| **刷新令牌** | 宽松但监控异常：短时间内同一 family 多次刷新 → 告警 |
| **内部服务** | 内部 token（service-to-service）走单独的白名单通道 |

---

## 5. 存储层

### 5.1 用户表

```sql
CREATE TABLE users (
    id                TEXT PRIMARY KEY,        -- "user_<ulid>"
    email             TEXT UNIQUE NOT NULL,
    password_hash     TEXT NOT NULL,           -- bcrypt, cost=12
    display_name      TEXT,
    is_active         BOOLEAN DEFAULT TRUE,
    email_verified_at TIMESTAMPTZ,
    created_at        TIMESTAMPTZ DEFAULT now(),
    updated_at        TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE user_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         TEXT NOT NULL REFERENCES users(id),
    refresh_count   INT DEFAULT 0,
    last_rotation   TIMESTAMPTZ,
    device_info     TEXT,
    ip_address      INET,
    created_at      TIMESTAMPTZ DEFAULT now(),
    revoked_at      TIMESTAMPTZ
);
```

### 5.2 令牌黑名单（JTI 黑名单）

对于需要提前撤销 access token 的场景（密码修改、账户封禁）：

```sql
CREATE TABLE token_blacklist (
    jti         TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,  -- 与 token exp 一致
    revoked_at  TIMESTAMPTZ DEFAULT now()
);

-- 定时清理已过期的黑名单记录
CREATE INDEX idx_blacklist_expires ON token_blacklist(expires_at)
    WHERE expires_at < now();
```

### 5.3 审计日志

```sql
CREATE TABLE audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type      TEXT NOT NULL,      -- 'login', 'logout', 'token_refresh',
                                        -- 'token_revoke', 'rate_limit', 'auth_fail'
    user_id         TEXT,
    ip_address      INET,
    device_info     TEXT,
    metadata        JSONB,              -- 事件相关附加数据
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_audit_user ON audit_log(user_id, created_at);
CREATE INDEX idx_audit_type ON audit_log(event_type, created_at);
```

---

## 6. API 接口

### 6.1 认证端点

```
POST   /auth/register          # 注册
POST   /auth/login             # 登录 → 返回 AT + RT
POST   /auth/refresh           # 刷新令牌 → 返回新 AT + 新 RT
POST   /auth/logout            # 撤销当前 RT
POST   /auth/revoke-all        # 撤销所有会话
GET    /auth/sessions          # 列出当前用户活跃会话
```

### 6.2 登录流程

```
Client                           Server
  │                                │
  │  POST /auth/login              │
  │  {email, password}             │
  │ ──────────────────────────►    │
  │                                ├─ validate email+password
  │                                ├─ check rate limit (5/min per user)
  │                                ├─ check account lockout
  │                                ├─ create session record
  │                                ├─ generate AT (15min) + RT (7d)
  │                                ├─ audit log: "login"
  │  ◄──────────────────────────  │
  │  200 {access_token,            │
  │        refresh_token,          │
  │        expires_in: 900}        │
  │                                │
```

### 6.3 刷新流程

```
Client                           Server
  │                                │
  │  POST /auth/refresh            │
  │  Authorization: Bearer <RT>    │
  │ ──────────────────────────►    │
  │                                ├─ check rate limit (10/min per token)
  │                                ├─ verify RT hash in DB
  │                                ├─ check revocation + expiry
  │                                ├─ ROTATION:
  │                                │   ├─ mark current RT as revoked
  │                                │   ├─ generate new RT (same family)
  │                                ├─ generate new AT
  │                                ├─ audit log: "token_refresh"
  │  ◄──────────────────────────  │
  │  200 {access_token,            │
  │        refresh_token,          │
  │        expires_in: 900}        │
  │                                │
```

### 6.4 令牌验证中间件

```python
from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer

security = HTTPBearer(auto_error=False)

async def verify_access_token(request: Request) -> TokenPayload:
    """验证 access token 中间件。"""
    auth = await security(request)

    if not auth or not auth.credentials:
        raise HTTPException(status_code=401, detail="missing_token")

    try:
        payload = decode_jwt(auth.credentials)
    except JWTExpiredError:
        raise HTTPException(status_code=401, detail="token_expired")
    except JWTError:
        raise HTTPException(status_code=401, detail="token_invalid")

    # 检查 JTI 黑名单
    if await is_jti_blacklisted(payload["jti"]):
        raise HTTPException(status_code=401, detail="token_revoked")

    # 检查 scope
    required_scope = request.scope.get("required_scope", "")
    if required_scope and required_scope not in payload.get("scope", []):
        raise HTTPException(status_code=403, detail="insufficient_permissions")

    # 注入用户信息
    request.state.user_id = payload["sub"]
    request.state.token_payload = payload

    return payload
```

---

## 7. 安全加固

### 7.1 密钥管理

| 密钥 | 用途 | 轮换周期 | 存储位置 |
|------|------|----------|----------|
| `JWT_SIGNING_KEY` | 签发 access token | 90 天 | 环境变量 / Vault / AWS Secrets Manager |
| `JWT_REFRESH_KEY` | 可选的 refresh token 签名 | 90 天 | 同左 |
| `BCRYPT_SALT` | bcrypt cost (12) | 固定 | 代码常量 |
| `API_KEY` | 服务间认证 | 180 天 | 环境变量 |

**密钥轮换策略（Key Rotation）**：

```python
class KeyManager:
    """支持多代密钥，签名用最新，验证用所有激活的密钥。"""

    def __init__(self):
        # 从 Vault / 环境变量加载
        self.active_keys: dict[str, str] = {}  # kid → secret

    def sign(self, payload: dict) -> str:
        kid = max(self.active_keys.keys())  # 最新密钥
        secret = self.active_keys[kid]
        payload["kid"] = kid
        return jwt.encode(payload, secret, algorithm="HS256")

    def verify(self, token: str) -> dict:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if kid not in self.active_keys:
            raise JWTError("unknown key ID")
        return jwt.decode(token, self.active_keys[kid], algorithms=["HS256"])
```

### 7.2 密码策略

```python
import bcrypt
from password_strength import PasswordPolicy

policy = PasswordPolicy.from_names(
    length=12,          # 最小 12 字符
    uppercase=1,        # 至少 1 个大写
    numbers=1,          # 至少 1 个数字
    special=1,          # 至少 1 个特殊字符
    nonletters=2,       # 至少 2 个非字母字符
)

def hash_password(password: str) -> str:
    if not policy.test(password):
        raise ValueError("Password does not meet policy requirements")
    return bcrypt.hashpw(
        password.encode(), bcrypt.gensalt(rounds=12)
    ).decode()

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())
```

### 7.3 Cookie vs. Header

| 场景 | 推荐方式 | 说明 |
|------|----------|------|
| Web 浏览器 | **httpOnly cookie** | 防止 XSS 窃取令牌 |
| 移动端/API | **Authorization header** | 更灵活，无 CSRF 风险 |
| Refresh Token | **httpOnly + Secure + SameSite=Strict** | 浏览器中 RT 应仅通过 cookie 传递 |

```python
# FastAPI 示例：将 RT 设置在 httpOnly cookie 中
response.set_cookie(
    key="refresh_token",
    value=new_rt,
    httponly=True,
    secure=True,          # HTTPS only
    samesite="strict",
    max_age=7 * 24 * 3600,
    path="/auth/",
)
```

### 7.4 其他安全措施

| 措施 | 实现 |
|------|------|
| **CORS** | 严格白名单，仅允许前端域名 |
| **CSRF** | 使用 SameSite=Strict + CSRF token（非 API） |
| **请求大小限制** | 限制请求体 ≤ 1MB |
| **请求超时** | 每个请求 30s 超时 |
| **TLS** | 全站 HTTPS，HSTS 头 |
| **指纹** | 可选：将 `device_fingerprint` 绑定到 RT |
| **IP 变化检测** | 刷新时 IP 变化 → 发送告警邮件 |

---

## 8. 攻击面分析

### 8.1 威胁模型

```
                      ┌───────────────────────────┐
                      │      攻击者能力假设         │
                      ├───────────────────────────┤
                      │ • 可以窃取单个 access token│
                      │ • 可以窃取单个 refresh token│
                      │ • 可以发起大量请求 (DDoS)   │
                      │ • 可以注册恶意账号          │
                      │ • 不能: 破解 bcrypt /      │
                      │   HS256 密钥               │
                      └───────────────────────────┘
```

### 8.2 攻击场景与防御

| 攻击 | 影响 | 防御 |
|------|------|------|
| **Access Token 泄露** | 攻击者可在 15 分钟内冒充用户 | 短过期时间 + 黑名单 + 审计 |
| **Refresh Token 泄露** | 攻击者可持续获取新 AT | Rotation + 重用检测 + 设备指纹 |
| **暴力破解密码** | 账号被攻破 | 速率限制 + 账号锁定 + bcrypt cost=12 |
| **Token 重放** | 重复使用被窃令牌 | JTI 唯一 + 黑名单 + 重用检测 |
| **CSRF** | 跨站请求伪造 | SameSite=Strict + CSRF token |
| **XSS** | 窃取 cookie | httpOnly cookie + Content-Security-Policy |
| **JWT 算法混淆** | 伪造令牌验证通过 | 严格设置 `algorithms=["HS256"]`，验证 `kid` |
| **时序侧信道** | 推测密码/令牌 | 使用恒定时间比较（bcrypt/hmac 天然恒定时间） |

### 8.3 异常检测规则

```yaml
# 用于 SIEM / 告警系统
rules:
  - name: "token_reuse_detected"
    condition: "同一 family 的 refresh token 在 10s 内被轮换两次"
    action: "撤销整个 family + 告警"

  - name: "rapid_login_failures"
    condition: "同一 IP 在 5min 内 10 次登录失败"
    action: "临时封禁 IP 30min + 告警"

  - name: "unusual_geo_change"
    condition: "同一用户在 1h 内从不同国家登录"
    action: "标记 + 邮件通知用户"

  - name: "refresh_token_burst"
    condition: "同一用户 1min 内刷新 5 次以上"
    action: "限速 + 审查 + 可选: 触发 CAPTCHA"
```

---

## 9. 部署清单

### 9.1 环境变量

```bash
# ===== Required =====
JWT_SIGNING_KEY=        # 64+ 字符随机字符串
DATABASE_URL=           # PostgreSQL 连接串
REDIS_URL=              # Redis 连接串

# ===== Optional =====
JWT_ACCESS_EXPIRE=900           # 15 min (default)
JWT_REFRESH_EXPIRE=604800       # 7 days (default)
BCRYPT_ROUNDS=12                # (default)
RATE_LIMIT_GLOBAL=10000         # req/min (default)
RATE_LIMIT_AUTH=30              # req/min per user (default)
RATE_LIMIT_LOGIN=5              # req/min per IP (default)
SENTRY_DSN=                     # 错误监控
```

### 9.2 依赖

```toml
# pyproject.toml
[dependencies]
# 认证核心
pyjwt = ">=2.8.0"               # JWT 签发验证
bcrypt = ">=4.1.0"              # 密码哈希
passlib = ">=1.7.4"             # 密码策略

# 速率限制
redis = ">=5.0.0"               # 滑动窗口存储
limits = ">=3.6.0"              # 速率限制算法库

# Web 框架 (示例)
fastapi = ">=0.109.0"
uvicorn = {extras = ["standard"], version = ">=0.27.0"}

# 安全
python-multipart = ">=0.0.6"    # form 解析
python-jose = {extras = ["cryptography"], version = ">=3.3.0"}
```

### 9.3 健康检查端点

```python
@router.get("/health")
async def health_check():
    """健康检查：验证所有外部依赖。"""
    status = {"status": "ok", "checks": {}}

    # 检查数据库
    try:
        await db.execute("SELECT 1")
        status["checks"]["database"] = "ok"
    except Exception as e:
        status["checks"]["database"] = f"fail: {e}"
        status["status"] = "degraded"

    # 检查 Redis
    try:
        await redis.ping()
        status["checks"]["redis"] = "ok"
    except Exception as e:
        status["checks"]["redis"] = f"fail: {e}"
        status["status"] = "degraded"

    # 检查密钥是否配置
    status["checks"]["jwt_key"] = (
        "ok" if JWT_SIGNING_KEY else "fail: JWT_SIGNING_KEY not set"
    )

    http_status = 200 if status["status"] == "ok" else 503
    return JSONResponse(content=status, status_code=http_status)
```

### 9.4 测试清单

- [ ] **单元测试**: 令牌签发、验证、过期、签名错误
- [ ] **单元测试**: bcrypt 哈希、密码验证、密码策略
- [ ] **单元测试**: 速率限制算法（滑动窗口精确性）
- [ ] **集成测试**: 完整的登录 → 刷新 → 登出流程
- [ ] **集成测试**: 令牌重用检测 + family 撤销
- [ ] **集成测试**: 速率限制触发（429 响应）
- [ ] **集成测试**: 账户锁定逻辑
- [ ] **安全测试**: JWT 算法混淆攻击（`alg: none`）
- [ ] **安全测试**: 暴力破解防护
- [ ] **安全测试**: CSRF / XSS 防护
- [ ] **负载测试**: 认证端点的 QPS 上限
- [ ] **负载测试**: 速率限制在高并发下的正确性

---

## 附录 A: 完整认证流程时序图

```
┌──────┐          ┌──────────┐          ┌─────────┐          ┌───────┐
│Client│          │API网关   │          │Auth Svc │          │  DB   │
└──┬───┘          └────┬─────┘          └────┬────┘          └──┬────┘
   │                    │                    │                   │
   │  POST /auth/login  │                    │                   │
   │───────────────────►│   rate limit check │                   │
   │                    ├───────────────────►│                   │
   │                    │  forward request   │                   │
   │                    │───────────────────►│                   │
   │                    │                    │  verify user      │
   │                    │                    ├──────────────────►│
   │                    │                    │◄──────────────────┤
   │                    │                    │                   │
   │                    │                    │  create session   │
   │                    │                    ├──────────────────►│
   │                    │                    │  store RT hash    │
   │                    │                    ├──────────────────►│
   │                    │                    │                   │
   │                    │                    │  gen AT + RT      │
   │                    │◄───────────────────┤                   │
   │  ◄─────────────────┤                    │                   │
   │  {AT, RT, expires} │                    │                   │
   │                    │                    │                   │
   │  === 14 min later ===                    │                   │
   │                    │                    │                   │
   │  POST /auth/refresh│                    │                   │
   │  Bearer: RT₁      │                    │                   │
   │───────────────────►│   rate limit check │                   │
   │                    ├───────────────────►│                   │
   │                    │  forward request   │                   │
   │                    │───────────────────►│                   │
   │                    │                    │  verify RT hash   │
   │                    │                    ├──────────────────►│
   │                    │                    │◄──────────────────┤
   │                    │                    │                   │
   │                    │                    │  ROTATION:        │
   │                    │                    │  ├─ revoke RT₁    │
   │                    │                    │  ├─ gen RT₂       │
   │                    │                    │  ├─ gen new AT    │
   │                    │                    │  ├─ store RT₂     │
   │                    │                    │  └─ same family   │
   │                    │                    ├──────────────────►│
   │                    │                    │◄──────────────────┤
   │                    │◄───────────────────┤                   │
   │  ◄─────────────────┤                    │                   │
   │  {AT₂, RT₂}       │                    │                   │
   │                    │                    │                   │
```

---

## 附录 B: 关键代码文件组织

```
src/auth/
├── __init__.py              # 导出模块接口
├── config.py                # 配置加载（环境变量 + 默认值）
├── models.py                # SQLAlchemy / Pydantic models
├── tokens.py                # JWT 签发、验证、黑名单
├── refresh.py               # Refresh Token 轮换逻辑
├── password.py              # 密码哈希、策略、验证
├── ratelimit.py             # 滑动窗口速率限制（Redis）
├── middleware.py             # FastAPI 中间件
├── routes.py                # 认证 API 路由
├── exceptions.py            # 自定义异常 + 错误处理
├── audit.py                 # 审计日志
├── keymanager.py            # 多代密钥管理
└── tests/
    ├── test_tokens.py
    ├── test_refresh.py
    ├── test_password.py
    ├── test_ratelimit.py
    └── test_middleware.py
```

---

## 附录 C: 生成刷新令牌与 JWT 密钥

```python
import secrets, base64

# 生成 64 字节的 JWT 签名密钥（HS256）
jwt_key = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode()
print(f"JWT_SIGNING_KEY={jwt_key}")
# → JWT_SIGNING_KEY=7Kj3mX9... (88 字符 base64)

# 生成 opaque refresh token
rt = "rt_" + secrets.token_hex(32)
print(f"Refresh Token: {rt}")
# → Refresh Token: rt_4f8a2b... (67 字符)
```
