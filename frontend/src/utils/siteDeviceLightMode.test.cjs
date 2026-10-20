/**
 * A site device account is drawn in the light theme on every page, and nothing else about theming moves.
 *
 *   node frontend/src/utils/siteDeviceLightMode.test.cjs
 */
const fs = require('fs');
const path = require('path');
const FRONT = path.join(__dirname, '..', '..');
const read = (...p) => fs.readFileSync(path.join(FRONT, ...p), 'utf8');
let passed = 0; let failed = 0;
const ok = (c, l) => { if (c) { passed += 1; console.log('  PASS ', l); } else { failed += 1; console.log('  FAIL ', l); } };

// 1. The rule itself, executed.
const modeSrc = read('src', 'utils', 'themeMode.js').replace('export const', 'const') + '\nmodule.exports = { effectiveIsDark };';
const m = { exports: {} }; new Function('module', modeSrc)(m);
const { effectiveIsDark } = m.exports;
ok(effectiveIsDark(true, 'light') === false, 'forced light beats a stored DARK choice');
ok(effectiveIsDark(false, 'light') === false, 'forced light with a stored light choice is light');
ok(effectiveIsDark(true, null) === true && effectiveIsDark(false, null) === false, 'not forced: the stored choice is used as it was');
ok(effectiveIsDark(true, undefined) === true, 'an unset force is "not forced"');

// 2. The wiring.
const ctx = read('src', 'context', 'ThemeContext.js');
ok(/forceTheme:\s*setForced/.test(ctx), 'ThemeContext exposes forceTheme');
ok(/if \(forced\) return;/.test(ctx), 'toggleTheme does nothing while a mode is forced');
const toggle = ctx.slice(ctx.indexOf('const toggleTheme'), ctx.indexOf('const colors'));
ok(toggle.indexOf('if (forced) return;') < toggle.indexOf('setItem'), 'and returns BEFORE it can write the stored choice');
ok(/getItem\('blueview_user'\)/.test(ctx) && /site_mode/.test(ctx), 'a stored site principal forces light at start (no dark frame on restart)');
ok(/THEME_KEY/.test(ctx) && /setUserIsDark\(val === 'dark'\)/.test(ctx), 'the stored choice is still read exactly as before');

ok(/themeForced: !!forced/.test(ctx), 'ThemeContext tells screens when the theme is forced');
ok(/disabled=\{themeForced\}/.test(read('app', 'settings.jsx')) && /disabled=\{themeForced\}/.test(read('src', 'components', 'FloatingNav.js')), 'and both theme switches are disabled while it is');
ok(/useRef\(getActiveMode\(\)\)/.test(ctx), 'the provider starts from the palette that is really active, not an assumed dark one');

const layout = read('app', '_layout.jsx');
ok(/function SiteDeviceLightMode\(\)/.test(layout), '_layout defines SiteDeviceLightMode');
ok(/forceTheme\(siteMode \? 'light' : null\)/.test(layout), 'it forces light for a site session and releases it otherwise');
ok(/if \(!isLoading\)/.test(layout.slice(layout.indexOf('function SiteDeviceLightMode'))), 'and only after the session has been read');
ok(/<SiteDeviceLightMode \/>/.test(layout), 'it is mounted');
const shell = layout.slice(layout.indexOf('function AppShell'), layout.indexOf('export default function RootLayout'));
ok(/<SiteDeviceLightMode \/>/.test(shell), 'it is mounted inside AppShell');
const prov = layout.indexOf('<ThemeProvider>'); const auth = layout.indexOf('<AuthProvider>'); const app = layout.indexOf('<AppShell />');
ok(prov < auth && auth < app, 'and AppShell is rendered inside both ThemeProvider and AuthProvider');

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
