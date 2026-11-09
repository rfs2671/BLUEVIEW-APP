import React, { useMemo, useRef } from 'react';
import { StyleSheet } from 'react-native';
import { WebView } from 'react-native-webview';
import { buildEntranceHtml } from '../utils/logoEntranceHtml';

/**
 * Phone version of the login entrance: the particle animation runs in a
 * transparent web view laid over the screen. The page tells the app when to
 * reveal the logo and the login card ('logo', 'ui', 'done'); see
 * utils/logoEntranceHtml.js. The web build has its own LogoEntrance.web.jsx.
 */
export default function LogoEntrance({ size, rect, dark, onEvent, onFail }) {
  const html = useMemo(
    () => buildEntranceHtml({ w: size.w, h: size.h, rect, dark }),
    // the page is built once per mount: its size and the logo's place do not change while it plays
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const cb = useRef(onEvent); cb.current = onEvent;
  return (
    <WebView
      source={{ html }}
      originWhitelist={['*']}
      style={styles.web}
      containerStyle={styles.web}
      pointerEvents="none"
      scrollEnabled={false}
      bounces={false}
      javaScriptEnabled
      opaque={false}
      androidLayerType="hardware"
      setSupportMultipleWindows={false}
      onMessage={(e) => { try { cb.current(String(e.nativeEvent.data)); } catch (_e) { /* the animation must never break login */ } }}
      onError={() => { if (onFail) onFail(); }}
      onRenderProcessGone={() => { if (onFail) onFail(); }}
    />
  );
}

const styles = StyleSheet.create({
  web: { ...StyleSheet.absoluteFillObject, backgroundColor: 'transparent' },
});
