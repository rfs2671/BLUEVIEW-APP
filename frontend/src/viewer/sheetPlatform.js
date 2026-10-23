/**
 * Web platform pieces for the tile viewer: decode a WebP into an ImageBitmap
 * (off the main thread where the browser allows), free it, the offline cache and
 * the device pixel ratio. The native twin is sheetPlatform.native.js.
 */
import { tileDisk } from './tileDisk.web';

export const platform = {
  name: 'web',
  /** Can this runtime draw tiles at all? */
  available() {
    return typeof document !== 'undefined' && typeof globalThis.createImageBitmap === 'function' && !!document.createElement('canvas').getContext;
  },
  async decode(bytes) {
    const blob = new Blob([bytes], { type: 'image/webp' });
    const bmp = await globalThis.createImageBitmap(blob);
    return { image: bmp, bytes: bmp.width * bmp.height * 4 };
  },
  dispose(image) { try { image.close(); } catch (_e) { /* already closed */ } },
  disk: tileDisk,
  dpr() { return Math.min(3, (typeof window !== 'undefined' && window.devicePixelRatio) || 1); },
  maxBytes: 192 * 1024 * 1024,
};
export default platform;
