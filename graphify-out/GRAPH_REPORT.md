# Graph Report - HyperSale  (2026-08-24)

## Corpus Check
- Corpus is ~11,926 words - fits in a single context window. You may not need a graph.

## Summary
- 529 nodes · 994 edges · 42 communities (28 shown, 14 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 72 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- App Configuration And Telemetry
- Durable Job Queue
- Identity And Role Resolution
- Worker Dispatch And Handlers
- Tenancy Doctrine And Sessions
- Token Verification And Errors
- Migrations And Schema Gates
- Web App Dependencies
- Web TypeScript Config
- Realtime Session Minting
- Request Correlation And Errors
- API Client Package
- Monorepo Root Scripts
- Web SPA Shell
- Marketing Site Package
- Realtime Cost Metering
- Error Envelope Tests
- Health Endpoint Tests
- Generated API Client
- Single Image Process Roles
- Evidence Scoring Doctrine
- RLS Hardening Migration
- Vite Environment Types
- M1 Deterministic Metrics
- M2 Rater Evaluation
- Backend Package Root
- Catalog Module Stub
- Identity Module Stub
- Insights Module Stub
- Knowledge Module Stub
- Platform Module Stub
- Practice Module Stub
- Review Module Stub
- Scoring Module Stub
- Backend Package Metadata

## God Nodes (most connected - your core abstractions)
1. `get_settings()` - 28 edges
2. `AuthError` - 22 edges
3. `Settings` - 20 edges
4. `AppError` - 20 edges
5. `TokenVerifier` - 20 edges
6. `tenant_session()` - 17 edges
7. `ClaimedJob` - 17 edges
8. `resolve_membership()` - 16 edges
9. `Worker` - 16 edges
10. `compilerOptions` - 15 edges

## Surprising Connections (you probably didn't know these)
- `Costs Are Configuration` --rationale_for--> `Settings`  [EXTRACTED]
  README.md → services/backend/app/config.py
- `Why Membership Lookup Cannot Be Workspace-Scoped` --rationale_for--> `resolve_membership()`  [EXTRACTED]
  MASTER_PRODUCT.md → services/backend/app/modules/identity/service.py
- `Why SET LOCAL Cannot Take Bind Parameters` --rationale_for--> `_set_guc()`  [EXTRACTED]
  MASTER_PRODUCT.md → services/backend/app/db/session.py
- `Why Membership Lookup Cannot Be Workspace-Scoped` --rationale_for--> `identity_session()`  [EXTRACTED]
  MASTER_PRODUCT.md → services/backend/app/db/session.py
- `Postgres SKIP LOCKED Queue` --references--> `claim()`  [EXTRACTED]
  MASTER_PRODUCT.md → services/backend/app/modules/platform/queue.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Workspace Tenancy Boundary** — services_backend_app_modules_identity_tokens_tokenverifier_verify, services_backend_app_modules_identity_service_resolve_membership, services_backend_app_modules_identity_deps_current_principal, services_backend_app_db_session_tenant_session, services_backend_alembic_versions_20260824_0002_queue_and_rls_hardening_upgrade [EXTRACTED 0.95]
- **Durable Job Lifecycle** — services_backend_app_modules_platform_queue_enqueue, services_backend_app_modules_platform_queue_claim, services_backend_app_modules_platform_queue_mark_succeeded, services_backend_app_modules_platform_queue_mark_failed, services_backend_app_modules_platform_queue_requeue_stalled, services_backend_app_workers_main_worker_run_once [EXTRACTED 0.95]
- **Fail-Closed Defaults** — services_backend_app_modules_identity_tokens_tokenverifier_verify, services_backend_app_modules_platform_usage_realtime_audio_cost, services_backend_app_db_session_system_session [INFERRED 0.70]

## Communities (42 total, 14 thin omitted)

### Community 0 - "App Configuration And Telemetry"
Cohesion: 0.06
Nodes (48): AsyncEngine, BaseSettings, Local Postgres Service, FastAPI, ge, le, LogRecord, ManagerPrincipal (+40 more)

### Community 1 - "Durable Job Queue"
Cohesion: 0.10
Nodes (49): Postgres SKIP LOCKED Queue, can_transition(), JobState, Durable job-state contract. SQL implementation follows the same state machine., backoff_seconds(), claim(), enqueue(), EnqueueResult (+41 more)

### Community 2 - "Identity And Role Resolution"
Cohesion: 0.09
Nodes (41): bearer_scheme, Header, HTTPAuthorizationCredentials, ForbiddenError, current_user(), MeResponse, my_workspaces(), BaseModel (+33 more)

### Community 3 - "Worker Dispatch And Handlers"
Cohesion: 0.09
Nodes (33): JobHandler, Why The Dispatcher Is The Only Cross-Tenant Component, dispose_engine(), Cross-tenant session for queue dispatch only. Sets no tenant GUC, so under RLS…, system_session(), ClaimedJob, AsyncSession, BaseModel (+25 more)

### Community 4 - "Tenancy Doctrine And Sessions"
Cohesion: 0.08
Nodes (42): M0 Gate — Skeleton And Truth, Honest Cost Per Roleplay Minute, Modular Monolith, RLS Is The Second Boundary, Integration Tests Prove Tenant Isolation, Why Membership Lookup Cannot Be Workspace-Scoped, Why SET LOCAL Cannot Take Bind Parameters, Every Repository Method Requires workspace_id (+34 more)

### Community 5 - "Token Verification And Errors"
Cohesion: 0.12
Nodes (28): PyJWK, AppError, AuthError, Expected, client-visible failure. Unexpected failures stay generic., JwksCache, In-process JWKS cache with TTL and rate-limited rotation refresh., TokenVerifier, Explicit settings so a developer's local .env cannot change a test outcome. (+20 more)

### Community 6 - "Migrations And Schema Gates"
Cohesion: 0.08
Nodes (30): Connection, DeclarativeBase, CI Backend Job, Migration Round-Trip Gate, ORM Drift Gate (alembic check), CI Postgres Service, Alembic Migration Dependency, Why Migrations Could Not Run At All (+22 more)

### Community 7 - "Web App Dependencies"
Cohesion: 0.07
Nodes (29): dependencies, react, react-dom, @tanstack/react-query, @tanstack/react-router, devDependencies, @playwright/test, @types/react (+21 more)

### Community 8 - "Web TypeScript Config"
Cohesion: 0.10
Nodes (20): compilerOptions, allowJs, allowSyntheticDefaultImports, esModuleInterop, isolatedModules, jsx, lib, module (+12 more)

### Community 9 - "Realtime Session Minting"
Cohesion: 0.16
Nodes (16): Browser-To-Provider WebRTC, Open Risk — No Rate Limit On Credential Minting, Short-Lived Backend-Authorized Credentials, Why Realtime Identity Must Come From The Token, post, create_realtime_session(), BaseModel, CurrentPrincipal (+8 more)

### Community 10 - "Request Correlation And Errors"
Cohesion: 0.28
Nodes (13): Exception, Request-scoped correlation state shared by logging, errors, and telemetry., app_error(), correlation_id_middleware(), error_response(), http_error(), Any, JSONResponse (+5 more)

### Community 11 - "API Client Package"
Cohesion: 0.17
Nodes (11): openapi-fetch, openapi-typescript, dependencies, openapi-fetch, devDependencies, openapi-typescript, name, private (+3 more)

### Community 12 - "Monorepo Root Scripts"
Cohesion: 0.17
Nodes (11): devDependencies, prettier, name, packageManager, private, scripts, build, dev:marketing (+3 more)

### Community 13 - "Web SPA Shell"
Cohesion: 0.22
Nodes (9): App(), runGateCheck(), Check, Config, getJson(), queryClient, CI Web Build Gate, PNPM Workspace Layout (+1 more)

### Community 14 - "Marketing Site Package"
Cohesion: 0.20
Nodes (9): dependencies, astro, name, private, scripts, build, dev, version (+1 more)

### Community 15 - "Realtime Cost Metering"
Cohesion: 0.31
Nodes (9): Why Unmeasured Cost Is Not Zero Cost, Cost of one realtime exchange. Seconds in, micro-USD out; no float money., realtime_audio_cost(), A zero cost must be distinguishable from a genuinely free call., test_cost_is_summed_per_direction(), test_negative_duration_is_rejected(), test_no_audio_is_not_a_missing_rate(), test_partial_minutes_round_to_whole_micro_usd() (+1 more)

### Community 16 - "Error Envelope Tests"
Cohesion: 0.43
Nodes (7): _assert_envelope(), TestClient, Every failure leaves through the same envelope, or clients cannot handle errors…, test_error_response_carries_the_caller_request_id(), test_protected_route_without_a_token_is_401(), test_public_config_never_exposes_provider_keys(), test_unknown_route_uses_the_error_envelope()

### Community 17 - "Health Endpoint Tests"
Cohesion: 0.53
Nodes (5): TestClient, test_health_echoes_a_supplied_request_id(), test_health_generates_a_request_id_when_absent(), test_health_is_live_without_a_database(), test_oversized_request_id_is_truncated()

### Community 18 - "Generated API Client"
Cohesion: 0.40
Nodes (4): No Hand-Written Frontend API Types, Generated API Client, Never Hand-Written, main(), Dump the OpenAPI document. The frontend client is generated from this file.…

### Community 19 - "Single Image Process Roles"
Cohesion: 0.40
Nodes (4): CI Image Build Gate, Two Deploy Units From One Image, One Image, Three Process Roles, entrypoint.sh script

### Community 20 - "Evidence Scoring Doctrine"
Cohesion: 0.50
Nodes (4): Evidence Verified In Code Before Persistence, Immutable Rubric And Model Provenance, Insufficient Evidence Is Neutral, Evidence-Backed Coaching Mission

## Knowledge Gaps
- **80 isolated node(s):** `name`, `private`, `version`, `dev`, `build` (+75 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **14 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_settings()` connect `App Configuration And Telemetry` to `Durable Job Queue`, `Worker Dispatch And Handlers`, `Tenancy Doctrine And Sessions`, `Migrations And Schema Gates`, `Realtime Session Minting`, `Realtime Cost Metering`?**
  _High betweenness centrality (0.119) - this node is a cross-community bridge._
- **Why does `tenant_session()` connect `Tenancy Doctrine And Sessions` to `App Configuration And Telemetry`, `Durable Job Queue`, `Identity And Role Resolution`, `Worker Dispatch And Handlers`?**
  _High betweenness centrality (0.044) - this node is a cross-community bridge._
- **Why does `AppError` connect `Token Verification And Errors` to `App Configuration And Telemetry`, `Realtime Session Minting`, `Request Correlation And Errors`, `Identity And Role Resolution`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Are the 11 inferred relationships involving `AuthError` (e.g. with `JwksCache` and `TokenVerifier`) actually correct?**
  _`AuthError` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `Settings` (e.g. with `TokenVerifier` and `realtime_audio_cost()`) actually correct?**
  _`Settings` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `AppError` (e.g. with `JwksCache` and `TokenVerifier`) actually correct?**
  _`AppError` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `TokenVerifier` (e.g. with `Settings` and `AppError`) actually correct?**
  _`TokenVerifier` has 11 INFERRED edges - model-reasoned connections that need verification._