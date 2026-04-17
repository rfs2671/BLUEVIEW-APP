import React, { useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  Switch,
  FlatList,
  ActivityIndicator,
} from 'react-native';
import { Clock, Calendar, ListChecks, Users, Building2, Package, FileText, Compass } from 'lucide-react-native';
import { GlassCard } from '../GlassCard';
import GlassButton from '../GlassButton';
import { useToast } from '../Toast';
import { whatsappAPI } from '../../utils/api';
import { spacing, borderRadius, typography } from '../../styles/theme';
import { useTheme } from '../../context/ThemeContext';

// ─── Defaults matching backend _default_bot_config ──────────────────
const DEFAULT_CONFIG = {
  bot_enabled: true,
  daily_summary_enabled: false,
  daily_summary_time: '17:00',
  daily_summary_days: [1, 2, 3, 4, 5],
  checklist_extraction_enabled: false,
  checklist_frequency: 'daily',
  checklist_time: '16:00',
  features: {
    who_on_site: true,
    dob_status: true,
    open_items: true,
    material_detection: true,
    plan_queries: false,
  },
  cross_project_summary: false,
};

// 30-min increments from 06:00 to 22:00
const TIME_SLOTS = (() => {
  const out = [];
  for (let h = 6; h <= 22; h++) {
    for (const m of [0, 30]) {
      if (h === 22 && m === 30) break;
      const hh = String(h).padStart(2, '0');
      const mm = String(m).padStart(2, '0');
      out.push(`${hh}:${mm}`);
    }
  }
  return out;
})();

const DAY_LABELS = [
  { value: 1, short: 'Mon' },
  { value: 2, short: 'Tue' },
  { value: 3, short: 'Wed' },
  { value: 4, short: 'Thu' },
  { value: 5, short: 'Fri' },
  { value: 6, short: 'Sat' },
  { value: 7, short: 'Sun' },
];

const formatTimeLabel = (hhmm) => {
  const [h, m] = hhmm.split(':').map((x) => parseInt(x, 10));
  const period = h >= 12 ? 'PM' : 'AM';
  const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
  const mm = String(m).padStart(2, '0');
  return `${h12}:${mm} ${period}`;
};

// ─── Time picker (horizontal scroll of chips) ───────────────────────
function TimePickerRow({ value, onChange, colors }) {
  const s = useMemo(() => buildInnerStyles(colors), [colors]);
  const renderChip = ({ item }) => {
    const isActive = item === value;
    return (
      <Pressable
        onPress={() => onChange(item)}
        style={({ pressed }) => [
          s.timeChip,
          isActive && s.timeChipActive,
          pressed && { opacity: 0.8 },
        ]}
      >
        <Text style={[s.timeChipText, isActive && s.timeChipTextActive]}>
          {formatTimeLabel(item)}
        </Text>
      </Pressable>
    );
  };
  return (
    <FlatList
      horizontal
      data={TIME_SLOTS}
      keyExtractor={(item) => item}
      renderItem={renderChip}
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={s.timeRowContent}
    />
  );
}

// ─── Day selector pills ─────────────────────────────────────────────
function DaySelector({ days, onChange, colors }) {
  const s = useMemo(() => buildInnerStyles(colors), [colors]);
  const toggleDay = (d) => {
    const set = new Set(days || []);
    if (set.has(d)) set.delete(d);
    else set.add(d);
    onChange(Array.from(set).sort((a, b) => a - b));
  };
  return (
    <View style={s.dayRow}>
      {DAY_LABELS.map((d) => {
        const active = (days || []).includes(d.value);
        return (
          <Pressable
            key={d.value}
            onPress={() => toggleDay(d.value)}
            style={({ pressed }) => [
              s.dayPill,
              active && s.dayPillActive,
              pressed && { opacity: 0.8 },
            ]}
          >
            <Text style={[s.dayText, active && s.dayTextActive]}>{d.short}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

// ─── Feature toggle row ─────────────────────────────────────────────
function FeatureRow({ label, icon, value, onChange, disabled, badge, colors }) {
  const s = useMemo(() => buildInnerStyles(colors), [colors]);
  return (
    <View style={[s.featureRow, disabled && { opacity: 0.55 }]}>
      <View style={s.featureLeft}>
        {icon}
        <Text style={s.featureLabel}>{label}</Text>
      </View>
      {badge ? (
        <View style={s.badge}>
          <Text style={s.badgeText}>{badge}</Text>
        </View>
      ) : (
        <Switch
          value={!!value}
          onValueChange={onChange}
          disabled={disabled}
          trackColor={{ false: colors.glass.border, true: colors.primary }}
          thumbColor={colors.white}
        />
      )}
    </View>
  );
}

// ─── Main panel ─────────────────────────────────────────────────────
export default function GroupConfigPanel({
  group,
  onSaved,
  onClose,
  qwenConfigured = false,
  hasIndexedDocs = false,
}) {
  const { colors } = useTheme();
  const s = useMemo(() => buildInnerStyles(colors), [colors]);
  const toast = useToast();

  // Merge incoming config over defaults so any missing field is safe.
  const initial = useMemo(() => {
    const src = group?.bot_config || {};
    return {
      ...DEFAULT_CONFIG,
      ...src,
      features: { ...DEFAULT_CONFIG.features, ...(src.features || {}) },
    };
  }, [group?.id]);

  const [config, setConfig] = useState(initial);
  const [saving, setSaving] = useState(false);

  const updateField = (patch) => setConfig((prev) => ({ ...prev, ...patch }));
  const updateFeature = (key, val) =>
    setConfig((prev) => ({
      ...prev,
      features: { ...prev.features, [key]: val },
    }));

  const isDimmed = !config.bot_enabled;

  const handleSave = async () => {
    // Client-side validation mirrors server rules for instant feedback
    if (
      config.daily_summary_enabled &&
      (!Array.isArray(config.daily_summary_days) || config.daily_summary_days.length === 0)
    ) {
      toast.error('Pick at least one day', 'Daily Summary requires at least one weekday.');
      return;
    }

    setSaving(true);
    try {
      const res = await whatsappAPI.updateGroupConfig(group.id || group._id, config);
      toast.success('Saved', 'Bot configuration updated.');
      if (onSaved) onSaved(res);
      if (onClose) onClose();
    } catch (e) {
      toast.error('Error', e?.response?.data?.detail || 'Could not save configuration.');
    } finally {
      setSaving(false);
    }
  };

  // Plan queries toggle behavior:
  // - No Qwen key on server → show "Requires Qwen API" badge, no toggle
  // - Qwen configured but no indexed docs → "Index documents first" badge, no toggle
  // - Qwen configured AND at least one indexed page → real Switch
  let planQueriesBadge = null;
  if (!qwenConfigured) planQueriesBadge = 'Requires Qwen API';
  else if (!hasIndexedDocs) planQueriesBadge = 'Index documents first';

  return (
    <GlassCard style={s.panel}>
      {/* Master switch */}
      <View style={s.masterRow}>
        <View style={{ flex: 1 }}>
          <Text style={s.masterLabel}>Bot Enabled</Text>
          <Text style={s.masterHint}>
            Master switch. When off, the bot is silent in this group.
          </Text>
        </View>
        <Switch
          value={!!config.bot_enabled}
          onValueChange={(v) => updateField({ bot_enabled: v })}
          trackColor={{ false: colors.glass.border, true: colors.primary }}
          thumbColor={colors.white}
        />
      </View>

      <View style={[s.sectionsWrap, isDimmed && s.dimmed]} pointerEvents={isDimmed ? 'none' : 'auto'}>
        {/* ── Daily Summary ── */}
        <Text style={s.sectionLabel}>DAILY SUMMARY</Text>
        <View style={s.settingRow}>
          <View style={s.settingRowLeft}>
            <Clock size={18} strokeWidth={1.5} color={colors.text.secondary} />
            <Text style={s.settingTitle}>Send Daily Summary</Text>
          </View>
          <Switch
            value={!!config.daily_summary_enabled}
            onValueChange={(v) => updateField({ daily_summary_enabled: v })}
            trackColor={{ false: colors.glass.border, true: colors.primary }}
            thumbColor={colors.white}
          />
        </View>
        {config.daily_summary_enabled && (
          <View style={s.sectionInner}>
            <Text style={s.subLabel}>Time (EST)</Text>
            <TimePickerRow
              value={config.daily_summary_time}
              onChange={(v) => updateField({ daily_summary_time: v })}
              colors={colors}
            />
            <Text style={[s.subLabel, { marginTop: spacing.md }]}>Days</Text>
            <DaySelector
              days={config.daily_summary_days}
              onChange={(v) => updateField({ daily_summary_days: v })}
              colors={colors}
            />
          </View>
        )}

        {/* ── Automated Checklist ── */}
        <Text style={s.sectionLabel}>AUTOMATED CHECKLIST</Text>
        <View style={s.settingRow}>
          <View style={s.settingRowLeft}>
            <ListChecks size={18} strokeWidth={1.5} color={colors.text.secondary} />
            <Text style={s.settingTitle}>Extract Action Items</Text>
          </View>
          <Switch
            value={!!config.checklist_extraction_enabled}
            onValueChange={(v) => updateField({ checklist_extraction_enabled: v })}
            trackColor={{ false: colors.glass.border, true: colors.primary }}
            thumbColor={colors.white}
          />
        </View>
        {config.checklist_extraction_enabled && (
          <View style={s.sectionInner}>
            <Text style={s.subLabel}>Frequency</Text>
            <View style={s.freqRow}>
              {[
                { value: 'daily', label: 'Daily Auto' },
                { value: 'on_demand', label: 'On Demand' },
              ].map((opt) => {
                const active = config.checklist_frequency === opt.value;
                return (
                  <Pressable
                    key={opt.value}
                    onPress={() => updateField({ checklist_frequency: opt.value })}
                    style={({ pressed }) => [
                      s.freqPill,
                      active && s.freqPillActive,
                      pressed && { opacity: 0.8 },
                    ]}
                  >
                    <Text style={[s.freqText, active && s.freqTextActive]}>
                      {opt.label}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
            {config.checklist_frequency === 'daily' && (
              <>
                <Text style={[s.subLabel, { marginTop: spacing.md }]}>Time (EST)</Text>
                <TimePickerRow
                  value={config.checklist_time}
                  onChange={(v) => updateField({ checklist_time: v })}
                  colors={colors}
                />
              </>
            )}
          </View>
        )}

        {/* ── Active features ── */}
        <Text style={s.sectionLabel}>BOT RESPONDS TO</Text>
        <FeatureRow
          label="Who's On Site"
          icon={<Users size={18} strokeWidth={1.5} color={colors.text.secondary} />}
          value={config.features?.who_on_site}
          onChange={(v) => updateFeature('who_on_site', v)}
          colors={colors}
        />
        <FeatureRow
          label="DOB Status"
          icon={<Building2 size={18} strokeWidth={1.5} color={colors.text.secondary} />}
          value={config.features?.dob_status}
          onChange={(v) => updateFeature('dob_status', v)}
          colors={colors}
        />
        <FeatureRow
          label="Open Items"
          icon={<FileText size={18} strokeWidth={1.5} color={colors.text.secondary} />}
          value={config.features?.open_items}
          onChange={(v) => updateFeature('open_items', v)}
          colors={colors}
        />
        <FeatureRow
          label="Material Requests"
          icon={<Package size={18} strokeWidth={1.5} color={colors.text.secondary} />}
          value={config.features?.material_detection}
          onChange={(v) => updateFeature('material_detection', v)}
          colors={colors}
        />
        <FeatureRow
          label="Plan Queries"
          icon={<Compass size={18} strokeWidth={1.5} color={colors.text.secondary} />}
          value={config.features?.plan_queries}
          onChange={(v) => updateFeature('plan_queries', v)}
          badge={planQueriesBadge}
          colors={colors}
        />
      </View>

      {/* Save */}
      <View style={s.footerRow}>
        <GlassButton
          title={saving ? 'Saving…' : 'Save Configuration'}
          loading={saving}
          onPress={handleSave}
          disabled={saving}
          style={{ flex: 1 }}
        />
      </View>
    </GlassCard>
  );
}

// Helper exported so the parent can show an indicator dot without
// duplicating the "non-default" logic.
export function isConfigNonDefault(cfg) {
  if (!cfg) return false;
  if (!cfg.bot_enabled) return false;
  if (cfg.daily_summary_enabled) return true;
  if (cfg.checklist_extraction_enabled) return true;
  if (cfg.features?.plan_queries) return true;
  return false;
}

const buildInnerStyles = (colors) =>
  StyleSheet.create({
    panel: {
      marginTop: spacing.sm,
      padding: spacing.lg,
    },
    masterRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
      paddingBottom: spacing.md,
      borderBottomWidth: 1,
      borderBottomColor: colors.glass.border,
    },
    masterLabel: {
      fontSize: 16,
      fontWeight: '600',
      color: colors.text.primary,
    },
    masterHint: {
      fontSize: 12,
      color: colors.text.muted,
      marginTop: 2,
    },
    sectionsWrap: {
      paddingTop: spacing.md,
    },
    dimmed: { opacity: 0.4 },
    sectionLabel: {
      fontSize: 11,
      fontWeight: '600',
      color: colors.text.muted,
      letterSpacing: 0.8,
      marginTop: spacing.md,
      marginBottom: spacing.sm,
    },
    settingRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingVertical: spacing.sm,
    },
    settingRowLeft: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
      flex: 1,
    },
    settingTitle: {
      fontSize: 14,
      fontWeight: '500',
      color: colors.text.primary,
    },
    sectionInner: {
      paddingTop: spacing.sm,
      paddingBottom: spacing.sm,
    },
    subLabel: {
      fontSize: 11,
      fontWeight: '600',
      color: colors.text.subtle,
      letterSpacing: 0.5,
      marginBottom: spacing.xs,
    },
    // Time picker
    timeRowContent: {
      gap: spacing.xs,
      paddingVertical: spacing.xs,
    },
    timeChip: {
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.xs + 2,
      borderRadius: borderRadius.full,
      borderWidth: 1,
      borderColor: colors.glass.border,
      backgroundColor: colors.glass.background,
    },
    timeChipActive: {
      borderColor: colors.primary,
      backgroundColor: colors.primary + '20',
    },
    timeChipText: {
      fontSize: 12,
      color: colors.text.secondary,
    },
    timeChipTextActive: {
      color: colors.primary,
      fontWeight: '600',
    },
    // Day pills
    dayRow: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: spacing.xs,
    },
    dayPill: {
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.xs + 2,
      borderRadius: borderRadius.full,
      borderWidth: 1,
      borderColor: colors.glass.border,
      backgroundColor: colors.glass.background,
    },
    dayPillActive: {
      borderColor: colors.primary,
      backgroundColor: colors.primary,
    },
    dayText: {
      fontSize: 12,
      color: colors.text.secondary,
    },
    dayTextActive: {
      color: colors.white || '#fff',
      fontWeight: '600',
    },
    // Frequency pills
    freqRow: { flexDirection: 'row', gap: spacing.xs },
    freqPill: {
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.xs + 2,
      borderRadius: borderRadius.full,
      borderWidth: 1,
      borderColor: colors.glass.border,
      backgroundColor: colors.glass.background,
    },
    freqPillActive: {
      borderColor: colors.primary,
      backgroundColor: colors.primary + '20',
    },
    freqText: { fontSize: 12, color: colors.text.secondary },
    freqTextActive: { color: colors.primary, fontWeight: '600' },
    // Feature rows
    featureRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingVertical: spacing.sm,
      borderTopWidth: 1,
      borderTopColor: colors.glass.border,
    },
    featureLeft: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
      flex: 1,
    },
    featureLabel: {
      fontSize: 14,
      color: colors.text.primary,
    },
    badge: {
      paddingHorizontal: 8,
      paddingVertical: 2,
      borderRadius: borderRadius.full,
      backgroundColor: colors.glass.background,
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    badgeText: {
      fontSize: 10,
      fontWeight: '600',
      color: colors.text.muted,
      textTransform: 'uppercase',
      letterSpacing: 0.5,
    },
    // Footer
    footerRow: {
      flexDirection: 'row',
      gap: spacing.sm,
      marginTop: spacing.md,
      paddingTop: spacing.md,
      borderTopWidth: 1,
      borderTopColor: colors.glass.border,
    },
  });
