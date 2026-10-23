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

export const platform = {
  name: 'native',
  available() { return getSkia() !== null; },
  async decode(bytes) {
    const sk = getSkia();
    if (!sk) throw new Error('Skia is not available');
    const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    const image = sk.Skia.Image.MakeImageFromEncoded(sk.Skia.Data.fromBytes(u8));
    if (!image) throw new Error('tile could not be decoded');
    return { image, bytes: image.width() * image.height() * 4 };
  },
  dispose(image) { try { if (image && image.dispose) image.dispose(); } catch (_e) { /* already freed */ } },
  disk: sheetTileStore,
  dpr() { return Math.min(3, PixelRatio.get() || 1); },
  maxBytes: 96 * 1024 * 1024,
};
export default platform;
