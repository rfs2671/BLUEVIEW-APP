// Native: there is no way to hold a picture of the old screen without a native
// module, so the caller falls back to its own animation. See viewTransition.web.js.
export function runThemeViewTransition() {
  return false;
}
