# Контракт `out/graph.json`

Единый файл данных для экрана просмотра (`out/viewer.html`) и AI-ассистента (`moneygraph serve`).
Пишется пайплайном (`moneygraph.export.write_graph_json`). **Все gid — строки** (18-значные числа не
помещаются в JS Number без потери точности).

```jsonc
{
  "meta": {
    "generated_at": "2026-09-23T14:00:00",
    "period": ["2026-07-01", "2026-07-31"],
    "n_nodes": 2248, "n_edges": 3119, "n_tx": 4840, "n_seed": 81,
    "total_kzt": 365890012.0,
    "roles": {                       // словарь ролей: порядок = приоритет в легенде
      "coordinator":  {"ru": "Координатор",   "color": "#e34948", "typology": "", "description": "..."},
      "consolidator": {"ru": "Консолидатор",  "color": "#eda100", "typology": "funnel account (воронка)", "description": "..."},
      "distributor":  {"ru": "Распределитель","color": "#4a3aa7", "description": "..."},
      "transit":      {"ru": "Транзит",       "color": "#2a78d6", "description": "..."},
      "terminal":     {"ru": "Конечный получатель", "color": "#008300", "description": "..."},
      "peripheral":   {"ru": "Периферия",     "color": "#a0a9b1", "description": "..."}
    },
    "role_counts": {"coordinator": 12, "...": 0},
    "flags": {"fast_transit": "rapid movement of funds: ушло дальше за ≤2 дн", "...": "..."}   // код флага → подпись
  },
  "nodes": [{
    "id": "100000003684369100",
    "role": "consolidator", "role_score": 0.83,
    "rule_fired": "R3: in_deg=11 ≥ 4",   // какое правило сработало (текст)
    "alt_role": "distributor",           // "" если нет
    "typology": "funnel account (воронка); rapid movement of funds",   // типологии AML, "" если нет
    "evidence": "Получает от 11 плательщиков ...",   // ≤200 символов
    "priority": 0.71, "rank": 12,        // rank: место по priority среди всех узлов (1 = важнейший)
    "cluster": 3,
    "is_seed": true, "depth": 0,
    "truncated": false,                  // true для узлов 4-го колена (исходящие не выгружены)
    "p_forward": null,                   // оценка вероятности пересылки дальше (только для truncated), 0..1
    "sink_status": "not_sink",           // confirmed_sink | truncated_depth | truncated_time | not_sink | no_data
    "in_deg": 24, "out_deg": 62, "in_kzt": 3848436.0, "out_kzt": 8588655.0, "in_tx": 58, "out_tx": 67,
    "pagerank": 0.0123, "betweenness": 0.0023,
    "fast_share": 0.75,                  // доля входящих, ушедших дальше за ≤2 дня (null если не считается)
    "flags": ["fast_transit", "burst_in"],
    "prio_parts": {"role": 0.3, "flow": 0.2, "centrality": 0.15, "seed": 0.05, "flags": 0.03},
    "x": 123.4, "y": -56.7               // предрасчитанные координаты раскладки (px)
  }],
  "edges": [{
    "from": "100000003684369100", "to": "100000008603629100",
    "sum": 120000.0, "n_tx": 2,
    "tx": [["2026-07-03", 50000.0], ["2026-07-15", 70000.0]]   // отдельные переводы (дата, сумма)
  }],
  "clusters": [{
    "id": 3, "n_nodes": 140, "n_seed": 4, "sum_internal": 12345678.0,
    "hypothesis": "Признаки точки консолидации ...",
    "top_gids": ["100000003684369100", "..."],
    "roles": {"consolidator": 3, "...": 0}
  }],
  "top": [{"rank": 1, "gid": "100000003684369100", "role": "coordinator", "priority": 0.91,
           "why": "...", "is_seed": false}]
}
```
