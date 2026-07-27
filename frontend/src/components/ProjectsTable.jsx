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
 * SYNCED column, honest semantics: the payload carries NO per-project
 * last-DOB-sync timestamp. first_poll_completed_at is stamped ONCE on the first
 * poll and never updated (server.py: `if not proj_doc.get("first_poll_...")`),
 * so it is NOT sync freshness — showing "4m" off it would mislead. We therefore
 * show only the one truthful bit it gives: "Never" when it is null (no poll has
 * ever completed — same signal the dashboard's "Never synced" rollup uses), and
 * "—" once a project has synced (freshness unknown). Real relative freshness is
 * blocked until the sync path persists a rolling timestamp — see
 * docs/audits/followups.md.
 */

const CLASS_LABEL = { major_b: 'MAJOR B', major_a: 'MAJOR A', regular: 'REGULAR' };

// Column flex + alignment — shared by header + row cells so they can't drift.
const COLUMNS = [
  { key: 'address', label: 'Address', flex: 3, numeric: false, align: 'flex-start' },
  { key: 'violations', label: 'Violations', flex: 1.2, numeric: true, align: 'center' },
  { key: 'permits', label: 'Permits', flex: 1.5, numeric: true, align: 'center' },
  { key: 'complaints', label: 'Complaints', flex: 1.3, numeric: true, align: 'center' },
  { key: 'synced', label: 'Synced', flex: 1.1, numeric: true, align: 'center' },
];
const FLEX = Object.fromEntries(COLUMNS.map((c) => [c.key, c.flex]));

const projectId = (p) => p._id || p.id;
const addrOf = (p) => p.address || p.name || '';
const hasSynced = (p) => !!p.first_poll_completed_at;

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
        // Two buckets only (synced / never) — no false ordering by first-poll time.
        case 'synced':     return ((hasSynced(a) ? 1 : 0) - (hasSynced(b) ? 1 : 0)) * mul;
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
        const { ov, pe, oc } = expo(p);
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
                  {ov}
                </Text>
              </View>

              {/* Permits expiring — attention only when > 0. (dob-summary carries
                  no soonest-expiry date, so no "· Nd" suffix; count only.) */}
              <Text numberOfLines={1} style={[styles.cell, styles.countText, { flex: FLEX.permits, color: pe > 0 ? semantic.attention : text.muted, fontWeight: pe > 0 ? '700' : '400' }]}>
                {pe}
              </Text>

              {/* Complaints — always neutral, count only. */}
              <Text numberOfLines={1} style={[styles.cell, styles.countText, { flex: FLEX.complaints, color: oc > 0 ? text.secondary : text.muted }]}>
                {oc}
              </Text>

              {/* Synced — "Never" (attention) when no poll has completed; "—" once
                  synced (no real freshness timestamp exists yet). */}
              <Text numberOfLines={1} style={[styles.cell, styles.countText, { flex: FLEX.synced, color: synced ? text.muted : semantic.attention }]}>
                {synced ? '—' : 'Never'}
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
