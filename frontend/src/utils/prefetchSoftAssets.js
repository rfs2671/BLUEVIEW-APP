import { Image } from 'react-native';
import { SOFT, SOFT_PANEL, SOFT_PILL, SOFT_PEBBLE, SOFT_LOGO } from '../components/softAssets';

/**
 * Loads the soft-silicone pictures of one theme into the image cache BEFORE that theme is shown.
 *
 * A theme switch remounts every screen, and each card then asks for its pictures for the first time in the new colours;
 * on a phone those decode on demand, so the page builds in piece by piece and the switch stutters. Warming the cache
 * while the wipe is still covering the screen (and a few seconds after launch for the other theme) means the new page
 * paints complete. Best effort: any failure is ignored, the pictures just load when drawn.
 */
const done = {};

function collect(node, out) {
  if (!node) return;
  if (typeof node === 'number') { out.push(node); return; }
  if (typeof node === 'object') Object.keys(node).forEach((k) => collect(node[k], out));
}

export function prefetchSoftAssets(mode) {
  if (done[mode]) return;
  done[mode] = true;
  try {
    const mods = [];
    const tones = mode === 'dark' ? ['dark'] : ['light'];
    tones.forEach((t) => {
      collect(SOFT[t], mods);
      collect(SOFT_PANEL[t], mods);
      ['', 'p', 'd'].forEach((suf) => collect(SOFT_PILL[t + suf], mods));
      collect(SOFT_PEBBLE[t], mods);
      collect(SOFT_LOGO[t], mods);
    });
    // The sidebar rail's own navy artwork belongs to the theme too (desktop web only, but harmless elsewhere).
    const rail = mode === 'dark' ? 'raild' : 'raill';
    ['', 'p', 'd'].forEach((suf) => collect(SOFT_PILL[rail + suf], mods));
    collect(SOFT_PEBBLE[rail], mods);
    mods.forEach((m) => {
      try {
        const src = Image.resolveAssetSource(m);
        if (src && src.uri) Image.prefetch(src.uri).catch(() => {});
      } catch (_e) { /* ignore */ }
    });
  } catch (_e) { /* ignore */ }
}
