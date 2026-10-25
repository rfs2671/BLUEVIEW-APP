/**
 * The renderer is loaded the first time a tiled drawing is actually shown, never at
 * app start. On native it imports Skia, a native module: a binary built before Skia
 * was added (an OTA update reaching an old build) would fail at import, and a static
 * import here would take the whole PDF viewer, and the screens that import it, down
 * with it. useSheetSession only reports 'tiled' when platform.available() is true,
 * so this is reached only where Skia is present.
 */
let pane = null;
export function getSheetPane() {
  if (!pane) {
    // eslint-disable-next-line global-require
    pane = require('./SheetPane').default;
  }
  return pane;
}
