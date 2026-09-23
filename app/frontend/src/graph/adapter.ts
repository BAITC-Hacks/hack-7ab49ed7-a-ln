import { DirectedGraph } from 'graphology';
import Sigma from 'sigma';
import { NodeCircleProgram, createNodeCompoundProgram } from 'sigma/rendering';
import type { NodeDisplayData } from 'sigma/types';
import type { Methodology, Subgraph } from '../api/types';
import { CLUSTER_COLORS, GRAPH_THEME as theme } from './theme';
import type { GraphFactory, GraphStyle } from './types';
import { fitNodes, focusNode } from './camera';

class SeedBorder extends NodeCircleProgram {
  processVisibleItem(index: number, offset: number, data: NodeDisplayData) {
    super.processVisibleItem(index, offset, {
      ...data,
      size: data.size + theme.borderSize,
      color: theme.seedBorder,
    });
  }
}
class SeedGap extends NodeCircleProgram {
  processVisibleItem(index: number, offset: number, data: NodeDisplayData) {
    super.processVisibleItem(index, offset, {
      ...data,
      size: data.size + theme.gapSize,
      color: theme.seedGap,
    });
  }
}
export function clusterColor(cluster: number) {
  return CLUSTER_COLORS[Math.abs(cluster) % CLUSTER_COLORS.length];
}
function pale(color: string) {
  if (!/^#[0-9a-f]{6}$/i.test(color)) return theme.mutedNode;
  return `#${[1, 3, 5]
    .map((i) =>
      Math.round(parseInt(color.slice(i, i + 2), 16) * theme.fadedOpacity + 255 * (1 - theme.fadedOpacity))
        .toString(16)
        .padStart(2, '0'),
    )
    .join('')}`;
}
function createGraph(data: Subgraph) {
  const graph = new DirectedGraph();
  for (const node of data.nodes)
    graph.addNode(node.id, {
      ...node,
      label: `…${node.id.slice(-6)}`,
      size: theme.minSize + theme.prioritySize * node.priority_score ** theme.priorityExponent,
      type: node.is_seed ? 'seed' : 'circle',
      color: theme.node,
    });
  for (const edge of data.edges) {
    if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target)) continue;
    graph.mergeDirectedEdgeWithKey(JSON.stringify([edge.source, edge.target]), edge.source, edge.target, {
      ...edge,
      size: Math.min(
        theme.edgeMaxSize,
        theme.edgeMinSize + Math.log10(Math.max(1, edge.sum_kzt)) / theme.edgeLogDivisor,
      ),
      color: theme.edge,
      type: 'arrow',
    });
  }
  return graph;
}
function applyStyle(renderer: Sigma, { colorBy, selected, methodology, highlight }: GraphStyle) {
  const highlighted = new Set(highlight?.nodes);
  const highlightedEdges = new Set(highlight?.edges.map((edge) => JSON.stringify(edge)));
  const dimOthers = highlighted.size > 0;
  renderer.setSetting('nodeReducer', (id, attributes) => {
    const emphasized = id === selected || highlighted.has(id);
    const color =
      colorBy === 'cluster'
        ? clusterColor(Number(attributes.cluster_id))
        : (methodology.roles[attributes.role as keyof Methodology['roles']]?.color ?? theme.node);
    return {
      ...attributes,
      color: dimOthers && !emphasized ? theme.mutedNode : attributes.truncated ? pale(color) : color,
      highlighted: emphasized,
      forceLabel: emphasized,
      zIndex: emphasized ? 2 : 0,
      size: Number(attributes.size) + (emphasized ? theme.selectedSize : 0),
    };
  });
  renderer.setSetting('edgeReducer', (id, attributes) => {
    const [source, target] = renderer.getGraph().extremities(id);
    const emphasized = highlightedEdges.size
      ? highlightedEdges.has(JSON.stringify([source, target]))
      : highlighted.has(source) && highlighted.has(target);
    return {
      ...attributes,
      color: dimOthers
        ? emphasized
          ? theme.highlightEdge
          : theme.mutedEdge
        : attributes.target === selected
          ? theme.incoming
          : attributes.source === selected
            ? theme.outgoing
            : theme.edge,
      zIndex: emphasized || attributes.target === selected || attributes.source === selected ? 1 : 0,
    };
  });
  renderer.refresh();
  if (selected && renderer.getGraph().hasNode(selected)) {
    focusNode(renderer, selected);
  }
}
function zoom(renderer: Sigma, direction: 'in' | 'out' | 'reset') {
  const camera = renderer.getCamera();
  if (direction === 'reset') camera.setState({ x: 0.5, y: 0.5, ratio: 1 });
  else
    camera.setState({
      ratio: Math.max(
        theme.minZoom,
        Math.min(theme.maxZoom, camera.ratio * (direction === 'in' ? theme.zoomIn : theme.zoomOut)),
      ),
    });
}
function createSigma(container: HTMLElement) {
  return new Sigma(new DirectedGraph(), container, {
    defaultEdgeType: 'arrow',
    labelFont: 'monospace',
    labelSize: 11,
    labelColor: { color: theme.label },
    labelDensity: 0.6,
    labelRenderedSizeThreshold: 9,
    minCameraRatio: theme.minZoom,
    maxCameraRatio: theme.maxZoom,
    stagePadding: 45,
    enableCameraRotation: false,
    hideEdgesOnMove: true,
    nodeProgramClasses: { seed: createNodeCompoundProgram([SeedBorder, SeedGap, NodeCircleProgram]) },
  });
}
export const createGraphRenderer: GraphFactory = (container, onSelect, onFailure) => {
  const renderer = createSigma(container);
  renderer.on('clickNode', ({ node }) => onSelect(node));
  const lost = (event: Event) => {
    event.preventDefault();
    onFailure(new Error('Графический контекст потерян. Связи доступны в таблице.'));
  };
  container.addEventListener('webglcontextlost', lost, true);
  return {
    replace: (data) => renderer.setGraph(createGraph(data)),
    style: (options) => applyStyle(renderer, options),
    fit: (ids) => fitNodes(renderer, ids),
    zoom: (direction) => zoom(renderer, direction),
    destroy() {
      container.removeEventListener('webglcontextlost', lost, true);
      renderer.kill();
    },
  };
};
