import { DirectedGraph } from 'graphology';
import Sigma from 'sigma';
import type { Settings } from 'sigma/settings';
import { expect, it, vi } from 'vitest';
import { createDemoData } from '../mocks/data';
import { createGraphRenderer } from './adapter';
import { GRAPH_THEME as theme } from './theme';

vi.mock('sigma', () => ({ default: vi.fn() }));
vi.mock('sigma/rendering', () => ({
  NodeCircleProgram: vi.fn(),
  createNodeCompoundProgram: vi.fn(),
}));

function createFakeSigma() {
  let graph = new DirectedGraph();
  let framed = false;
  const camera = { animate: vi.fn(), setState: vi.fn(), ratio: 1 };
  const renderer = {
    on: vi.fn(),
    kill: vi.fn(),
    setSetting: vi.fn<Sigma['setSetting']>(),
    setGraph: vi.fn((value: DirectedGraph) => {
      graph = value;
      framed = false;
    }),
    getGraph: () => graph,
    getCamera: () => camera,
    getDimensions: () => ({ width: 800, height: 600 }),
    framedGraphToViewport: ({ x, y }: { x: number; y: number }) => ({ x: x * 600, y: y * 600 }),
    refresh: vi.fn(() => {
      framed = true;
    }),
    getNodeDisplayData: vi.fn((id: string) => {
      if (!graph.hasNode(id)) return undefined;
      return framed ? { x: 0.25, y: 0.75 } : graph.getNodeAttributes(id);
    }),
  };
  vi.mocked(Sigma).mockImplementation(function () {
    return renderer as unknown as Sigma;
  });
  const adapter = createGraphRenderer(document.createElement('div'), vi.fn(), vi.fn());
  return { renderer, camera, adapter };
}

it('targets framed coordinates after replace followed immediately by style', () => {
  const { renderer, camera, adapter } = createFakeSigma();
  const data = createDemoData();
  const selected = data.nodes[0].id;
  adapter.replace({ ...data.graph, nodes: data.graph.nodes.map((n) => ({ ...n, x: 2000, y: -1000 })) });
  adapter.style({ colorBy: 'role', selected, methodology: data.methodology });

  expect(renderer.refresh.mock.invocationCallOrder[0]).toBeLessThan(
    renderer.getNodeDisplayData.mock.invocationCallOrder[0],
  );
  const target = camera.animate.mock.calls[0][0] as { x: number; y: number; ratio: number };
  expect(target.x).toBeGreaterThanOrEqual(0);
  expect(target.x).toBeLessThanOrEqual(1);
  expect(target.y).toBeGreaterThanOrEqual(0);
  expect(target.y).toBeLessThanOrEqual(1);
  expect(target.ratio).toBe(theme.selectedZoom);
  adapter.destroy();
});

it('dims unrelated nodes and edges and fits assistant highlights', () => {
  const { renderer, camera, adapter } = createFakeSigma();
  const data = createDemoData();
  const edge = data.edges[0];
  const ids = [edge.source, edge.target];
  adapter.replace(data.graph);
  adapter.style({
    colorBy: 'role',
    selected: null,
    methodology: data.methodology,
    highlight: { nodes: ids, edges: [[edge.source, edge.target]] },
  });
  const nodeReducer = renderer.setSetting.mock.calls.find(
    ([key]) => key === 'nodeReducer',
  )?.[1] as NonNullable<Settings['nodeReducer']>;
  const edgeReducer = renderer.setSetting.mock.calls.find(
    ([key]) => key === 'edgeReducer',
  )?.[1] as NonNullable<Settings['edgeReducer']>;
  const graph = renderer.getGraph();
  const unrelated = data.nodes.find((n) => !ids.includes(n.id))!;
  expect(nodeReducer(unrelated.id, graph.getNodeAttributes(unrelated.id)).color).toBe(theme.mutedNode);
  expect(nodeReducer(edge.source, graph.getNodeAttributes(edge.source)).highlighted).toBe(true);
  const key = JSON.stringify([edge.source, edge.target]);
  expect(edgeReducer(key, graph.getEdgeAttributes(key)).color).toBe(theme.highlightEdge);
  const otherEdge = graph.edges().find((id) => id !== key)!;
  expect(edgeReducer(otherEdge, graph.getEdgeAttributes(otherEdge)).color).toBe(theme.mutedEdge);

  renderer.getNodeDisplayData.mockImplementation((id) => {
    if (id === ids[0]) return { x: 0.1, y: 0.2 };
    if (id === ids[1]) return { x: 0.9, y: 0.8 };
    return undefined;
  });
  adapter.fit([...ids, 'missing']);
  expect(camera.animate).toHaveBeenLastCalledWith(
    { x: 0.5, y: 0.5, ratio: 0.75 },
    { duration: theme.cameraDuration },
  );
  adapter.destroy();
});
