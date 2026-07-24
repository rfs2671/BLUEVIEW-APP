import React, { useState, useMemo, useEffect } from 'react';
import { View, Text, Pressable, StyleSheet } from 'react-native';
import { ChevronUp, ChevronDown, MoreVertical, Trash2 } from 'lucide-react-native';
import apiClient from '../utils/api';
import { bandFor } from './RiskScoreCircle';
import { useFeatureFlag } from '../hooks/useFeatureFlag';
import { semantic, chrome, border, surface, text } from '../styles/semanticColors';
import { spacing, borderRadius, typography } from '../styles/theme';

/**
 * ProjectsTable — desktop-only (>=1024) replacement for the projects card list.
 *
 * Mobile is untouched: projects/index.jsx branches on useIsDesktop() and still
 * renders its existing card list below the breakpoint.
 *
 * Columns are limited to what the existing GET /api/projects payload can
 * actually answer (see docs/audits/ui-inventory-2026-07-23.md Follow-ups):
 *   Address, BIN, Class, Risk, Status.
 * Violations / Permits-expiring / Last-sync are deliberately NOT here — they
 * need a server-side dob-summary aggregation (and, for "last sync", a field
 * the sync job does not currently write). Rendering them from client-side
 * dob-logs calls would produce wrong numbers: that endpoint defaults to a
 * 30-day detected_at window, caps at 200 rows, and detected_at is a
 * backfill/sync stamp rather than an event date.
 *
 * defcon_tier is intentionally NOT surfaced here — one severity scale per
 * view. Risk score is the scale; a second colored tier alongside it would be
 * two verdicts competing for the same glance.
 */

const CLASS_LABEL = { major_b: 'MAJOR B', major_a: 'MAJOR A', regular: 'REGULAR' };
// Ordering only — NOT severity. Project class is a classification, so every
// badge renders neutral (taxonomy: MAJOR B is not an alarm).
const CLASS_RANK = { major_b: 3, major_a: 2, regular: 1 };

const COLUMNS = [
  { key: 'address', label: 'Address', flex: 3, numeric: false },
  { key: 'bin', label: 'BIN', flex: 1.4, numeric: false },
  { key: 'class', label: 'Class', flex: 1.3, numeric: true },
  { key: 'risk', label: 'Risk', flex: 1, numeric: true },
  { key: 'status', label: 'Status', flex: 1.2, numeric: false },
];

const projectId = (p) => p._id || p.id;

/**
 * Risk presentation. Thresholds are NOT reimplemented here — bandFor() is
 * imported from RiskScoreCircle so there is one source of truth for the
 * [30, 60, 80] cutoffs (the audit already flagged score_band/bandFor drifting
 * as parallel implementations; this does not add a third).
 *
 * Colors map the band onto the semantic taxonomy rather than bandFor's raw
 * hexes. Critical uses criticalText because this renders as TEXT on a card
 * surface, where plain `critical` fails WCAG AA (4.03:1 on surface-1).
 * A null/uncomputed score is ALWAYS neutral "Scoring" — never green.
 */
function riskPresentation(score) {
  const band = bandFor(score);
  if (score == null || !Number.isFinite(Number(score))) {
    return { label: band.label, color: semantic.neutral, pending: true };
  }
  const value = String(Math.round(Number(score)));
  if (band.label === 'LOW RISK') return { label: value, color: semantic.verified };
  if (band.label === 'CRITICAL RISK') return { label: value, color: semantic.criticalText };
  // MODERATE / HIGH both map to attention — the taxonomy has exactly four
  // state tokens, so the two middle bands share one.
  return { label: value, color: semantic.attention };
}

export default function ProjectsTable({ projects, onRowPress, onDelete }) {
  // Default sort: risk descending, nulls last (see comparator).
  const [sortKey, setSortKey] = useState('risk');
  const [sortDir, setSortDir] = useState('desc');
  const [menuFor, setMenuFor] = useState(null);
  const [riskById, setRiskById] = useState({});

  const v2RiskScoreEnabled = useFeatureFlag('v2_risk_score');

  // Stable dependency — `projects` is a fresh array every render, so keying
  // the effect on the id list avoids an infinite refetch loop.
  const idsKey = useMemo(() => projects.map(projectId).join(','), [projects]);

  // ── N+1 WARNING ────────────────────────────────────────────────────────
  // One GET /api/projects/{id}/risk-score per row, because the list payload
  // carries no score. Acceptable at the current scale (single-digit
  // projects) and each failure degrades to "Scoring" rather than an error.
  // Past ~20 projects this MUST move to the server-side dob-summary
  // aggregation (one request returning score + open-violation + expiring-
  // permit counts for every project) — see the Follow-ups section of
  // docs/audits/ui-inventory-2026-07-23.md.
  // ───────────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!v2RiskScoreEnabled) return undefined;
    let cancelled = false;
    (async () => {
      const entries = await Promise.all(
        projects.map(async (p) => {
          const id = projectId(p);
          try {
            const r = await apiClient.get(`/api/projects/${id}/risk-score`);
            const doc = r?.data?.score;
            const n = doc && typeof doc.score === 'number' ? Number(doc.score) : null;
            return [id, n];
          } catch (_e) {
            // Silent — a failed score renders as neutral "Scoring", never as
            // a reassuring value, and never as a toast per row.
            return [id, null];
          }
        }),
      );
      if (!cancelled) setRiskById(Object.fromEntries(entries));
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey, v2RiskScoreEnabled]);

  const riskFor = (p) => {
    const v = riskById[projectId(p)];
    return v === undefined ? null : v;
  };

  const valueFor = (p, key) => {
    switch (key) {
      case 'address': return p.address || p.name || '';
      case 'bin': return p.nyc_bin || '';
      case 'status': return p.status || '';
      default: return '';
    }
  };

  const sorted = useMemo(() => {
    const arr = [...projects];
    const mul = sortDir === 'asc' ? 1 : -1;
    arr.sort((a, b) => {
      if (sortKey === 'risk') {
        const ra = riskFor(a);
        const rb = riskFor(b);
        // Nulls sort last in BOTH directions — an uncomputed score must never
        // float to the top of an exposure-ordered list.
        if (ra == null && rb == null) return 0;
        if (ra == null) return 1;
        if (rb == null) return -1;
        return (ra - rb) * mul;
      }
      if (sortKey === 'class') {
        const ca = CLASS_RANK[a.project_class] || 0;
        const cb = CLASS_RANK[b.project_class] || 0;
        return (ca - cb) * mul;
      }
      return String(valueFor(a, sortKey)).toLowerCase()
        .localeCompare(String(valueFor(b, sortKey)).toLowerCase()) * mul;
    });
    return arr;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects, sortKey, sortDir, riskById]);

  const toggleSort = (key) => {
    if (key === sortKey) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setSortKey(key);
    // Numeric columns lead with the "most" end; text columns read A→Z.
    setSortDir(COLUMNS.find((c) => c.key === key)?.numeric ? 'desc' : 'asc');
  };

  return (
    <View style={styles.root}>
      {/* Header */}
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
                { flex: col.flex },
                hovered && { backgroundColor: surface.card },
              ]}
            >
              <Text
                numberOfLines={1}
                style={[
                  styles.headerText,
                  { color: active ? chrome.brand : text.muted },
                ]}
              >
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
        const risk = riskPresentation(riskFor(p));
        const classLabel = CLASS_LABEL[p.project_class] || null;
        const open = menuFor === id;
        return (
          <View
            key={id}
            // Raise the open row so its popover paints above later rows.
            style={[styles.row, { borderBottomColor: border.subtle }, open && styles.rowRaised]}
          >
            <Pressable
              onPress={() => onRowPress(p)}
              accessibilityRole="link"
              accessibilityLabel={`Open ${p.address || p.name || 'project'}`}
              style={({ hovered }) => [
                styles.rowMain,
                hovered && { backgroundColor: surface.card },
              ]}
            >
              {/* Address — single line. The card list printed name AND address,
                  which are the same string for most projects (create_project
                  sets name = address when only one is supplied). */}
              <Text numberOfLines={1} style={[styles.cell, styles.addressCell, { flex: 3, color: text.primary }]}>
                {p.address || p.name || '—'}
              </Text>

              <Text numberOfLines={1} style={[styles.cell, { flex: 1.4, color: text.secondary }]}>
                {p.nyc_bin || '—'}
              </Text>

              <View style={[styles.cell, { flex: 1.3 }]}>
                {classLabel ? (
                  <View style={[styles.badge, { backgroundColor: semantic.neutralBg }]}>
                    <Text numberOfLines={1} style={[styles.badgeText, { color: semantic.neutralStrong }]}>
                      {classLabel}
                    </Text>
                  </View>
                ) : (
                  <Text style={[styles.cellText, { color: text.muted }]}>—</Text>
                )}
              </View>

              <Text
                numberOfLines={1}
                style={[
                  styles.cell, styles.cellText,
                  { flex: 1, color: risk.color },
                  risk.pending && styles.pendingText,
                ]}
              >
                {risk.label}
              </Text>

              <Text numberOfLines={1} style={[styles.cell, styles.cellText, { flex: 1.2, color: text.secondary }]}>
                {p.status || '—'}
              </Text>
            </Pressable>

            {/* Overflow menu — sibling of the row Pressable, so tapping it can
                never trigger row navigation. Delete logic itself is unchanged:
                this calls the same handler (and therefore the same
                confirmation) the card list used. */}
            <View style={styles.actionsCell}>
              <Pressable
                onPress={() => setMenuFor(open ? null : id)}
                hitSlop={8}
                accessibilityRole="button"
                accessibilityLabel="Row actions"
                style={({ hovered }) => [
                  styles.kebab,
                  hovered && { backgroundColor: surface.glassHover },
                ]}
              >
                <MoreVertical size={16} strokeWidth={1.5} color={text.muted} />
              </Pressable>

              {open ? (
                <View
                  style={[
                    styles.menu,
                    { backgroundColor: surface.glass, borderColor: border.medium },
                  ]}
                >
                  <Pressable
                    onPress={() => { setMenuFor(null); onDelete(p); }}
                    accessibilityRole="button"
                    style={({ hovered }) => [
                      styles.menuItem,
                      hovered && { backgroundColor: surface.card },
                    ]}
                  >
                    <Trash2 size={14} strokeWidth={1.5} color={semantic.neutral} />
                    <Text style={[styles.menuItemText, { color: text.primary }]}>
                      Delete project
                    </Text>
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
  headerText: {
    fontSize: typography.sizes.xs,
    fontWeight: '600',
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    borderBottomWidth: 1,
    overflow: 'visible',
  },
  rowRaised: { zIndex: 10 },
  rowMain: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm + 2,
    borderRadius: borderRadius.sm,
  },
  cell: { paddingHorizontal: spacing.sm },
  cellText: { fontSize: typography.sizes.sm },
  addressCell: { fontSize: typography.sizes.sm, fontWeight: '500' },
  pendingText: { fontStyle: 'italic' },
  badge: {
    alignSelf: 'flex-start',
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: borderRadius.full,
  },
  badgeText: { fontSize: 10, fontWeight: '600', letterSpacing: 0.5 },
  actionsCell: { width: 44, alignItems: 'center', justifyContent: 'center' },
  kebab: { padding: spacing.xs, borderRadius: borderRadius.sm },
  menu: {
    position: 'absolute',
    top: 32,
    right: 4,
    minWidth: 170,
    borderWidth: 1,
    borderRadius: borderRadius.md,
    paddingVertical: spacing.xs,
    zIndex: 20,
  },
  menuItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  menuItemText: { fontSize: typography.sizes.sm },
});
