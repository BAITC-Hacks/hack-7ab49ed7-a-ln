import type { components } from './generated';

type Schema = components['schemas'];
export type ErrorBody = Schema['ErrorBody'];
export type FieldIssue = Schema['FieldIssue'];
export type Meta = Schema['Meta'];
export type Session = Schema['SessionState'];
export type Methodology = Schema['Methodology'];
export type RunSummary = Schema['RunSummary'];
export type Run = Schema['Run'];
export type GraphNode = Schema['GraphNode'];
export type GraphEdge = Schema['GraphEdge'];
export type Subgraph = Schema['Subgraph'];
export type NodeRow = Schema['NodeRow'];
export type NodeDetail = Schema['NodeDetail'];
export type Counterparty = Schema['Counterparty'];
export type Transaction = Schema['Transaction'];
export type TopItem = Schema['TopItem'];
export type Cluster = Schema['Cluster'];
export type ResilienceRow = Schema['ResilienceRow'];
export type Overview = Schema['Overview'];
export type DataRequest = Schema['DataRequest'];
export type ExportFile = Schema['ExportItem'];
export type AssistantAction = Schema['AssistantAction'];
export type AssistantAnswer = Schema['AssistantAnswer'];
export type PathResult = Schema['PathResult'];
export type Role = GraphNode['role'];
export type MetricUnit = Schema['Metric']['unit'];
export type AssistantMode = NonNullable<Schema['AssistantRequest']['mode']>;
export interface Page<T> {
  items: T[];
  total: number;
}
export type SortBy =
  | 'priority_score'
  | 'role_score'
  | 'in_kzt'
  | 'out_kzt'
  | 'in_deg'
  | 'out_deg'
  | 'traced_in_kzt'
  | 'control_nodes';
export interface Filters {
  role?: Role[];
  cluster_id?: number;
  min_priority?: number;
  hide_peripheral?: boolean;
  q?: string;
  is_seed?: boolean;
  flag?: string;
}
