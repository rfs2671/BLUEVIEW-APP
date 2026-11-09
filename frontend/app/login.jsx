import React, { useState, useEffect, useRef, useCallback } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Image, Platform, AccessibilityInfo } from 'react-native';
import Animated, { useSharedValue, useAnimatedStyle, withTiming, Easing } from 'react-native-reanimated';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Mail, Lock, Eye, EyeOff, ArrowRight, Building2 } from 'lucide-react-native';
import AnimatedBackground from '../src/components/AnimatedBackground';
import { GlassCard } from '../src/components/GlassCard';
import GlassInput from '../src/components/GlassInput';
import GlassButton from '../src/components/GlassButton';
import { useToast } from '../src/components/Toast';
import { useAuth } from '../src/context/AuthContext';
import { spacing, borderRadius, typography } from '../src/styles/theme';
import { semantic } from '../src/styles/semanticColors';
import { useTheme } from '../src/context/ThemeContext';
import { useT } from '../src/i18n';
import { readLoginAnswer, companyLabel, roleLabel } from '../src/utils/loginChoice';
import LogoEntrance from '../src/components/LogoEntrance';
import { logoSource } from '../src/utils/logoSource';

// THE ENTRANCE PLAYS ONCE PER APP LAUNCH. Coming back to this screen (signing out,
// a session ending) shows the finished screen straight away.
let entrancePlayed = false;

// The logo forms at the middle of the screen at its normal size, then rises into place together with the login card.
const HERO_SCALE = 1;

// WHERE A ROLE LANDS AFTER LOGIN.
//
// A `superintendent` fell through to '/' — the admin dashboard — because only
// site_mode and cp were named. Nothing then routed him to the CP logbook list,
// and the CP nav is not rendered on that screen, so he reached neither the list
// nor the nav: the two places his own statutory log is reachable from.
//
// He belongs on /logbooks for the same reason a CP does. That is where the
// thirteen log types are listed, including the Construction Superintendent Log
// he is the one person required to file. _layout.jsx's path constraint is
// widened to match, or he would be bounced straight back off it.
const LOGBOOK_LIST_ROLES = ['cp', 'superintendent'];

function getRedirectPath(userData) {
  if (userData.site_mode) return '/site';
  if (LOGBOOK_LIST_ROLES.includes(userData.role)) return '/logbooks';
  return '/';
}

export default function LoginScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { login, isAuthenticated, isLoading: authLoading, siteMode, user } = useAuth();
  const toast = useToast();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  // ONE EMAIL, SEVERAL COMPANIES. Non-null while the person picks which
  // company to sign in to: [{ companyName, role, choiceToken }].
  const [choices, setChoices] = useState(null);
  const t = useT('loginPicker');

  // ── Login entrance (particles pulled into the logo) ──────────────────────
  // phase: 'measure' (waiting for the logo's place on screen), 'playing', 'done'.
  // Anything going wrong, or a tap, or reduced motion, lands on 'done' with the
  // real screen fully shown. Nothing here can leave the form hidden: a timer
  // guarantees it.
  const logoSrc = logoSource(isDark);
  const [phase, setPhase] = useState(entrancePlayed ? 'done' : 'measure');
  const [entranceCfg, setEntranceCfg] = useState(null);
  const overlayRef = useRef(null);
  const logoBoxRef = useRef(null);
  const startedRef = useRef(false);
  const logoOp = useSharedValue(entrancePlayed ? 1 : 0);
  const uiOp = useSharedValue(entrancePlayed ? 1 : 0);
  const uiY = useSharedValue(entrancePlayed ? 0 : 150);
  // The logo is laid out in its final place; during the entrance it is only DRAWN in the middle
  // of the screen (shifted by dyV and enlarged) and rises into place as riseP goes 0 -> 1.
  const riseP = useSharedValue(entrancePlayed ? 1 : 0);
  const dyV = useSharedValue(0);
  const dxV = useSharedValue(0);
  const logoStyle = useAnimatedStyle(() => ({
    opacity: logoOp.value,
    transform: [
      { translateX: dxV.value * (1 - riseP.value) },
      { translateY: dyV.value * (1 - riseP.value) },
      { scale: 1 + (HERO_SCALE - 1) * (1 - riseP.value) },
    ],
  }), [logoOp, riseP, dyV, dxV]);
  const uiStyle = useAnimatedStyle(() => ({ opacity: uiOp.value, transform: [{ translateY: uiY.value }] }), [uiOp, uiY]);

  const finishEntrance = useCallback(() => {
    entrancePlayed = true;
    logoOp.value = withTiming(1, { duration: 90 });
    riseP.value = withTiming(1, { duration: 90 });
    uiOp.value = withTiming(1, { duration: 90 });
    uiY.value = withTiming(0, { duration: 90 });
    setPhase('done');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onEntranceEvent = useCallback((name) => {
    if (name === 'started') { startedRef.current = true; return; }
    if (name === 'logo') { logoOp.value = withTiming(1, { duration: 340, easing: Easing.out(Easing.quad) }); return; }
    if (name === 'rise') {
      // logo and card move up at the same moment, on the same smooth curve; the card fades in as it climbs
      const ease = Easing.inOut(Easing.cubic);
      riseP.value = withTiming(1, { duration: 620, easing: ease });
      uiY.value = withTiming(0, { duration: 620, easing: ease });
      uiOp.value = withTiming(1, { duration: 340, easing: Easing.out(Easing.quad) });
      return;
    }
    if (name === 'done') finishEntrance();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const beginEntrance = useCallback(() => {
    if (phase !== 'measure') return;
    // a beat for the layout to settle (the card is centred and can shift once fonts and insets land)
    setTimeout(() => {
    const o = overlayRef.current; const l = logoBoxRef.current;
    if (!o || !l || typeof o.measureInWindow !== 'function') return;
    o.measureInWindow((ox, oy, ow, oh) => {
      l.measureInWindow((lx, ly, lw, lh) => {
        if (!ow || !oh || !lw || !lh) { finishEntrance(); return; }
        // the logo is drawn "contain" inside its box: find where the picture itself sits
        const sc = Math.min(lw / 2103, lh / 1080);
        const dw = 2103 * sc; const dh = 1080 * sc;
        // The swarm lands in the MIDDLE of the screen, a little larger than the finished logo.
        const cw = dw * HERO_SCALE; const ch = dh * HERO_SCALE;
        dyV.value = (oy + oh / 2) - (ly + lh / 2); // from its final place down to the middle
        dxV.value = (ox + ow / 2) - (lx + lw / 2);
        setEntranceCfg({
          size: { w: ow, h: oh },
          rect: { x: ow / 2 - cw / 2, y: oh / 2 - ch / 2, w: cw, h: ch },
        });
        setPhase('playing');
      });
    });
    }, 90);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  useEffect(() => {
    if (phase === 'done') return undefined;
    try {
      AccessibilityInfo.isReduceMotionEnabled().then((r) => { if (r) finishEntrance(); }).catch(() => {});
    } catch (_e) { /* ignore */ }
    // never leave the form hidden: not started in time, or not finished in time
    const t1 = setTimeout(() => { if (!startedRef.current) finishEntrance(); }, 3000);
    const t2 = setTimeout(finishEntrance, 6000);
    return () => { clearTimeout(t1); clearTimeout(t2); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase === 'done']);

  const pwdRef = useRef(null);

  useEffect(() => {
    if (isAuthenticated && !authLoading) {
      if (siteMode) {
        router.replace('/site');
      } else if (LOGBOOK_LIST_ROLES.includes(user?.role)) {
        // THE SAME LIST getRedirectPath USES, AND IT WAS NOT. This branch —
        // the one that runs when an ALREADY-authenticated session lands on the
        // login screen, which is every cold start with a live token — named
        // only 'cp'. So the superintendent fix above applied on the day he
        // typed his password and never again: the next launch dropped him on
        // '/', the admin dashboard, which renders neither the logbook list nor
        // the CP nav. Two spellings of one rule, and only one of them was
        // fixed.
        router.replace('/logbooks');
      } else {
        router.replace('/');
      }
    }
  }, [isAuthenticated, authLoading, siteMode, user]);

  const handleSubmit = async () => {
    if (!email.trim() || !password.trim()) {
      setError('Please enter email and password');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const result = await login(email, password);
      // The password opened accounts in more than one company: no session
      // yet. Show the picker; a choice finishes in handleChoose.
      if (result && result.choose_company === true) {
        const answer = readLoginAnswer(result);
        if (answer.kind !== 'choose') throw new Error(t('failed'));
        setChoices(answer.accounts);
        return;
      }
      finishLogin(result);
    } catch (err) {
      const errorMessage = err.response?.data?.detail || err.message || 'Invalid credentials';
      setError(errorMessage);
      toast.error('Login Failed', errorMessage);
    } finally {
      setLoading(false);
    }
  };

  const finishLogin = (userData) => {
    const dest = getRedirectPath(userData);

    if (userData.site_mode) {
      toast.success('Site Mode', `Connected to ${userData.project_name || 'project'}`);
    } else {
      toast.success('Welcome back!', `Logged in as ${userData.full_name || userData.name || userData.email}`);
    }

    router.replace(dest);
  };

  const handleChoose = async (account) => {
    if (loading) return;
    setLoading(true);
    setError('');
    try {
      const userData = await login(email, password, account.choiceToken);
      finishLogin(userData);
    } catch (err) {
      // A choice lives five minutes. Whatever went wrong, the way on is a
      // fresh sign-in, so the form comes back with the reason under it.
      const errorMessage = err.response?.data?.detail || err.message || t('failed');
      setChoices(null);
      setError(errorMessage);
      toast.error(t('failedTitle'), errorMessage);
    } finally {
      setLoading(false);
    }
  };

  const backToForm = () => {
    setChoices(null);
    setError('');
  };

  // FIX: branded splash instead of bare white View
  if (authLoading) {
    return (
      <AnimatedBackground>
        <View style={s.loadingContainer}>
          <Image
            source={logoSrc}
            style={{ width: '100%', maxWidth: 440, height: 200, resizeMode: 'contain' }}
          />
          <ActivityIndicator size="large" color={colors.primary} style={{ marginTop: spacing.lg }} />
        </View>
      </AnimatedBackground>
    );
  }

  return (
    <AnimatedBackground>
      {/* BOTTOM EDGE IS LOAD-BEARING HERE, unlike the other screens that take
          edges={['top']}. This layout is CENTRED and its last element is a
          link; dropping the bottom inset puts that link on the home
          indicator. See 02649d3, which fixed the same symptom, and 0e87696,
          which undid it.

          AND IT IS A JSX COMMENT, not //. In JSX child position `//` is not
          a comment, it is text: f486caf shipped these four lines as visible
          copy above the logo on both auth screens, and the `['top']` inside
          them parsed as an expression container and rendered as `top`.
          React 19 throws on bare text in a <View>, and AnimatedBackground
          renders its children inside one. */}
      <SafeAreaView style={s.container} edges={['top', 'bottom']}>
        <ScrollView
          style={s.scroll}
          contentContainerStyle={s.scrollContent}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
        <View style={s.content}>
          {/* Logo */}
          <View style={s.logoContainer}>
            <Animated.View
              ref={logoBoxRef}
              collapsable={false}
              onLayout={beginEntrance}
              style={[s.logoImage, logoStyle]}
            >
              <Image
                source={logoSrc}
                style={{ width: '100%', height: '100%' }}
                resizeMode="contain"
              />
            </Animated.View>
          </View>

          <Animated.View style={[{ alignSelf: 'stretch' }, uiStyle]}>
          <GlassCard style={s.card}>
            <View style={s.welcomeSection}>
              <Text style={s.welcomeLabel}>WELCOME TO</Text>
              <Text style={s.welcomeTitle}>LeveLog</Text>
            </View>

            {choices ? (
              <View style={s.form}>
                <Text style={s.pickerTitle}>{t('title')}</Text>
                <Text style={s.pickerHint}>{t('hint')}</Text>
                {choices.map((account) => (
                  <Pressable
                    key={account.choiceToken}
                    onPress={() => handleChoose(account)}
                    disabled={loading}
                    style={({ pressed }) => [s.choiceRow, (pressed || loading) && s.choiceRowDim]}
                    accessibilityRole="button"
                    accessibilityLabel={companyLabel(account, t)}
                  >
                    <Building2 size={20} strokeWidth={1.5} color={colors.text.subtle} />
                    <View style={s.choiceText}>
                      <Text style={s.choiceName}>{companyLabel(account, t)}</Text>
                      {roleLabel(account.role, t) ? (
                        <Text style={s.choiceRole}>{roleLabel(account.role, t)}</Text>
                      ) : null}
                    </View>
                    <ArrowRight size={18} strokeWidth={1.5} color={colors.text.subtle} />
                  </Pressable>
                ))}
                {loading ? <ActivityIndicator color={colors.primary} /> : null}
                {error ? (
                  <Text style={s.errorText}>{error}</Text>
                ) : null}
                <Pressable
                  onPress={backToForm}
                  disabled={loading}
                  style={s.backRow}
                  accessibilityRole="button"
                  accessibilityLabel={t('back')}
                >
                  <Text style={s.backText}>{t('back')}</Text>
                </Pressable>
              </View>
            ) : (() => {
              const formContent = (
                <View style={s.form}>
                  <View style={s.inputGroup}>
                    <Text style={s.inputLabel}>EMAIL</Text>
                    <GlassInput
                      value={email}
                      onChangeText={setEmail}
                      placeholder="Enter your email"
                      keyboardType="email-address"
                      autoCapitalize="none"
                      returnKeyType="next"
                      onSubmitEditing={() => pwdRef.current?.focus()}
                      leftIcon={<Mail size={20} strokeWidth={1.5} color={colors.text.subtle} />}
                    />
                  </View>

                  <View style={s.inputGroup}>
                    <Text style={s.inputLabel}>PASSWORD</Text>
                    <GlassInput
                      ref={pwdRef}
                      value={password}
                      onChangeText={setPassword}
                      placeholder="Enter password"
                      secureTextEntry={!showPassword}
                      returnKeyType="go"
                      onSubmitEditing={handleSubmit}
                      leftIcon={<Lock size={20} strokeWidth={1.5} color={colors.text.subtle} />}
                      rightIcon={
                        <Pressable onPress={() => setShowPassword(!showPassword)}>
                          {showPassword ? (
                            <EyeOff size={20} strokeWidth={1.5} color={colors.text.subtle} />
                          ) : (
                            <Eye size={20} strokeWidth={1.5} color={colors.text.subtle} />
                          )}
                        </Pressable>
                      }
                    />
                  </View>

                  {error ? (
                    <Text style={s.errorText}>{error}</Text>
                  ) : null}

                  <GlassButton
                    title={loading ? 'Signing in...' : 'Sign In'}
                    icon={!loading ? <ArrowRight size={18} strokeWidth={1.5} color={colors.text.primary} /> : null}
                    onPress={handleSubmit}
                    loading={loading}
                    style={s.submitBtn}
                  />
                </View>
              );
              return Platform.OS === 'web' ? (
                <form
                  style={{ display: 'contents' }}
                  onSubmit={(e) => { e.preventDefault(); handleSubmit(); }}
                >
                  {formContent}
                </form>
              ) : formContent;
            })()}
          </GlassCard>

          {/* Signup affordance — a first-time, unauthenticated visitor must be
              able to reach registration on first paint (App Store reviewers
              self-register here). Reachable directly at /register too. */}
          <Pressable
            onPress={() => router.push('/register')}
            style={s.signupRow}
            accessibilityRole="link"
            accessibilityLabel="Create an account"
          >
            <Text style={s.signupText}>
              Don't have an account? <Text style={s.signupLink}>Sign up</Text>
            </Text>
          </Pressable>
          </Animated.View>
        </View>
        </ScrollView>
      </SafeAreaView>

      {/* THE ENTRANCE OVERLAY. Always mounted so it can be measured; it holds the
          particle animation while playing and a tap anywhere skips it. */}
      <View
        ref={overlayRef}
        collapsable={false}
        pointerEvents={phase === 'playing' ? 'auto' : 'none'}
        style={StyleSheet.absoluteFill}
      >
        {phase === 'playing' && entranceCfg ? (
          <>
            <LogoEntrance
              size={entranceCfg.size}
              rect={entranceCfg.rect}
              dark={isDark}
              onEvent={onEntranceEvent}
              onFail={finishEntrance}
            />
            <Pressable
              style={StyleSheet.absoluteFill}
              onPress={finishEntrance}
              accessibilityRole="button"
              accessibilityLabel="Skip intro"
            />
          </>
        ) : null}
      </View>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    container: { flex: 1 },
  scroll: { flex: 1 },
  // flexGrow lets the stack vertically center when the viewport is tall
  // enough, and SCROLL when it's taller than the viewport — so the signup
  // link is always reachable (~768px screens included), not just full-screen.
  scrollContent: {
    flexGrow: 1,
    justifyContent: 'center',
    // Trailing scroll extent so the signup link below the card can be
    // scrolled CLEAR of a raised keyboard, not merely up against it.
    paddingBottom: spacing.xxl,
  },
  content: {
    padding: spacing.lg,
    maxWidth: 440,
    width: '100%',
    alignSelf: 'center',
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  logoContainer: {
    alignItems: 'center',
    marginBottom: -spacing.md,
    marginTop: spacing.xl,
  },
  logoImage: {
    width: '100%',
    height: 200,
    alignSelf: 'center',
  },
  card: { padding: spacing.xl },
  welcomeSection: { marginBottom: spacing.xl },
  welcomeLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.xs,
  },
  welcomeTitle: {
    fontSize: 28,
    fontFamily: typography.display, fontWeight: '800',
    color: colors.text.primary,
  },
  form: { gap: spacing.md },
  inputGroup: { gap: spacing.xs },
  inputLabel: {
    ...typography.label,
    color: colors.text.muted,
  },
  errorText: {
    fontSize: 13,
    color: colors.error || semantic.criticalText,
    textAlign: 'center',
  },
  submitBtn: {
    marginTop: spacing.sm,
  },
  pickerTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.text.primary,
  },
  pickerHint: {
    fontSize: 14,
    color: colors.text.muted,
  },
  choiceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
    backgroundColor: colors.glass.background,
  },
  choiceRowDim: {
    opacity: 0.5, // tokens.opacity.o50, the disabled/busy dim
  },
  choiceText: { flex: 1 },
  choiceName: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text.primary,
  },
  choiceRole: {
    fontSize: 13,
    color: colors.text.muted,
    marginTop: 2,
  },
  backRow: {
    alignItems: 'center',
    paddingVertical: spacing.sm,
  },
  backText: {
    fontSize: 14,
    color: colors.primary,
    fontWeight: '600',
  },
  signupRow: {
    marginTop: spacing.lg,
    alignItems: 'center',
  },
  signupText: {
    fontSize: 14,
    color: colors.text.muted,
  },
  signupLink: {
    color: colors.primary,
    fontWeight: '600',
  },
});
}
