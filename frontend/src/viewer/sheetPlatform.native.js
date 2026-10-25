/**
 * Native platform pieces for the tile viewer: decode WebP into a Skia image, free
 * it, the on-device tile store and the pixel ratio. `available()` is the runtime
 * guard: Skia is a native module, so a binary built before it was added (an OTA
 * update reaching an old build) must report "no" and keep the PDF viewer rather
 * than crash. The web twin is sheetPlatform.js.
 */
import { PixelRatio } from 'react-native';
import { sheetTileStore } from '../utils/sheetTileStore';

let skia;                               // undefined = not tried, null = not available
function getSkia() {
  if (skia !== undefined) return skia;
  try {
    // eslint-disable-next-line global-require
    const mod = require('@shopify/react-native-skia');
    skia = mod && mod.Skia && mod.Skia.Data && mod.Skia.Image && typeof mod.Skia.Image.MakeImageFromEncoded === 'function' ? mod : null;
  } catch (_e) {
    skia = null;
  }
  return skia;
}

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
  /**
   * How tiles are drawn here: 'skia' (the native GPU renderer, in builds that include it) or
   * 'webview' (the same engine hosted in a WebView page, which an OTA update can deliver to a
   * build without Skia). null when neither works, and the PDF viewer is kept.
   * EXPO_PUBLIC_SHEET_TILES_RENDERER=webview forces the WebView even where Skia exists.
   */
  mode() {
    if (process.env.EXPO_PUBLIC_SHEET_TILES_RENDERER === 'webview') return hasWebView() ? 'webview' : null;
    if (getSkia() !== null) return 'skia';
    return hasWebView() ? 'webview' : null;
  },
  available() { return platform.mode() !== null; },
  async decode(bytes) {
    const sk = getSkia();
    if (!sk) throw new Error('Skia is not available');
    const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    const image = sk.Skia.Image.MakeImageFromEncoded(sk.Skia.Data.fromBytes(u8));
    if (!image) throw new Error('tile could not be decoded');
    return { image, bytes: image.width() * image.height() * 4 };
  },
  // A decoded tile is a native Skia image (GPU texture). Freeing it is DEFERRED by a
  // short grace period: the scene the canvas is drawing can still hold an evicted tile
  // (or a fallback ancestor) for a frame or two, and drawing a freed image crashes in
  // native code. The controller has already dropped its own reference by now; nothing
  // else holds one: the Reanimated shared values carry only numbers and plain rects.
  disposeDelayMs: 500,
  dispose(image) {
    if (!image || !image.dispose) return;
    setTimeout(() => { try { image.dispose(); } catch (_e) { /* already freed */ } }, platform.disposeDelayMs);
  },
  disk: sheetTileStore,
  dpr() { return Math.min(3, PixelRatio.get() || 1); },
  maxBytes: 96 * 1024 * 1024,
};
export default platform;
