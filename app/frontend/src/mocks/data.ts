import type {
  GraphEdge,
  GraphNode,
  Methodology,
  NodeDetail,
  Overview,
  Role,
  Run,
  Subgraph,
} from '../api/types';

export function createDemoData() {
  const role_order: Role[] = [
    'coordinator',
    'consolidator',
    'distributor',
    'transit',
    'terminal',
    'peripheral',
  ];
  const labels = [
    'Координатор',
    'Консолидатор',
    'Распределитель',
    'Транзит',
    'Конечный получатель',
    'Периферия',
  ];
  const colors = ['#9c598d', '#087d85', '#d99732', '#488cc1', '#7774b0', '#a6b6bf'];
  const roles = Object.fromEntries(
    role_order.map((role, i) => [
      role,
      {
        label: labels[i],
        color: colors[i],
        rule: `Синтетический пример роли «${labels[i]}». В реальном анализе правило и пороги передаёт сервер.`,
      },
    ]),
  ) as Methodology['roles'];
  const methodology: Methodology = {
    roles,
    role_order,
    flags: {
      truncated: 'Достигнута граница выгрузки',
      sync_inflow: 'Синхронные поступления',
      seed: 'Исходный клиент',
    },
    priority_components: [
      { key: 'volume', label: 'Видимый оборот', weight: 0.6 },
      { key: 'connections', label: 'Структурные связи', weight: 0.4 },
    ],
    limitations: [
      'Демонстрационные данные синтетические и не описывают реальных клиентов.',
      'Наблюдаются только исходящие переводы от исходных клиентов. Полный баланс неизвестен.',
      'Узлы на предельной глубине могут иметь невидимые исходящие переводы.',
      'Переводы ниже порога сбора и операции вне банка не видны.',
    ],
  };
  const nodes: GraphNode[] = Array.from({ length: 42 }, (_, i) => ({
    id: String(100000000000000001n + BigInt(i)),
    x: Math.cos(i * 2.39996) * (6 + i / 3),
    y: Math.sin(i * 2.39996) * (6 + i / 3),
    role: role_order[i % 6],
    cluster_id: Math.floor(i / 7) + 1,
    priority_score: Number((0.98 - i * 0.021).toFixed(3)),
    priority_rank: i + 1,
    top_rank: i < 20 ? i + 1 : null,
    is_seed: i % 11 === 0,
    truncated: i % 7 === 6,
    in_kzt: 0,
    out_kzt: 0,
  }));
  const edges: GraphEdge[] = nodes.flatMap((node, i) =>
    i === nodes.length - 1
      ? []
      : [
          {
            source: node.id,
            target: nodes[i + 1].id,
            sum_kzt: 12500 * (1 + (i % 9)),
            n_tx: 1 + (i % 3),
            first_date: '2026-07-04',
            last_date: '2026-07-25',
          },
          ...(i % 3 === 0 && i + 5 < nodes.length
            ? [
                {
                  source: node.id,
                  target: nodes[i + 5].id,
                  sum_kzt: 27000,
                  n_tx: 2,
                  first_date: '2026-07-11',
                  last_date: '2026-07-20',
                },
              ]
            : []),
        ],
  );
  for (const node of nodes) {
    node.in_kzt = edges.filter((e) => e.target === node.id).reduce((s, e) => s + e.sum_kzt, 0);
    node.out_kzt = edges.filter((e) => e.source === node.id).reduce((s, e) => s + e.sum_kzt, 0);
  }
  const details: NodeDetail[] = nodes.map((node, i) => ({
    ...node,
    role_score: 0.7,
    priority_reliability: 1,
    depth: i % 5,
    flags: node.truncated ? ['truncated'] : i % 3 === 0 ? ['sync_inflow'] : [],
    in_deg: edges.filter((e) => e.target === node.id).length,
    out_deg: edges.filter((e) => e.source === node.id).length,
    in_tx: edges.filter((e) => e.target === node.id).reduce((s, e) => s + e.n_tx, 0),
    out_tx: edges.filter((e) => e.source === node.id).reduce((s, e) => s + e.n_tx, 0),
    evidence: `Видимый вход ${node.in_kzt} ₸; выход ${node.out_kzt} ₸. Рекомендуется проверить характер переводов.`,
    card: 'Синтетический пример карточки. Для вывода о характере связей необходима дополнительная проверка.',
    why: 'Приоритетный узел в синтетическом примере: рекомендуется изучить контрагентов и назначение переводов.',
    metrics: [
      { key: 'visible_in', label: 'Наблюдаемый вход', value: node.in_kzt, unit: 'kzt' },
      {
        key: 'pass_ratio',
        label: 'Отдал / получил',
        value: node.in_kzt ? node.out_kzt / node.in_kzt : null,
        unit: 'ratio',
      },
    ],
    priority_components: methodology.priority_components.map((c) => ({
      ...c,
      value: node.priority_score,
      contribution: c.weight * node.priority_score,
    })),
    rules: {
      coordinator: node.role === 'coordinator',
      consolidator: node.role === 'consolidator',
      distributor: node.role === 'distributor',
      transit: node.role === 'transit',
      terminal: node.role === 'terminal',
    },
    n_payers: edges.filter((e) => e.target === node.id).length,
    n_recipients: edges.filter((e) => e.source === node.id).length,
  }));
  const summary = {
    n_nodes: nodes.length,
    n_edges: edges.length,
    n_tx: edges.reduce((sum, e) => sum + e.n_tx, 0),
    n_seeds: nodes.filter((n) => n.is_seed).length,
    total_kzt: edges.reduce((sum, e) => sum + e.sum_kzt, 0),
    period: ['2026-07-01', '2026-07-31'] as [string, string],
    n_clusters: 6,
    roles: Object.fromEntries(
      role_order.map((role) => [role, nodes.filter((n) => n.role === role).length]),
    ) as Record<Role, number>,
    flags: { truncated: nodes.filter((n) => n.truncated).length },
  };
  const run: Run = {
    id: '00000000-0000-4000-8000-000000000001',
    name: 'Синтетическая сеть · июль 2026',
    source: 'demo',
    status: 'succeeded',
    cancel_requested: false,
    stage_code: 'done',
    stage_label: 'Анализ завершён',
    progress: 1,
    error: null,
    attempts: 1,
    created_at: '2026-09-23T10:00:00Z',
    updated_at: '2026-09-23T10:00:05Z',
    started_at: '2026-09-23T10:00:01Z',
    finished_at: '2026-09-23T10:00:05Z',
    duration_s: 4,
    poll_after_ms: null,
    params: {
      observation_start: '2026-07-01',
      observation_end: '2026-07-31',
      max_depth: 4,
      min_transfer_kzt: 5000,
      collection_direction: 'outgoing',
    },
    warnings: ['Синтетическая демонстрация интерфейса.'],
    summary,
    engine_version: 'demo-1.2',
  };
  const overview: Overview = {
    params: run.params,
    summary,
    model: { status: 'insufficient_data', auc_cv: null, auc_transfer: null, base_rate: null, n_train: 0 },
    resilience: { base: { reach: nodes.length, flow: summary.total_kzt }, rows: [] },
    data_requests: { 'Полная выписка': nodes.filter((n) => n.truncated).length },
    warnings: run.warnings,
  };
  const graph: Subgraph = {
    center: null,
    nodes,
    edges,
    total_nodes: nodes.length,
    total_edges: edges.length,
    truncated: false,
    truncation_reason: null,
  };
  return { methodology, nodes, edges, details, summary, run, overview, graph };
}
export type DemoData = ReturnType<typeof createDemoData>;
