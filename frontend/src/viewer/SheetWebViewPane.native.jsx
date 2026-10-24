/**
 * The tile viewer inside a WebView, for phones whose installed app has no Skia (so it can be
 * delivered with an OTA update). The page (webview/main.js) does all the drawing and
 * gestures; this component loads it, hands it the login token in a message (never in a
 * URL) and relays taps back through the handle.
 */
import React, { useCallback, useEffect, useRef } from 'react';
import { View } from 'react-native';
import { WebView } from 'react-native-webview';
import { getToken } from '../utils/api';
import { SHEET_WEBVIEW_HTML } from './webview/sheetWebViewHtml';
import { API_BASE } from './sheetClient';

// The page's origin: an origin the API already allows (CORS), so its fetches are permitted.
const PAGE_ORIGIN = process.env.EXPO_PUBLIC_WEB_APP_URL || 'https://app.levelog.com';
const SOURCE = { html: SHEET_WEBVIEW_HTML, baseUrl: PAGE_ORIGIN };

export default function SheetWebViewPane({ handle, projectId, fileId, manifest, dpr = 2, portal = null, showCallouts = true, interactive = true, background = '#131E27', onFatal }) {
  const ref = useRef(null);
  const sent = useRef(false);

  useEffect(() => {
    handle.attach((m) => {
      if (ref.current) ref.current.injectJavaScript(`window.__sheetRecv(${JSON.stringify(m)});true;`);
    });
    handle.onError((message) => { if (onFatal) onFatal(message); });
    return () => handle.attach(null);
  }, [handle, onFatal]);

  // the page asks for nothing: once it has loaded, give it everything it needs in one message
  const sendInit = useCallback(async () => {
    if (sent.current || !ref.current) return;
    sent.current = true;
    const token = await getToken();
    if (!token) { if (onFatal) onFatal('not signed in'); return; }
    const init = JSON.stringify({ type: 'init', apiBase: API_BASE, token, projectId, fileId, manifest, dpr, portal, showCallouts, interactive, background });
    ref.current.injectJavaScript(`window.__sheetRecv(${init});true;`);
  }, [projectId, fileId, manifest, dpr, portal, showCallouts, interactive, background, onFatal]);

  // a newer manifest (the second compile pass finished) goes to the open page
  useEffect(() => { handle.setManifest(manifest); }, [handle, manifest]);

  const onMessage = useCallback((e) => {
    let m = null;
    try { m = JSON.parse(e.nativeEvent.data); } catch (_e) { return; }
    if (m && m.type === 'loaded') { sent.current = false; sendInit(); }   // once per page load
    else handle.receive(m);
  }, [handle, sendInit]);

  return (
    <View style={{ flex: 1, backgroundColor: background }}>
      <WebView
        ref={ref}
        source={SOURCE}
        originWhitelist={['*']}
        onMessage={onMessage}
        javaScriptEnabled
        domStorageEnabled={false}
        scrollEnabled={false}
        bounces={false}
        overScrollMode="never"
        setSupportMultipleWindows={false}
        allowsInlineMediaPlayback
        androidLayerType="hardware"
        style={{ flex: 1, backgroundColor: background }}
        onError={() => onFatal && onFatal('webview error')}
        onHttpError={() => onFatal && onFatal('webview http error')}
        onRenderProcessGone={() => onFatal && onFatal('webview process gone')}
        onContentProcessDidTerminate={() => onFatal && onFatal('webview process terminated')}
      />
    </View>
  );
}
