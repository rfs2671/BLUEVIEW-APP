/**
 * /settings/notifications — Phase B1b notification preferences UI.
 *
 * Consumes B1a backend endpoints:
 *   GET   /api/users/me/notification-preferences  → load + defaults
 *   PATCH /api/users/me/notification-preferences  → save
 *   GET   /api/users/me/recent-signals?days=7     → "you'd receive ~N" tooltip
 *
 * Layout:
 *   • Header: title + 1-2 sentence explainer + back button.
 *   • Section A: per-signal_kind controls, grouped by family,
 *     each family collapsible (default expanded on desktop,
 *     collapsed on mobile).
 *   • Section B: severity-keyed channel routes (the
 *     channel_routes_default config — fallback when no per-kind
 *     override exists).
 *   • Section C: digest timing (daily_at, weekly_day, timezone).
 *   • Section D: per-project overrides (collapsible — link list,
 *     real per-project page lands in B1c).
 *   • Section E: footer with Save / Reset / last-saved.
 *
 * State management:
 *   • prefs: the in-memory editable copy of the loaded record.
 *   • dirty: boolean — true iff prefs differs from initialPrefs.
 *   • saving: boolean — true while PATCH is in flight.
 *   • recent: {signal_kind: count, ...} — for the tooltip.
 *
 * Save flow: PATCH the WHOLE prefs object (signal_kind_overrides +
 * channel_routes_default + digest_window). The backend's
 * normalize_*_patch helpers validate; on success we replace the
 * cached initialPrefs so the dirty flag clears.
 *
 * Mobile:
 *   • Each section is an accordion (collapsed by default).
 *   • Save button sticks to the bottom.
 *   • Toggles + dropdowns are touch-sized.
 *
 * SMS channel: rendered as a disabled toggle with a "Coming in v1.1"
 * pill. In_app channel: rendered as a regular toggle but labeled
 * "Currently shows in Activity feed" (tooltip). Both are accepted
 * by the backend schema even though only email is deliverable today.
 */

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  Switch,
  Platform,
  useWindowDimensions,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  Bell,
  Mail,
  MessageSquare,
  Smartphone,
  ChevronDown,
  ChevronUp,
  Save,
  RotateCcw,
  Info,
  AlertCircle,
  Check,
  Clock,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import { useAuth } from '../../src/context/AuthContext';
import { useTheme } from '../../src/context/ThemeContext';
import { useToast } from '../../src/components/Toast';
import apiClient from '../../src/utils/api';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import {
  SIGNAL_FAMILIES,
  SIGNAL_KIND_INDEX,
  TOTAL_SIGNAL_KINDS,
  SEVERITY_PALETTE,
} from '../../src/constants/signalKinds';

// ── Static select options ────────────────────────────────────────

const DELIVERY_OPTIONS = [
  { value: 'immediate', label: 'Immediate' },
  { value: 'digest_daily', label: 'Daily digest' },
  { value: 'digest_weekly', label: 'Weekly digest' },
  { value: 'feed_only', label: 'Feed only' },
];

const THRESHOLD_OPTIONS = [
  { value: 'any', label: 'Any severity' },
  { value: 'warning_or_above', label: 'Warning or higher' },
  { value: 'critical_only', label: 'Critical only' },
  { value: 'none', label: 'Off' },
];

const WEEKLY_DAY_OPTIONS = [
  { value: 'monday', label: 'Monday' },
  { value: 'tuesday', label: 'Tuesday' },
  { value: 'wednesday', label: 'Wednesday' },
  { value: 'thursday', label: 'Thursday' },
  { value: 'friday', label: 'Friday' },
  { value: 'saturday', label: 'Saturday' },
  { value: 'sunday', label: 'Sunday' },
];

const TIMEZONE_OPTIONS = [
  { value: 'America/New_York', label: 'Eastern (NYC)' },
  { value: 'America/Chicago', label: 'Central' },
  { value: 'America/Denver', label: 'Mountain' },
  { value: 'America/Los_Angeles', label: 'Pacific' },
  { value: 'UTC', label: 'UTC' },
];

const HOUR_OPTIONS = (() => {
  const out = [];
  for (let h = 0; h < 24; h++) {
    const hh = String(h).padStart(2, '0');
    out.push({ value: `${hh}:00`, label: `${hh}:00` });
  }
  return out;
})();

const MOBILE_BREAKPOINT = 720;

// ── Helpers ──────────────────────────────────────────────────────

/**
 * Returns the effective override for a signal_kind, merging the
 * stored override with the implicit default (channels = severity →
 * channel_routes_default[severity], threshold = 'any', delivery =
 * default-for-severity). Used to populate row controls when no
 * explicit override exists yet.
 */
function effectiveOverrideFor(prefs, kind) {
  const stored =
    prefs?.signal_kind_overrides && prefs.signal_kind_overrides[kind.key];
  if (stored) {
    return {
      channels: Array.isArray(stored.channels) ? stored.channels : [],
      severity_threshold: stored.severity_threshold || 'any',
      delivery: stored.delivery || defaultDeliveryFor(kind.defaultSeverity),
      isExplicit: true,
    };
  }
  const routes =
    (prefs?.channel_routes_default && prefs.channel_routes_default[kind.defaultSeverity]) ||
    [];
  return {
    channels: routes,
    severity_threshold: 'any',
    delivery: defaultDeliveryFor(kind.defaultSeverity),
    isExplicit: false,
  };
}

function defaultDeliveryFor(severity) {
  if (severity === 'critical') return 'immediate';
  if (severity === 'warning') return 'digest_daily';
  return 'feed_only';
}

function deepEqual(a, b) {
  // Shallow-enough equality for the prefs object — JSON stringify is
  // fine because prefs are dicts of dicts of primitives + lists.
  try {
    return JSON.stringify(a) === JSON.stringify(b);
  } catch (_e) {
    return false;
  }
}

// ── Channel toggle (with disabled SMS) ──────────────────────────

const CHANNEL_TOGGLES = [
  {
    key: 'email',
    label: 'Email',
    Icon: Mail,
    enabled: true,
    badge: null,
  },
  {
    key: 'sms',
    label: 'SMS',
    Icon: MessageSquare,
    enabled: false,
    badge: 'v1.1',
  },
  {
    key: 'in_app',
    label: 'In-App',
    Icon: Smartphone,
    enabled: true,
    badge: 'feed',
  },
];

const ChannelToggleRow = ({ channels, onChange, colors, styles, compact = false }) => {
  return (
    <View style={[styles.channelRow, compact && styles.channelRowCompact]}>
      {CHANNEL_TOGGLES.map((ch) => {
        const isOn = (channels || []).includes(ch.key);
        const baseStyle = [
          styles.channelChip,
          isOn && styles.channelChipOn,
          !ch.enabled && styles.channelChipDisabled,
        ];
        return (
          <Pressable
            key={ch.key}
            onPress={ch.enabled ? () => onChange(ch.key, !isOn) : undefined}
            disabled={!ch.enabled}
            style={baseStyle}
          >
            <ch.Icon
              size={13}
              strokeWidth={1.5}
              color={isOn ? '#fff' : colors.text.muted}
            />
            <Text
              style={[
                styles.channelChipLabel,
                isOn && { color: '#fff' },
                !ch.enabled && { color: colors.text.muted },
              ]}
            >
              {ch.label}
            </Text>
            {ch.badge && (
              <Text style={styles.channelBadge}>{ch.badge}</Text>
            )}
          </Pressable>
        );
      })}
    </View>
  );
};

// ── Lightweight select: tap to cycle. No native Picker for web parity. ──

const SelectChip = ({ value, options, onChange, styles, colors }) => {
  const idx = options.findIndex((o) => o.value === value);
  const safeIdx = idx >= 0 ? idx : 0;
  const cycle = () => {
    const next = options[(safeIdx + 1) % options.length];
    if (next) onChange(next.value);
  };
  return (
    <Pressable
      onPress={cycle}
      style={({ pressed }) => [
        styles.selectChip,
        pressed && { opacity: 0.7 },
      ]}
    >
      <Text style={styles.selectChipText} numberOfLines={1}>
        {options[safeIdx]?.label || value}
      </Text>
      <ChevronDown size={12} strokeWidth={1.5} color={colors.text.muted} />
    </Pressable>
  );
};

// ── Severity badge ──────────────────────────────────────────────

const SeverityBadge = ({ severity, styles }) => {
  const palette = SEVERITY_PALETTE[severity] || SEVERITY_PALETTE.info;
  return (
    <View
      style={[
        styles.sevBadge,
        { backgroundColor: palette.bg, borderColor: `${palette.color}80` },
      ]}
    >
      <Text style={[styles.sevBadgeText, { color: palette.color }]}>
        {palette.label}
      </Text>
    </View>
  );
};

// ── Main page ────────────────────────────────────────────────────

export default function NotificationPreferencesScreen() {
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const { colors, isDark } = useTheme();
  const toast = useToast();
  const styles = useMemo(() => buildStyles(colors), [colors]);

  const { width: winWidth } = useWindowDimensions();
  const isMobile = winWidth < MOBILE_BREAKPOINT;

  // ── Auth guard ────────────────────────────────────────────────
  useEffect(() => {
    if (authLoading) return undefined;
    if (isAuthenticated === false) {
      const t = setTimeout(() => router.replace('/login'), 0);
      return () => clearTimeout(t);
    }
    return undefined;
  }, [isAuthenticated, authLoading]);

  // ── State ─────────────────────────────────────────────────────
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [initialPrefs, setInitialPrefs] = useState(null);
  const [prefs, setPrefs] = useState(null);
  const [recentCounts, setRecentCounts] = useState({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [lastSavedAt, setLastSavedAt] = useState(null);

  // Family expand state. Defaults: expanded on desktop, collapsed on mobile.
  const [expandedFamilies, setExpandedFamilies] = useState(() => {
    const out = {};
    for (const fam of SIGNAL_FAMILIES) out[fam.key] = true;
    return out;
  });
  useEffect(() => {
    // When switching between desktop ↔ mobile breakpoints, recompute
    // defaults. Operator-explicit toggles persist for the session.
    setExpandedFamilies((prev) => {
      const out = {};
      for (const fam of SIGNAL_FAMILIES) {
        out[fam.key] = isMobile ? false : prev[fam.key] !== false;
      }
      return out;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isMobile]);

  const [showProjectsSection, setShowProjectsSection] = useState(false);

  // ── Initial load ──────────────────────────────────────────────
  const loadPreferences = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [prefsResp, recentResp] = await Promise.all([
        apiClient.get('/api/users/me/notification-preferences'),
        apiClient.get('/api/users/me/recent-signals?days=7').catch(() => ({ data: { counts_by_signal_kind: {} } })),
      ]);
      const data = prefsResp.data || {};
      setInitialPrefs(data);
      setPrefs(JSON.parse(JSON.stringify(data)));  // deep clone for edits
      setLastSavedAt(data.updated_at || null);
      const counts = (recentResp.data && recentResp.data.counts_by_signal_kind) || {};
      setRecentCounts(counts);
    } catch (e) {
      console.error('[notification-preferences] load failed:', e?.message || e);
      setLoadError('Could not load your notification preferences. Please try again.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isAuthenticated) loadPreferences();
  }, [isAuthenticated, loadPreferences]);

  // ── Dirty tracking ────────────────────────────────────────────
  const dirty = useMemo(() => {
    if (!initialPrefs || !prefs) return false;
    return !deepEqual(initialPrefs, prefs);
  }, [initialPrefs, prefs]);

  // ── Mutators ──────────────────────────────────────────────────
  const updatePrefs = (mutator) => {
    setPrefs((prev) => {
      if (!prev) return prev;
      const next = JSON.parse(JSON.stringify(prev));
      mutator(next);
      return next;
    });
  };

  const updateOverride = (signalKind, partial) => {
    updatePrefs((next) => {
      const base = (next.signal_kind_overrides && next.signal_kind_overrides[signalKind]) || {};
      const kind = SIGNAL_KIND_INDEX[signalKind];
      const fallbackChannels =
        (next.channel_routes_default && next.channel_routes_default[kind?.defaultSeverity]) || [];
      next.signal_kind_overrides = next.signal_kind_overrides || {};
      next.signal_kind_overrides[signalKind] = {
        channels: base.channels || fallbackChannels,
        severity_threshold: base.severity_threshold || 'any',
        delivery: base.delivery || defaultDeliveryFor(kind?.defaultSeverity),
        ...partial,
      };
    });
  };

  const resetOverride = (signalKind) => {
    updatePrefs((next) => {
      if (next.signal_kind_overrides && signalKind in next.signal_kind_overrides) {
        delete next.signal_kind_overrides[signalKind];
      }
    });
  };

  const toggleChannelOnRow = (signalKind, channel, on) => {
    const eff = effectiveOverrideFor(prefs, SIGNAL_KIND_INDEX[signalKind] || { key: signalKind, defaultSeverity: 'info' });
    const next = on
      ? Array.from(new Set([...eff.channels, channel]))
      : eff.channels.filter((c) => c !== channel);
    updateOverride(signalKind, { channels: next });
  };

  const toggleSeverityChannel = (severity, channel, on) => {
    updatePrefs((next) => {
      next.channel_routes_default = next.channel_routes_default || {
        critical: [], warning: [], info: [],
      };
      const cur = next.channel_routes_default[severity] || [];
      next.channel_routes_default[severity] = on
        ? Array.from(new Set([...cur, channel]))
        : cur.filter((c) => c !== channel);
    });
  };

  const updateDigestWindow = (key, value) => {
    updatePrefs((next) => {
      next.digest_window = next.digest_window || {};
      next.digest_window[key] = value;
    });
  };

  // ── Save ──────────────────────────────────────────────────────
  const handleSave = async () => {
    if (!prefs || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      const payload = {
        signal_kind_overrides: prefs.signal_kind_overrides || {},
        channel_routes_default: prefs.channel_routes_default || {},
        digest_window: prefs.digest_window || {},
      };
      const resp = await apiClient.patch(
        '/api/users/me/notification-preferences',
        payload,
      );
      const saved = resp.data || prefs;
      setInitialPrefs(saved);
      setPrefs(JSON.parse(JSON.stringify(saved)));
      setLastSavedAt(saved.updated_at || new Date().toISOString());
      toast.success('Saved', 'Your notification preferences are updated.');
    } catch (e) {
      const detail = e?.response?.data?.detail;
      let msg;
      if (typeof detail === 'object' && detail !== null) {
        if (Array.isArray(detail.errors)) {
          msg = detail.errors.join('\n');
        } else {
          msg = detail.message || 'Save failed';
        }
      } else if (typeof detail === 'string') {
        msg = detail;
      } else {
        msg = e?.message || 'Save failed';
      }
      setSaveError(msg);
      toast.error('Could not save', msg);
    } finally {
      setSaving(false);
    }
  };

  const handleResetAll = () => {
    if (!initialPrefs) return;
    setPrefs(JSON.parse(JSON.stringify(initialPrefs)));
    setSaveError(null);
  };

  // ── Render ────────────────────────────────────────────────────

  if (loading || !prefs) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container} edges={['top']}>
          <Header router={router} colors={colors} styles={styles} />
          <View style={styles.loadingWrap}>
            <ActivityIndicator size="large" color={colors.text.primary} />
            <Text style={styles.loadingText}>
              {loadError || 'Loading preferences…'}
            </Text>
            {loadError && (
              <Pressable onPress={loadPreferences} style={styles.retryBtn}>
                <Text style={styles.retryBtnText}>Retry</Text>
              </Pressable>
            )}
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  const lastSavedLabel = lastSavedAt
    ? `Last saved ${new Date(lastSavedAt).toLocaleString('en-US', {
        month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
      })}`
    : 'Not yet saved';

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container} edges={['top']}>
        <Header router={router} colors={colors} styles={styles} />

        <ScrollView
          style={styles.scroll}
          contentContainerStyle={[
            styles.scrollContent,
            isMobile && { paddingBottom: 120 },  // room for sticky save bar
          ]}
          showsVerticalScrollIndicator={false}
        >
          {/* Intro */}
          <GlassCard style={styles.introCard}>
            <View style={styles.introHeader}>
              <Bell size={22} strokeWidth={1.5} color={colors.text.primary} />
              <View style={{ flex: 1 }}>
                <Text style={styles.introTitle}>Notification Preferences</Text>
                <Text style={styles.introBody}>
                  Choose which DOB compliance signals reach you and how. Defaults
                  are conservative — info-severity stays in the activity feed,
                  warnings are batched into a daily 7am digest, critical alerts
                  email you immediately.
                </Text>
              </View>
            </View>
          </GlassCard>

          {/* ── SECTION A — Per-signal_kind ────────────────────────────── */}
          <Text style={styles.sectionLabel}>WHAT YOU&apos;LL BE NOTIFIED ABOUT</Text>
          <Text style={styles.sectionBlurb}>
            One row per signal type ({TOTAL_SIGNAL_KINDS} total). Adjust channels,
            severity threshold, and delivery cadence per signal. Reset a row to
            inherit the severity-default routing in section B.
          </Text>
          {SIGNAL_FAMILIES.map((fam) => {
            const expanded = !!expandedFamilies[fam.key];
            return (
              <GlassCard key={fam.key} style={styles.familyCard}>
                <Pressable
                  onPress={() =>
                    setExpandedFamilies((prev) => ({ ...prev, [fam.key]: !prev[fam.key] }))
                  }
                  style={styles.familyHeader}
                >
                  <View style={{ flex: 1 }}>
                    <Text style={styles.familyTitle}>{fam.label}</Text>
                    {fam.blurb && (
                      <Text style={styles.familyBlurb}>{fam.blurb}</Text>
                    )}
                  </View>
                  {expanded ? (
                    <ChevronUp size={18} strokeWidth={1.5} color={colors.text.muted} />
                  ) : (
                    <ChevronDown size={18} strokeWidth={1.5} color={colors.text.muted} />
                  )}
                </Pressable>
                {expanded && (
                  <View style={styles.familyBody}>
                    {fam.kinds.map((kind) => {
                      const eff = effectiveOverrideFor(prefs, kind);
                      const recent = recentCounts[kind.key] || 0;
                      return (
                        <View key={kind.key} style={styles.kindRow}>
                          <View style={styles.kindRowHeader}>
                            <View style={{ flex: 1 }}>
                              <View style={styles.kindRowTitleRow}>
                                <Text style={styles.kindRowLabel}>{kind.label}</Text>
                                <SeverityBadge
                                  severity={kind.defaultSeverity}
                                  styles={styles}
                                />
                              </View>
                              <Text style={styles.kindRowTooltip}>{kind.tooltip}</Text>
                              <Text style={styles.kindRowRecent}>
                                {recent === 0
                                  ? 'No matches in last 7 days'
                                  : `${recent} matched in last 7 days`}
                              </Text>
                            </View>
                            {eff.isExplicit && (
                              <Pressable
                                onPress={() => resetOverride(kind.key)}
                                style={styles.resetRowBtn}
                              >
                                <RotateCcw size={12} strokeWidth={1.5} color={colors.text.muted} />
                                <Text style={styles.resetRowBtnText}>Reset</Text>
                              </Pressable>
                            )}
                          </View>
                          <ChannelToggleRow
                            channels={eff.channels}
                            onChange={(ch, on) => toggleChannelOnRow(kind.key, ch, on)}
                            colors={colors}
                            styles={styles}
                          />
                          <View style={styles.kindRowControls}>
                            <View style={styles.kindRowControlGroup}>
                              <Text style={styles.kindRowControlLabel}>
                                Severity threshold
                              </Text>
                              <SelectChip
                                value={eff.severity_threshold}
                                options={THRESHOLD_OPTIONS}
                                onChange={(v) =>
                                  updateOverride(kind.key, { severity_threshold: v })
                                }
                                styles={styles}
                                colors={colors}
                              />
                            </View>
                            <View style={styles.kindRowControlGroup}>
                              <Text style={styles.kindRowControlLabel}>
                                Delivery
                              </Text>
                              <SelectChip
                                value={eff.delivery}
                                options={DELIVERY_OPTIONS}
                                onChange={(v) =>
                                  updateOverride(kind.key, { delivery: v })
                                }
                                styles={styles}
                                colors={colors}
                              />
                            </View>
                          </View>
                        </View>
                      );
                    })}
                  </View>
                )}
              </GlassCard>
            );
          })}

          {/* ── SECTION B — Severity-keyed defaults ─────────────────────── */}
          <Text style={styles.sectionLabel}>CHANNEL ROUTING BY SEVERITY</Text>
          <Text style={styles.sectionBlurb}>
            When no per-signal override exists, signals route by severity using
            these channels.
          </Text>
          <GlassCard style={styles.card}>
            {['critical', 'warning', 'info'].map((sev) => {
              const channels = (prefs.channel_routes_default || {})[sev] || [];
              return (
                <View key={sev} style={styles.severityRow}>
                  <View style={styles.severityRowLeft}>
                    <SeverityBadge severity={sev} styles={styles} />
                    <Text style={styles.severityHelp}>
                      {sev === 'critical'
                        ? 'Stop work orders, failed inspections, DOB violations'
                        : sev === 'warning'
                        ? 'DOB complaints, scheduled inspections, license renewals due'
                        : 'New permits, filing approvals, 311 calls'}
                    </Text>
                  </View>
                  <ChannelToggleRow
                    channels={channels}
                    onChange={(ch, on) => toggleSeverityChannel(sev, ch, on)}
                    colors={colors}
                    styles={styles}
                    compact
                  />
                </View>
              );
            })}
          </GlassCard>

          {/* ── SECTION C — Delivery timing ──────────────────────────────── */}
          <Text style={styles.sectionLabel}>DELIVERY TIMING</Text>
          <Text style={styles.sectionBlurb}>
            When digests fire and which timezone the schedule respects.
          </Text>
          <GlassCard style={styles.card}>
            <View style={styles.timingRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.timingLabel}>Daily digest time</Text>
                <Text style={styles.timingHelp}>
                  When the daily-digest signals fire each morning.
                </Text>
              </View>
              <SelectChip
                value={(prefs.digest_window && prefs.digest_window.daily_at) || '07:00'}
                options={HOUR_OPTIONS}
                onChange={(v) => updateDigestWindow('daily_at', v)}
                styles={styles}
                colors={colors}
              />
            </View>
            <View style={styles.timingRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.timingLabel}>Weekly digest day</Text>
                <Text style={styles.timingHelp}>
                  Day of the week the weekly digest sends.
                </Text>
              </View>
              <SelectChip
                value={(prefs.digest_window && prefs.digest_window.weekly_day) || 'monday'}
                options={WEEKLY_DAY_OPTIONS}
                onChange={(v) => updateDigestWindow('weekly_day', v)}
                styles={styles}
                colors={colors}
              />
            </View>
            <View style={styles.timingRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.timingLabel}>Timezone</Text>
                <Text style={styles.timingHelp}>
                  Used for both daily and weekly digest schedules.
                </Text>
              </View>
              <SelectChip
                value={(prefs.digest_window && prefs.digest_window.timezone) || 'America/New_York'}
                options={TIMEZONE_OPTIONS}
                onChange={(v) => updateDigestWindow('timezone', v)}
                styles={styles}
                colors={colors}
              />
            </View>
          </GlassCard>

          {/* ── SECTION D — Per-project overrides (collapsible) ────────── */}
          <Pressable
            onPress={() => setShowProjectsSection((v) => !v)}
            style={styles.collapsedSectionHeader}
          >
            <Text style={styles.sectionLabel}>PER-PROJECT OVERRIDES</Text>
            {showProjectsSection ? (
              <ChevronUp size={16} strokeWidth={1.5} color={colors.text.muted} />
            ) : (
              <ChevronDown size={16} strokeWidth={1.5} color={colors.text.muted} />
            )}
          </Pressable>
          {showProjectsSection && (
            <GlassCard style={styles.card}>
              <View style={styles.b1cPlaceholder}>
                <Info size={16} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={styles.b1cPlaceholderText}>
                  Per-project preference overrides ship in B1c. The backend
                  endpoints already exist; the per-project UI page lands next.
                </Text>
              </View>
            </GlassCard>
          )}

          {/* ── Footer info ─────────────────────────────────────────── */}
          <View style={styles.footerInfoRow}>
            <Clock size={12} strokeWidth={1.5} color={colors.text.muted} />
            <Text style={styles.footerInfoText}>{lastSavedLabel}</Text>
          </View>
          {!isMobile && (
            <View style={styles.desktopActionRow}>
              <GlassButton
                title="Reset to last saved"
                onPress={handleResetAll}
                disabled={!dirty || saving}
                icon={<RotateCcw size={14} strokeWidth={1.5} color={colors.text.primary} />}
              />
              <GlassButton
                title={saving ? 'Saving…' : 'Save changes'}
                onPress={handleSave}
                loading={saving}
                disabled={!dirty || saving}
                icon={!saving && <Save size={14} strokeWidth={1.5} color={colors.text.primary} />}
              />
            </View>
          )}
          {saveError && (
            <View style={styles.errorBlock}>
              <AlertCircle size={14} strokeWidth={1.5} color="#ef4444" />
              <Text style={styles.errorBlockText}>{saveError}</Text>
            </View>
          )}
        </ScrollView>

        {/* Mobile sticky save bar */}
        {isMobile && (
          <View style={styles.mobileStickyBar}>
            <Pressable
              onPress={handleResetAll}
              disabled={!dirty || saving}
              style={[
                styles.mobileSecondaryBtn,
                (!dirty || saving) && styles.mobileBtnDisabled,
              ]}
            >
              <RotateCcw size={14} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={styles.mobileSecondaryBtnText}>Reset</Text>
            </Pressable>
            <Pressable
              onPress={handleSave}
              disabled={!dirty || saving}
              style={[
                styles.mobilePrimaryBtn,
                (!dirty || saving) && styles.mobileBtnDisabled,
              ]}
            >
              {saving ? (
                <ActivityIndicator size="small" color="#fff" />
              ) : (
                <Save size={14} strokeWidth={1.5} color="#fff" />
              )}
              <Text style={styles.mobilePrimaryBtnText}>
                {saving ? 'Saving…' : dirty ? 'Save changes' : 'Saved'}
              </Text>
            </Pressable>
          </View>
        )}
      </SafeAreaView>
    </AnimatedBackground>
  );
}

// ── Header subcomponent ─────────────────────────────────────────

const Header = ({ router, colors, styles }) => (
  <View style={styles.header}>
    <Pressable onPress={() => router.back()} style={styles.backBtn}>
      <ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />
    </Pressable>
    <Text style={styles.headerTitle}>Notification Preferences</Text>
    <View style={{ width: 28 }} />
  </View>
);

// ── Styles ──────────────────────────────────────────────────────

function buildStyles(colors) {
  return StyleSheet.create({
    container: { flex: 1 },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.md,
    },
    backBtn: {
      width: 28,
      height: 28,
      alignItems: 'center',
      justifyContent: 'center',
    },
    headerTitle: {
      fontFamily: typography.semibold,
      fontSize: 16,
      color: colors.text.primary,
    },
    scroll: { flex: 1 },
    scrollContent: {
      paddingHorizontal: spacing.lg,
      paddingBottom: spacing.xl,
      gap: spacing.md,
    },

    loadingWrap: {
      flex: 1, alignItems: 'center', justifyContent: 'center', gap: spacing.sm,
    },
    loadingText: {
      fontFamily: typography.regular,
      fontSize: 13,
      color: colors.text.muted,
    },
    retryBtn: {
      paddingVertical: spacing.sm,
      paddingHorizontal: spacing.md,
      borderRadius: borderRadius.md,
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    retryBtnText: {
      fontFamily: typography.medium,
      fontSize: 13,
      color: colors.text.primary,
    },

    // ── Intro ──
    introCard: {
      padding: spacing.lg,
    },
    introHeader: {
      flexDirection: 'row',
      gap: spacing.md,
      alignItems: 'flex-start',
    },
    introTitle: {
      fontFamily: typography.semibold,
      fontSize: 16,
      color: colors.text.primary,
      marginBottom: 4,
    },
    introBody: {
      fontFamily: typography.regular,
      fontSize: 13,
      color: colors.text.secondary,
      lineHeight: 19,
    },

    // ── Section labels ──
    sectionLabel: {
      fontFamily: typography.semibold,
      fontSize: 11,
      letterSpacing: 1,
      color: colors.text.muted,
      marginTop: spacing.md,
      marginBottom: 4,
    },
    sectionBlurb: {
      fontFamily: typography.regular,
      fontSize: 12,
      color: colors.text.secondary,
      marginBottom: spacing.sm,
      lineHeight: 17,
    },
    card: {
      padding: spacing.md,
      gap: spacing.sm,
    },
    collapsedSectionHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingVertical: spacing.xs,
      marginTop: spacing.md,
    },

    // ── Family card ──
    familyCard: {
      padding: 0,
      overflow: 'hidden',
    },
    familyHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
      padding: spacing.md,
    },
    familyTitle: {
      fontFamily: typography.semibold,
      fontSize: 14,
      color: colors.text.primary,
    },
    familyBlurb: {
      fontFamily: typography.regular,
      fontSize: 12,
      color: colors.text.muted,
      marginTop: 2,
    },
    familyBody: {
      paddingHorizontal: spacing.md,
      paddingBottom: spacing.md,
      gap: spacing.md,
    },

    // ── Kind row ──
    kindRow: {
      paddingVertical: spacing.sm,
      borderTopWidth: 1,
      borderTopColor: colors.glass.border,
      gap: spacing.sm,
    },
    kindRowHeader: {
      flexDirection: 'row',
      gap: spacing.sm,
      alignItems: 'flex-start',
    },
    kindRowTitleRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
      marginBottom: 2,
    },
    kindRowLabel: {
      fontFamily: typography.medium,
      fontSize: 13,
      color: colors.text.primary,
    },
    kindRowTooltip: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: colors.text.muted,
      lineHeight: 15,
    },
    kindRowRecent: {
      fontFamily: typography.regular,
      fontSize: 10,
      color: colors.text.subtle || colors.text.muted,
      letterSpacing: 0.3,
      marginTop: 4,
    },
    resetRowBtn: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      paddingVertical: 4,
      paddingHorizontal: 8,
      borderRadius: borderRadius.sm,
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    resetRowBtnText: {
      fontFamily: typography.medium,
      fontSize: 11,
      color: colors.text.muted,
    },
    kindRowControls: {
      flexDirection: 'row',
      gap: spacing.sm,
      flexWrap: 'wrap',
    },
    kindRowControlGroup: {
      gap: 2,
      flex: 1,
      minWidth: 140,
    },
    kindRowControlLabel: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: colors.text.muted,
    },

    // ── Severity row ──
    severityRow: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: spacing.md,
      paddingVertical: spacing.sm,
      borderTopWidth: 1,
      borderTopColor: colors.glass.border,
      flexWrap: 'wrap',
    },
    severityRowLeft: {
      flex: 1, gap: 4,
      minWidth: 200,
    },
    severityHelp: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: colors.text.muted,
      lineHeight: 16,
    },

    // ── Severity badge ──
    sevBadge: {
      paddingVertical: 2, paddingHorizontal: 8,
      borderRadius: borderRadius.sm,
      borderWidth: 1,
      alignSelf: 'flex-start',
    },
    sevBadgeText: {
      fontFamily: typography.semibold,
      fontSize: 10,
      letterSpacing: 0.5,
    },

    // ── Channel chips ──
    channelRow: {
      flexDirection: 'row',
      gap: 6,
      flexWrap: 'wrap',
    },
    channelRowCompact: {
      justifyContent: 'flex-end',
    },
    channelChip: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      paddingVertical: 6,
      paddingHorizontal: 10,
      borderRadius: borderRadius.sm,
      borderWidth: 1,
      borderColor: colors.glass.border,
      backgroundColor: 'transparent',
    },
    channelChipOn: {
      backgroundColor: '#3b82f6',
      borderColor: '#3b82f6',
    },
    channelChipDisabled: {
      opacity: 0.55,
    },
    channelChipLabel: {
      fontFamily: typography.medium,
      fontSize: 12,
      color: colors.text.primary,
    },
    channelBadge: {
      fontFamily: typography.medium,
      fontSize: 9,
      color: colors.text.muted,
      backgroundColor: colors.glass.background,
      paddingHorizontal: 4,
      paddingVertical: 1,
      borderRadius: 3,
      marginLeft: 2,
    },

    // ── SelectChip ──
    selectChip: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      paddingVertical: 6,
      paddingHorizontal: 10,
      borderRadius: borderRadius.sm,
      borderWidth: 1,
      borderColor: colors.glass.border,
      backgroundColor: colors.glass.background,
      maxWidth: 220,
    },
    selectChipText: {
      fontFamily: typography.medium,
      fontSize: 12,
      color: colors.text.primary,
      flexShrink: 1,
    },

    // ── Timing ──
    timingRow: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: spacing.sm,
      paddingVertical: spacing.sm,
      borderTopWidth: 1,
      borderTopColor: colors.glass.border,
    },
    timingLabel: {
      fontFamily: typography.medium,
      fontSize: 13,
      color: colors.text.primary,
    },
    timingHelp: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: colors.text.muted,
      marginTop: 2,
      lineHeight: 16,
    },

    // ── Project placeholder ──
    b1cPlaceholder: {
      flexDirection: 'row',
      gap: spacing.sm,
      alignItems: 'flex-start',
      padding: spacing.sm,
    },
    b1cPlaceholderText: {
      flex: 1,
      fontFamily: typography.regular,
      fontSize: 12,
      color: colors.text.secondary,
      lineHeight: 17,
    },

    // ── Footer ──
    footerInfoRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      marginTop: spacing.md,
    },
    footerInfoText: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: colors.text.muted,
    },
    desktopActionRow: {
      flexDirection: 'row',
      gap: spacing.sm,
      justifyContent: 'flex-end',
      marginTop: spacing.sm,
    },
    errorBlock: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: spacing.sm,
      padding: spacing.sm,
      borderRadius: borderRadius.md,
      borderWidth: 1,
      borderColor: '#ef444440',
      backgroundColor: '#ef444415',
      marginTop: spacing.sm,
    },
    errorBlockText: {
      flex: 1,
      fontFamily: typography.regular,
      fontSize: 12,
      color: '#ef4444',
      lineHeight: 17,
    },

    // ── Mobile sticky bar ──
    mobileStickyBar: {
      position: 'absolute',
      bottom: 0,
      left: 0,
      right: 0,
      flexDirection: 'row',
      gap: spacing.sm,
      padding: spacing.md,
      borderTopWidth: 1,
      borderTopColor: colors.glass.border,
      backgroundColor: colors.background?.start || 'rgba(5,10,18,0.95)',
    },
    mobilePrimaryBtn: {
      flex: 1,
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 6,
      paddingVertical: spacing.sm + 2,
      borderRadius: borderRadius.md,
      backgroundColor: '#3b82f6',
    },
    mobilePrimaryBtnText: {
      fontFamily: typography.semibold,
      fontSize: 14,
      color: '#fff',
    },
    mobileSecondaryBtn: {
      flex: 1,
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 6,
      paddingVertical: spacing.sm + 2,
      borderRadius: borderRadius.md,
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    mobileSecondaryBtnText: {
      fontFamily: typography.medium,
      fontSize: 13,
      color: colors.text.muted,
    },
    mobileBtnDisabled: {
      opacity: 0.5,
    },
  });
}
