/**
 * /settings/notifications — Phase B1b.1 progressive disclosure.
 *
 * Layout:
 *   Header — back + simplified copy.
 *   Section A — three preset radio cards (Critical only / Standard /
 *     Everything) + "Customize per signal type" link toggling the
 *     advanced section.
 *   Section B — delivery timing (compact, always visible).
 *   Section C — advanced (collapsible). Channel routing by severity
 *     + per-signal table grouped by family. Header carries a
 *     "Reset to <anchorPreset>" link when the anchor preset is not
 *     'custom'.
 *   Footer — last-saved + Save / Reset (sticky on mobile).
 *
 * State:
 *   prefs              — current editable copy.
 *   initialPrefs       — last-saved server snapshot. dirty = JSON
 *                        diff against prefs.
 *   anchorPreset       — the preset the user explicitly intended.
 *                        Initialized to detectActivePreset(initialPrefs);
 *                        updated on every preset radio click. Drives
 *                        the "Reset to <preset>" affordance even
 *                        when the user customizes inside Advanced
 *                        and the live detection drifts to 'custom'.
 *   advancedOpen       — collapsible state for Section C. Defaults
 *                        to true when the active preset is 'custom'
 *                        (so a user landing on a custom shape sees
 *                        the per-signal table immediately).
 *
 * Interaction:
 *   • Clicking a preset radio → applies that preset's shape via
 *     buildPresetPrefs, sets anchorPreset.
 *   • Clicking "Reset to <preset>" → re-applies anchorPreset.
 *   • Editing inside Advanced → prefs mutates; the live-detected
 *     preset drifts to 'custom'; radio renders unfilled. anchorPreset
 *     stays so the Reset link remains accessible.
 *   • Save → PATCH the whole prefs object; on success, replace
 *     initialPrefs with the response. anchorPreset stays consistent
 *     because Save doesn't change the preset intent.
 */

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
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
  Sliders,
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
  SEVERITY_PALETTE,
} from '../../src/constants/signalKinds';
import {
  PRESETS,
  PRESET_ORDER,
  buildPresetPrefs,
  detectActivePreset,
} from '../../src/utils/notificationPresets';

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

function defaultDeliveryFor(severity) {
  if (severity === 'critical') return 'immediate';
  if (severity === 'warning') return 'digest_daily';
  return 'feed_only';
}

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

function deepEqual(a, b) {
  try {
    return JSON.stringify(a) === JSON.stringify(b);
  } catch (_e) {
    return false;
  }
}

// ── Channel toggle row ──────────────────────────────────────────

const CHANNEL_TOGGLES = [
  { key: 'email', label: 'Email', Icon: Mail, enabled: true, badge: null },
  { key: 'sms', label: 'SMS', Icon: MessageSquare, enabled: false, badge: 'v1.1' },
  { key: 'in_app', label: 'In-App', Icon: Smartphone, enabled: true, badge: 'feed' },
];

const ChannelToggleRow = ({ channels, onChange, colors, styles, compact = false }) => (
  <View style={[styles.channelRow, compact && styles.channelRowCompact]}>
    {CHANNEL_TOGGLES.map((ch) => {
      const isOn = (channels || []).includes(ch.key);
      return (
        <Pressable
          key={ch.key}
          onPress={ch.enabled ? () => onChange(ch.key, !isOn) : undefined}
          disabled={!ch.enabled}
          style={[
            styles.channelChip,
            isOn && styles.channelChipOn,
            !ch.enabled && styles.channelChipDisabled,
          ]}
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
          {ch.badge && <Text style={styles.channelBadge}>{ch.badge}</Text>}
        </Pressable>
      );
    })}
  </View>
);

// ── Lightweight cycling select ──────────────────────────────────

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

// ── Preset radio card ────────────────────────────────────────────

const PresetRadioCard = ({
  preset,
  selected,
  onSelect,
  styles,
  colors,
}) => (
  <Pressable
    onPress={() => onSelect(preset.key)}
    style={({ pressed }) => [
      styles.presetCard,
      selected && styles.presetCardSelected,
      pressed && { opacity: 0.85 },
    ]}
  >
    <View
      style={[
        styles.presetRadio,
        selected && styles.presetRadioSelected,
      ]}
    >
      {selected && <View style={styles.presetRadioInner} />}
    </View>
    <View style={styles.presetTextBlock}>
      <View style={styles.presetTitleRow}>
        <Text style={styles.presetTitle}>{preset.label}</Text>
        {preset.badge && (
          <Text style={styles.presetBadge}>{preset.badge}</Text>
        )}
      </View>
      <Text style={styles.presetSubtitle}>{preset.subtitle}</Text>
      <Text style={styles.presetBodyHelp}>{preset.bodyHelp}</Text>
    </View>
  </Pressable>
);

// ── Main page ────────────────────────────────────────────────────

export default function NotificationPreferencesScreen() {
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const { colors } = useTheme();
  const toast = useToast();
  const styles = useMemo(() => buildStyles(colors), [colors]);

  const { width: winWidth } = useWindowDimensions();
  const isMobile = winWidth < MOBILE_BREAKPOINT;

  // Auth guard
  useEffect(() => {
    if (authLoading) return undefined;
    if (isAuthenticated === false) {
      const t = setTimeout(() => router.replace('/login'), 0);
      return () => clearTimeout(t);
    }
    return undefined;
  }, [isAuthenticated, authLoading]);

  // ── State ──
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [initialPrefs, setInitialPrefs] = useState(null);
  const [prefs, setPrefs] = useState(null);
  const [recentCounts, setRecentCounts] = useState({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [lastSavedAt, setLastSavedAt] = useState(null);

  // The preset the user "intended" — drives Reset to <preset>.
  // Initialized on load to whatever the saved prefs match. Updated
  // whenever the user clicks a preset radio.
  const [anchorPreset, setAnchorPreset] = useState('critical_only');

  // Advanced section toggle. Default: collapsed unless prefs are
  // already custom (in which case the per-signal table is what the
  // user needs to see).
  const [advancedOpen, setAdvancedOpen] = useState(false);

  // Family expand state inside Advanced.
  const [expandedFamilies, setExpandedFamilies] = useState(() => {
    const out = {};
    for (const fam of SIGNAL_FAMILIES) out[fam.key] = !isMobile;
    return out;
  });
  useEffect(() => {
    setExpandedFamilies((prev) => {
      const out = {};
      for (const fam of SIGNAL_FAMILIES) {
        out[fam.key] = isMobile ? false : prev[fam.key] !== false;
      }
      return out;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isMobile]);

  // ── Initial load ──
  const loadPreferences = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [prefsResp, recentResp] = await Promise.all([
        apiClient.get('/api/users/me/notification-preferences'),
        apiClient
          .get('/api/users/me/recent-signals?days=7')
          .catch(() => ({ data: { counts_by_signal_kind: {} } })),
      ]);
      const data = prefsResp.data || {};
      setInitialPrefs(data);
      setPrefs(JSON.parse(JSON.stringify(data)));
      setLastSavedAt(data.updated_at || null);
      const detected = detectActivePreset(data);
      setAnchorPreset(detected);
      // Auto-expand Advanced when the loaded prefs are custom — the
      // user almost certainly wants to see what they've got configured.
      setAdvancedOpen(detected === 'custom');
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

  // Live-detected preset (from current edits, not the anchor).
  const livePreset = useMemo(
    () => (prefs ? detectActivePreset(prefs) : 'custom'),
    [prefs],
  );

  // Dirty: prefs differ from saved state.
  const dirty = useMemo(() => {
    if (!initialPrefs || !prefs) return false;
    return !deepEqual(initialPrefs, prefs);
  }, [initialPrefs, prefs]);

  // ── Mutators ──
  const updatePrefs = (mutator) => {
    setPrefs((prev) => {
      if (!prev) return prev;
      const next = JSON.parse(JSON.stringify(prev));
      mutator(next);
      return next;
    });
  };

  const handlePresetSelect = (presetKey) => {
    if (!prefs) return;
    setPrefs((prev) => buildPresetPrefs(presetKey, prev));
    setAnchorPreset(presetKey);
    setSaveError(null);
  };

  const handleResetToAnchor = () => {
    if (!prefs || anchorPreset === 'custom') return;
    setPrefs((prev) => buildPresetPrefs(anchorPreset, prev));
    setSaveError(null);
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

  const toggleChannelOnRow = (signalKind, channel, on) => {
    const eff = effectiveOverrideFor(
      prefs,
      SIGNAL_KIND_INDEX[signalKind] || { key: signalKind, defaultSeverity: 'info' },
    );
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

  // ── Save ──
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
      // Recompute anchor — saving a custom shape locks in 'custom'
      // as the new anchor; saving a preset shape keeps it as that
      // preset.
      const detected = detectActivePreset(saved);
      setAnchorPreset(detected);
      toast.success('Saved', 'Your notification preferences are updated.');
    } catch (e) {
      const detail = e?.response?.data?.detail;
      let msg;
      if (typeof detail === 'object' && detail !== null) {
        msg = Array.isArray(detail.errors)
          ? detail.errors.join('\n')
          : (detail.message || 'Save failed');
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

  const handleResetUnsaved = () => {
    if (!initialPrefs) return;
    setPrefs(JSON.parse(JSON.stringify(initialPrefs)));
    setAnchorPreset(detectActivePreset(initialPrefs));
    setSaveError(null);
  };

  // ── Render ──

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

  const anchorPresetMeta = PRESETS[anchorPreset];

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container} edges={['top']}>
        <Header router={router} colors={colors} styles={styles} />

        <ScrollView
          style={styles.scroll}
          contentContainerStyle={[
            styles.scrollContent,
            isMobile && { paddingBottom: 120 },
          ]}
          showsVerticalScrollIndicator={false}
        >
          {/* Intro */}
          <GlassCard style={styles.introCard}>
            <View style={styles.introHeader}>
              <Bell size={22} strokeWidth={1.5} color={colors.text.primary} />
              <View style={{ flex: 1 }}>
                <Text style={styles.introTitle}>Choose how we notify you</Text>
                <Text style={styles.introBody}>
                  Pick a preset that matches your style, or customize per signal type.
                </Text>
              </View>
            </View>
          </GlassCard>

          {/* ── Section A — Presets ─────────────────────────────── */}
          <View style={styles.presetGroup}>
            {PRESET_ORDER.map((key) => (
              <PresetRadioCard
                key={key}
                preset={PRESETS[key]}
                selected={livePreset === key}
                onSelect={handlePresetSelect}
                styles={styles}
                colors={colors}
              />
            ))}
            <Pressable
              onPress={() => setAdvancedOpen((v) => !v)}
              style={styles.customizeLink}
            >
              <Sliders size={14} strokeWidth={1.5} color={colors.text.primary} />
              <Text style={styles.customizeLinkText}>
                {advancedOpen
                  ? 'Hide per-signal customization'
                  : 'Customize per signal type'}
              </Text>
              {advancedOpen ? (
                <ChevronUp size={14} strokeWidth={1.5} color={colors.text.muted} />
              ) : (
                <ChevronDown size={14} strokeWidth={1.5} color={colors.text.muted} />
              )}
            </Pressable>
            {livePreset === 'custom' && (
              <View style={styles.customStateBanner}>
                <Info size={13} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={styles.customStateBannerText}>
                  You&apos;ve customized per-signal settings — none of the
                  presets above match exactly.
                  {anchorPreset !== 'custom'
                    ? ` Click "Reset to ${PRESETS[anchorPreset].label}" inside Advanced to revert.`
                    : ''}
                </Text>
              </View>
            )}
          </View>

          {/* ── Section B — Delivery timing ─────────────────────── */}
          <Text style={styles.sectionLabel}>DELIVERY TIMING</Text>
          <GlassCard style={styles.timingCard}>
            <View style={styles.timingRow}>
              <Text style={styles.timingLabel}>Daily digest time</Text>
              <SelectChip
                value={(prefs.digest_window && prefs.digest_window.daily_at) || '07:00'}
                options={HOUR_OPTIONS}
                onChange={(v) => updateDigestWindow('daily_at', v)}
                styles={styles}
                colors={colors}
              />
            </View>
            <View style={styles.timingRow}>
              <Text style={styles.timingLabel}>Weekly digest day</Text>
              <SelectChip
                value={(prefs.digest_window && prefs.digest_window.weekly_day) || 'monday'}
                options={WEEKLY_DAY_OPTIONS}
                onChange={(v) => updateDigestWindow('weekly_day', v)}
                styles={styles}
                colors={colors}
              />
            </View>
            <View style={[styles.timingRow, styles.timingRowLast]}>
              <Text style={styles.timingLabel}>Timezone</Text>
              <SelectChip
                value={(prefs.digest_window && prefs.digest_window.timezone) || 'America/New_York'}
                options={TIMEZONE_OPTIONS}
                onChange={(v) => updateDigestWindow('timezone', v)}
                styles={styles}
                colors={colors}
              />
            </View>
          </GlassCard>

          {/* ── Section C — Advanced (collapsible) ──────────────── */}
          {advancedOpen && (
            <View>
              <View style={styles.advancedHeaderRow}>
                <Text style={styles.sectionLabel}>ADVANCED — PER-SIGNAL TYPE</Text>
                {anchorPreset !== 'custom' && anchorPresetMeta && (
                  <Pressable onPress={handleResetToAnchor} style={styles.resetAnchorLink}>
                    <RotateCcw size={12} strokeWidth={1.5} color={colors.text.muted} />
                    <Text style={styles.resetAnchorLinkText}>
                      Reset to {anchorPresetMeta.label}
                    </Text>
                  </Pressable>
                )}
              </View>
              <Text style={styles.sectionBlurb}>
                Per-signal overrides take precedence over the preset shape. Each
                row carries channel toggles, a severity threshold, and a
                delivery cadence.
              </Text>

              {/* Channel routes by severity (fallback for unknown future kinds) */}
              <GlassCard style={styles.routesCard}>
                <Text style={styles.routesHeader}>Severity fallback routes</Text>
                <Text style={styles.routesHelp}>
                  Applies only to signal types not explicitly set below
                  (e.g. new signal types added in future updates).
                </Text>
                {['critical', 'warning', 'info'].map((sev) => {
                  const channels = (prefs.channel_routes_default || {})[sev] || [];
                  return (
                    <View key={sev} style={styles.severityRow}>
                      <SeverityBadge severity={sev} styles={styles} />
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

              {/* Per-signal table — 9 family cards */}
              {SIGNAL_FAMILIES.map((fam) => {
                const expanded = !!expandedFamilies[fam.key];
                return (
                  <GlassCard key={fam.key} style={styles.familyCard}>
                    <Pressable
                      onPress={() =>
                        setExpandedFamilies((prev) => ({
                          ...prev,
                          [fam.key]: !prev[fam.key],
                        }))
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
            </View>
          )}

          {/* Footer */}
          <View style={styles.footerInfoRow}>
            <Clock size={12} strokeWidth={1.5} color={colors.text.muted} />
            <Text style={styles.footerInfoText}>{lastSavedLabel}</Text>
          </View>
          {!isMobile && (
            <View style={styles.desktopActionRow}>
              <GlassButton
                title="Reset to last saved"
                onPress={handleResetUnsaved}
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
              onPress={handleResetUnsaved}
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
    <Text style={styles.headerTitle}>Notifications</Text>
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
      width: 28, height: 28,
      alignItems: 'center', justifyContent: 'center',
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

    // Intro
    introCard: { padding: spacing.lg },
    introHeader: {
      flexDirection: 'row', gap: spacing.md, alignItems: 'flex-start',
    },
    introTitle: {
      fontFamily: typography.semibold,
      fontSize: 17,
      color: colors.text.primary,
      marginBottom: 4,
    },
    introBody: {
      fontFamily: typography.regular,
      fontSize: 13,
      color: colors.text.secondary,
      lineHeight: 19,
    },

    // Section labels
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

    // ── Preset radio cards ──
    presetGroup: { gap: spacing.sm },
    presetCard: {
      flexDirection: 'row',
      gap: spacing.md,
      padding: spacing.md,
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: colors.glass.border,
      backgroundColor: colors.glass.background,
      alignItems: 'flex-start',
    },
    presetCardSelected: {
      borderColor: '#3b82f6',
      backgroundColor: 'rgba(59, 130, 246, 0.08)',
    },
    presetRadio: {
      width: 18, height: 18,
      borderRadius: 9,
      borderWidth: 2,
      borderColor: colors.glass.border,
      alignItems: 'center', justifyContent: 'center',
      marginTop: 2,
    },
    presetRadioSelected: { borderColor: '#3b82f6' },
    presetRadioInner: {
      width: 10, height: 10, borderRadius: 5, backgroundColor: '#3b82f6',
    },
    presetTextBlock: { flex: 1 },
    presetTitleRow: {
      flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 4,
    },
    presetTitle: {
      fontFamily: typography.semibold,
      fontSize: 15,
      color: colors.text.primary,
    },
    presetBadge: {
      fontFamily: typography.semibold,
      fontSize: 10,
      letterSpacing: 0.6,
      color: '#3b82f6',
      backgroundColor: 'rgba(59, 130, 246, 0.12)',
      paddingHorizontal: 6,
      paddingVertical: 2,
      borderRadius: 4,
      textTransform: 'uppercase',
    },
    presetSubtitle: {
      fontFamily: typography.medium,
      fontSize: 13,
      color: colors.text.secondary,
      lineHeight: 18,
      marginBottom: 4,
    },
    presetBodyHelp: {
      fontFamily: typography.regular,
      fontSize: 12,
      color: colors.text.muted,
      lineHeight: 17,
    },

    customizeLink: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      paddingVertical: spacing.sm,
      paddingHorizontal: spacing.sm,
      alignSelf: 'flex-start',
    },
    customizeLinkText: {
      fontFamily: typography.medium,
      fontSize: 13,
      color: colors.text.primary,
      textDecorationLine: 'underline',
    },
    customStateBanner: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: 6,
      padding: spacing.sm,
      borderRadius: borderRadius.md,
      borderWidth: 1,
      borderColor: colors.glass.border,
      backgroundColor: colors.glass.background,
    },
    customStateBannerText: {
      flex: 1,
      fontFamily: typography.regular,
      fontSize: 11,
      color: colors.text.muted,
      lineHeight: 16,
    },

    // ── Timing card (compact) ──
    timingCard: { padding: spacing.md, gap: 0 },
    timingRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingVertical: spacing.sm,
      borderBottomWidth: 1,
      borderBottomColor: colors.glass.border,
    },
    timingRowLast: { borderBottomWidth: 0 },
    timingLabel: {
      fontFamily: typography.medium,
      fontSize: 13,
      color: colors.text.primary,
    },

    // ── Advanced section ──
    advancedHeaderRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      flexWrap: 'wrap',
      gap: 6,
      marginTop: spacing.md,
      marginBottom: 4,
    },
    resetAnchorLink: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      paddingVertical: 4,
      paddingHorizontal: 8,
      borderRadius: borderRadius.sm,
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    resetAnchorLinkText: {
      fontFamily: typography.medium,
      fontSize: 11,
      color: colors.text.muted,
    },

    // Severity routes inside advanced
    routesCard: { padding: spacing.md, gap: spacing.xs, marginBottom: spacing.sm },
    routesHeader: {
      fontFamily: typography.semibold,
      fontSize: 13,
      color: colors.text.primary,
    },
    routesHelp: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: colors.text.muted,
      lineHeight: 16,
      marginBottom: spacing.xs,
    },
    severityRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
      paddingVertical: spacing.xs,
      borderTopWidth: 1,
      borderTopColor: colors.glass.border,
      flexWrap: 'wrap',
    },

    // Family cards
    familyCard: { padding: 0, overflow: 'hidden' },
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
    kindRow: {
      paddingVertical: spacing.sm,
      borderTopWidth: 1,
      borderTopColor: colors.glass.border,
      gap: spacing.sm,
    },
    kindRowHeader: {
      flexDirection: 'row', gap: spacing.sm, alignItems: 'flex-start',
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
    kindRowControls: {
      flexDirection: 'row',
      gap: spacing.sm,
      flexWrap: 'wrap',
    },
    kindRowControlGroup: {
      gap: 2, flex: 1, minWidth: 140,
    },
    kindRowControlLabel: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: colors.text.muted,
    },

    // Severity badge
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

    // Channel chips
    channelRow: {
      flexDirection: 'row', gap: 6, flexWrap: 'wrap',
    },
    channelRowCompact: { justifyContent: 'flex-end' },
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
    channelChipDisabled: { opacity: 0.55 },
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

    // SelectChip
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

    // Footer
    footerInfoRow: {
      flexDirection: 'row', alignItems: 'center', gap: 6,
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

    // Mobile sticky bar
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
    mobileBtnDisabled: { opacity: 0.5 },
  });
}
