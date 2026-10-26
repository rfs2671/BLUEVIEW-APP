/**
 * Phone platform pieces for the tile viewer. A phone draws tiles in a WebView page
 * (SheetWebViewPane.native.jsx + webview/main.js): the same engine and canvas viewer as the
 * web app, delivered with an ordinary OTA update. Everything that needs an image decoder, a
 * tile cache or a disk store lives in that page, so nothing is created here.
 *
 * (A native Skia renderer was built and removed: the WebView is as fast in practice, ships
 * without a new native build, and carries nothing that has to be compiled into the app.)
 */
import { PixelRatio } from 'react-native';

let webview;                            // undefined = not tried, true/false after
function hasWebView() {
  if (webview !== undefined) return webview;
  try {
    // eslint-disable-next-line global-require
    webview = Boolean(require('react-native-webview').WebView);
  } catch (_e) {
    webview = false;
  }
  return webview;
}

export const platform = {
  name: 'native',
  /** 'webview' when the app has react-native-webview; null otherwise, and the PDF viewer is kept. */
  mode() { return hasWebView() ? 'webview' : null; },
  available() { return platform.mode() !== null; },
  dpr() { return Math.min(3, PixelRatio.get() || 1); },
  // the page owns decoding and caching; the app keeps nothing on disk for tiles
  decode: null,
  dispose() {},
  disk: null,
  maxBytes: 0,
};
export default platform;
