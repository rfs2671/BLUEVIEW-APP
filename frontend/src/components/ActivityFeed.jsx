/**
 * MR.14 commit 3 / Phase B0.1 — Activity feed component.
 *
 * Renders the v1 monitoring product's signal stream for a single
 * project. Reads from GET /api/projects/{id}/dob-logs (server-side
 * rendered via lib.dob_signal_templates) so all template logic
 * lives backend-side; this component is a pure renderer + filter
 * controller.
 *
 * Phase B0.1: rewritten to use the LeveLog design system.
 *   • useTheme() for theme-aware colors (dark + light).
 *   • GlassCard for signal cards, modal cards, filter panel.
 *   • typography.label for uppercase tracked section headers
 *     (matches "QUICK ACTIONS", "ON-SITE WORKERS", etc. on the
 *     project hub).
 *   • colors.status.* for severity coloring (matches the rest of
 *     the app's status indicators).
 *   • All buttons / chips / inputs match patterns used elsewhere.
 *
 * Mobile + desktop responsive. Filter panel collapses to a bottom
 * sheet on narrow viewports.
 *
 * Props:
 *   projectId: string (required)
 *   onUnreadCountChange?: (count: number) => void  // hook for badges
 */

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  RefreshControl,
  Modal,
  TextInput,
  useWindowDimensions,
  Linking,
} from 'react-native';
import {
  AlertTriangle,
  Info,
  X,
  Filter,
  Search,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Eye,
  EyeOff,
  CheckCheck,
  RefreshCw,
} from 'lucide-react-native';
import InfoTooltip from './InfoTooltip';
import { SIGNAL_KIND_GROUP_HELP } from '../utils/signalKindHelp';
import { GlassCard } from './GlassCard';
import { useTheme } from '../context/ThemeContext';
import { spacing, borderRadius, typography } from '../styles/theme';
import { dobAPI } from '../utils/api';

// ── Severity palette helper ───────────────────────────────────────
//
// Severity colors are theme-aware: they mirror colors.status.* +
// colors.error / .warning / .primary so the feed feels visually
// part of the rest of the app (the same red on a critical signal
// here matches the red on a critical status pill on the project
// hub). The Icon assignment is intentional: critical/warning both
// use AlertTriangle; info uses the Info glyph.

function buildSeverityPalette(colors) {
  return {
    critical: {
      color: colors.error,
      bg: colors.status?.errorBg || 'rgba(239, 68, 68, 0.10)',
      border: colors.error,
      label: 'Critical',
      Icon: AlertTriangle,
    },
    warning: {
      color: colors.warning,
      bg: colors.status?.warningBg || 'rgba(251, 191, 36, 0.20)',
      border: colors.warning,
      label: 'Warning',
      Icon: AlertTriangle,
    },
    info: {
      color: colors.primary,
      bg: 'rgba(59, 130, 246, 0.12)',
      border: colors.primary,
      label: 'Info',
      Icon: Info,
    },
  };
}

// ── Date-range filter options ─────────────────────────────────────

const DATE_RANGE_OPTIONS = [
  { value: 'today', label: 'Today' },
  { value: '7d', label: 'Past 7 days' },
  { value: '30d', label: 'Past 30 days' },
  { value: 'all', label: 'All time' },
];

// ── Signal-kind filter options (organized by category) ───────────

const SIGNAL_KIND_GROUPS = [
  {
    label: 'Permits',
    kinds: ['permit_issued', 'permit_expired', 'permit_revoked', 'permit_renewed'],
  },
  {
    label: 'Job Filings',
    kinds: ['filing_approved', 'filing_disapproved', 'filing_withdrawn', 'filing_pending'],
  },
  {
    label: 'Violations',
    kinds: ['violation_dob', 'violation_ecb', 'violation_resolved'],
  },
  {
    label: 'Stop Work Orders',
    kinds: ['stop_work_full', 'stop_work_partial'],
  },
  {
    label: 'Complaints',
    kinds: ['complaint_dob', 'complaint_311'],
  },
  {
    label: 'Inspections',
    kinds: ['inspection_scheduled', 'inspection_passed', 'inspection_failed', 'final_signoff'],
  },
  {
    label: 'Compliance',
    kinds: ['cofo_temporary', 'cofo_final', 'cofo_pending', 'facade_fisp', 'boiler_inspection', 'elevator_inspection'],
  },
  {
    label: 'License',
    kinds: ['license_renewal_due'],
  },
];

// ── Helpers ───────────────────────────────────────────────────────

function formatRelativeTime(isoString) {
  if (!isoString) return '';
  const d = new Date(isoString);
  if (isNaN(d.getTime())) return '';
  const now = new Date();
  const diffMs = now - d;
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);
  if (diffMin < 1) return 'Just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHour < 24) return `${diffHour}h ago`;
  if (diffDay === 1) return 'Yesterday';
  if (diffDay < 7) return `${diffDay}d ago`;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function humanizeKind(kind) {
  if (!kind) return '';
  return kind
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// ── Signal card ───────────────────────────────────────────────────

function SignalCard({ log, onMarkRead, onViewRaw, styles, colors, severityPalette }) {
  const [expanded, setExpanded] = useState(false);
  const sev = severityPalette[log.severity_kind] || severityPalette.info;
  const SevIcon = sev.Icon;
  const isRead = !!log.is_read;

  return (
    <GlassCard
      style={[
        styles.card,
        // Severity stripe along the leading edge — matches the
        // visual language of severity-tagged content elsewhere.
        { borderLeftWidth: 3, borderLeftColor: sev.color },
        isRead && styles.cardRead,
      ]}
      hoverEffect={false}
    >
      <View style={styles.cardHeader}>
        <View style={[
          styles.iconBubble,
          { backgroundColor: sev.bg, borderColor: `${sev.color}40` },
        ]}>
          <SevIcon size={18} color={sev.color} />
        </View>
        <View style={styles.cardHeaderText}>
          <Text
            style={[styles.cardTitle, isRead && styles.textMuted]}
            numberOfLines={2}
          >
            {log.title || log.ai_summary || 'DOB record'}
          </Text>
          <Text style={styles.cardMeta}>
            {formatRelativeTime(log.status_changed_at || log.detected_at)}
            {log.signal_kind ? ` · ${humanizeKind(log.signal_kind)}` : ''}
          </Text>
        </View>
        {!isRead && (
          <View
            style={[styles.unreadDot, { backgroundColor: sev.color }]}
            accessibilityLabel="Unread"
          />
        )}
      </View>

      {log.body ? (
        <Text
          style={[styles.cardBody, isRead && styles.textMuted]}
          numberOfLines={3}
        >
          {log.body}
        </Text>
      ) : null}

      {log.action_text ? (
        <Pressable
          onPress={() => setExpanded((p) => !p)}
          style={styles.actionToggle}
          accessibilityRole="button"
        >
          <Text style={[styles.actionToggleText, { color: sev.color }]}>
            {expanded ? 'Hide what to do' : 'What to do'}
          </Text>
          {expanded
            ? <ChevronUp size={14} color={sev.color} />
            : <ChevronDown size={14} color={sev.color} />}
        </Pressable>
      ) : null}
      {expanded && log.action_text ? (
        <View style={[
          styles.actionPanel,
          { backgroundColor: sev.bg, borderColor: `${sev.color}40` },
        ]}>
          <Text style={styles.actionPanelText}>{log.action_text}</Text>
        </View>
      ) : null}

      <View style={styles.cardActions}>
        {log.dob_link ? (
          <Pressable
            onPress={() => Linking.openURL(log.dob_link).catch(() => {})}
            style={styles.cardActionBtn}
          >
            <ExternalLink size={14} color={colors.text.muted} />
            <Text style={styles.cardActionText}>Open on DOB</Text>
          </Pressable>
        ) : null}
        <Pressable onPress={() => onViewRaw(log)} style={styles.cardActionBtn}>
          <Text style={styles.cardActionText}>View raw data</Text>
        </Pressable>
        {!isRead ? (
          <Pressable
            onPress={() => onMarkRead(log)}
            style={[styles.cardActionBtn, styles.cardActionBtnEnd]}
            accessibilityRole="button"
            accessibilityLabel="Mark as read"
          >
            <Eye size={14} color={colors.text.muted} />
            <Text style={styles.cardActionText}>Mark read</Text>
          </Pressable>
        ) : (
          <View style={[styles.cardActionBtn, styles.cardActionBtnEnd]}>
            <EyeOff size={14} color={colors.text.subtle || colors.text.muted} />
            <Text style={[styles.cardActionText, styles.textMuted]}>Read</Text>
          </View>
        )}
      </View>
    </GlassCard>
  );
}

// ── Filter panel ──────────────────────────────────────────────────

function FilterPanel({
  filters,
  onChange,
  onClose,
  isMobile,
  styles,
  colors,
  severityPalette,
}) {
  const [search, setSearch] = useState(filters.search || '');

  const togglesignalKind = (kind) => {
    const current = filters.signal_kinds || [];
    const next = current.includes(kind)
      ? current.filter((k) => k !== kind)
      : [...current, kind];
    onChange({ ...filters, signal_kinds: next });
  };
  const setSeverityKind = (sk) => {
    onChange({ ...filters, severity_kind: filters.severity_kind === sk ? null : sk });
  };
  const setDateRange = (dr) => onChange({ ...filters, date_range: dr });
  const toggleUnreadOnly = () =>
    onChange({ ...filters, unread_only: !filters.unread_only });
  const applySearch = () => onChange({ ...filters, search: search.trim() });

  return (
    <ScrollView
      style={[styles.filterPanel, isMobile && styles.filterPanelMobile]}
      contentContainerStyle={{ paddingBottom: spacing.xl }}
      showsVerticalScrollIndicator={false}
    >
      <View style={styles.filterHeader}>
        <Text style={styles.filterTitle}>Filters</Text>
        {onClose ? (
          <Pressable onPress={onClose} accessibilityRole="button" hitSlop={8}>
            <X size={20} color={colors.text.muted} />
          </Pressable>
        ) : null}
      </View>

      <Text style={styles.filterSectionLabel}>SEARCH</Text>
      <View style={styles.searchRow}>
        <Search size={16} color={colors.text.muted} />
        <TextInput
          style={styles.searchInput}
          value={search}
          onChangeText={setSearch}
          onSubmitEditing={applySearch}
          onBlur={applySearch}
          placeholder="Search title or body…"
          placeholderTextColor={colors.text.subtle || colors.text.muted}
          returnKeyType="search"
        />
      </View>

      <Text style={styles.filterSectionLabel}>DATE RANGE</Text>
      <View style={styles.pillRow}>
        {DATE_RANGE_OPTIONS.map((opt) => {
          const active = filters.date_range === opt.value;
          return (
            <Pressable
              key={opt.value}
              onPress={() => setDateRange(opt.value)}
              style={[styles.pill, active && styles.pillActive]}
            >
              <Text style={[
                styles.pillText,
                active && styles.pillTextActive,
              ]}>{opt.label}</Text>
            </Pressable>
          );
        })}
      </View>

      <Text style={styles.filterSectionLabel}>SEVERITY</Text>
      <View style={styles.pillRow}>
        {['critical', 'warning', 'info'].map((sk) => {
          const active = filters.severity_kind === sk;
          const sev = severityPalette[sk];
          return (
            <Pressable
              key={sk}
              onPress={() => setSeverityKind(sk)}
              style={[
                styles.pill,
                active && {
                  backgroundColor: sev.bg,
                  borderColor: sev.color,
                },
              ]}
            >
              <Text style={[
                styles.pillText,
                active && { color: sev.color, fontWeight: '600' },
              ]}>{sev.label}</Text>
            </Pressable>
          );
        })}
      </View>

      <Pressable onPress={toggleUnreadOnly} style={styles.unreadToggle}>
        <View
          style={[
            styles.checkbox,
            filters.unread_only && styles.checkboxActive,
          ]}
        >
          {filters.unread_only ? <CheckCheck size={12} color="#fff" /> : null}
        </View>
        <Text style={styles.unreadToggleText}>Show unread only</Text>
      </Pressable>

      <Text style={styles.filterSectionLabel}>SIGNAL TYPE</Text>
      {SIGNAL_KIND_GROUPS.map((group) => (
        <View key={group.label} style={styles.kindGroup}>
          {/* Phase B3: tooltip on each filter group label explaining
              the kinds in that group in plain English. Per-chip
              tooltips would clutter at 26 chips; group-level
              tooltips cover all chips in 8 lookups. */}
          <View style={styles.kindGroupHeader}>
            <Text style={styles.kindGroupLabel}>{group.label}</Text>
            <InfoTooltip
              text={SIGNAL_KIND_GROUP_HELP[group.label] || ''}
              size={13}
            />
          </View>
          <View style={styles.pillRow}>
            {group.kinds.map((kind) => {
              const active = (filters.signal_kinds || []).includes(kind);
              return (
                <Pressable
                  key={kind}
                  onPress={() => togglesignalKind(kind)}
                  style={[styles.pill, active && styles.pillActive]}
                >
                  <Text style={[
                    styles.pillText,
                    active && styles.pillTextActive,
                  ]}>{humanizeKind(kind)}</Text>
                </Pressable>
              );
            })}
          </View>
        </View>
      ))}
    </ScrollView>
  );
}

// ── Raw-data modal ────────────────────────────────────────────────

function RawDataModal({ log, onClose, styles, colors }) {
  if (!log) return null;
  const entries = Object.entries(log).filter(([k]) => !k.startsWith('_'));
  return (
    <Modal visible animationType="fade" transparent onRequestClose={onClose}>
      <Pressable
        style={styles.modalOverlay}
        onPress={onClose}
        accessibilityRole="button"
      >
        <Pressable
          // Inner pressable intercepts taps so clicking inside the
          // card doesn't dismiss.
          onPress={() => {}}
          style={{ width: '100%', maxWidth: 720 }}
        >
          <GlassCard variant="modal" style={styles.modalCard}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Raw DOB record</Text>
              <Pressable
                onPress={onClose}
                accessibilityRole="button"
                hitSlop={8}
              >
                <X size={20} color={colors.text.muted} />
              </Pressable>
            </View>
            <ScrollView
              style={{ maxHeight: 480 }}
              showsVerticalScrollIndicator={false}
            >
              {entries.map(([k, v]) => (
                <View key={k} style={styles.rawRow}>
                  <Text style={styles.rawKey}>{k}</Text>
                  <Text style={styles.rawValue} selectable>
                    {v === null || v === undefined
                      ? '—'
                      : typeof v === 'object'
                      ? JSON.stringify(v, null, 2)
                      : String(v)}
                  </Text>
                </View>
              ))}
            </ScrollView>
          </GlassCard>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

// ── Main component ────────────────────────────────────────────────

const PAGE_SIZE = 20;

const DEFAULT_FILTERS = {
  signal_kinds: [],
  severity_kind: null,
  date_range: '30d',
  unread_only: false,
  search: '',
};

export default function ActivityFeed({ projectId, onUnreadCountChange }) {
  const { width } = useWindowDimensions();
  const isMobile = width < 768;
  const { colors, isDark } = useTheme();
  const styles = useMemo(() => buildStyles(colors, isDark), [colors, isDark]);
  const severityPalette = useMemo(() => buildSeverityPalette(colors), [colors]);

  const [logs, setLogs] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [skip, setSkip] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [filtersOpen, setFiltersOpen] = useState(!isMobile);
  const [rawModalLog, setRawModalLog] = useState(null);
  const [error, setError] = useState(null);

  const loadPage = useCallback(async ({ reset = false } = {}) => {
    if (!projectId) return;
    const useSkip = reset ? 0 : skip;
    if (reset) setLoading(true);
    setError(null);
    try {
      const params = {
        ...filters,
        limit: PAGE_SIZE,
        skip: useSkip,
      };
      const data = await dobAPI.getLogs(projectId, params);
      const newLogs = data.logs || [];
      setTotal(data.total || 0);
      setLogs((prev) => (reset ? newLogs : [...prev, ...newLogs]));
      setHasMore(useSkip + newLogs.length < (data.total || 0));
      if (reset) setSkip(newLogs.length);
      else setSkip((s) => s + newLogs.length);
      if (typeof onUnreadCountChange === 'function') {
        onUnreadCountChange(
          (data.logs || []).filter((l) => !l.is_read).length,
        );
      }
    } catch (e) {
      console.error('[ActivityFeed] load error:', e);
      setError(e?.response?.data?.detail || 'Could not load activity.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [projectId, filters, skip, onUnreadCountChange]);

  // Reset + refetch whenever filters change.
  useEffect(() => {
    loadPage({ reset: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    projectId,
    filters.date_range,
    filters.severity_kind,
    filters.unread_only,
    filters.search,
    JSON.stringify(filters.signal_kinds || []),
  ]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    loadPage({ reset: true });
  }, [loadPage]);

  const handleMarkRead = useCallback(async (log) => {
    try {
      await dobAPI.markRead(projectId, log.id);
      setLogs((prev) =>
        prev.map((l) => (l.id === log.id ? { ...l, is_read: true } : l)),
      );
    } catch (e) {
      console.error('[ActivityFeed] markRead error:', e);
    }
  }, [projectId]);

  const handleMarkAllRead = useCallback(async () => {
    try {
      await dobAPI.markAllRead(projectId);
      setLogs((prev) => prev.map((l) => ({ ...l, is_read: true })));
    } catch (e) {
      console.error('[ActivityFeed] markAllRead error:', e);
    }
  }, [projectId]);

  const visibleLogs = logs;
  const unreadCount = visibleLogs.filter((l) => !l.is_read).length;

  const filtersActive = useMemo(() => {
    return (
      (filters.signal_kinds || []).length > 0 ||
      !!filters.severity_kind ||
      filters.date_range !== '30d' ||
      filters.unread_only ||
      !!filters.search
    );
  }, [filters]);

  // Phase B3: empty-state copy. When no filters are active and the
  // feed is empty, this is most often a brand-new project waiting on
  // its first 15-min poll. The friendlier copy points the operator
  // at the right expectation rather than implying nothing has
  // happened.
  const emptyStateMsg = filtersActive
    ? 'No signals matching your filters.'
    : "We're monitoring DOB. Your first signals will appear within 15 minutes.";

  return (
    <View style={[styles.container, isMobile && styles.containerMobile]}>
      {/* Header bar — uppercase tracked label + counts */}
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={styles.headerLabel}>ACTIVITY</Text>
          <Text style={styles.headerSubtitle}>
            {total} signal{total === 1 ? '' : 's'}
            {unreadCount > 0 ? ` · ${unreadCount} unread` : ''}
          </Text>
        </View>
        <Pressable
          onPress={onRefresh}
          style={({ pressed }) => [
            styles.headerBtn,
            pressed && styles.headerBtnPressed,
          ]}
          accessibilityLabel="Refresh"
        >
          <RefreshCw size={14} color={colors.text.secondary} />
        </Pressable>
        {unreadCount > 0 ? (
          <Pressable
            onPress={handleMarkAllRead}
            style={({ pressed }) => [
              styles.headerBtn,
              styles.headerBtnPrimary,
              pressed && styles.headerBtnPressed,
            ]}
          >
            <CheckCheck size={14} color={colors.primary} />
            <Text style={[styles.headerBtnText, { color: colors.primary }]}>
              Mark all read
            </Text>
          </Pressable>
        ) : null}
        {isMobile ? (
          <Pressable
            onPress={() => setFiltersOpen(true)}
            style={({ pressed }) => [
              styles.headerBtn,
              pressed && styles.headerBtnPressed,
            ]}
            accessibilityLabel="Open filters"
          >
            <Filter size={14} color={colors.text.secondary} />
            <Text style={styles.headerBtnText}>Filters</Text>
          </Pressable>
        ) : null}
      </View>

      {error ? (
        <View style={styles.errorBanner}>
          <Text style={styles.errorText}>{error}</Text>
        </View>
      ) : null}

      <View style={[styles.body, isMobile && styles.bodyMobile]}>
        {/* Desktop: side panel */}
        {!isMobile ? (
          <FilterPanel
            filters={filters}
            onChange={setFilters}
            isMobile={false}
            styles={styles}
            colors={colors}
            severityPalette={severityPalette}
          />
        ) : null}

        {/* Feed */}
        <ScrollView
          style={styles.feed}
          contentContainerStyle={styles.feedContent}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={onRefresh}
              tintColor={colors.text.muted}
            />
          }
          onMomentumScrollEnd={(e) => {
            const { layoutMeasurement, contentOffset, contentSize } = e.nativeEvent;
            const padding = 80;
            if (
              hasMore &&
              !loading &&
              layoutMeasurement.height + contentOffset.y >= contentSize.height - padding
            ) {
              loadPage({ reset: false });
            }
          }}
        >
          {loading && visibleLogs.length === 0 ? (
            <View style={styles.loadingState}>
              <ActivityIndicator size="large" color={colors.primary} />
            </View>
          ) : visibleLogs.length === 0 ? (
            <View style={styles.emptyState}>
              <Info size={28} color={colors.text.muted} />
              <Text style={styles.emptyStateText}>{emptyStateMsg}</Text>
            </View>
          ) : (
            <>
              {visibleLogs.map((log) => (
                <SignalCard
                  key={log.id}
                  log={log}
                  onMarkRead={handleMarkRead}
                  onViewRaw={setRawModalLog}
                  styles={styles}
                  colors={colors}
                  severityPalette={severityPalette}
                />
              ))}
              {hasMore ? (
                <View style={styles.loadMoreRow}>
                  {loading ? (
                    <ActivityIndicator size="small" color={colors.text.muted} />
                  ) : (
                    <Text style={styles.loadMoreText}>Scroll for more…</Text>
                  )}
                </View>
              ) : null}
            </>
          )}
        </ScrollView>
      </View>

      {/* Mobile filter sheet */}
      {isMobile ? (
        <Modal
          visible={filtersOpen}
          animationType="slide"
          transparent
          onRequestClose={() => setFiltersOpen(false)}
        >
          <Pressable
            style={styles.modalOverlay}
            onPress={() => setFiltersOpen(false)}
            accessibilityRole="button"
          >
            <Pressable onPress={() => {}} style={styles.bottomSheetWrap}>
              <GlassCard variant="modal" style={styles.bottomSheet}>
                <FilterPanel
                  filters={filters}
                  onChange={setFilters}
                  onClose={() => setFiltersOpen(false)}
                  isMobile
                  styles={styles}
                  colors={colors}
                  severityPalette={severityPalette}
                />
              </GlassCard>
            </Pressable>
          </Pressable>
        </Modal>
      ) : null}

      {rawModalLog ? (
        <RawDataModal
          log={rawModalLog}
          onClose={() => setRawModalLog(null)}
          styles={styles}
          colors={colors}
        />
      ) : null}
    </View>
  );
}

// ── Styles ────────────────────────────────────────────────────────

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    container: {
      flex: 1,
      // Transparent so AnimatedBackground (mounted by the route
      // shell) shows through. Matches the chrome of every other
      // page in the app.
      backgroundColor: 'transparent',
    },
    containerMobile: {
      paddingHorizontal: 0,
    },

    // ── Header ───────────────────────────────────────────────────
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.md,
      borderBottomWidth: 1,
      borderBottomColor: colors.glass.border,
      backgroundColor: 'transparent',
      gap: spacing.sm,
    },
    headerLabel: {
      ...typography.label,
      color: colors.text.muted,
    },
    headerSubtitle: {
      fontSize: 12,
      color: colors.text.muted,
      marginTop: 4,
    },
    headerBtn: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      paddingHorizontal: spacing.sm + 2,
      paddingVertical: 6,
      borderRadius: borderRadius.sm,
      borderWidth: 1,
      borderColor: colors.glass.border,
      backgroundColor: colors.glass.background,
    },
    headerBtnPrimary: {
      backgroundColor: 'rgba(59, 130, 246, 0.10)',
      borderColor: 'rgba(59, 130, 246, 0.40)',
    },
    headerBtnPressed: {
      opacity: 0.7,
      transform: [{ scale: 0.98 }],
    },
    headerBtnText: {
      fontSize: 12,
      color: colors.text.secondary,
      fontWeight: '500',
    },

    // ── Body / layout ────────────────────────────────────────────
    body: {
      flex: 1,
      flexDirection: 'row',
    },
    bodyMobile: {
      flexDirection: 'column',
    },
    feed: {
      flex: 1,
    },
    feedContent: {
      padding: spacing.md,
      gap: spacing.md,
    },

    // ── Filter panel ─────────────────────────────────────────────
    filterPanel: {
      width: 300,
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.md,
      borderRightWidth: 1,
      borderRightColor: colors.glass.border,
      backgroundColor: 'transparent',
    },
    filterPanelMobile: {
      width: '100%',
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.lg,
      borderRightWidth: 0,
    },
    filterHeader: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: spacing.md,
    },
    filterTitle: {
      fontSize: 18,
      fontWeight: '500',
      color: colors.text.primary,
    },
    filterSectionLabel: {
      ...typography.label,
      color: colors.text.muted,
      marginTop: spacing.lg,
      marginBottom: spacing.sm,
    },

    // ── Search ───────────────────────────────────────────────────
    searchRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.sm + 2,
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.md,
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    searchInput: {
      flex: 1,
      fontSize: 14,
      color: colors.text.primary,
      paddingVertical: 0,
      // RN web: outline ring on focus would clash with the glass
      // border. The input borrows the parent's border instead.
      outlineStyle: 'none',
    },

    // ── Pills / chips ────────────────────────────────────────────
    pillRow: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: 6,
    },
    pill: {
      paddingHorizontal: spacing.sm + 2,
      paddingVertical: 6,
      borderRadius: borderRadius.full,
      backgroundColor: colors.glass.background,
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    pillActive: {
      backgroundColor: 'rgba(59, 130, 246, 0.12)',
      borderColor: colors.primary,
    },
    pillText: {
      fontSize: 12,
      color: colors.text.secondary,
    },
    pillTextActive: {
      color: colors.primary,
      fontWeight: '600',
    },

    // ── Unread toggle ────────────────────────────────────────────
    unreadToggle: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
      marginTop: spacing.md,
    },
    checkbox: {
      width: 18,
      height: 18,
      borderRadius: 4,
      borderWidth: 1.5,
      borderColor: colors.border?.medium || colors.glass.border,
      alignItems: 'center',
      justifyContent: 'center',
    },
    checkboxActive: {
      backgroundColor: colors.primary,
      borderColor: colors.primary,
    },
    unreadToggleText: {
      fontSize: 13,
      color: colors.text.secondary,
    },
    kindGroup: {
      marginTop: spacing.sm,
    },
    kindGroupHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      marginBottom: 4,
    },
    kindGroupLabel: {
      fontSize: 11,
      color: colors.text.muted,
      fontWeight: '500',
    },

    // ── Signal card ──────────────────────────────────────────────
    card: {
      // GlassCard handles padding via its cardContent rule
      // (default: spacing.xl). Override with a tighter pad so the
      // feed shows more cards per viewport without feeling cramped.
      // The GlassCard component still renders the gradient + blur
      // layers underneath.
      padding: 0,
      // The leading severity stripe is a 3px left border, applied
      // here on the outer card. GlassCard's content padding is
      // unaffected.
      borderTopLeftRadius: borderRadius.xxl,
      borderBottomLeftRadius: borderRadius.xxl,
    },
    cardRead: {
      opacity: 0.65,
    },
    cardHeader: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: spacing.sm + 2,
      marginBottom: spacing.sm,
    },
    iconBubble: {
      width: 32,
      height: 32,
      borderRadius: borderRadius.full,
      borderWidth: 1,
      alignItems: 'center',
      justifyContent: 'center',
    },
    cardHeaderText: {
      flex: 1,
    },
    cardTitle: {
      fontSize: 14,
      fontWeight: '600',
      color: colors.text.primary,
      lineHeight: 19,
    },
    cardMeta: {
      fontSize: 11,
      color: colors.text.muted,
      marginTop: 3,
    },
    unreadDot: {
      width: 8,
      height: 8,
      borderRadius: 4,
      marginTop: 6,
    },
    cardBody: {
      fontSize: 13,
      color: colors.text.secondary,
      lineHeight: 19,
      marginBottom: spacing.sm,
    },
    textMuted: {
      color: colors.text.muted,
    },
    actionToggle: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      marginVertical: 4,
      alignSelf: 'flex-start',
    },
    actionToggleText: {
      fontSize: 12,
      fontWeight: '500',
    },
    actionPanel: {
      padding: spacing.sm + 2,
      borderRadius: borderRadius.md,
      marginVertical: spacing.xs,
      borderWidth: 1,
    },
    actionPanelText: {
      fontSize: 13,
      color: colors.text.primary,
      lineHeight: 18,
    },
    cardActions: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
      marginTop: spacing.sm,
      paddingTop: spacing.sm,
      borderTopWidth: 1,
      borderTopColor: colors.glass.border,
    },
    cardActionBtn: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
    },
    cardActionBtnEnd: {
      marginLeft: 'auto',
    },
    cardActionText: {
      fontSize: 12,
      color: colors.text.muted,
    },

    // ── Loading / empty states ───────────────────────────────────
    loadingState: {
      paddingVertical: 60,
      alignItems: 'center',
    },
    emptyState: {
      paddingVertical: 60,
      alignItems: 'center',
      gap: spacing.sm + 4,
    },
    emptyStateText: {
      fontSize: 14,
      color: colors.text.muted,
      textAlign: 'center',
      paddingHorizontal: spacing.xl,
      lineHeight: 20,
    },
    loadMoreRow: {
      paddingVertical: spacing.md,
      alignItems: 'center',
    },
    loadMoreText: {
      fontSize: 12,
      color: colors.text.muted,
    },
    errorBanner: {
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.sm + 2,
      backgroundColor: colors.status?.errorBg || 'rgba(239, 68, 68, 0.10)',
      borderBottomWidth: 1,
      borderBottomColor: `${colors.error}40`,
    },
    errorText: {
      fontSize: 13,
      color: colors.error,
    },

    // ── Modal ────────────────────────────────────────────────────
    modalOverlay: {
      flex: 1,
      backgroundColor: 'rgba(0, 0, 0, 0.55)',
      justifyContent: 'flex-end',
      alignItems: 'center',
      padding: spacing.md,
    },
    bottomSheetWrap: {
      width: '100%',
      maxWidth: 720,
      maxHeight: '85%',
    },
    bottomSheet: {
      // GlassCard renders the surface; the inner FilterPanel
      // ScrollView paints the content.
      padding: 0,
    },
    modalCard: {
      // For the raw-data modal — GlassCard variant="modal" wraps
      // the content in a blurred glass surface, theme-aware.
      padding: 0,
      maxHeight: '85%',
    },
    modalHeader: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.md,
      borderBottomWidth: 1,
      borderBottomColor: colors.glass.border,
    },
    modalTitle: {
      fontSize: 16,
      fontWeight: '500',
      color: colors.text.primary,
    },
    rawRow: {
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.sm + 2,
      borderBottomWidth: 1,
      borderBottomColor: colors.glass.border,
    },
    rawKey: {
      ...typography.label,
      fontSize: 10,
      color: colors.text.muted,
    },
    rawValue: {
      fontSize: 13,
      color: colors.text.primary,
      marginTop: 4,
      fontFamily: 'monospace',
      lineHeight: 18,
    },
  });
}
