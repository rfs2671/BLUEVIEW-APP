/**
 * Where a callout portal's camera starts and what it may reach. Shared by the React
 * portal (Skia / web) and the WebView page so they cannot drift.
 *
 * THE WHOLE TARGET SHEET IS LOADED; THE CROP ONLY FRAMES THE FIRST VIEW. The crop is an
 * estimate (`crop_exact: false`), so clipping to it would cut off whatever the estimate
 * missed. The camera starts on the crop with a 40% margin around it, and the reader can
 * pan and zoom across the whole sheet. It is confined to the target PAGE, not to the crop
 * and not into the other pages of the file.
 */
export const CROP_MARGIN = 0.4;

/** Apply the framing once the viewport is measured; returns true when it did. */
export function framePortal(controller, portal) {
  if (!controller || controller.viewport.width <= 0) return false;
  controller.setBounds(portal.page, [0, 0, 1, 1], 0);
  if (portal.box) controller.frameBox(portal.page, portal.box, CROP_MARGIN);
  else controller.frameBox(portal.page, [0, 0, 1, 1], 0.02);
  return true;
}

/** Call framePortal now and again whenever the viewport width changes (rotation, resize). */
export function keepPortalFramed(controller, portal) {
  let done = -1;
  const run = () => {
    const w = controller.viewport.width;
    if (w > 0 && w !== done && framePortal(controller, portal)) done = w;
  };
  run();
  return controller.on('change', run);
}
