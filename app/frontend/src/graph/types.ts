import type { AssistantAnswer, Methodology, Subgraph } from '../api/types';

export interface GraphStyle {
  colorBy: 'role' | 'cluster';
  selected: string | null;
  methodology: Methodology;
  highlight?: AssistantAnswer['highlight'];
}
export interface GraphRenderer {
  replace(data: Subgraph): void;
  style(options: GraphStyle): void;
  fit(ids: string[]): void;
  zoom(direction: 'in' | 'out' | 'reset'): void;
  destroy(): void;
}
export type GraphFactory = (
  container: HTMLElement,
  onSelect: (id: string) => void,
  onFailure: (error: Error) => void,
) => GraphRenderer;
