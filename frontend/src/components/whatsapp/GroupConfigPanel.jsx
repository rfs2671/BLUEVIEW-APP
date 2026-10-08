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
import { GlassCard } from '../GlassCard';
import GlassButton from '../GlassButton';
import { useToast } from '../Toast';
import { whatsappAPI } from '../../utils/api';
import { BOT_SETTINGS, botSettingValue, withBotSetting, configForSave } from '../../utils/whatsappSettings';
import { spacing, borderRadius, typography } from '../../styles/theme';
import { useTheme } from '../../context/ThemeContext';

// What the panel shows is the server's EFFECTIVE config (GET
// /api/whatsapp/groups/{project_id} merges stored values over defaults, the
// same merge the bot reads). The rows are BOT_SETTINGS: only settings the bot
// acts on today, each with a plain name and one line.
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
export function TimePickerRow({ value, onChange, colors, slots = TIME_SLOTS }) {
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
      data={slots}
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

// ─── One setting: plain name, one line, a switch ────────────────────
function SettingRow({ setting, value, onChange, colors, disabled }) {
  const s = useMemo(() => buildInnerStyles(colors), [colors]);
  return (
    <View style={[s.featureRow, disabled && { opacity: 0.55 }]}>
      <View style={{ flex: 1, marginRight: spacing.sm }}>
        <Text style={s.featureLabel}>{setting.label}</Text>
        <Text style={s.masterHint}>{setting.line}</Text>
      </View>
      <Switch
        value={!!value}
        onValueChange={onChange}
        disabled={disabled}
        accessibilityLabel={setting.label}
        trackColor={{ false: colors.glass.border, true: colors.primary }}
        thumbColor={colors.white}
      />
    </View>
  );
}

// ─── What the bot does in one group ─────────────────────────────────
export default function GroupConfigPanel({ group, onSaved, onClose }) {
  const { colors } = useTheme();
  const s = useMemo(() => buildInnerStyles(colors), [colors]);
  const toast = useToast();

  const [config, setConfig] = useState(() => group?.bot_config || {});
  const [saving, setSaving] = useState(false);

  const set = (setting, on) => setConfig((prev) => withBotSetting(prev, setting, on));
  const updateField = (patch) => setConfig((prev) => ({ ...prev, ...patch }));
  const answering = config.bot_enabled !== false;

  const handleSave = async () => {
    if (
      config.daily_summary_enabled &&
      (!Array.isArray(config.daily_summary_days) || config.daily_summary_days.length === 0)
    ) {
      toast.error('Pick at least one day', 'The daily summary needs at least one day.');
      return;
    }
    setSaving(true);
    try {
      const res = await whatsappAPI.updateGroupConfig(group.id || group._id, configForSave(config));
      toast.success('Saved', 'Group settings updated.');
      if (onSaved) onSaved(res);
      if (onClose) onClose();
    } catch (e) {
      toast.error('Not saved', e?.response?.data?.detail || 'Could not save these settings.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <GlassCard style={s.panel}>
      {BOT_SETTINGS.map((setting) => (
        <View key={setting.key}>
          <SettingRow
            setting={setting}
            value={botSettingValue(config, setting)}
            onChange={(v) => set(setting, v)}
            disabled={setting.key !== 'bot_enabled' && !answering}
            colors={colors}
          />
          {setting.key === 'daily_summary_enabled' && answering && config.daily_summary_enabled ? (
            <View style={s.sectionInner}>
              <Text style={s.subLabel}>Time (Eastern)</Text>
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
          ) : null}
          {setting.key === 'checklist_extraction_enabled' && answering && config.checklist_extraction_enabled ? (
            <View style={s.sectionInner}>
              <Text style={s.subLabel}>When</Text>
              <View style={s.freqRow}>
                {[
                  { value: 'daily', label: 'Every day' },
                  { value: 'on_demand', label: 'Only when asked' },
                ].map((opt) => {
                  const active = config.checklist_frequency === opt.value;
                  return (
                    <Pressable
                      key={opt.value}
                      onPress={() => updateField({ checklist_frequency: opt.value })}
                      style={({ pressed }) => [s.freqPill, active && s.freqPillActive, pressed && { opacity: 0.8 }]}
                    >
                      <Text style={[s.freqText, active && s.freqTextActive]}>{opt.label}</Text>
                    </Pressable>
                  );
                })}
              </View>
              {config.checklist_frequency === 'daily' ? (
                <>
                  <Text style={[s.subLabel, { marginTop: spacing.md }]}>Time (Eastern)</Text>
                  <TimePickerRow
                    value={config.checklist_time}
                    onChange={(v) => updateField({ checklist_time: v })}
                    colors={colors}
                  />
                </>
              ) : (
                <Text style={s.masterHint}>Ask for it in the group: "@levelog checklist".</Text>
              )}
            </View>
          ) : null}
        </View>
      ))}

      <View style={s.footerRow}>
        <GlassButton
          title={saving ? 'Saving…' : 'Save'}
          loading={saving}
          onPress={handleSave}
          disabled={saving}
          style={{ flex: 1 }}
        />
      </View>
    </GlassCard>
  );
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
