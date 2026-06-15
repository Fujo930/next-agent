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
