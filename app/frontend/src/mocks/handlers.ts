import { delay, http, HttpResponse } from 'msw';
import { API_BASE } from '../api/base';
import type { AssistantAnswer, Run } from '../api/types';
import { createDemoData } from './data';
import { findPath, graphSubset, walk } from './graph';

const json = <T>(value: T, status = 200) =>
  HttpResponse.json(value as never, { status, headers: { 'X-Request-ID': 'mock-request' } });
const error = (message: string, status = 404) =>
  json(
    {
      error: {
        code: status === 401 ? 'unauthorized' : status === 409 ? 'conflict' : 'not_found',
        message,
        request_id: 'mock-request',
        details: null,
        retryable: false,
      },
    },
    status,
  );
const page = <T>(items: T[], q: URLSearchParams) => ({
  items: items.slice(
    Number(q.get('offset') ?? 0),
    Number(q.get('offset') ?? 0) + Number(q.get('limit') ?? 50),
  ),
  total: items.length,
});
export function createHandlers({ authRequired = false }: { authRequired?: boolean } = {}) {
  const data = createDemoData();
  const runs = new Map<string, Run>([[data.run.id, data.run]]);
  const polls = new Map<string, number>();
  let authenticated = !authRequired;
  const url = (path: string) => `${API_BASE}${path}`;
  const created = (name: string) => {
    const run: Run = {
      ...data.run,
      id: crypto.randomUUID(),
      name,
      status: 'queued',
      stage_code: 'queued',
      stage_label: 'В очереди',
      progress: 0,
      poll_after_ms: 500,
      summary: null,
      started_at: null,
      finished_at: null,
      duration_s: null,
    };
    runs.set(run.id, run);
    polls.set(run.id, 0);
    return run;
  };
  const advance = (run: Run) => {
    if (run.status === 'running' && run.cancel_requested) {
      Object.assign(run, { status: 'cancelled', poll_after_ms: null, stage_code: null, stage_label: null });
    }
    if (run.status !== 'queued' && run.status !== 'running') return run;
    const count = (polls.get(run.id) ?? 0) + 1;
    polls.set(run.id, count);
    if (count >= 3) {
      Object.assign(run, {
        status: 'succeeded',
        stage_code: 'done',
        stage_label: 'Анализ завершён',
        progress: 1,
        summary: data.summary,
        poll_after_ms: null,
      });
    } else {
      Object.assign(run, {
        status: 'running',
        stage_code: 'features',
        stage_label: 'Расчёт признаков',
        progress: count / 3,
      });
    }
    return run;
  };
  return [
    http.all(`${API_BASE}/*`, ({ request }) => {
      const path = new URL(request.url).pathname.slice(API_BASE.length);
      if (authRequired && !authenticated && !['/meta', '/health', '/ready', '/session'].includes(path))
        return error('Требуется вход в систему.', 401);
    }),
    http.get(url('/meta'), () =>
      json({
        version: '1.2.0-demo',
        auth_required: authRequired,
        llm_enabled: false,
        limits: { max_upload_mb: 200, max_zip_members: 3, max_nodes: 100000, max_transactions: 1000000 },
      }),
    ),
    http.get(url('/session'), () => json({ authenticated, auth_required: authRequired })),
    http.post(url('/session'), async ({ request }) => {
      const body = (await request.json()) as { token: string };
      if (body.token !== 'demo-token') return error('Неверный токен.', 401);
      authenticated = true;
      return new HttpResponse(null, { status: 204 });
    }),
    http.delete(url('/session'), () => {
      authenticated = false;
      return new HttpResponse(null, { status: 204 });
    }),
    http.get(url('/methodology'), ({ request }) => {
      const runId = new URL(request.url).searchParams.get('run_id');
      if (runId && runs.get(runId)?.status !== 'succeeded') return error('Анализ ещё не завершён.', 409);
      return json(data.methodology);
    }),
    http.get(url('/runs'), ({ request }) =>
      json(page([...runs.values()].reverse().map(advance), new URL(request.url).searchParams)),
    ),
    http.post(url('/runs/demo'), () => json(created('Демо-исследование'), 202)),
    http.post(url('/runs'), async ({ request }) => {
      const form = await request.formData();
      if (!form.getAll('files').length) return error('Не выбраны файлы.', 400);
      return json(created(String(form.get('name') || 'Загруженная выгрузка · синтетический анализ')), 202);
    }),
    http.get(url('/runs/:runId'), ({ params }) => {
      const run = runs.get(String(params.runId));
      if (!run) return error('Исследование не найдено.');
      return json(advance(run));
    }),
    http.post(url('/runs/:runId/cancel'), ({ params }) => {
      const run = runs.get(String(params.runId));
      if (!run) return error('Исследование не найдено.');
      if (!['queued', 'running'].includes(run.status)) return error('Анализ уже завершён.', 409);
      if (run.status === 'running') {
        Object.assign(run, { cancel_requested: true, stage_label: 'Отмена…' });
      } else {
        Object.assign(run, { status: 'cancelled', poll_after_ms: null, stage_code: null, stage_label: null });
      }
      return json(run, 202);
    }),
    http.post(url('/runs/:runId/retry'), ({ params }) => {
      const run = runs.get(String(params.runId));
      if (!run) return error('Исследование не найдено.');
      Object.assign(run, {
        status: 'queued',
        cancel_requested: false,
        error: null,
        stage_code: 'queued',
        progress: 0,
        poll_after_ms: 500,
        stage_label: 'В очереди',
      });
      polls.set(run.id, 0);
      return json(run, 202);
    }),
    http.delete(url('/runs/:runId'), ({ params }) => {
      runs.delete(String(params.runId));
      return new HttpResponse(null, { status: 204 });
    }),
    http.get(url('/runs/:runId/overview'), () => json(data.overview)),
    http.get(url('/runs/:runId/graph'), ({ request }) => {
      const q = new URL(request.url).searchParams;
      return json(
        graphSubset(
          data,
          data.nodes.filter(
            (n) =>
              (!q.getAll('role').length || q.getAll('role').includes(n.role)) &&
              (!q.has('cluster_id') || n.cluster_id === Number(q.get('cluster_id'))) &&
              n.priority_score >= Number(q.get('min_priority') ?? 0) &&
              (q.get('hide_peripheral') !== 'true' || n.role !== 'peripheral'),
          ),
          q,
        ),
      );
    }),
    http.post(url('/runs/:runId/graph/nodes'), async ({ request }) => {
      const body = (await request.json()) as { ids: string[]; include_edges: boolean };
      const result = graphSubset(
        data,
        data.nodes.filter((n) => body.ids.includes(n.id)),
        new URLSearchParams(),
      );
      return json({ ...result, edges: body.include_edges ? result.edges : [] });
    }),
    http.get(url('/runs/:runId/nodes'), ({ request }) => {
      const q = new URL(request.url).searchParams;
      const items = data.details.filter(
        (n) =>
          (!q.getAll('role').length || q.getAll('role').includes(n.role)) &&
          (!q.has('cluster_id') || n.cluster_id === Number(q.get('cluster_id'))) &&
          (!q.has('flag') || n.flags.includes(q.get('flag')!)) &&
          (!q.has('is_seed') || n.is_seed === (q.get('is_seed') === 'true')) &&
          (!q.has('q') || n.id.includes(q.get('q')!)),
      );
      const sort = q.get('sort_by') ?? 'priority_score';
      items.sort(
        (a, b) =>
          (Number(a[sort as keyof typeof a] ?? 0) - Number(b[sort as keyof typeof b] ?? 0)) *
            (q.get('sort_order') === 'asc' ? 1 : -1) || a.id.localeCompare(b.id),
      );
      return json(page(items, q));
    }),
    http.get(url('/runs/:runId/search'), async ({ request }) => {
      await delay(50);
      const q = new URL(request.url).searchParams;
      return json(
        page(
          data.nodes.filter((n) => n.id.includes(q.get('q') ?? '')),
          q,
        ),
      );
    }),
    http.get(url('/runs/:runId/nodes/:gid'), ({ params }) => {
      const node = data.details.find((n) => n.id === params.gid);
      return node ? json(node) : error('Клиент не найден.');
    }),
    http.get(url('/runs/:runId/nodes/:gid/counterparties'), ({ request, params }) => {
      const q = new URL(request.url).searchParams;
      const inc = q.get('direction') === 'in';
      return json(
        page(
          data.edges
            .filter((e) => (inc ? e.target === params.gid : e.source === params.gid))
            .map((e) => ({
              id: inc ? e.source : e.target,
              role: data.nodes.find((n) => n.id === (inc ? e.source : e.target))!.role,
              ...e,
            }))
            .sort((a, b) => b.sum_kzt - a.sum_kzt),
          q,
        ),
      );
    }),
    http.get(url('/runs/:runId/nodes/:gid/transactions'), ({ request, params }) => {
      const q = new URL(request.url).searchParams;
      const direction = q.get('direction');
      const items = data.edges
        .filter(
          (e) =>
            (direction === 'in'
              ? e.target === params.gid
              : direction === 'out'
                ? e.source === params.gid
                : e.source === params.gid || e.target === params.gid) &&
            (!q.has('counterparty') ||
              e.source === q.get('counterparty') ||
              e.target === q.get('counterparty')),
        )
        .flatMap((e) =>
          Array.from({ length: e.n_tx }, () => ({
            source: e.source,
            target: e.target,
            date: e.first_date,
            sum_kzt: e.sum_kzt / e.n_tx,
          })),
        );
      return json(page(items, q));
    }),
    ...['neighborhood', 'trace'].map((operation) =>
      http.get(url(`/runs/:runId/nodes/:gid/${operation}`), ({ request, params }) => {
        const q = new URL(request.url).searchParams;
        const id = String(params.gid);
        return json(
          graphSubset(
            data,
            walk(data, id, q.get('direction') ?? 'both', Number(q.get('depth') ?? q.get('max_hops') ?? 1)),
            q,
            id,
          ),
        );
      }),
    ),
    http.get(url('/runs/:runId/path'), ({ request }) => {
      const q = new URL(request.url).searchParams;
      const source = q.get('source')!;
      const target = q.get('target')!;
      const directed = findPath(data, source, target);
      const nodes = directed.length ? directed : findPath(data, source, target, true);
      return json({
        found: !!nodes.length,
        directed: !!directed.length,
        nodes,
        edges: data.edges.filter((e) =>
          nodes.some(
            (id, i) =>
              i > 0 &&
              ((e.source === nodes[i - 1] && e.target === id) ||
                (e.source === id && e.target === nodes[i - 1])),
          ),
        ),
      });
    }),
    http.get(url('/runs/:runId/top'), () => json({ items: data.details.filter((n) => n.top_rank !== null) })),
    http.get(url('/runs/:runId/clusters'), ({ request }) => {
      const q = new URL(request.url).searchParams;
      const items = Array.from({ length: 6 }, (_, i) => {
        const nodes = data.nodes.filter((n) => n.cluster_id === i + 1);
        return {
          cluster_id: i + 1,
          n_nodes: nodes.length,
          n_seed: nodes.filter((n) => n.is_seed).length,
          sum_kzt_internal: data.edges
            .filter((e) => nodes.some((n) => n.id === e.source) && nodes.some((n) => n.id === e.target))
            .reduce((s, e) => s + e.sum_kzt, 0),
          top_gids: nodes.slice(0, 3).map((n) => n.id),
          hypothesis:
            'Группа связанных переводами клиентов. Рекомендуется проверить общие назначения платежей.',
          max_priority: Math.max(...nodes.map((n) => n.priority_score)),
          roles: Object.fromEntries(
            data.methodology.role_order.map((role) => [role, nodes.filter((n) => n.role === role).length]),
          ),
          n_truncated: nodes.filter((n) => n.truncated).length,
        };
      });
      const key = q.get('sort_by') ?? 'max_priority';
      items.sort((a, b) => Number(b[key as keyof typeof b]) - Number(a[key as keyof typeof a]));
      return json(page(items, q));
    }),
    http.get(url('/runs/:runId/data-requests'), ({ request }) =>
      json(
        page(
          data.nodes
            .filter((n) => n.truncated)
            .map((n) => ({
              id: n.id,
              request: 'Полная выписка',
              value_kzt: n.in_kzt,
              reason: 'Исходящие переводы за пределами глубины сбора неизвестны.',
            })),
          new URL(request.url).searchParams,
        ),
      ),
    ),
    http.post(url('/runs/:runId/assistant'), async ({ request }) => {
      await delay(100);
      const body = (await request.json()) as { question: string };
      const ids = body.question.match(/\d{18}/g) ?? data.nodes.slice(0, 5).map((n) => n.id);
      const found = data.details.filter((n) => ids.includes(n.id));
      const answer: AssistantAnswer = {
        mode_used: 'offline',
        intent: 'demo',
        answer_markdown: found.length
          ? '**Рекомендуется проверить связи этих клиентов.**\n\nЭто синтетический пример ответа. Роли являются гипотезами.'
          : 'Клиент не найден в синтетическом наборе.',
        citations: found.map((n) => ({ id: n.id, role: n.role, note: n.evidence })),
        actions: found.length
          ? [{ type: 'highlight', ids: found.map((n) => n.id), label: 'Показать найденных клиентов' }]
          : [],
        highlight: { nodes: found.map((n) => n.id), edges: [] },
        candidates: [],
        warnings: ['Ответ эмулируется для проверки интерфейса.'],
        suggestions: found.slice(0, 2).map((n) => `почему ${n.id}`),
      };
      return json(answer);
    }),
    http.get(url('/runs/:runId/exports'), () =>
      json({
        items: [
          {
            name: 'nodes_roles',
            filename: 'nodes_roles.csv',
            content_type: 'text/csv',
            size_bytes: 3000,
            description: 'Роли клиентов',
          },
          {
            name: 'run_report',
            filename: 'run_report.md',
            content_type: 'text/markdown',
            size_bytes: 80,
            description: 'Отчёт об анализе',
          },
        ],
      }),
    ),
    http.get(
      url('/runs/:runId/exports/:name'),
      ({ params }) =>
        new HttpResponse(
          params.name === 'run_report'
            ? '# Синтетическое исследование\nРоли — гипотезы для проверки.'
            : [
                'gid,role,priority_score',
                ...data.nodes.map((n) => `${n.id},${n.role},${n.priority_score}`),
              ].join('\n'),
          {
            headers: {
              'Content-Type': params.name === 'run_report' ? 'text/markdown' : 'text/csv',
              'Content-Disposition': `attachment; filename="${params.name === 'run_report' ? 'run_report.md' : 'nodes_roles.csv'}"`,
            },
          },
        ),
    ),
  ];
}
