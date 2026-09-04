import React, { useEffect, useRef, useState } from 'react';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { View, Text, StyleSheet, Pressable } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { useRouter, usePathname } from 'expo-router';
import { AuthProvider, useAuth } from '../src/context/AuthContext';
import { DatabaseProvider } from '../src/context/DatabaseContext';
import { ThemeProvider, useTheme } from '../src/context/ThemeContext';
import { ToastProvider, useToast } from '../src/components/Toast';
import { FeatureFlagsProvider } from '../src/context/FeatureFlagsContext';
import { InspectorLockProvider, useInspectorLock } from '../src/context/InspectorLockContext';
import { siteDeviceTarget } from '../src/utils/inspectorConfinement';
import { cpPathAllowed, cpNoCompanyPathAllowed, CP_HOME } from '../src/utils/cpConfinement';
import { initSentry, captureException as sentryCaptureException } from '../src/lib/sentry';
import { registerRateLimitToast } from '../src/utils/api';
import { setupDraftAutoSync } from '../src/utils/draftSync';
import { setupFiledPhotoAutoDrain } from '../src/utils/filedPhotoQueue';
import { setupSiteManifestSync } from '../src/utils/siteManifestStore';
import { setupAdminPlanPrefetch } from '../src/utils/adminPlanPrefetch';
import { semantic, withAlpha } from '../src/styles/semanticColors';
import { useIsDesktop } from '../src/hooks/useIsDesktop';
import DesktopShell from '../src/components/DesktopShell';

// Phase C1: initialize Sentry at module top-level so any error
// during AuthProvider / ThemeProvider / DatabaseProvider mounting
// is captured. No-op when EXPO_PUBLIC_SENTRY_DSN is unset (local
// dev, preview deploys without Sentry). Init is idempotent — safe
// to call from module scope on hot-reload.
initSentry();

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('App crash caught by ErrorBoundary:', error, errorInfo);
    this.setState({ errorInfo });
    // Phase C1: forward render-time crashes to Sentry. captureException
    // is a no-op when Sentry isn't initialized (no DSN), so this is
    // safe in local dev too.
    try {
      sentryCaptureException(error, {
        componentStack: (errorInfo && errorInfo.componentStack) || null,
      });
    } catch (_e) { /* never let the error path itself throw */ }
  }

  render() {
    if (this.state.hasError) {
      const msg =
        (this.state.error && (this.state.error.message || String(this.state.error))) ||
        'Unknown error';
      // Surface the stack so users can screenshot it to support. Trim
      // to keep the screen readable on phone.
      const stack = String(
        (this.state.errorInfo && this.state.errorInfo.componentStack) ||
        (this.state.error && this.state.error.stack) ||
        ''
      ).slice(0, 800);

      return (
        <View style={errorStyles.container}>
          <Text style={errorStyles.title}>Something went wrong</Text>
          <Text style={errorStyles.message}>
            The app encountered an unexpected error. Please restart.
          </Text>
          <View style={errorStyles.detailBox}>
            <Text selectable style={errorStyles.errorName}>{msg}</Text>
            {stack ? (
              <Text selectable style={errorStyles.stack}>{stack}</Text>
            ) : null}
          </View>
          <Pressable
            style={errorStyles.button}
            onPress={() => this.setState({ hasError: false, error: null, errorInfo: null })}
          >
            <Text style={errorStyles.buttonText}>Try Again</Text>
          </Pressable>
        </View>
      );
    }
    return this.props.children;
  }
}

const errorStyles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#050a12',
    padding: 32,
  },
  title: {
    color: '#fff',
    fontSize: 22,
    fontWeight: '700',
    marginBottom: 12,
  },
  message: {
    color: '#94a3b8',
    fontSize: 15,
    textAlign: 'center',
    marginBottom: 24,
    lineHeight: 22,
  },
  button: {
    backgroundColor: '#3b82f6',
    paddingHorizontal: 28,
    paddingVertical: 12,
    borderRadius: 8,
  },
  buttonText: {
    color: '#fff',
    fontSize: 15,
    fontWeight: '600',
  },
  detailBox: {
    backgroundColor: withAlpha('#ffffff', 0.06),
    borderColor: withAlpha('#ffffff', 0.15),
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
    marginBottom: 20,
    maxWidth: 520,
    width: '100%',
  },
  errorName: {
    color: semantic.criticalText,
    fontSize: 13,
    fontWeight: '600',
    marginBottom: 8,
  },
  stack: {
    color: '#94a3b8',
    fontSize: 11,
    lineHeight: 14,
  },
});

// Phase B3 — onboarding state values from the backend that mean "user
// is mid-flow and must land on /onboarding". Pre-B3 users (no field
// on doc) get show_onboarding=false from the API and never trip this.
const _ONBOARDING_IN_FLIGHT_STEPS = new Set(['1', '2', '3', '4']);

function _userInOnboarding(user) {
  if (!user) return false;
  const step = user.onboarding_step;
  if (step === undefined || step === null) return false;
  return _ONBOARDING_IN_FLIGHT_STEPS.has(String(step));
}

function RouteGuard() {
  // Phase C1.1 — every hook below is called unconditionally on every
  // render, in a stable order. Pre-C1.1 the useToast() call was
  // wrapped in try/catch, which is a rules-of-hooks (d) pattern —
  // a hook that runs in only one branch of a try/catch creates a
  // conditional-hook footprint that surfaces as React error #310 in
  // production builds (the pattern was latent until C1's
  // @sentry/react bundling reorganized the module-load sequence
  // enough to trip it). useToast now returns null instead of
  // throwing when the provider is missing, so the call is safe
  // unconditional.
  const router = useRouter();
  const pathname = usePathname();
  const { user, siteMode, isAuthenticated, isLoading } = useAuth();
  // `loading` IS LOAD-BEARING AND WAS NOT READ. InspectorLockProvider starts
  // isLocked=false / loading=true and then reads the persisted flag off
  // AsyncStorage. Without `loading` this guard could not tell "not locked"
  // from "not read yet", and it ACTED on the difference — the site arm below
  // is the thing that puts a tablet on the full dashboard. See
  // src/utils/inspectorConfinement.js.
  const { isLocked: inspectorLocked, loading: inspectorLoading } = useInspectorLock();
  const toast = useToast();
  const [isMounted, setIsMounted] = useState(false);
  // Set when THIS guard parked a device on the read-only tab because the lock
  // state was still unknown, so the hold can be released once it is known.
  const heldForLockRef = useRef(false);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    if (!isMounted || isLoading || !isAuthenticated) return;

    const isSiteDevice = siteMode || user?.role === 'site_device';
    // A superintendent is held to the same paths as a CP, and for the same
    // reason: /logbooks is where his own statutory log lives. login.jsx sends
    // him here; without this he would be sent back to '/' on the next render.
    const isCp = user?.role === 'cp' || user?.role === 'superintendent';

    // Phase B3: customer onboarding gate. Newly-registered users
    // (onboarding_step ∈ {1,2,3,4} on their /auth/me payload) land
    // on /onboarding on every authed page until they hit
    // "completed" or "skipped". Site devices and CPs are excluded —
    // those role gates run below and have stricter path constraints.
    if (
      !isSiteDevice &&
      !isCp &&
      _userInOnboarding(user) &&
      pathname !== '/onboarding' &&
      pathname !== '/login'
    ) {
      router.replace('/onboarding');
      return;
    }

    // Site device: can ONLY be on /site/*, /login — and, while Tier 1 ③
    // "Inspector Mode" is engaged, only on the read-only /site/logbooks tab.
    // /login stays reachable throughout so a logout is still possible. The
    // super releases the lock with the "Exit Inspector Mode" control on the
    // logbooks screen; unlocking flips inspectorLocked and re-runs this
    // effect, restoring normal navigation.
    //
    // BOTH RULES ARE ONE DECISION NOW, in src/utils/inspectorConfinement.js.
    // They used to be two sequential ifs, which meant a locked device was
    // first sent TO the dashboard and then bounced off it — and, before the
    // hydration state was read at all, sometimes only the first half ran.
    if (isSiteDevice) {
      const { target, heldForLock } = siteDeviceTarget({
        pathname,
        isLocked: inspectorLocked,
        lockLoading: inspectorLoading,
        heldForLock: heldForLockRef.current,
      });
      heldForLockRef.current = heldForLock;
      if (target && target !== pathname) {
        router.replace(target);
      }
      return;
    }

    // CP: can be on /logbooks/*, /documents, /settings, /consent, /login — NOT
    // admin routes.
    //
    // THE LIST IS IN src/utils/cpConfinement.js NOW, and /consent is on it.
    // Inline, it was a boolean expression inside an effect inside a component
    // that renders null: nothing in the suite could execute it and nothing
    // enumerated it. /consent was added to the app in #308, pushed to by
    // twelve signing screens in b1f1ec5, and never added here — so every CP
    // signature between 2026-09-01 and 2026-09-03 was bounced off the consent
    // screen onto this very line's destination before the agreement painted.
    if (isCp && !cpPathAllowed(pathname)) {
      router.replace(CP_HOME);
    }

    // CP user exists but has no company assignment — authenticated but every
    // company-gated API endpoint will 403. Contain them to safe paths and surface
    // a clear action instead of a cascade of silent errors.
    if (user?.role === 'cp' && !user?.company_id) {
      if (!cpNoCompanyPathAllowed(pathname)) {
        router.replace(CP_HOME);
        if (toast && typeof toast.error === 'function') {
          setTimeout(() => {
            try {
              toast.error(
                'Account Setup Incomplete',
                'Ask your admin to assign you to a company in Settings → Team.'
              );
            } catch (_e) {
              // Non-blocking — redirect already happened.
            }
          }, 400);
        }
      }
    }
  }, [isMounted, isLoading, isAuthenticated, user, siteMode, pathname,
    inspectorLocked, inspectorLoading]);

  return null;
}

/**
 * The gate tablet keeps itself current, with nobody preparing it.
 *
 * A fixed Android tablet bolted to a construction gate has to hold everything
 * the project has approved it to see — plans, documents and submitted logbooks
 * — and still open all of it after a cold boot with the network down. This
 * mounts the manifest poll that fills it: startup, NetInfo reconnect,
 * foreground, and a plain interval.
 *
 * GATED ON THE SITE DEVICE, WHICH IS WHAT "/site/*" MEANS HERE. RouteGuard
 * already confines a site_device to /site/*, so `siteMode && siteProject.id`
 * is the same population by a more reliable test than a pathname — and it
 * cannot start polling a project on a CP's phone.
 *
 * KEYED ON THE PROJECT ID, NOT MOUNTED ONCE. siteProject resolves after the
 * auth bootstrap, so a run at mount would find no project and the first fill
 * would wait out a whole interval. Re-running when the id appears is also what
 * lets a device re-provisioned to another project switch without a restart.
 */
function SiteManifestSync() {
  const { siteMode, siteProject } = useAuth();
  const projectId = siteMode && siteProject?.id ? siteProject.id : null;

  useEffect(() => {
    if (!projectId) return undefined;
    const stop = setupSiteManifestSync(() => projectId);
    return () => { if (typeof stop === 'function') stop(); };
  }, [projectId]);

  return null;
}

/**
 * THE SAME PROMISE, ON THE OTHER DEVICE THAT CAN OPEN PLANS.
 *
 * An admin's phone held nothing: it cached a plan at the moment he tapped it,
 * which is the "open it once while online" instruction the ruling removes. The
 * plans an inspector asks about are the ones nobody opened.
 *
 * NOT THE CP. He does not see plans, so he is out of scope and this must not
 * spend his battery or his data — hence the role test rather than merely
 * "not a site device".
 *
 * MOUNTED ONCE, NOT KEYED ON A PROJECT. Unlike the tablet, which syncs the one
 * job it is bolted to, this walks every assigned project on each trigger and
 * reads the list at fire time — so a project assigned this afternoon is picked
 * up on the next foreground with no remount.
 */
const PLAN_PREFETCH_ROLES = new Set(['admin', 'owner', 'superintendent']);

function AdminPlanPrefetch() {
  const { user, siteMode, isAuthenticated } = useAuth();
  const role = String(user?.role || '').trim().toLowerCase();
  const enabled = !!isAuthenticated && !siteMode && PLAN_PREFETCH_ROLES.has(role);

  useEffect(() => {
    // `enabled` is also read at fire time inside the hook, so a sign-out stops
    // a walk that is already scheduled rather than only preventing the next.
    const stop = setupAdminPlanPrefetch(() => enabled);
    return () => { if (typeof stop === 'function') stop(); };
  }, [enabled]);

  return null;
}

function AppShell() {
  const { isDark, themeKey } = useTheme();
  const toast = useToast();
  const bg = isDark ? '#050a12' : '#D6E4F7';
  // RN-Web desktop presentation layer. False on native and on web < 1024,
  // where the tree below is byte-identical to what it was before this hook.
  const isDesktop = useIsDesktop();

  // Phase C2 — bridge 429 responses from api.js's response
  // interceptor to the user-visible toast system. Re-registers
  // every render so the latest toast handle is always live.
  useEffect(() => {
    registerRateLimitToast(({ message }) => {
      if (toast && typeof toast.error === 'function') {
        toast.error('Slow down', message);
      }
    });
    return () => registerRateLimitToast(null);
  }, [toast]);

  // Offline drafts: drain the pending-push index on every reconnect (and once
  // at startup). markPending() used to only RECORD a failed push — nothing ever
  // re-sent it, so "syncs when you reconnect" was not actually built. This is
  // the drain. It only re-sends pushes the user already initiated.
  useEffect(() => {
    const unsubscribe = setupDraftAutoSync();
    return () => { if (typeof unsubscribe === 'function') unsubscribe(); };
  }, []);

  // A PHOTOGRAPH FOR A FILED LOG, TAKEN IN A CELLAR. Same shape as the draft
  // drain above and here for the same reason: photographs are taken where
  // there is no signal, so the upload is held on the device and something has
  // to send it. THIS IS THAT SOMETHING — startup, reconnect and foreground,
  // all three inside setupFiledPhotoAutoDrain. `sendPendingSignatures` is why
  // this line is written down rather than assumed: it existed, it was correct,
  // and nothing ever called it, so nothing ever drained.
  useEffect(() => {
    const unsubscribe = setupFiledPhotoAutoDrain();
    return () => { if (typeof unsubscribe === 'function') unsubscribe(); };
  }, []);

  // One Stack element, optionally wrapped. On mobile the rendered tree is
  // <View><StatusBar/><RouteGuard/><Stack/></View> — exactly as before.
  const stack = (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: bg },
        animation: 'fade',
      }}
    />
  );

  return (
    <View key={themeKey} style={[styles.container, { backgroundColor: bg }]}>
      <StatusBar style={isDark ? 'light' : 'dark'} />
      <RouteGuard />
      <SiteManifestSync />
      <AdminPlanPrefetch />
      {isDesktop ? <DesktopShell>{stack}</DesktopShell> : stack}
    </View>
  );
}

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <ErrorBoundary>
        <ThemeProvider>
          <DatabaseProvider>
            <AuthProvider>
              <FeatureFlagsProvider>
                <InspectorLockProvider>
                  <ToastProvider>
                    <AppShell />
                  </ToastProvider>
                </InspectorLockProvider>
              </FeatureFlagsProvider>
            </AuthProvider>
          </DatabaseProvider>
        </ThemeProvider>
      </ErrorBoundary>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, overflow: 'hidden' },
});
