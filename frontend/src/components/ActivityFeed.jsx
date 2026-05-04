/**
 * MR.14 commit 3 — Activity feed component.
 *
 * Renders the v1 monitoring product's signal stream for a single
 * project. Reads from GET /api/projects/{id}/dob-logs (server-side
 * rendered via lib.dob_signal_templates) so all template logic
 * lives backend-side; this component is a pure renderer + filter
 * controller.
 *
 * Mobile + desktop responsive. Filter panel collapses to a bottom
 * sheet on narrow viewports.
 *
 * Props:
 *   projectId: string (required)
 *   onUnreadCountChange?: (count: number) => void  // hook for badges
 *
 * The component owns its own data fetching. Parent passes projectId
 * and optionally subscribes to unread-count changes for header
 * badges / nav decoration.
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
  CheckCircle,
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
import { dobAPI } from '../utils/api';

// ── Severity-coded styling ────────────────────────────────────────

const SEVERITY_STYLES = {
  critical: {
    color: '#ef4444',
    bg: 'rgba(239, 68, 68, 0.08)',
    border: 'rgba(239, 68, 68, 0.3)',
    label: 'Critical',
    Icon: AlertTriangle,
  },
  warning: {
    color: '#f59e0b',
    bg: 'rgba(245, 158, 11, 0.08)',
    border: 'rgba(245, 158, 11, 0.3)',
    label: 'Warning',
    Icon: AlertTriangle,
  },
  info: {
    color: '#3b82f6',
    bg: 'rgba(59, 130, 246, 0.08)',
    border: 'rgba(59, 130, 246, 0.3)',
    label: 'Info',
    Icon: Info,
  },
};

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

function SignalCard({ log, onMarkRead, onViewRaw }) {
  const [expanded, setExpanded] = useState(false);
  const sev = SEVERITY_STYLES[log.severity_kind] || SEVERITY_STYLES.info;
  const SevIcon = sev.Icon;
  const isRead = !!log.is_read;

  return (
    <View style={[
      styles.card,
      { borderLeftColor: sev.color },
      isRead && styles.cardRead,
    ]}>
      <View style={styles.cardHeader}>
        <View style={[styles.iconBubble, { backgroundColor: sev.bg }]}>
          <SevIcon size={18} color={sev.color} />
        </View>
        <View style={styles.cardHeaderText}>
          <Text style={[styles.cardTitle, isRead && styles.textMuted]} numberOfLines={2}>
            {log.title || log.ai_summary || 'DOB record'}
          </Text>
          <Text style={styles.cardMeta}>
            {formatRelativeTime(log.status_changed_at || log.detected_at)}
            {log.signal_kind ? ` · ${humanizeKind(log.signal_kind)}` : ''}
          </Text>
        </View>
        {!isRead && <View style={[styles.unreadDot, { backgroundColor: sev.color }]} />}
      </View>

      {log.body ? (
        <Text style={[styles.cardBody, isRead && styles.textMuted]} numberOfLines={3}>
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
          {expanded ? <ChevronUp size={14} color={sev.color} /> : <ChevronDown size={14} color={sev.color} />}
        </Pressable>
      ) : null}
      {expanded && log.action_text ? (
        <View style={[styles.actionPanel, { backgroundColor: sev.bg }]}>
          <Text style={styles.actionPanelText}>{log.action_text}</Text>
        </View>
      ) : null}

      <View style={styles.cardActions}>
        {log.dob_link ? (
          <Pressable
            onPress={() => Linking.openURL(log.dob_link).catch(() => {})}
            style={styles.cardActionBtn}
          >
            <ExternalLink size={14} color="#64748b" />
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
            <Eye size={14} color="#64748b" />
            <Text style={styles.cardActionText}>Mark read</Text>
          </Pressable>
        ) : (
          <View style={[styles.cardActionBtn, styles.cardActionBtnEnd]}>
            <EyeOff size={14} color="#94a3b8" />
            <Text style={[styles.cardActionText, styles.textMuted]}>Read</Text>
          </View>
        )}
      </View>
    </View>
  );
}

// ── Filter panel ──────────────────────────────────────────────────

function FilterPanel({ filters, onChange, onClose, isMobile }) {
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

  const setDateRange = (dr) => {
    onChange({ ...filters, date_range: dr });
  };

  const toggleUnreadOnly = () => {
    onChange({ ...filters, unread_only: !filters.unread_only });
  };

  const applySearch = () => {
    onChange({ ...filters, search: search.trim() });
  };

  return (
    <ScrollView
      style={[styles.filterPanel, isMobile && styles.filterPanelMobile]}
      contentContainerStyle={{ paddingBottom: 32 }}
    >
      <View style={styles.filterHeader}>
        <Text style={styles.filterTitle}>Filters</Text>
        {onClose ? (
          <Pressable onPress={onClose} accessibilityRole="button">
            <X size={20} color="#64748b" />
          </Pressable>
        ) : null}
      </View>

      <Text style={styles.filterSectionLabel}>Search</Text>
      <View style={styles.searchRow}>
        <Search size={16} color="#94a3b8" />
        <TextInput
          style={styles.searchInput}
          value={search}
          onChangeText={setSearch}
          onSubmitEditing={applySearch}
          onBlur={applySearch}
          placeholder="Search title or body…"
          placeholderTextColor="#94a3b8"
          returnKeyType="search"
        />
      </View>

      <Text style={styles.filterSectionLabel}>Date range</Text>
      <View style={styles.pillRow}>
        {DATE_RANGE_OPTIONS.map((opt) => (
          <Pressable
            key={opt.value}
            onPress={() => setDateRange(opt.value)}
            style={[
              styles.pill,
              filters.date_range === opt.value && styles.pillActive,
            ]}
          >
            <Text style={[
              styles.pillText,
              filters.date_range === opt.value && styles.pillTextActive,
            ]}>{opt.label}</Text>
          </Pressable>
        ))}
      </View>

      <Text style={styles.filterSectionLabel}>Severity</Text>
      <View style={styles.pillRow}>
        {['critical', 'warning', 'info'].map((sk) => {
          const active = filters.severity_kind === sk;
          const sev = SEVERITY_STYLES[sk];
          return (
            <Pressable
              key={sk}
              onPress={() => setSeverityKind(sk)}
              style={[
                styles.pill,
                active && { backgroundColor: sev.bg, borderColor: sev.color },
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
        <View style={[styles.checkbox, filters.unread_only && styles.checkboxActive]}>
          {filters.unread_only ? <CheckCheck size={12} color="#fff" /> : null}
        </View>
        <Text style={styles.unreadToggleText}>Show unread only</Text>
      </Pressable>

      <Text style={styles.filterSectionLabel}>Signal type</Text>
      {SIGNAL_KIND_GROUPS.map((group) => (
        <View key={group.label} style={styles.kindGroup}>
          <Text style={styles.kindGroupLabel}>{group.label}</Text>
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

function RawDataModal({ log, onClose }) {
  if (!log) return null;
  // Show all top-level keys + values, prettified.
  const entries = Object.entries(log).filter(([k]) => !k.startsWith('_'));
  return (
    <Modal visible animationType="slide" transparent onRequestClose={onClose}>
      <View style={styles.modalOverlay}>
        <View style={styles.modalCard}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>Raw DOB record</Text>
            <Pressable onPress={onClose} accessibilityRole="button">
              <X size={20} color="#64748b" />
            </Pressable>
          </View>
          <ScrollView style={{ maxHeight: 480 }}>
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
        </View>
      </View>
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
        prev.map((l) =>
          l.id === log.id ? { ...l, is_read: true } : l,
        ),
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

  // Empty-state messaging.
  const filtersActive = useMemo(() => {
    return (
      (filters.signal_kinds || []).length > 0 ||
      !!filters.severity_kind ||
      filters.date_range !== '30d' ||
      filters.unread_only ||
      !!filters.search
    );
  }, [filters]);

  const emptyStateMsg = filtersActive
    ? 'No signals matching your filters.'
    : "No activity in the past 30 days. We're monitoring DOB for changes.";

  return (
    <View style={[styles.container, isMobile && styles.containerMobile]}>
      {/* Header bar */}
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={styles.headerTitle}>Activity</Text>
          <Text style={styles.headerSubtitle}>
            {total} signal{total === 1 ? '' : 's'}
            {unreadCount > 0 ? ` · ${unreadCount} unread` : ''}
          </Text>
        </View>
        <Pressable onPress={onRefresh} style={styles.headerBtn} accessibilityLabel="Refresh">
          <RefreshCw size={16} color="#64748b" />
        </Pressable>
        {unreadCount > 0 ? (
          <Pressable onPress={handleMarkAllRead} style={styles.headerBtn}>
            <CheckCheck size={14} color="#3b82f6" />
            <Text style={styles.headerBtnText}>Mark all read</Text>
          </Pressable>
        ) : null}
        {isMobile ? (
          <Pressable
            onPress={() => setFiltersOpen(true)}
            style={styles.headerBtn}
            accessibilityLabel="Open filters"
          >
            <Filter size={16} color="#64748b" />
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
          />
        ) : null}

        {/* Feed */}
        <ScrollView
          style={styles.feed}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
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
              <ActivityIndicator size="large" color="#3b82f6" />
            </View>
          ) : visibleLogs.length === 0 ? (
            <View style={styles.emptyState}>
              <Info size={28} color="#94a3b8" />
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
                />
              ))}
              {hasMore ? (
                <View style={styles.loadMoreRow}>
                  {loading ? (
                    <ActivityIndicator size="small" color="#94a3b8" />
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
          <View style={styles.modalOverlay}>
            <View style={styles.bottomSheet}>
              <FilterPanel
                filters={filters}
                onChange={setFilters}
                onClose={() => setFiltersOpen(false)}
                isMobile
              />
            </View>
          </View>
        </Modal>
      ) : null}

      {rawModalLog ? (
        <RawDataModal log={rawModalLog} onClose={() => setRawModalLog(null)} />
      ) : null}
    </View>
  );
}

// ── Styles ────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f8fafc',
  },
  containerMobile: {
    paddingHorizontal: 0,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#e2e8f0',
    backgroundColor: '#ffffff',
    gap: 8,
  },
  headerTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: '#0f172a',
  },
  headerSubtitle: {
    fontSize: 12,
    color: '#64748b',
    marginTop: 2,
  },
  headerBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 6,
    backgroundColor: '#f1f5f9',
  },
  headerBtnText: {
    fontSize: 12,
    color: '#475569',
    fontWeight: '500',
  },
  body: {
    flex: 1,
    flexDirection: 'row',
  },
  bodyMobile: {
    flexDirection: 'column',
  },
  feed: {
    flex: 1,
    padding: 12,
  },
  filterPanel: {
    width: 280,
    paddingHorizontal: 16,
    paddingVertical: 16,
    backgroundColor: '#ffffff',
    borderRightWidth: 1,
    borderRightColor: '#e2e8f0',
  },
  filterPanelMobile: {
    width: '100%',
    paddingHorizontal: 16,
    borderRightWidth: 0,
  },
  filterHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  filterTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#0f172a',
  },
  filterSectionLabel: {
    fontSize: 11,
    color: '#64748b',
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginTop: 16,
    marginBottom: 8,
  },
  searchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 10,
    paddingVertical: 8,
    backgroundColor: '#f1f5f9',
    borderRadius: 6,
  },
  searchInput: {
    flex: 1,
    fontSize: 14,
    color: '#0f172a',
    paddingVertical: 0,
  },
  pillRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
  },
  pill: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 14,
    backgroundColor: '#f1f5f9',
    borderWidth: 1,
    borderColor: 'transparent',
  },
  pillActive: {
    backgroundColor: 'rgba(59, 130, 246, 0.1)',
    borderColor: 'rgba(59, 130, 246, 0.3)',
  },
  pillText: {
    fontSize: 12,
    color: '#475569',
  },
  pillTextActive: {
    color: '#1d4ed8',
    fontWeight: '600',
  },
  unreadToggle: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginTop: 16,
  },
  checkbox: {
    width: 16,
    height: 16,
    borderRadius: 4,
    borderWidth: 1.5,
    borderColor: '#cbd5e1',
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkboxActive: {
    backgroundColor: '#3b82f6',
    borderColor: '#3b82f6',
  },
  unreadToggleText: {
    fontSize: 13,
    color: '#475569',
  },
  kindGroup: {
    marginTop: 8,
  },
  kindGroupLabel: {
    fontSize: 11,
    color: '#94a3b8',
    fontWeight: '500',
    marginBottom: 4,
  },
  card: {
    backgroundColor: '#ffffff',
    padding: 14,
    marginBottom: 10,
    borderRadius: 8,
    borderLeftWidth: 4,
    borderColor: '#e2e8f0',
    borderWidth: StyleSheet.hairlineWidth,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.04,
    shadowRadius: 2,
    elevation: 1,
  },
  cardRead: {
    opacity: 0.7,
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    marginBottom: 8,
  },
  iconBubble: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  cardHeaderText: {
    flex: 1,
  },
  cardTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#0f172a',
    lineHeight: 18,
  },
  cardMeta: {
    fontSize: 11,
    color: '#94a3b8',
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
    color: '#475569',
    lineHeight: 18,
    marginBottom: 8,
  },
  textMuted: {
    color: '#94a3b8',
  },
  actionToggle: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    marginVertical: 4,
  },
  actionToggleText: {
    fontSize: 12,
    fontWeight: '500',
  },
  actionPanel: {
    padding: 10,
    borderRadius: 6,
    marginVertical: 4,
  },
  actionPanelText: {
    fontSize: 13,
    color: '#0f172a',
    lineHeight: 17,
  },
  cardActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginTop: 8,
    paddingTop: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#e2e8f0',
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
    color: '#64748b',
  },
  loadingState: {
    paddingVertical: 60,
    alignItems: 'center',
  },
  emptyState: {
    paddingVertical: 60,
    alignItems: 'center',
    gap: 12,
  },
  emptyStateText: {
    fontSize: 14,
    color: '#64748b',
    textAlign: 'center',
    paddingHorizontal: 40,
  },
  loadMoreRow: {
    paddingVertical: 16,
    alignItems: 'center',
  },
  loadMoreText: {
    fontSize: 12,
    color: '#94a3b8',
  },
  errorBanner: {
    paddingHorizontal: 16,
    paddingVertical: 10,
    backgroundColor: 'rgba(239, 68, 68, 0.08)',
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(239, 68, 68, 0.3)',
  },
  errorText: {
    fontSize: 13,
    color: '#ef4444',
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'flex-end',
  },
  bottomSheet: {
    maxHeight: '80%',
    backgroundColor: '#ffffff',
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    paddingTop: 8,
  },
  modalCard: {
    margin: 24,
    backgroundColor: '#ffffff',
    borderRadius: 12,
    overflow: 'hidden',
    maxHeight: '80%',
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#e2e8f0',
  },
  modalTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#0f172a',
  },
  rawRow: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#e2e8f0',
  },
  rawKey: {
    fontSize: 11,
    color: '#64748b',
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  rawValue: {
    fontSize: 13,
    color: '#0f172a',
    marginTop: 2,
    fontFamily: 'monospace',
  },
});
