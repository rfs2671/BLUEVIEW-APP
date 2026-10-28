/**
 * The canvas renderer and the WebView host are loaded the first time a tiled drawing is actually
 * shown, never at app start, and the shared code reaches them through these two functions so the
 * right file is chosen per platform: SheetPane.web.jsx on the web (SheetPane.jsx, an empty
 * placeholder, on a phone) and SheetWebViewPane.native.jsx on a phone (an empty placeholder on
 * the web).
 */
let pane = null;
export function getSheetPane() {
  if (!pane) {
    // eslint-disable-next-line global-require
    pane = require('./SheetPane').default;
  }
  return pane;
}

let webviewPane = null;
/** The WebView-hosted viewer (native only; on web this resolves to an empty component). */
export function getSheetWebViewPane() {
  if (!webviewPane) {
    // eslint-disable-next-line global-require
    webviewPane = require('./SheetWebViewPane').default;
  }
  return webviewPane;
}
