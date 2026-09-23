import type Sigma from 'sigma';
import { GRAPH_THEME as theme } from './theme';

export function focusNode(renderer: Sigma, id: string) {
  const position = renderer.getNodeDisplayData(id);
  if (!position) return;
  void renderer
    .getCamera()
    .animate({ x: position.x, y: position.y, ratio: theme.selectedZoom }, { duration: theme.cameraDuration });
}

export function fitNodes(renderer: Sigma, ids: string[]) {
  renderer.refresh();
  const positions = ids.flatMap((id) => {
    const position = renderer.getNodeDisplayData(id);
    return position ? [position] : [];
  });
  if (!positions.length) return;
  const left = Math.min(...positions.map((p) => p.x));
  const right = Math.max(...positions.map((p) => p.x));
  const bottom = Math.min(...positions.map((p) => p.y));
  const top = Math.max(...positions.map((p) => p.y));
  const cameraState = { x: 0.5, y: 0.5, ratio: 1, angle: 0 };
  const start = renderer.framedGraphToViewport({ x: left, y: bottom }, { cameraState });
  const end = renderer.framedGraphToViewport({ x: right, y: top }, { cameraState });
  const { width, height } = renderer.getDimensions();
  const ratio = Math.max(
    theme.selectedZoom,
    Math.abs(end.x - start.x) / Math.max(1, width - theme.fitPadding * 2),
    Math.abs(end.y - start.y) / Math.max(1, height - theme.fitPadding * 2),
  );
  void renderer
    .getCamera()
    .animate(
      { x: (left + right) / 2, y: (bottom + top) / 2, ratio: Math.min(theme.maxZoom, ratio) },
      { duration: theme.cameraDuration },
    );
}
