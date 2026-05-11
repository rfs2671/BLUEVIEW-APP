/**
 * V2.3 Commit 7 — In-app notifications list component.
 *
 * Renders a project's notifications inbox. Used in two modes:
 *
 *   mode="inline" — shows up to 3 most recent unread items + a
 *     "See all →" link. Embedded on the project page directly
 *     so operators see fresh predictions without leaving the page.
 *
 *   mode="full" — paginated list view with mark-all-read button
 *     and unread-only toggle. Used on the standalone route at
 *     /project/[id]/notifications.
 *
 * Polling: when mode="inline", parent receives the unread count
 * via the onUnreadCountChange callback so it can render a badge
 * (mirrors the ActivityFeed.jsx pattern). The component itself
 * does not poll — the parent decides cadence. The standalone
 * route does no polling (it's a leaf page; operator refreshes
 * by navigating back).
 *
 * Patterns adopted from ActivityFeed.jsx:
 *   • GlassCard for each item card + the empty/loading state
 *   • Severity-driven icon + color (info / warning / critical)
 *   • Mark-read on click + deeplink follow
 *   • Pull-to-refresh in full mode
 *
 * Props:
 *   projectId: string (required)
 *   mode: "inline" | "full" (default "inline")
 *   onUnreadCountChange?: (count: number) => void
 *   onSeeAll?: () => void  (inline mode only — router.push hook)
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  RefreshControl,
} from 'react-native';
import {
  AlertTriangle,
  AlertCircle,
  Info,
  Bell,
  ChevronRight,
  CheckCheck,
} from 'lucide-react-native';
import { GlassCard } from './GlassCard';
import { useTheme } from '../context/ThemeContext';
import { spacing, borderRadius, typography } from '../styles/theme';
import { notificationsAPI } from '../utils/api';

const SEVERITY_ICONS = {
  critical: AlertCircle,
  warning: AlertTriangle,
  info: Info,
};

const SEVERITY_COLORS = {
  critical: '#f87171',
  warning: '#fbbf24',
  info: '#94a3b8',
};

const INLINE_PREVIEW_COUNT = 3;

function _relativeTime(isoOrDate) {
  if (!isoOrDate) return '';
  const t = typeof isoOrDate === 'string'
    ? new Date(isoOrDate)
    : isoOrDate;
  const ms = Date.now() - t.getTime();
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return 'just now';
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day}d ago`;
  return t.toLocaleDateString();
}

export default function NotificationsList({
  projectId,
  mode = 'inline',
  onUnreadCountChange,
  onSeeAll,
}) {
  const { colors } = useTheme();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [unreadOnly, setUnreadOnly] = useState(mode === 'inline');
  const [error, setError] = useState(null);

  const fetchItems = useCallback(async () => {
    if (!projectId) return;
    setError(null);
    try {
      const limit = mode === 'inline' ? INLINE_PREVIEW_COUNT : 50;
      const data = await notificationsAPI.list({
        projectId,
        unreadOnly,
        limit,
      });
      setItems(data.items || []);
      // Report unread count to parent for badge display.
      if (onUnreadCountChange) {
        const countData = await notificationsAPI.unreadCount({ projectId });
        onUnreadCountChange(countData.count || 0);
      }
    } catch (e) {
      setError(e?.response?.data?.detail || 'Failed to load notifications');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [projectId, mode, unreadOnly, onUnreadCountChange]);

  useEffect(() => {
    setLoading(true);
    fetchItems();
  }, [fetchItems]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    fetchItems();
  }, [fetchItems]);

  const handleMarkRead = useCallback(async (item) => {
    if (item.read_at) return;
    try {
      await notificationsAPI.markRead(item.id || item._id);
      // Optimistic local update.
      setItems((prev) => prev.map((n) =>
        (n.id || n._id) === (item.id || item._id)
          ? { ...n, read_at: new Date().toISOString() }
          : n,
      ));
      if (onUnreadCountChange) {
        const countData = await notificationsAPI.unreadCount({ projectId });
        onUnreadCountChange(countData.count || 0);
      }
    } catch (e) {
      // Best-effort; failure logged but doesn't break the click.
      console.warn('[notifications] markRead failed:', e);
    }
  }, [projectId, onUnreadCountChange]);

  const handleMarkAllRead = useCallback(async () => {
    try {
      await notificationsAPI.markAllRead({ projectId });
      await fetchItems();
    } catch (e) {
      setError('Failed to mark all read');
    }
  }, [projectId, fetchItems]);

  const styles = useMemo(() => _makeStyles(colors), [colors]);

  // ── Loading / empty / error states ──────────────────────────

  if (loading && !refreshing) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="small" color={colors.text.secondary} />
      </View>
    );
  }

  if (error) {
    return (
      <GlassCard style={styles.errorCard}>
        <Text style={[styles.errorText, { color: colors.status.critical }]}>
          {error}
        </Text>
      </GlassCard>
    );
  }

  if (items.length === 0) {
    return (
      <GlassCard style={styles.emptyCard}>
        <Bell size={20} color={colors.text.secondary} />
        <Text style={[styles.emptyText, { color: colors.text.secondary }]}>
          {unreadOnly ? 'No unread notifications' : 'No notifications yet'}
        </Text>
      </GlassCard>
    );
  }

  // ── Inline preview (max 3) ──────────────────────────────────

  if (mode === 'inline') {
    return (
      <View style={styles.container}>
        {items.map((item) => (
          <NotificationItem
            key={item.id || item._id}
            item={item}
            colors={colors}
            onPress={() => handleMarkRead(item)}
          />
        ))}
        {onSeeAll && (
          <Pressable onPress={onSeeAll} style={styles.seeAll}>
            <Text style={[styles.seeAllText, { color: colors.text.secondary }]}>
              See all notifications
            </Text>
            <ChevronRight size={16} color={colors.text.secondary} />
          </Pressable>
        )}
      </View>
    );
  }

  // ── Full mode ───────────────────────────────────────────────

  return (
    <ScrollView
      style={styles.container}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
      }
    >
      <View style={styles.header}>
        <Pressable
          onPress={() => setUnreadOnly((u) => !u)}
          style={styles.toggle}
        >
          <Text style={[styles.toggleText, { color: colors.text.primary }]}>
            {unreadOnly ? 'Showing unread' : 'Showing all'}
          </Text>
        </Pressable>
        <Pressable onPress={handleMarkAllRead} style={styles.markAll}>
          <CheckCheck size={16} color={colors.text.secondary} />
          <Text style={[styles.markAllText, { color: colors.text.secondary }]}>
            Mark all read
          </Text>
        </Pressable>
      </View>

      {items.map((item) => (
        <NotificationItem
          key={item.id || item._id}
          item={item}
          colors={colors}
          onPress={() => handleMarkRead(item)}
        />
      ))}
    </ScrollView>
  );
}


function NotificationItem({ item, colors, onPress }) {
  const Icon = SEVERITY_ICONS[item.severity] || Info;
  const tint = SEVERITY_COLORS[item.severity] || SEVERITY_COLORS.info;
  const isUnread = !item.read_at;
  const styles = _makeStyles(colors);
  return (
    <Pressable onPress={onPress}>
      <GlassCard
        style={[styles.itemCard, isUnread && styles.itemCardUnread]}
      >
        <View style={styles.itemRow}>
          <Icon size={18} color={tint} />
          <View style={styles.itemBody}>
            <Text
              style={[
                styles.itemTitle,
                { color: colors.text.primary },
                isUnread && styles.itemTitleUnread,
              ]}
            >
              {item.title}
            </Text>
            <Text style={[styles.itemMessage, { color: colors.text.primary }]}>
              {item.message}
            </Text>
            <Text style={[styles.itemMeta, { color: colors.text.secondary }]}>
              {_relativeTime(item.created_at)}
              {isUnread ? ' • Unread' : ''}
            </Text>
          </View>
        </View>
      </GlassCard>
    </Pressable>
  );
}


function _makeStyles(colors) {
  return StyleSheet.create({
    container: {
      gap: spacing.sm,
    },
    centered: {
      padding: spacing.lg,
      alignItems: 'center',
    },
    errorCard: {
      padding: spacing.md,
    },
    errorText: {
      ...typography.body,
    },
    emptyCard: {
      padding: spacing.md,
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
    },
    emptyText: {
      ...typography.body,
    },
    header: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      paddingHorizontal: spacing.sm,
      paddingVertical: spacing.xs,
    },
    toggle: {
      padding: spacing.xs,
    },
    toggleText: {
      ...typography.label,
    },
    markAll: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.xs,
      padding: spacing.xs,
    },
    markAllText: {
      ...typography.label,
    },
    itemCard: {
      padding: spacing.md,
      marginBottom: spacing.xs,
    },
    itemCardUnread: {
      borderColor: 'rgba(96, 165, 250, 0.35)',
      borderWidth: 1,
    },
    itemRow: {
      flexDirection: 'row',
      gap: spacing.sm,
      alignItems: 'flex-start',
    },
    itemBody: {
      flex: 1,
      gap: spacing.xxs || 2,
    },
    itemTitle: {
      ...typography.label,
      marginBottom: 2,
    },
    itemTitleUnread: {
      fontWeight: '700',
    },
    itemMessage: {
      ...typography.body,
    },
    itemMeta: {
      ...typography.caption || typography.label,
      fontSize: 12,
      marginTop: 4,
    },
    seeAll: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      padding: spacing.sm,
      gap: spacing.xs,
    },
    seeAllText: {
      ...typography.label,
    },
  });
}
