import React, { useEffect, useMemo, useRef } from 'react';
import { buildEntranceHtml } from '../utils/logoEntranceHtml';

/**
 * Web version of the login entrance: the same page, in a transparent iframe
 * over the screen. It posts 'levelog-entrance:<event>' to the window.
 */
export default function LogoEntrance({ size, rect, dark, onEvent }) {
  const html = useMemo(
    () => buildEntranceHtml({ w: size.w, h: size.h, rect, dark }),
    // built once per mount, as on the phone
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const cb = useRef(onEvent); cb.current = onEvent;
  useEffect(() => {
    const on = (e) => {
      const m = String(e.data || '');
      if (m.indexOf('levelog-entrance:') !== 0) return;
      try { cb.current(m.slice('levelog-entrance:'.length)); } catch (_e) { /* never break login */ }
    };
    window.addEventListener('message', on);
    return () => window.removeEventListener('message', on);
  }, []);
  return React.createElement('iframe', {
    srcDoc: html,
    title: '',
    'aria-hidden': true,
    tabIndex: -1,
    style: { position: 'absolute', left: 0, top: 0, width: size.w, height: size.h, border: 0, background: 'transparent', pointerEvents: 'none' },
  });
}
