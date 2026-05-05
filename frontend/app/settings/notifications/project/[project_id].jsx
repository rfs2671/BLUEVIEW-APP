/**
 * /settings/notifications/project/[project_id] — Phase B1c.
 *
 * Project-scoped notification preferences. Same preset cards +
 * delivery timing + advanced section as the global settings page,
 * but:
 *   • Loads via GET /api/projects/{id}/notification-preferences/{user_id}.
 *     The backend falls back to user-global → defaults when no
 *     project-scoped record exists, so the form always renders
 *     against a fully-populated shape.
 *   • Saves via PATCH /api/projects/{id}/notification-preferences/{user_id}.
 *   • Header shows project name + address.
 *   • "Reset to user-global preferences" header button — DELETE
 *     the project-scoped record, then navigate back to the global
 *     settings page.
 *   • Live preview is project-scoped (preview endpoint takes the
 *     project_id query param).
 *
 * The form-rendering logic largely mirrors the global page. We
 * deliberately don't extract a shared component because that would
 * touch the byte-for-byte test pins on the global file. The shared
 * pieces (PRESET_ORDER, PRESETS, buildPresetPrefs, detectActivePreset,
 * SIGNAL_FAMILIES, SIGNAL_KIND_INDEX, SEVERITY_PALETTE) all import
 * from the existing modules so the shapes are guaranteed identical.
 */

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  Alert,
  useWindowDimensions,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
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
  Eye,
  Mailbox,
  Inbox,
  Building2,
  Sliders,
  Clock,
} from 'lucide-react-native';
import AnimatedBackground from '../../../../src/components/AnimatedBackground';
import { GlassCard } from '../../../../src/components/GlassCard';
import GlassButton from '../../../../src/components/GlassButton';
import { useAuth } from '../../../../src/context/AuthContext';
import { useTheme } from '../../../../src/context/ThemeContext';
import { useToast } from '../../../../src/components/Toast';
import apiClient from '../../../../src/utils/api';
import { spacing, borderRadius, typography } from '../../../../src/styles/theme';
import {
  SIGNAL_FAMILIES,
  SIGNAL_KIND_INDEX,
  SEVERITY_PALETTE,
} from '../../../../src/constants/signalKinds';
import {
  PRESETS,
  PRESET_ORDER,
  buildPresetPrefs,
  detectActivePreset,
} from '../../../../src/utils/notificationPresets';

// Static option lists — same as the global page.
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

// Helpers (duplicated from global page; small + cheap).
function defaultDeliveryFor(severity) {
  if (severity === 'critical') return 'immediate';
  if (severity === 'warning') return 'digest_daily';
  return 'feed_only';
}
function effectiveOverrideFor(prefs, kind) {
  const stored = prefs?.signal_kind_overrides && prefs.signal_kind_overrides[kind.key];
  if (stored) {
    return {
      channels: Array.isArray(stored.channels) ? stored.channels : [],
      severity_threshold: stored.severity_threshold || 'any',
      delivery: stored.delivery || defaultDeliveryFor(kind.defaultSeverity),
      isExplicit: true,
    };
  }
  const routes = (prefs?.channel_routes_default && prefs.channel_routes_default[kind.defaultSeverity]) || [];
  return {
    channels: routes,
    severity_threshold: 'any',
    delivery: defaultDeliveryFor(kind.defaultSeverity),
    isExplicit: false,
  };
}
function deepEqual(a, b) {
  try { return JSON.stringify(a) === JSON.stringify(b); }
  catch (_e) { return false; }
}

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
          <ch.Icon size={13} strokeWidth={1.5} color={isOn ? '#fff' : colors.text.muted} />
          <Text style={[styles.channelChipLabel, isOn && { color: '#fff' }, !ch.enabled && { color: colors.text.muted }]}>
            {ch.label}
          </Text>
          {ch.badge && <Text style={styles.channelBadge}>{ch.badge}</Text>}
        </Pressable>
      );
    })}
  </View>
);

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
      style={({ pressed }) => [styles.selectChip, pressed && { opacity: 0.7 }]}
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
    <View style={[styles.sevBadge, { backgroundColor: palette.bg, borderColor: `${palette.color}80` }]}>
      <Text style={[styles.sevBadgeText, { color: palette.color }]}>
        {palette.label}
      </Text>
    </View>
  );
};

const PresetRadioCard = ({ preset, selected, onSelect, styles }) => (
  <Pressable
    onPress={() => onSelect(preset.key)}
    style={({ pressed }) => [
      styles.presetCard,
      selected && styles.presetCardSelected,
      pressed && { opacity: 0.85 },
    ]}
  >
    <View style={[styles.presetRadio, selected && styles.presetRadioSelected]}>
      {selected && <View style={styles.presetRadioInner} />}
    </View>
    <View style={styles.presetTextBlock}>
      <View style={styles.presetTitleRow}>
        <Text style={styles.presetTitle}>{preset.label}</Text>
        {preset.badge && <Text style={styles.presetBadge}>{preset.badge}</Text>}
      </View>
      <Text style={styles.presetSubtitle}>{preset.subtitle}</Text>
      <Text style={styles.presetBodyHelp}>{preset.bodyHelp}</Text>
    </View>
  </Pressable>
);

// ── Page ─────────────────────────────────────────────────────────

export default function ProjectNotificationPreferencesScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const projectId = params?.project_id;
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
  const { colors } = useTheme();
  const toast = useToast();
  const styles = useMemo(() => buildStyles(colors), [colors]);
  const { width: winWidth } = useWindowDimensions();
  const isMobile = winWidth < MOBILE_BREAKPOINT;

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
  const [project, setProject] = useState(null);
  const [initialPrefs, setInitialPrefs] = useState(null);
  const [prefs, setPrefs] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [resetting, setResetting] = useState(false);
  const [lastSavedAt, setLastSavedAt] = useState(null);
  const [anchorPreset, setAnchorPreset] = useState('critical_only');
  const [advancedOpen, setAdvancedOpen] = useState(false);
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

  // Live preview (project-scoped via ?project_id=).
  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const userId = user?.id || user?._id || user?.user_id;

  const loadPreferences = useCallback(async () => {
    if (!projectId || !userId) return;
    setLoading(true);
    setLoadError(null);
    try {
      const [prefsResp, projResp] = await Promise.all([
        apiClient.get(`/api/projects/${projectId}/notification-preferences/${userId}`),
        apiClient.get(`/api/projects/${projectId}`).catch(() => ({ data: null })),
      ]);
      const data = prefsResp.data || {};
      setInitialPrefs(data);
      setPrefs(JSON.parse(JSON.stringify(data)));
      setLastSavedAt(data.updated_at || null);
      const detected = detectActivePreset(data);
      setAnchorPreset(detected);
      setAdvancedOpen(detected === 'custom');
      if (projResp?.data) setProject(projResp.data);
    } catch (e) {
      console.error('[project-prefs] load failed:', e?.message || e);
      setLoadError('Could not load this project’s notification preferences.');
    } finally {
      setLoading(false);
    }
  }, [projectId, userId]);

  useEffect(() => {
    if (isAuthenticated && userId && projectId) loadPreferences();
  }, [isAuthenticated, userId, projectId, loadPreferences]);

  const livePreset = useMemo(
    () => (prefs ? detectActivePreset(prefs) : 'custom'),
    [prefs],
  );

  const dirty = useMemo(() => {
    if (!initialPrefs || !prefs) return false;
    return !deepEqual(initialPrefs, prefs);
  }, [initialPrefs, prefs]);

  // Debounced project-scoped preview.
  useEffect(() => {
    if (!prefs || !projectId) return undefined;
    let cancelled = false;
    const handle = setTimeout(async () => {
      setPreviewLoading(true);
      try {
        const payload = {
          signal_kind_overrides: prefs.signal_kind_overrides || {},
          channel_routes_default: prefs.channel_routes_default || {},
          digest_window: prefs.digest_window || {},
        };
        const resp = await apiClient.post(
          `/api/users/me/notification-preferences/preview?project_id=${encodeURIComponent(projectId)}`,
          payload,
        );
        if (!cancelled) setPreview(resp.data || null);
      } catch (e) {
        if (!cancelled) {
          console.warn('[project-prefs] preview failed:', e?.message || e);
        }
      } finally {
        if (!cancelled) setPreviewLoading(false);
      }
    }, 500);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [prefs, projectId]);

  // Mutators.
  const updatePrefs = (mutator) => {
    setPrefs((prev) => {
      if (!prev) return prev;
      const next = JSON.parse(JSON.stringify(prev));
      mutator(next);
      return next;
    });
  };
  const handlePresetSelect = (key) => {
    if (!prefs) return;
    setPrefs((prev) => buildPresetPrefs(key, prev));
    setAnchorPreset(key);
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

  const handleSave = async () => {
    if (!prefs || saving || !projectId || !userId) return;
    setSaving(true);
    setSaveError(null);
    try {
      const payload = {
        signal_kind_overrides: prefs.signal_kind_overrides || {},
        channel_routes_default: prefs.channel_routes_default || {},
        digest_window: prefs.digest_window || {},
      };
      const resp = await apiClient.patch(
        `/api/projects/${projectId}/notification-preferences/${userId}`,
        payload,
      );
      const saved = resp.data || prefs;
      setInitialPrefs(saved);
      setPrefs(JSON.parse(JSON.stringify(saved)));
      setLastSavedAt(saved.updated_at || new Date().toISOString());
      const detected = detectActivePreset(saved);
      setAnchorPreset(detected);
      toast.success('Saved', `Preferences saved for ${project?.name || 'this project'}.`);
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

  const handleResetToUserGlobal = () => {
    if (!projectId || !userId || resetting) return;
    Alert.alert(
      'Reset to user-global?',
      'This will remove this project’s custom preferences. The project will use your global notification settings instead.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Reset',
          style: 'destructive',
          onPress: async () => {
            setResetting(true);
            try {
              await apiClient.delete(
                `/api/projects/${projectId}/notification-preferences/${userId}`,
              );
              toast.success(
                'Reset',
                'Project will now use your global preferences.',
              );
              router.replace('/settings/notifications');
            } catch (e) {
              toast.error(
                'Could not reset',
                e?.response?.data?.detail?.message || e?.message || 'Try again.',
              );
            } finally {
              setResetting(false);
            }
          },
        },
      ],
    );
  };

  // ── Render ────────────────────────────────────────────────────

  if (loading || !prefs) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container} edges={['top']}>
          <Header
            router={router}
            colors={colors}
            styles={styles}
            project={project}
          />
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
    : 'Not yet saved for this project';
  const anchorPresetMeta = PRESETS[anchorPreset];

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container} edges={['top']}>
        <Header router={router} colors={colors} styles={styles} project={project} />

        <ScrollView
          style={styles.scroll}
          contentContainerStyle={[
            styles.scrollContent,
            isMobile && { paddingBottom: 120 },
          ]}
          showsVerticalScrollIndicator={false}
        >
          {/* Project meta + reset-to-user-global */}
          <GlassCard style={styles.introCard}>
            <View style={styles.introHeader}>
              <Building2 size={22} strokeWidth={1.5} color={colors.text.primary} />
              <View style={{ flex: 1 }}>
                <Text style={styles.introTitle}>
                  {project?.name || 'Project preferences'}
                </Text>
                {project?.address && (
                  <Text style={styles.introAddr}>{project.address}</Text>
                )}
                <Text style={styles.introBody}>
                  Custom preferences for this project. They override your
                  user-global settings whenever a signal lands on this project.
                </Text>
              </View>
            </View>
            <Pressable
              onPress={handleResetToUserGlobal}
              disabled={resetting}
              style={[styles.resetGlobalBtn, resetting && { opacity: 0.6 }]}
            >
              {resetting ? (
                <ActivityIndicator size="small" color={colors.text.muted} />
              ) : (
                <RotateCcw size={14} strokeWidth={1.5} color={colors.text.muted} />
              )}
              <Text style={styles.resetGlobalBtnText}>
                Reset to user-global preferences
              </Text>
            </Pressable>
          </GlassCard>

          {/* Section A — Presets */}
          <View style={styles.presetGroup}>
            {PRESET_ORDER.map((key) => (
              <PresetRadioCard
                key={key}
                preset={PRESETS[key]}
                selected={livePreset === key}
                onSelect={handlePresetSelect}
                styles={styles}
              />
            ))}
            <Pressable
              onPress={() => setAdvancedOpen((v) => !v)}
              style={styles.customizeLink}
            >
              <Sliders size={14} strokeWidth={1.5} color={colors.text.primary} />
              <Text style={styles.customizeLinkText}>
                {advancedOpen ? 'Hide per-signal customization' : 'Customize per signal type'}
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
                  You&apos;ve customized per-signal settings for this project.
                  {anchorPreset !== 'custom'
                    ? ` Click "Reset to ${PRESETS[anchorPreset].label}" inside Advanced to revert.`
                    : ''}
                </Text>
              </View>
            )}
          </View>

          {/* Live preview (project-scoped) */}
          <PreviewCard
            preview={preview}
            loading={previewLoading}
            project={project}
            styles={styles}
            colors={colors}
          />

          {/* Section B — Delivery timing */}
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

          {/* Section C — Advanced */}
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
              <GlassCard style={styles.routesCard}>
                <Text style={styles.routesHeader}>Severity fallback routes</Text>
                <Text style={styles.routesHelp}>
                  Applies only to signal types not explicitly set below.
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
                                    onChange={(v) => updateOverride(kind.key, { severity_threshold: v })}
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
                                    onChange={(v) => updateOverride(kind.key, { delivery: v })}
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

// ── Subcomponents ───────────────────────────────────────────────

const Header = ({ router, colors, styles, project }) => (
  <View style={styles.header}>
    <Pressable
      onPress={() => router.replace('/settings/notifications')}
      style={styles.backBtn}
    >
      <ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />
    </Pressable>
    <View style={{ flex: 1, alignItems: 'center' }}>
      <Text style={styles.headerTitle} numberOfLines={1}>
        {project?.name || 'Project notifications'}
      </Text>
      <Text style={styles.headerSubtitle}>Project-scoped overrides</Text>
    </View>
    <View style={{ width: 28 }} />
  </View>
);

const PreviewCard = ({ preview, loading, project, styles, colors }) => {
  if (!preview) return null;
  const summary = (preview && preview.summary) || {};
  const total = summary.total_signals_seen || 0;
  if (total === 0 && !loading) {
    return (
      <GlassCard style={styles.previewCard}>
        <View style={styles.previewHeader}>
          <Eye size={16} strokeWidth={1.5} color={colors.text.muted} />
          <Text style={styles.previewTitle}>Live preview</Text>
        </View>
        <Text style={styles.previewEmpty}>
          No DOB activity in the last 7 days for {project?.name || 'this project'}.
        </Text>
      </GlassCard>
    );
  }
  const stats = [
    { key: 'i', Icon: Mail, c: '#ef4444', bg: 'rgba(239,68,68,0.10)', count: summary.immediate_emails || 0, label: 'immediate emails' },
    { key: 'd', Icon: Mailbox, c: '#f59e0b', bg: 'rgba(245,158,11,0.10)', count: summary.digest_daily_signals || 0, label: 'daily digest' },
    { key: 'w', Icon: Mailbox, c: '#3b82f6', bg: 'rgba(59,130,246,0.10)', count: summary.digest_weekly_signals || 0, label: 'weekly digest' },
    { key: 'f', Icon: Inbox, c: '#6b7280', bg: 'rgba(107,114,128,0.10)', count: summary.suppressed_signals || 0, label: 'feed-only' },
  ];
  return (
    <GlassCard style={styles.previewCard}>
      <View style={styles.previewHeader}>
        <Eye size={16} strokeWidth={1.5} color={colors.text.primary} />
        <View style={{ flex: 1 }}>
          <Text style={styles.previewTitle}>
            Live preview — last 7 days{loading ? ' (updating…)' : ''}
          </Text>
          <Text style={styles.previewSubtitle}>
            For {project?.name || 'this project'} only.
          </Text>
        </View>
      </View>
      <View style={styles.previewGrid}>
        {stats.map((s) => (
          <View key={s.key} style={[styles.previewStat, { backgroundColor: s.bg }]}>
            <s.Icon size={14} strokeWidth={1.5} color={s.c} />
            <Text style={[styles.previewStatCount, { color: s.c }]}>{s.count}</Text>
            <Text style={styles.previewStatLabel}>{s.label}</Text>
          </View>
        ))}
      </View>
    </GlassCard>
  );
};

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
    backBtn: { width: 28, height: 28, alignItems: 'center', justifyContent: 'center' },
    headerTitle: {
      fontFamily: typography.semibold,
      fontSize: 15,
      color: colors.text.primary,
    },
    headerSubtitle: {
      fontFamily: typography.regular,
      fontSize: 10,
      color: colors.text.muted,
      letterSpacing: 0.4,
      textTransform: 'uppercase',
    },
    scroll: { flex: 1 },
    scrollContent: {
      paddingHorizontal: spacing.lg,
      paddingBottom: spacing.xl,
      gap: spacing.md,
    },
    loadingWrap: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: spacing.sm },
    loadingText: { fontFamily: typography.regular, fontSize: 13, color: colors.text.muted },
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

    introCard: { padding: spacing.lg, gap: spacing.sm },
    introHeader: { flexDirection: 'row', gap: spacing.md, alignItems: 'flex-start' },
    introTitle: {
      fontFamily: typography.semibold,
      fontSize: 17,
      color: colors.text.primary,
      marginBottom: 4,
    },
    introAddr: {
      fontFamily: typography.regular,
      fontSize: 12,
      color: colors.text.muted,
      marginBottom: spacing.xs,
    },
    introBody: {
      fontFamily: typography.regular,
      fontSize: 13,
      color: colors.text.secondary,
      lineHeight: 19,
    },
    resetGlobalBtn: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      paddingVertical: 6,
      paddingHorizontal: 10,
      borderRadius: borderRadius.sm,
      borderWidth: 1,
      borderColor: colors.glass.border,
      alignSelf: 'flex-start',
    },
    resetGlobalBtnText: {
      fontFamily: typography.medium,
      fontSize: 12,
      color: colors.text.muted,
    },

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
      width: 18, height: 18, borderRadius: 9,
      borderWidth: 2, borderColor: colors.glass.border,
      alignItems: 'center', justifyContent: 'center', marginTop: 2,
    },
    presetRadioSelected: { borderColor: '#3b82f6' },
    presetRadioInner: { width: 10, height: 10, borderRadius: 5, backgroundColor: '#3b82f6' },
    presetTextBlock: { flex: 1 },
    presetTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 4 },
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
      paddingHorizontal: 6, paddingVertical: 2,
      borderRadius: 4, textTransform: 'uppercase',
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

    // Preview
    previewCard: { padding: spacing.md, gap: spacing.sm },
    previewHeader: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm },
    previewTitle: { fontFamily: typography.semibold, fontSize: 13, color: colors.text.primary, marginBottom: 2 },
    previewSubtitle: { fontFamily: typography.regular, fontSize: 11, color: colors.text.muted },
    previewEmpty: { fontFamily: typography.regular, fontSize: 12, color: colors.text.muted, lineHeight: 17 },
    previewGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
    previewStat: { flex: 1, minWidth: 130, padding: spacing.sm, borderRadius: borderRadius.md, gap: 2 },
    previewStatCount: { fontFamily: typography.semibold, fontSize: 22, lineHeight: 26, marginTop: 2 },
    previewStatLabel: { fontFamily: typography.medium, fontSize: 12, color: colors.text.primary },

    // Timing
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
    timingLabel: { fontFamily: typography.medium, fontSize: 13, color: colors.text.primary },

    // Advanced
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
    resetAnchorLinkText: { fontFamily: typography.medium, fontSize: 11, color: colors.text.muted },

    routesCard: { padding: spacing.md, gap: spacing.xs, marginBottom: spacing.sm },
    routesHeader: { fontFamily: typography.semibold, fontSize: 13, color: colors.text.primary },
    routesHelp: { fontFamily: typography.regular, fontSize: 11, color: colors.text.muted, lineHeight: 16, marginBottom: spacing.xs },
    severityRow: {
      flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
      paddingVertical: spacing.xs,
      borderTopWidth: 1, borderTopColor: colors.glass.border,
      flexWrap: 'wrap',
    },

    familyCard: { padding: 0, overflow: 'hidden' },
    familyHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
      padding: spacing.md,
    },
    familyTitle: { fontFamily: typography.semibold, fontSize: 14, color: colors.text.primary },
    familyBlurb: { fontFamily: typography.regular, fontSize: 12, color: colors.text.muted, marginTop: 2 },
    familyBody: { paddingHorizontal: spacing.md, paddingBottom: spacing.md, gap: spacing.md },
    kindRow: {
      paddingVertical: spacing.sm,
      borderTopWidth: 1, borderTopColor: colors.glass.border,
      gap: spacing.sm,
    },
    kindRowHeader: { flexDirection: 'row', gap: spacing.sm, alignItems: 'flex-start' },
    kindRowTitleRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: 2 },
    kindRowLabel: { fontFamily: typography.medium, fontSize: 13, color: colors.text.primary },
    kindRowTooltip: { fontFamily: typography.regular, fontSize: 11, color: colors.text.muted, lineHeight: 15 },
    kindRowControls: { flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' },
    kindRowControlGroup: { gap: 2, flex: 1, minWidth: 140 },
    kindRowControlLabel: { fontFamily: typography.regular, fontSize: 11, color: colors.text.muted },

    sevBadge: {
      paddingVertical: 2, paddingHorizontal: 8,
      borderRadius: borderRadius.sm,
      borderWidth: 1, alignSelf: 'flex-start',
    },
    sevBadgeText: { fontFamily: typography.semibold, fontSize: 10, letterSpacing: 0.5 },

    channelRow: { flexDirection: 'row', gap: 6, flexWrap: 'wrap' },
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
    channelChipOn: { backgroundColor: '#3b82f6', borderColor: '#3b82f6' },
    channelChipDisabled: { opacity: 0.55 },
    channelChipLabel: { fontFamily: typography.medium, fontSize: 12, color: colors.text.primary },
    channelBadge: {
      fontFamily: typography.medium,
      fontSize: 9,
      color: colors.text.muted,
      backgroundColor: colors.glass.background,
      paddingHorizontal: 4, paddingVertical: 1,
      borderRadius: 3, marginLeft: 2,
    },

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
    selectChipText: { fontFamily: typography.medium, fontSize: 12, color: colors.text.primary, flexShrink: 1 },

    footerInfoRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: spacing.md },
    footerInfoText: { fontFamily: typography.regular, fontSize: 11, color: colors.text.muted },
    desktopActionRow: { flexDirection: 'row', gap: spacing.sm, justifyContent: 'flex-end', marginTop: spacing.sm },
    errorBlock: {
      flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm,
      padding: spacing.sm, borderRadius: borderRadius.md,
      borderWidth: 1, borderColor: '#ef444440',
      backgroundColor: '#ef444415', marginTop: spacing.sm,
    },
    errorBlockText: { flex: 1, fontFamily: typography.regular, fontSize: 12, color: '#ef4444', lineHeight: 17 },

    mobileStickyBar: {
      position: 'absolute', bottom: 0, left: 0, right: 0,
      flexDirection: 'row', gap: spacing.sm,
      padding: spacing.md,
      borderTopWidth: 1, borderTopColor: colors.glass.border,
      backgroundColor: colors.background?.start || 'rgba(5,10,18,0.95)',
    },
    mobilePrimaryBtn: {
      flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
      gap: 6, paddingVertical: spacing.sm + 2,
      borderRadius: borderRadius.md, backgroundColor: '#3b82f6',
    },
    mobilePrimaryBtnText: { fontFamily: typography.semibold, fontSize: 14, color: '#fff' },
    mobileSecondaryBtn: {
      flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
      gap: 6, paddingVertical: spacing.sm + 2,
      borderRadius: borderRadius.md,
      borderWidth: 1, borderColor: colors.glass.border,
    },
    mobileSecondaryBtnText: { fontFamily: typography.medium, fontSize: 13, color: colors.text.muted },
    mobileBtnDisabled: { opacity: 0.5 },
  });
}
