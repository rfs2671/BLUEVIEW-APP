// The LeveLog logo for the current theme. The dark theme keeps the light
// outlined mark; the light theme gets the solid navy mark.
// (Static require paths, so the bundler can find both.)
export function logoSource(isDark) {
  return isDark
    ? require('../../assets/logo-header.png')
    : require('../../assets/logo-header-light.png');
}
