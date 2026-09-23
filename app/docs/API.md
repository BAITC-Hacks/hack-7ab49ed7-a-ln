# MoneyGraph API — contract v1.4

Base path `/api/v1`. JSON UTF-8. **gids and run ids are strings.** Money: KZT, number with ≤ 2 decimals.
Dates `YYYY-MM-DD`; timestamps ISO 8601 UTC (`2026-09-23T10:00:00Z`). Shares are fractions 0..1 (`unit: "share"`).
Source of truth: `/api/v1/openapi.json` (requires auth; checked in as `app/frontend/src/api/openapi.json`, regenerated
with real fixtures by `backend/tools/export_contract.py`). There is no Swagger UI: its CDN assets are blocked by the CSP.

## Errors
Any 4xx/5xx: `{"error": {"code": str, "message": str (Russian), "request_id": str, "details": [...]|null, "retryable": bool}}`.
Codes: `unauthorized`, `not_found`, `run_not_ready`, `validation_error` (details = `[{field, message}]`, Russian;
HTTP 422 for malformed request parameters, 400 for invalid uploaded data), `payload_too_large`, `conflict`,
`rate_limited`, `service_unavailable`, `method_not_allowed`, `internal_error`, and `http_error` for any other
protocol-level status (malformed bodies are `validation_error`, unknown routes `not_found`). Every response, 500s included, has header
`X-Request-ID`: the client's value is echoed when it matches `[A-Za-z0-9._-]{1,64}`, otherwise the server generates one.
The OpenAPI schema documents this envelope (`ErrorResponse`) for every error status.

## Auth
If the server has `MG_API_TOKEN`, all `/api/v1/*` except `/api/v1/health`, `/api/v1/ready`, `/api/v1/meta`, `/api/v1/session`
require auth: HttpOnly cookie `mg_session` (set by `POST /api/v1/session`) **or** `Authorization: Bearer <token>`.
For `POST /api/v1/runs` auth and the declared/streamed body size are checked before the multipart body is parsed.
Login attempts are rate limited per client address (`MG_LOGIN_ATTEMPTS_PER_MINUTE`).
| Method | Path | |
|---|---|---|
| POST | `/api/v1/session` | body `{token}` → 204 + `Set-Cookie: mg_session=…; HttpOnly; SameSite=Strict; Path=/api` ; 401 if wrong |
| DELETE | `/api/v1/session` | 204, clears cookie |
| GET | `/api/v1/session` | `{authenticated: bool, auth_required: bool}` |

## Meta
| GET | `/api/v1/health` | `{status: "ok", version}` (public, liveness; `version` = contract version, `1.4.0`) |
|---|---|---|
| GET | `/api/v1/ready` | `{status: "ready"}` or 503 (DB reachable, data dir writable, run scheduler alive) |
| GET | `/api/v1/meta` | public: `{version, auth_required, llm_enabled, limits: {max_upload_mb, max_zip_members, max_nodes, max_transactions}}` |
| GET | `/api/v1/methodology?run_id=` | optional `run_id` makes rule texts use that run's crawl depth. `{roles: {<role>: {label, color, rule}}, role_order: [...], flags: {<flag>: label}, priority_components: [{key, label, weight}], limitations: [str]}` |

Roles (fixed order): `coordinator, consolidator, distributor, transit, terminal, peripheral`.

## Runs
| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/runs?limit=50&offset=0` | `{items: Run[], total}` newest first |
| POST | `/api/v1/runs` | multipart form: `files` (repeatable field: 1 `.zip` **or** exactly 3 `.parquet` named edges/nodes/transactions), `name` (opt), `observation_start`, `observation_end` (opt, `YYYY-MM-DD`, end ≥ start), `max_depth` (opt int 1..50), `min_transfer_kzt` (opt finite number, 0 < x ≤ 10¹²). 202 → `Run` (`queued`). 422 malformed parameters, 400 `validation_error` (files, columns, types, limits — see below), 413 `payload_too_large` |
| POST | `/api/v1/runs/demo` | 202 → `Run` from the bundled demo dataset |
| GET | `/api/v1/runs/{run_id}` | `Run` |
| POST | `/api/v1/runs/{run_id}/cancel` | 202 → `Run`: queued → `cancelled` at once; running → stays `running` with `cancel_requested: true` until the worker is stopped, then `cancelled` (a result finishing at that moment is discarded). 409 if finished |
| POST | `/api/v1/runs/{run_id}/retry` | 202 → `Run` (failed/cancelled → `queued`, attempts reset); 409 otherwise |
| DELETE | `/api/v1/runs/{run_id}` | 204; 409 while `running` (cancel first) |

```
Run = {id, name, source: "upload"|"demo", status: "queued"|"running"|"succeeded"|"failed"|"cancelled",
       stage_code: "queued"|"validating"|"features"|"roles"|"clusters"|"exports"|"publishing"|"done"|null,
       stage_label: str|null (Russian), progress: number 0..1|null  (stage and label are null once failed/cancelled),
       cancel_requested: bool, attempts: int,
       error: {code: "validation_error"|"engine_error"|"worker_crashed"|"timeout"|"cancelled", message, retryable,
               details: [{field, message}]|null}|null,
       created_at, updated_at, started_at|null, finished_at|null, duration_s: number|null,
       poll_after_ms: int|null  (suggested polling interval while queued/running; null when final),
       params: {observation_start, observation_end, max_depth, min_transfer_kzt, collection_direction: "outgoing"},
       warnings: [str]  (e.g. "окно наблюдения не задано — взято по датам транзакций"),
       summary: RunSummary|null, engine_version: str}
RunSummary = {n_nodes, n_edges, n_tx, n_seeds, total_kzt, period: [from, to], n_clusters,
              roles: {<role>: count}, flags: {<flag>: count}}
```
Endpoints below need `status = succeeded` (else 409 `run_not_ready`); unknown run → 404.

### Upload admission
The API checks, before the run is created (400 with `details`): archive layout (zip-slip, member count, uncompressed
size), file names, and each parquet footer — required columns, column types, row counts (`MG_MAX_NODES`,
`MG_MAX_TRANSACTIONS`), estimated in-memory size of the required columns (per value, never below the stored page
size; `MG_MAX_DECODED_MB`) and seed tracing size (nodes × seeds ≤ `MG_MAX_TRACE_CELLS`). Nothing is decompressed
beyond the seed flags. Full validation (text dates ≤ 40 characters, checked before they are expanded; ids in
0..2⁶³−1, positive finite amounts, parseable dates, unique nodes, edges consistent with transactions, collection
params consistent with the data) runs in the isolated worker: failures end the run as `failed` with
`error.code = "validation_error"`, `retryable = false` and field-level `error.details`.
Dates may be `date`, `timestamp` or ISO 8601 strings; values with an offset or time zone are converted to UTC,
naive values are taken as written.

## Analytics (paths relative to `/api/v1`)
| Method | Path | Response |
|---|---|---|
| GET | `/runs/{id}/overview` | `{summary, model: {status: "ok"\|"insufficient_data", auc_cv\|null, auc_transfer\|null, base_rate\|null, n_train}, resilience: {base, rows: ResilienceRow[]}, data_requests: {<request>: count}, warnings: [str]}` |
| GET | `/runs/{id}/graph` | overview for rendering. Query: `role` (repeatable), `cluster_id`, `min_priority`, `hide_peripheral`, `max_nodes` (default 5000, ≤ 20000), `max_edges` (default 20000, ≤ 50000) → `Subgraph`. Nodes kept by priority desc (id tie-break); edges only among kept nodes, heaviest first |
| POST | `/runs/{id}/graph/nodes` | body `{ids: string[] (≤ 500), include_edges: bool}` → `Subgraph` with exactly these nodes (+ edges among them) — hydration for assistant/path results |
| GET | `/runs/{id}/nodes` | table. Query: `q` (gid substring ≥ 3), `role` (repeatable), `cluster_id`, `is_seed`, `flag`, `sort_by` ∈ {priority_score, role_score, in_kzt, out_kzt, in_deg, out_deg, traced_in_kzt, control_nodes}, `sort_order` ∈ {desc, asc} (default desc; tie-break id asc), `limit` ≤ 500 (50), `offset` → `{items: NodeRow[], total}` |
| GET | `/runs/{id}/search?q=&limit=20` | `{items: {id, role, priority_score, priority_rank}[], total}` (q ≥ 3 digits, substring) |
| GET | `/runs/{id}/nodes/{gid}` | `NodeDetail` |
| GET | `/runs/{id}/nodes/{gid}/counterparties?direction=in\|out&limit=50&offset=0` | `{items: Counterparty[], total}` sorted by sum desc |
| GET | `/runs/{id}/nodes/{gid}/transactions?counterparty=&direction=in\|out\|both&limit=100&offset=0` | `{items: {date, source, target, sum_kzt}[], total}` by date |
| GET | `/runs/{id}/nodes/{gid}/neighborhood?depth=1..3&direction=in\|out\|both&max_nodes=300&max_edges=1000` | `Subgraph` (center = gid) |
| GET | `/runs/{id}/nodes/{gid}/trace?direction=up\|down&max_hops=1..6&max_nodes=500` | `Subgraph` (nodes closest to gid first; edges capped at 4 × `max_nodes`); `up` = who can have sent money to the node (towards seeds), `down` = where it can have gone. **Graph reachability, not proven money movement** |
| GET | `/runs/{id}/path?source=&target=` | `{found, directed: bool (false = fallback undirected), nodes: string[], edges: GraphEdge[]}` |
| GET | `/runs/{id}/top?limit=50` | `{items: TopItem[]}` |
| GET | `/runs/{id}/clusters?limit=100&offset=0&sort_by=max_priority\|n_nodes\|n_seed` | `{items: Cluster[], total}`; members via `/nodes?cluster_id=` |
| GET | `/runs/{id}/clusters/{cluster_id}` | `Cluster` |
| GET | `/runs/{id}/data-requests?limit=100&offset=0` | `{items: {id, request, value_kzt, reason}[], total}` |
| POST | `/runs/{id}/assistant` | body `{question, mode: "auto"\|"offline"\|"llm"}` → `AssistantAnswer` |
| GET | `/runs/{id}/exports` | `{items: {name, filename, content_type, size_bytes: int\|null (null for the lazily built bundle), description}[]}` |
| GET | `/runs/{id}/exports/{name}` | file (`Content-Disposition: attachment`) for names from the list above; `bundle` = zip of all |

### Shapes
```
GraphNode  = {id, x, y, role, cluster_id, priority_score, priority_rank, top_rank|null, is_seed, truncated,
              in_kzt, out_kzt}
GraphEdge  = {source, target, sum_kzt, n_tx, first_date, last_date}
Subgraph   = {center: str|null, nodes: GraphNode[], edges: GraphEdge[],
              total_nodes: int (matching before limits), total_edges: int,
              truncated: bool, truncation_reason: "max_nodes"|"max_edges"|null}
NodeRow    = {id, role, role_score, priority_score, priority_rank, top_rank|null, cluster_id, depth, is_seed,
              truncated, flags: string[], in_deg, out_deg, in_kzt, out_kzt, in_tx, out_tx, evidence}
NodeDetail = NodeRow + {card: str, why: str|null,
   metrics: {key, label, value: number|string|null, unit: "kzt"|"share"|"count"|"days"|"z"|"gid"|"ratio"|null}[],
   priority_components: {key, label, weight, value, contribution}[],
   priority_reliability: number (seed ×0.85, last hop ×0.75, isolated 0; priority = Σ contributions × reliability),
   rules: {coordinator, consolidator, distributor, transit, terminal: bool},
   n_payers, n_recipients}
Counterparty = {id, role, sum_kzt, n_tx, first_date, last_date}
TopItem    = {top_rank, id, role, priority_score, role_score, is_seed, cluster_id, evidence, why, flags}
Cluster    = {cluster_id, n_nodes, n_seed, sum_kzt_internal, top_gids: string[], hypothesis, max_priority,
              roles: {<role>: count}, n_truncated}
ResilienceRow = {removed_top_n, reach_top, flow_top, reach_random, flow_random, components_top, components_random}
   reach_* / flow_* = share 0..1 of the base reach (nodes reachable from seeds) / base flow still left after removing
   the top-N priority nodes or N random nodes (random = mean of trials); components_* = weakly connected components.
   Resilience.base = {reach, flow, lcc, components} of the untouched graph.
AssistantAnswer = {mode_used: "offline"|"llm", intent: str, answer_markdown: str (Russian, no raw HTML),
   citations: {id, role, note}[], actions: {type: "focus"|"highlight"|"path", ids: string[], label}[],
   highlight: {nodes: string[], edges: [source, target][]},
   candidates: {fragment, ids: string[]}[] (ambiguous gid fragments), warnings: [str], suggestions: [str]}
```

### Assistant intents (offline, Russian)
`кто собирает деньги с <gid>, <gid>…` (common downstream collectors ≤ 4 hops) · `путь от <gid> к <gid>` ·
`откуда деньги у <gid>` · `куда ушли деньги <gid>` · `кластер <gid|номер>` · `топ <N> <роль>` · `почему <gid>`.
gid = full 18 digits or unique substring ≥ 6 digits (ambiguous → `candidates`). LLM mode only when the server
enables it (`MG_LLM_ENABLED=true` + `MG_ANTHROPIC_API_KEY`): an agent whose tools are the same graph operations.

## Changelog
- v1.4 (additive, independent backend review, rounds 5–6): `Run.cancel_requested`; `RunError.details` for validation
  failures found by the worker; error `details` typed as `FieldIssue {field, message}` and `RunError.code` as an enum
  (Codex question); upload admission from parquet footers (types, rows, decoded size, trace size);
  non-finite `min_transfer_kzt` → 422 and `observation_end < observation_start` → 400; `/api/v1/openapi.json`
  requires auth and `/api/v1/docs` is gone; request id kept on 500s; documented trace edge cap and resilience units;
  protocol errors (malformed multipart, unknown routes) in the Russian envelope; stage fields null on final runs.
- v1.3 (additive, implementation review): `Run.source`; `NodeDetail.priority_reliability`; optional
  `/methodology?run_id=`; bundle `size_bytes` nullable; error codes `service_unavailable`, `method_not_allowed`;
  422 vs 400 for validation errors; OpenAPI documents `ErrorResponse` on every route (Codex finding, round 4).
- v1.2 (code rules adopted): every endpoint moved under the versioned base `/api/v1`; future breaking changes get `/api/v2`.
- v1.1 (after Codex review, round 1): collection params + warnings on runs; bounded `Subgraph` with totals;
  `POST /graph/nodes` hydration; counterparties & transactions paginated; sort enums; run stage codes, progress,
  structured error, cancel/retry, attempts, `poll_after_ms`; public `/meta` + protected `/methodology`;
  cookie session; structured assistant answers; `priority_rank` (all nodes) vs `top_rank` (top list).
- v1.0: initial draft.
