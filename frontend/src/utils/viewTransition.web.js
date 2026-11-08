import { flushSync } from 'react-dom';

/**
 * A REAL TRANSFORMATION on the web: the browser keeps a picture of the old page,
 * the new theme is rendered live, and the new page is revealed inside a circle
 * that grows out of the control that was pressed. Nothing is covered or blanked:
 * outside the circle you still see the old screen, inside it the new one, both
 * the real thing.
 *
 * Returns true when it ran. False (older browsers, reduced motion) means the
 * caller should use its own fallback.
 */
let styled = false;
function ensureStyle() {
  if (styled || typeof document === 'undefined') return;
  styled = true;
  const el = document.createElement('style');
  el.textContent = `
    ::view-transition-old(root), ::view-transition-new(root) { animation: none; mix-blend-mode: normal; }
    ::view-transition-old(root) { z-index: 1; }
    ::view-transition-new(root) { z-index: 2; }
  `;
  document.head.appendChild(el);
}

export function runThemeViewTransition({ x, y, commit }) {
  if (typeof document === 'undefined' || typeof document.startViewTransition !== 'function') return false;
  try {
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return false;
  } catch (_e) { /* ignore */ }
  ensureStyle();
  const R = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
  const t = document.startViewTransition(() => { flushSync(commit); });
  t.ready.then(() => {
    document.documentElement.animate(
      { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${R}px at ${x}px ${y}px)`] },
      { duration: 560, easing: 'cubic-bezier(0.22, 0.7, 0.2, 1)', pseudoElement: '::view-transition-new(root)' },
    );
  }).catch(() => {});
  return true;
}
