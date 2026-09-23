import Ajv2020 from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import { describe, expect, it } from 'vitest';
import openapi from '../api/openapi.json';

const fixtureSchemas: Record<string, string> = {
  error_not_found: 'ErrorResponse',
  error_upload: 'ErrorResponse',
  error_validation: 'ErrorResponse',
  assistant_ambiguous: 'AssistantAnswer',
  assistant_collectors: 'AssistantAnswer',
  assistant_explain: 'AssistantAnswer',
  assistant_help: 'AssistantAnswer',
  cluster_detail: 'Cluster',
  clusters: 'ClusterPage',
  counterparties_in: 'CounterpartyPage',
  counterparties_out: 'CounterpartyPage',
  data_requests: 'DataRequestPage',
  exports: 'ExportList',
  graph: 'Subgraph',
  graph_hydrate: 'Subgraph',
  meta: 'Meta',
  methodology: 'Methodology',
  neighborhood: 'Subgraph',
  node_detail: 'NodeDetail',
  nodes_page: 'NodePage',
  overview: 'Overview',
  path: 'PathResult',
  run_cancelled: 'Run',
  run_cancelling: 'Run',
  run_failed_validation: 'Run',
  run_queued: 'Run',
  run_succeeded: 'Run',
  runs_list: 'RunList',
  search: 'SearchResult',
  session: 'SessionState',
  top: 'TopList',
  trace_down: 'Subgraph',
  trace_up: 'Subgraph',
  transactions: 'TransactionPage',
};
describe('captured backend fixtures', () => {
  const fixtures = import.meta.glob('./fixtures/*.json', { eager: true, import: 'default' });
  for (const [name, schema] of Object.entries(fixtureSchemas))
    it(`${name} matches ${schema}`, () => {
      const ajv = new Ajv2020({ strict: false, allErrors: true });
      addFormats(ajv);
      ajv.addSchema({ $id: 'contract', components: openapi.components });
      const validate = ajv.compile({ $ref: `contract#/components/schemas/${schema}` });
      expect(validate(fixtures[`./fixtures/${name}.json`]), JSON.stringify(validate.errors)).toBe(true);
    });
});
