# MoneyGraph frontend

React 19, strict TypeScript, Vite, TanStack Query, React Router, Graphology/Sigma, CSS Modules.
All application text is Russian. Client identifiers remain strings throughout the application.

## Run

```sh
npm ci
npm run dev
```

Vite forwards `/api` to `http://localhost:8000`. The HTTP boundary defines `/api/v1` once in
`src/api/base.ts`. Session cookies are included; access tokens are never stored in localStorage or
sessionStorage. Navigation and filters are encoded in the workspace URL.

```sh
VITE_MOCK_API=true npm run dev
```

This enables an explicitly labelled synthetic API, including uploads, job transitions, filtering,
pagination, graph operations, assistant output, and CSV/report downloads. It does not analyze uploaded
files. Production builds disable mocks unless explicitly configured otherwise.

## Contract and tests

```sh
npm run gen:api
npm run check
PLAYWRIGHT_BROWSERS_PATH=.browsers npx playwright install chromium
PLAYWRIGHT_BROWSERS_PATH=.browsers npm run test:e2e
```

`check` runs formatting, strict type checking, ESLint, Vitest, and the production build.
`src/api/generated.d.ts` is generated from the backend's checked-in OpenAPI schema; `types.ts` contains
aliases plus UI filter types. Captured fixtures are validated against OpenAPI and used in a real-node UI test.
The synthetic mock and captured-fixture tests serve different purposes: stateful interaction coverage
and fidelity to the backend contract.

HTTP and graph rendering have injectable interfaces. Query keys include the run and filters; requests
consume abort signals. Latest-action cancellation protects graph and assistant actions. Changing runs
unmounts their workspace state. Graph hydration batches at 500 IDs; explicit path/highlight edges are
preserved across batches. Arbitrary groups larger than 500 disclose incomplete induced connections.

Sigma is loaded asynchronously so a WebGL import/initialization failure can fall back to an accessible,
paginated table. Its adapter owns the mutable Graphology instance. Server coordinates are preserved,
seeds have rings, arrows retain transfer direction, and collection-boundary nodes use faded colors.
Camera selection uses refreshed Sigma coordinates. Assistant highlights dim unrelated elements;
«Показать на графе» hydrates and fits the highlighted subgraph. Ctrl/Cmd+Enter submits assistant
questions; Enter inserts a newline. Priority and role scores use two decimal places, while shares use percent.
Markdown allows a small formatting-only element set: no HTML, images, or links from assistant text.
Structured citations and actions supply navigable client references.

## Container

```sh
docker build -t moneygraph-frontend .
docker run --rm --network <backend-network> -p 8080:8080 moneygraph-frontend
```

The nginx container runs as the `nginx` user on port **8080**. The backend must resolve as `backend:8000`.
The config provides SPA fallback, a 1 MB default body limit, gzip, long-lived asset caching, noncached HTML,
and response security headers. CSP forbids inline scripts; inline styles are permitted for Sigma's
canvas positioning and data-driven role colors. TLS and secure-cookie policy belong at the deployment
edge/backend. The production image contains only nginx and the compiled application.
nginx overwrites client-supplied forwarding headers with the connection IP for backend rate limiting.
The exact `/api/v1/runs` location streams uploads without full request buffering or an nginx size cap;
the backend enforces its configured upload limit and returns JSON errors. Other API locations retain
the 1 MB cap. The 60-second body timeout covers idle gaps, not total upload duration; deployments exposed
to untrusted clients should set an upload concurrency budget at their ingress.

## Review notes

The app does not infer transaction semantics absent from the contract. Trace results are labelled as
reachability; an undirected path fallback is disclosed. Role scores are hypotheses, never allegations.
The graph's priority/peripheral filters are explicitly distinguished from supported node-table filters.
Contract v1.4 keeps cancelling jobs running until the worker stops. The UI shows «Отмена…», disables
repeat cancellation and keeps polling; worker validation details appear in the list and workspace.
Non-retryable failures link to a fresh upload instead of retrying immutable input.
Resilience values are shares; trace edges are capped at four times `max_nodes`.
