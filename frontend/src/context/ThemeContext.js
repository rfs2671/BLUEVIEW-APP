import React, { createContext, useContext, useState, useEffect, useMemo } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { applyTheme, colors as themeColors } from '../styles/theme';

const THEME_KEY = 'blueview_theme';
// The same blob AuthContext reads its session out of (api.js getStoredUser).
// See the note on the boot effect for why the theme reads storage directly
// rather than the auth context.
const USER_KEY = 'blueview_user';

const ThemeContext = createContext(null);

/**
 * Is this install a jobsite gate tablet?
 *
 * The same test the RouteGuard in app/_layout.jsx makes — `siteMode ||
 * user?.role === 'site_device'` — against the stored user rather than the auth
 * context, because AuthContext sets siteMode from EITHER the `site_mode` flag
 * on /auth/me or the role, and a device provisioned before the role existed
 * carries only the flag.
 */
export const isSiteDeviceUser = (u) => (
  !!u && (u.site_mode === true || u.role === 'site_device')
);

export const ThemeProvider = ({ children }) => {
  const [isDark, setIsDark]     = useState(true);
  const [themeKey, setThemeKey] = useState(0);
  // THE GATE TABLET IS PINNED TO LIGHT. It is a fixed installation bolted up at
  // a construction gate and read in daylight by DOB inspectors who did not
  // configure it and cannot reconfigure it: the RouteGuard confines a site
  // device to `/site/*` and `/login`, and both theme switches in the product
  // (app/settings.jsx and the SettingsModal in src/components/FloatingNav.js)
  // live on routes it can never reach. So this is not a default it can move
  // off — it is a pin, and the stored preference is not consulted for it. A
  // `blueview_theme` value on a gate tablet can only have been left there by
  // whoever provisioned it, and the inspector in the sun is the one who pays.
  const [isPinnedLight, setIsPinnedLight] = useState(false);

  const applyMode = (dark) => {
    applyTheme(dark ? 'dark' : 'light');
    setIsDark(dark);
    setThemeKey(k => k + 1);
  };

  // COLD BOOT. This provider mounts OUTSIDE AuthProvider (app/_layout.jsx:
  // ThemeProvider > DatabaseProvider > AuthProvider), so useAuth() is not
  // available here and the theme cannot be derived from the auth context at
  // the moment it is decided. It reads the stored user directly instead —
  // local, synchronous-ish, and no network. Deriving it from AuthContext alone
  // would mean waiting on validateSession's /auth/me round trip, which on a
  // jobsite connection can be the whole axios timeout: the gate tablet would
  // sit dark in the sun for exactly as long as the signal is bad.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      let storedUser = null;
      let storedTheme = null;
      try { storedUser = JSON.parse(await AsyncStorage.getItem(USER_KEY)); } catch (_) {}
      try { storedTheme = await AsyncStorage.getItem(THEME_KEY); } catch (_) {}
      if (cancelled) return;

      if (isSiteDeviceUser(storedUser)) {
        setIsPinnedLight(true);
        applyMode(false);
        return;
      }
      if (storedTheme !== null) applyMode(storedTheme === 'dark');
    })();
    return () => { cancelled = true; };
  }, []);

  /**
   * The live role, reported by a consumer that IS inside AuthProvider.
   *
   * A tablet is provisioned by LOGGING IN, and a login is not a cold boot: the
   * effect above already ran, against the previous stored user or none at all.
   * Without this the device installed this morning stays dark until something
   * restarts the app — which on a kiosk tablet may be weeks. AppShell calls
   * this whenever siteMode changes.
   *
   * One-directional on purpose: being told "not a site device" clears the pin
   * (a logout, or an admin signing in on the same hardware) but never pushes
   * anyone to dark. Only the site device's pin moves the palette.
   */
  const setSiteDevice = (isSiteDevice) => {
    const pinned = !!isSiteDevice;
    setIsPinnedLight(pinned);
    if (pinned && isDark) applyMode(false);
  };

  const toggleTheme = async () => {
    // No control reaches this on a gate tablet today. The guard is what keeps
    // that true if one is ever added to a /site screen by someone who does not
    // know why the tablet is light.
    if (isPinnedLight) return;
    const next = !isDark;
    applyMode(next);
    try { await AsyncStorage.setItem(THEME_KEY, next ? 'dark' : 'light'); } catch (_) {}
  };

  // Deep copy: new identity on each toggle → triggers downstream re-renders
  const colors = useMemo(() => JSON.parse(JSON.stringify(themeColors)), [themeKey]);

  return (
    <ThemeContext.Provider value={{ isDark, isPinnedLight, themeKey, colors, toggleTheme, setSiteDevice }}>
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = () => {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used inside ThemeProvider');
  return ctx;
};

export default ThemeContext;
