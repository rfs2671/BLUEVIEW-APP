import React, { useState, useMemo, useEffect } from 'react';
import { View, Text, Pressable, StyleSheet } from 'react-native';
import { ChevronUp, ChevronDown, MoreVertical, Trash2, Eye } from 'lucide-react-native';
import apiClient from '../utils/api';
import { semantic, chrome, border, surface, text } from '../styles/semanticColors';
import { spacing, borderRadius, typography } from '../styles/theme';

/**
 * ProjectsTable — desktop-only (>=1024) compliance TRIAGE table for a NYC GC.
 *
 * Mobile is untouched: projects/index.jsx branches on useIsDesktop() and still
 * renders its existing card list below the breakpoint.
 *
 * Reads standing exposure from ONE portfolio-wide GET /api/projects/dob-summary
 * (by_project: open_violations / open_complaints / permits_expiring) — no N+1
 * per-row call. Class + BIN are demoted to the row overflow menu (reference,
 * not triage). The risk-score column was removed (score shelved).
 *
 * SYNCED column now reads last_dob_sync_at — a ROLLING timestamp written by
 * run_dob_sync_for_project on every successful sync, so a real relative time
 * ("4m", "3d") is honest. This replaces first_poll_completed_at, which is
 * stamped ONCE on the first poll and never updated, and therefore answered
 * "has this ever synced?" rather than "how fresh is this?".
 *
 * A project with no last_dob_sync_at has not completed a sync since the field
 * shipped; it reads "Never" until its next nightly/manual run stamps it.
 */

const CLASS_LABEL = { major_b: 'MAJOR B', major_a: 'MAJOR A', regular: 'REGULAR' };

// Column flex + alignment — shared by header + row cells so they can't drift.
const COLUMNS = [
  { key: 'address', label: 'Address', flex: 3, numeric: false, align: 'flex-start' },
  { key: 'violations', label: 'Violations', flex: 1.2, numeric: true, align: 'center' },
  // "Expiring", not "Permits": this cell is expiring-within-30d over ACTIVE
  // permits — a different subset relationship than the open-of-total used by
  // violations and complaints. Under a "Permits" header, "0 of 5" still reads
  // as "0 of 5 permits are active".
  { key: 'permits', label: 'Expiring', flex: 1.5, numeric: true, align: 'center' },
  { key: 'complaints', label: 'Complaints', flex: 1.3, numeric: true, align: 'center' },
  { key: 'synced', label: 'Synced', flex: 1.1, numeric: true, align: 'center' },
];
const FLEX = Object.fromEntries(COLUMNS.map((c) => [c.key, c.flex]));

const projectId = (p) => p._id || p.id;
const addrOf = (p) => p.address || p.name || '';
const syncedAt = (p) => {
  const t = p.last_dob_sync_at ? new Date(p.last_dob_sync_at).getTime() : NaN;
  return Number.isNaN(t) ? null : t;
};
const hasSynced = (p) => syncedAt(p) !== null;

// Coarse relative age — the column is ~90px, so one unit is all that fits.
// Deliberately not "just now": a sync that landed seconds ago still reads "0m",
// which is precise without implying live streaming.
const relAge = (ms) => {
  const mins = Math.max(0, Math.floor((Date.now() - ms) / 60000));
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  const days = Math.floor(hrs / 24);
  return days < 365 ? `${days}d` : `${Math.floor(days / 365)}y`;
};

export default function ProjectsTable({ projects, onRowPress, onDelete }) {
  // Default: exposure-descending — open_violations, then permits_expiring, then
  // open_complaints (all desc). The "violations" comparator IS that composite,
  // so the Violations header reads as active by default.
  const [sortKey, setSortKey] = useState('violations');
  const [sortDir, setSortDir] = useState('desc');
  const [menuFor, setMenuFor] = useState(null);
  const [summary, setSummary] = useState({}); // by_project keyed by project_id

  // ── ONE portfolio-wide dob-summary call — no N+1. ─────────────────────────
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await apiClient.get('/api/projects/dob-summary');
        if (!cancelled) setSummary(r?.data?.by_project || {});
      } catch (_e) {
        if (!cancelled) setSummary({}); // degrade to zeros, never an error toast
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const expo = (p) => {
    const s = summary[projectId(p)] || {};
    return {
      ov: Number(s.open_violations) || 0,
      pe: Number(s.permits_expiring) || 0,
      oc: Number(s.open_complaints) || 0,
      // Denominators for the "{subset} of {total}" cells. Without them a
      // project with 5 active permits and 0 expiring rendered a bare "0" —
      // read as "no permits", the opposite of the truth. Same numbers and
      // same wording as the project page's DOB tiles (dob-logs.jsx ofText).
      tv: Number(s.total_violations) || 0,
      tp: Number(s.total_permits) || 0,
      tc: Number(s.total_complaints) || 0,
    };
  };

  const sorted = useMemo(() => {
    const mul = sortDir === 'asc' ? 1 : -1;
    const byNums = (a, b, keys) => {
      const A = expo(a), B = expo(b);
      for (const k of keys) { if (A[k] !== B[k]) return (A[k] - B[k]) * mul; }
      return 0;
    };
    const arr = [...projects];
    arr.sort((a, b) => {
      switch (sortKey) {
        case 'violations': return byNums(a, b, ['ov', 'pe', 'oc']);
        case 'permits':    return byNums(a, b, ['pe', 'ov', 'oc']);
        case 'complaints': return byNums(a, b, ['oc', 'ov', 'pe']);
        // Real recency ordering now that the timestamp rolls. Never-synced sorts
        // as oldest (0) so it sinks to the stale end, which is where it belongs.
        case 'synced':     return ((syncedAt(a) || 0) - (syncedAt(b) || 0)) * mul;
        default: // address
          return addrOf(a).toLowerCase().localeCompare(addrOf(b).toLowerCase()) * mul;
      }
    });
    return arr;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects, sortKey, sortDir, summary]);

  const toggleSort = (key) => {
    if (key === sortKey) { setSortDir((d) => (d === 'asc' ? 'desc' : 'asc')); return; }
    setSortKey(key);
    setSortDir(COLUMNS.find((c) => c.key === key)?.numeric ? 'desc' : 'asc');
  };

  return (
    <View style={styles.root}>
      {/* Header — labels use the readable secondary token (muted failed contrast);
          the sorted column uses the brand token. */}
      <View style={[styles.headerRow, { borderBottomColor: border.medium }]}>
        {COLUMNS.map((col) => {
          const active = sortKey === col.key;
          const Arrow = sortDir === 'asc' ? ChevronUp : ChevronDown;
          return (
            <Pressable
              key={col.key}
              onPress={() => toggleSort(col.key)}
              accessibilityRole="button"
              accessibilityLabel={`Sort by ${col.label}`}
              style={({ hovered }) => [
                styles.headerCell,
                { flex: col.flex, justifyContent: col.align },
                hovered && { backgroundColor: surface.card },
              ]}
            >
              <Text numberOfLines={1} style={[styles.headerText, { color: active ? chrome.brand : text.secondary }]}>
                {col.label}
              </Text>
              {active ? <Arrow size={13} strokeWidth={2} color={chrome.brand} /> : null}
            </Pressable>
          );
        })}
        <View style={styles.actionsCell} />
      </View>

      {/* Rows */}
      {sorted.map((p) => {
        const id = projectId(p);
        const { ov, pe, oc, tv, tp, tc } = expo(p);
        const open = menuFor === id;
        const synced = hasSynced(p);
        const classLabel = CLASS_LABEL[p.project_class] || null;
        return (
          <View
            key={id}
            style={[styles.row, { borderBottomColor: border.subtle }, open && styles.rowRaised]}
          >
            <Pressable
              onPress={() => onRowPress(p)}
              accessibilityRole="link"
              accessibilityLabel={`Open ${addrOf(p) || 'project'}`}
              style={({ hovered }) => [styles.rowMain, hovered && { backgroundColor: surface.card }]}
            >
              <Text numberOfLines={1} style={[styles.cell, styles.addressCell, { flex: FLEX.address, color: text.primary }]}>
                {addrOf(p) || '—'}
              </Text>

              {/* Violations — filled dot + count, centered. Critical only when > 0. */}
              <View style={[styles.cell, styles.countCell, { flex: FLEX.violations }]}>
                <View style={[styles.dot, { backgroundColor: ov > 0 ? semantic.critical : semantic.neutral }]} />
                <Text style={[styles.countText, { color: ov > 0 ? semantic.criticalText : text.muted, fontWeight: ov > 0 ? '700' : '400' }]}>
                  {ov} of {tv}
                </Text>
              </View>

              {/* Permits expiring OF ACTIVE — attention only when > 0. The
                  denominator is what stops "0" reading as "no permits".
                  (dob-summary carries no soonest-expiry date, so no "· Nd"
                  suffix; counts only.) */}
              <Text numberOfLines={1} style={[styles.cell, styles.countText, { flex: FLEX.permits, color: pe > 0 ? semantic.attention : text.muted, fontWeight: pe > 0 ? '700' : '400' }]}>
                {pe} of {tp}
              </Text>

              {/* Complaints — always neutral, count only. */}
              <Text numberOfLines={1} style={[styles.cell, styles.countText, { flex: FLEX.complaints, color: oc > 0 ? text.secondary : text.muted }]}>
                {oc} of {tc}
              </Text>

              {/* Synced — real relative age off last_dob_sync_at; "Never"
                  (attention) until a sync has stamped it. */}
              <Text numberOfLines={1} style={[styles.cell, styles.countText, { flex: FLEX.synced, color: synced ? text.muted : semantic.attention }]}>
                {synced ? relAge(syncedAt(p)) : 'Never'}
              </Text>
            </Pressable>

            {/* Overflow menu — view, delete, and CLASS + BIN (demoted here). */}
            <View style={styles.actionsCell}>
              <Pressable
                onPress={() => setMenuFor(open ? null : id)}
                hitSlop={8}
                accessibilityRole="button"
                accessibilityLabel="Row actions"
                style={({ hovered }) => [styles.kebab, hovered && { backgroundColor: surface.glassHover }]}
              >
                <MoreVertical size={16} strokeWidth={1.5} color={text.muted} />
              </Pressable>

              {open ? (
                // Opaque popover (surface.menu) + shadow so it OCCLUDES the rows
                // behind it — the translucent glass fills let cells bleed through.
                <View style={[styles.menu, { backgroundColor: surface.menu, borderColor: border.medium }]}>
                  {/* Reference: class + BIN (not triage columns). */}
                  <View style={[styles.menuInfo, { borderBottomColor: border.subtle }]}>
                    <Text numberOfLines={1} style={[styles.menuInfoText, { color: text.secondary }]}>
                      {(classLabel || '—')}  ·  BIN {p.nyc_bin || '—'}
                    </Text>
                  </View>
                  <Pressable
                    onPress={() => { setMenuFor(null); onRowPress(p); }}
                    accessibilityRole="button"
                    style={({ hovered }) => [styles.menuItem, hovered && { backgroundColor: surface.card }]}
                  >
                    <Eye size={14} strokeWidth={1.5} color={semantic.neutral} />
                    <Text style={[styles.menuItemText, { color: text.primary }]}>View project</Text>
                  </Pressable>
                  <Pressable
                    onPress={() => { setMenuFor(null); onDelete(p); }}
                    accessibilityRole="button"
                    style={({ hovered }) => [styles.menuItem, hovered && { backgroundColor: surface.card }]}
                  >
                    <Trash2 size={14} strokeWidth={1.5} color={semantic.neutral} />
                    <Text style={[styles.menuItemText, { color: text.primary }]}>Delete project</Text>
                  </Pressable>
                </View>
              ) : null}
            </View>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { width: '100%', overflow: 'visible' },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    borderBottomWidth: 1,
    paddingRight: 44,
    marginBottom: spacing.xs,
  },
  headerCell: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
    borderRadius: borderRadius.sm,
  },
  headerText: { fontSize: typography.sizes.xs, fontWeight: '600', letterSpacing: 0.5, textTransform: 'uppercase' },
  row: { flexDirection: 'row', alignItems: 'center', borderBottomWidth: 1, overflow: 'visible' },
  rowRaised: { zIndex: 30 },
  rowMain: { flex: 1, flexDirection: 'row', alignItems: 'center', paddingVertical: spacing.sm + 2, borderRadius: borderRadius.sm },
  cell: { paddingHorizontal: spacing.sm },
  countText: { fontSize: typography.sizes.sm, textAlign: 'center' },
  countCell: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  addressCell: { fontSize: typography.sizes.sm, fontWeight: '500' },
  actionsCell: { width: 44, alignItems: 'center', justifyContent: 'center' },
  kebab: { padding: spacing.xs, borderRadius: borderRadius.sm },
  menu: {
    position: 'absolute', top: 32, right: 4, minWidth: 200,
    borderWidth: 1, borderRadius: borderRadius.md, paddingVertical: spacing.xs, zIndex: 40,
    // Popover elevation (RN Web → boxShadow).
    shadowColor: '#000', shadowOffset: { width: 0, height: 8 }, shadowOpacity: 0.35, shadowRadius: 16, elevation: 12,
  },
  menuInfo: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderBottomWidth: StyleSheet.hairlineWidth },
  menuInfoText: { fontSize: 11, fontWeight: '600', letterSpacing: 0.3 },
  menuItem: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  menuItemText: { fontSize: typography.sizes.sm },
});
