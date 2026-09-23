# MoneyGraph — architecture

Web application for AML analysts: upload a transaction-graph extract (three parquet files or one zip) → the analysis
engine assigns roles, clusters and priorities → the analyst explores the network, reads justifications, asks the
assistant and exports CSVs. Russian UI. Single-tenant, on-prem friendly.

Built by two AI agents that review each other: **Claude** owns backend, engine and infrastructure, **Codex
(GPT-6-Astra)** owns the frontend. Rules for both: `../CODE_RULES.md`. Decision log: `COLLABORATION.md`.

## Components
```
app/
  docker-compose.yml          backend + frontend (nginx) — `docker compose up --build`
  .env.example                every runtime setting (MG_*)
  backend/                    Python 3.12, FastAPI, uv
    src/moneygraph/           analysis engine (pure; no I/O except its input/output directories)
      collection.py           Collection: crawl depth, observation window, min transfer — passed explicitly
      data.py                 footer inspection (limits) + staged validation (columns → types → values →
                              aggregates) + normalize
      features/               flows, chronological seed-money tracing, dominator control, structure,
                              temporal (FIFO), cycles, hop anomaly, continuation model
      roles.py priority.py clusters.py resilience.py report.py exports.py artifacts.py layout.py
      pipeline.py             run(data_dir, out_dir, api_dir, overrides, limits, progress) -> RunStats
    src/mg_api/               HTTP API (FastAPI app factory, no import-time side effects)
      app.py                  create_app(settings, launcher, llm): wiring, error envelope
      middleware.py           request id + access log + 500 envelope; upload guard (auth, byte budget) on raw ASGI
      services.py             Services container on app.state; auth dependency
      runs/                   repository (SQLite + migrations), scheduler, worker, uploads, serialize
      analytics/              run data store (LRU with byte budget), graph operations, views
      assistant/              offline intents, LLM agent with tools, LLM port
      routers/                meta, session, runs, analytics, assistant, exports
    tests/                    pytest: engine rules, input admission, tracing, API, auth, middleware, lifecycle,
                              repository fencing, scheduler, cache, assistant
    tools/export_contract.py  writes openapi.json + real fixtures into the frontend
  frontend/                   React 19 + TypeScript + Vite (Codex) — see frontend/README.md
```

## Boundaries (swap and fake at the edges)
| Port | Production implementation | Test fake |
|---|---|---|
| `RunRepository` | `SqliteRunRepository` (WAL, versioned additive migrations) | real SQLite in a temp dir |
| `WorkerLauncher` | `ProcessLauncher` (multiprocessing *spawn*, one killable process per run) | `InlineLauncher`, `BlockingLauncher` |
| `LLMClient` | `AnthropicLLM` (SDK errors → `LLMUnavailable` at the edge) | `FakeLLM` with scripted responses |
| run artifact loader | `load_run` (parquet/json from `current/api`) | injectable into `RunCache` |
| HTTP client (frontend) | fetch/XHR client | MSW + fake client |

## Run lifecycle
`POST /api/v1/runs` is guarded on the raw ASGI stream (auth, declared and streamed byte budget) before FastAPI parses
the multipart body. Files are streamed into `runs/<id>/input` and unpacked with zip-slip and size limits; then only the
parquet footers are inspected (columns, types, row counts, estimated in-memory size, nodes × seeds for tracing). The
run row is inserted last and atomically, so the scheduler can never claim a half-uploaded run, and a failed insert
removes the staged files. Full validation decodes the data and therefore runs in the separate worker process, where
text columns are length-checked while still dictionary-encoded.

Memory is contained at two levels, both best effort. Each run has a resident-memory budget (`MG_RUN_MEMORY_MB`) that
the scheduler samples on every tick (normally every 0.5 s, later while the database is busy); a run found above it is
stopped and fails with its own error, so gradual growth is attributed to the run that caused it. The container limit
(`MG_BACKEND_MEMORY`) is the hard backstop for anything faster: run processes start from a lightweight bootstrap that
sets `oom_score_adj=1000` before the analysis libraries load, so the kernel prefers stopping a run process — possibly a
concurrent one — over the API. The API is not immune: its own allocations, such as several cold analytics loads at
once, count against the same limit. Size the limits so that `MG_WORKERS × MG_RUN_MEMORY_MB` plus the API (about 1.5 GB
with the default cache) fits in `MG_BACKEND_MEMORY`.

The scheduler thread claims queued runs atomically (`UPDATE … WHERE status='queued'` inside `BEGIN IMMEDIATE`); every
claim gets a fresh `claim_id`, and every later write (progress, heartbeat, finish) is fenced by it, so a worker whose
lease expired cannot touch a newer attempt. The worker writes to `attempts/<n>-<random>/`; publication happens inside
the same write transaction that marks the run `succeeded` (`publish_and_succeed`): it re-checks the claim and
`cancel_requested`, swaps the `current` symlink atomically, then commits, keeping the claim on the row as the identity
of the published attempt. A cancellation that lands first wins over both success and failure. The scheduler kills any
process whose claim it no longer holds and supervises the publishing process until it exits. Crashes and expired
leases requeue the run up to `MG_MAX_ATTEMPTS`; cancel and timeout kill the process. Only `SQLITE_BUSY`/`SQLITE_LOCKED`
are retried; any other scheduler failure stops the scheduler and turns `/api/v1/ready` into 503.

The analytics cache loads each published attempt once: concurrent misses share the first loader's result — cached or
not, success or error — and a load that raced a republish or deletion is served but not cached.

## Upgrades
Schema migrations are additive, so the previous version keeps working against a migrated database. Run processes,
however, are fenced only from this version on: never let two backend versions process runs from the same data volume.
Stop the old backend before starting the new one — `docker compose up` recreates the container that way, and stopping a
container ends all of its analysis processes.

## Invariants
- gids are 18-digit int64 → strings in every JSON payload.
- Engine output is deterministic (fixed seeds, stable sorts); a refactor is checked by byte-identical role output.
- Analytics endpoints read only published artifacts; graph responses are bounded and report truncation.
- Only the holder of the current `claim_id` can change a running run; publication and success are one transaction.
- Every error leaves the API in the envelope with the request id, including unhandled 500s.
- LLM tool calls are validated against strict schemas before any graph operation runs; invalid input goes back to the
  model as a tool error.
- Everything user-facing is phrased as a hypothesis, never as an accusation.

## Scaling path (documented, not implemented)
Artifacts are columnar → swap the pandas cache for DuckDB queries; graph operations on igraph; overview served as
cluster super-nodes plus on-demand ego networks; the scheduler's SQLite queue → Postgres `SKIP LOCKED` or a broker
for multi-host workers.
