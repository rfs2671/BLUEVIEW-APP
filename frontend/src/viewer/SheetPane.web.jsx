/**
 * The web renderer: a thin React wrapper around the framework-free canvas viewer
 * (canvasViewer.js), which the phone WebView page mounts too.
 */
import React, { useEffect, useRef } from 'react';
import { mountCanvasViewer } from './canvasViewer';

export { paint } from './canvasViewer';

const BG = '#131E27';

export default function SheetPane({
  controller, onTap, onDoubleTap, interactive = true, background, showCallouts = true, testID, style,
}) {
  const wrapRef = useRef(null);
  const cbs = useRef({ onTap, onDoubleTap });
  cbs.current = { onTap, onDoubleTap };

  useEffect(() => {
    if (!wrapRef.current || !controller) return undefined;
    const v = mountCanvasViewer(wrapRef.current, controller, {
      interactive, background, showCallouts,
      onTap: (hit, p) => cbs.current.onTap && cbs.current.onTap(hit, p),
      onDoubleTap: () => cbs.current.onDoubleTap && cbs.current.onDoubleTap(),
    });
    return () => v.destroy();
  }, [controller, interactive, background, showCallouts]);

  return (
    <div
      ref={wrapRef}
      data-testid={testID}
      style={{ position: 'relative', width: '100%', height: '100%', overflow: 'hidden', background: background || BG, ...style }}
    />
  );
}
