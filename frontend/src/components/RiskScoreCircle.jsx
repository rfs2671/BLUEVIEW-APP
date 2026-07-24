/**
 * Phase V2.1.2 — Compact Risk Score Circle gauge.
 *
 * Replaces the full-width text-heavy RiskScoreCard with a small
 * SVG circular gauge intended to live inline in project lists
 * and project detail headers as a side feature, not a full tab.
 *
 * Behavior:
 *   • Diameter ~84 px. Fits next to existing badges + StatCards.
 *   • Score number (0–100, rounded) inside the circle.
 *   • Radial fill colored by band (matches lib/risk_score/schema.py
 *     score_band thresholds: green ≤30, yellow ≤60, orange ≤80,
 *     red >80).
 *   • Hover (web) shows a small tooltip with the 95% CI range.
 *   • Tap / click opens the side drawer (RiskScoreDrawer) for
 *     full breakdown — never navigates away from the current page.
 *   • Loading: solid grey ring + "—".
 *   • No-score-yet: greyed ring + "—" placeholder.
 *   • Fetch failure: silent (no scary error UI); falls back to "—".
 *
 * Hard rules pinned by tests:
 *   • useFeatureFlag('v2_risk_score') is the FIRST hook in the
 *     component (rules-of-hooks; same C1.3 / V2.0 / V2.1 pattern).
 *   • Flag OFF returns null BEFORE fetching anything.
 *   • Score-band thresholds match the backend (schema.py::score_band).
 *
 * Usage:
 *   import RiskScoreCircle from '../../src/components/RiskScoreCircle';
 *   <RiskScoreCircle projectId={projectId} isAdmin={isAdmin} size={84} />
 */

import React, { useEffect, useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  Platform,
} from 'react-native';
import Svg, { Circle, G } from 'react-native-svg';
import { useFeatureFlag } from '../hooks/useFeatureFlag';
import { useTheme } from '../context/ThemeContext';
import { spacing, borderRadius, typography } from '../styles/theme';
import apiClient from '../utils/api';
import RiskScoreDrawer from './RiskScoreDrawer';

// Color tokens — duplicated from RiskScoreCard so the new card can
// stand alone. Tests pin these against backend schema.py::score_band.
//
// Phase V2.1.4: band labels gained "RISK" suffix so the word
// underneath the circle reads as a verdict in plain English
// ("LOW RISK", "CRITICAL RISK") rather than an abbreviation
// the operator's compliance staff has to learn.
const BAND_GREEN  = { fg: '#22c55e', track: 'rgba(34, 197, 94, 0.18)',  label: 'LOW RISK' };
const BAND_YELLOW = { fg: '#eab308', track: 'rgba(234, 179, 8, 0.18)',  label: 'MODERATE RISK' };
const BAND_ORANGE = { fg: '#f97316', track: 'rgba(249, 115, 22, 0.18)', label: 'HIGH RISK' };
const BAND_RED    = { fg: '#ef4444', track: 'rgba(239, 68, 68, 0.20)',  label: 'CRITICAL RISK' };
// Pending band — score not yet computed (null / undefined / NaN /
// fetch-failed). Neutral slate, deliberately NOT green: an uncomputed
// score must never read as low-risk in a compliance product. These are
// the same muted values the render already falls back to for no-score,
// so the pending band is now the single source of truth for that state.
const BAND_PENDING = { fg: 'rgba(148, 163, 184, 0.55)', track: 'rgba(148, 163, 184, 0.20)', label: 'Scoring' };

// Title shown above the circle. Pinned in tests so an accidental
// rename surfaces immediately.
export const RISK_SCORE_TITLE = 'DOB Risk Score';
// Band-word shown below the circle when there's no score yet.
export const PENDING_LABEL = 'PENDING';

// Score-band thresholds — pinned to backend schema.py::score_band.
// Boundaries (≤30 green, ≤60 yellow, ≤80 orange, >80 red) match
// exactly. A test in test_v2_1_2_risk_score_redesign.py asserts
// each boundary case (29 / 30 / 31 / 60 / 61 / 80 / 81 / 99).
export function bandFor(score) {
  // Guard missing/uncomputed scores FIRST, before any numeric comparison.
  // null and undefined (== null), plus anything that isn't a finite number
  // (NaN, Infinity, non-numeric strings), resolve to the neutral pending
  // band — NEVER green. Previously null returned BAND_GREEN and NaN fell
  // through to BAND_RED; both were wrong. Note: 0 is a REAL score and is
  // finite, so it passes this guard and correctly lands in BAND_GREEN below.
  if (score == null) return BAND_PENDING;
  const s = Number(score);
  if (!Number.isFinite(s)) return BAND_PENDING;
  if (s <= 30) return BAND_GREEN;
  if (s <= 60) return BAND_YELLOW;
  if (s <= 80) return BAND_ORANGE;
  return BAND_RED;
}

const RiskScoreCircle = ({ projectId, isAdmin = false, size = 84 }) => {
  // ── Flag check FIRST (rules-of-hooks). MUST stay at the top of
  //    the component body, never inside a conditional or after an
  //    early return. C1.3 incident pattern.
  const v2RiskScoreEnabled = useFeatureFlag('v2_risk_score');

  // All other hooks unconditional — they run on every render even
  // when the flag is off; the return-null below is the LAST step.
  const { colors, isDark } = useTheme();
  const styles = useMemo(() => buildStyles(colors, isDark), [colors, isDark]);

  const [loading, setLoading] = useState(true);
  const [scoreDoc, setScoreDoc] = useState(null);
  const [hovered, setHovered] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    if (!v2RiskScoreEnabled || !projectId) return;
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        const r = await apiClient.get(
          `/api/projects/${projectId}/risk-score`,
        );
        if (!cancelled) setScoreDoc(r?.data?.score || null);
      } catch (_e) {
        // Silent fail — circle just shows "—". Project list with
        // 50 projects shouldn't paint 50 error toasts.
        if (!cancelled) setScoreDoc(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [v2RiskScoreEnabled, projectId]);

  // ── Fail-closed render: flag OFF → nothing. ───────────────
  if (!v2RiskScoreEnabled) {
    return null;
  }

  // Geometry. The SVG ring uses stroke-dashoffset to render a
  // radial fill 0..100% based on score / 100.
  const stroke = Math.max(4, Math.round(size / 12));
  const radius = (size - stroke) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * radius;

  const hasScore = scoreDoc && typeof scoreDoc.score === 'number';
  const score = hasScore ? Number(scoreDoc.score) : null;
  // bandFor is the single source of truth: a real score maps to its risk
  // band; a missing score maps to BAND_PENDING (neutral, never green).
  const band = bandFor(hasScore ? score : null);

  const fillFraction = hasScore ? Math.max(0, Math.min(1, score / 100)) : 0;
  const dashOffset = circumference * (1 - fillFraction);

  const trackColor = band.track;
  const ringColor  = band.fg;
  const fgColor    = band.fg;
  // Band word shown below the circle. Three states:
  //   • has score   → "LOW RISK" / "MODERATE RISK" / etc. (color-matched)
  //   • loading     → blank string (avoids label flicker while fetching)
  //   • no score    → "Scoring" (BAND_PENDING.label) in neutral muted gray
  const bandWordText = (!hasScore && loading) ? '' : band.label;
  const bandWordColor = hasScore ? fgColor : colors.text.muted;

  const ciLow  = hasScore ? Math.round(Number(scoreDoc.confidence_low  || 0)) : null;
  const ciHigh = hasScore ? Math.round(Number(scoreDoc.confidence_high || 0)) : null;
  const tooltipText = hasScore
    ? `${ciLow}–${ciHigh} / 100`
    : null;

  // Compact font sizes for small circles (project list at size=56)
  // and larger fonts for the prominent project-header circle
  // (size=84). Mobile (<768 viewport) uses the same fonts as the
  // small variant — readable but unobtrusive.
  const compact = size < 70;
  const titleFontSize    = compact ? 9  : 11;
  const bandWordFontSize = compact ? 8  : 10;

  // Web hover handlers degrade to no-ops on native.
  const hoverProps = Platform.OS === 'web'
    ? {
        onHoverIn:  () => setHovered(true),
        onHoverOut: () => setHovered(false),
      }
    : {};

  return (
    <>
      <Pressable
        onPress={() => setDrawerOpen(true)}
        accessibilityRole="button"
        accessibilityLabel={
          hasScore
            ? `${RISK_SCORE_TITLE} ${Math.round(score)} of 100, ${band.label}. Tap to see breakdown.`
            : `${RISK_SCORE_TITLE} not yet calculated. Tap for details.`
        }
        style={({ pressed }) => [
          styles.wrap,
          // Total height = title + circle + band word + small gaps.
          // Title ≈ titleFontSize + 4px, band word ≈ bandWordFontSize + 4px.
          {
            width: Math.max(size, 96),
            height: size + (titleFontSize + 4) + (bandWordFontSize + 6),
          },
          pressed && styles.wrapPressed,
        ]}
        {...hoverProps}
      >
        {/* Title above the circle — gives a number on its own
            ("2") the context to be read as "DOB Risk Score 2". */}
        <Text
          style={[
            styles.title,
            { fontSize: titleFontSize, color: colors.text.muted },
          ]}
          numberOfLines={1}
        >
          {RISK_SCORE_TITLE}
        </Text>

        <View style={{ width: size, height: size }}>
          <Svg width={size} height={size}>
            {/* Rotate -90deg so the radial fill grows clockwise
                from 12 o'clock instead of from 3 o'clock. */}
            <G rotation={-90} origin={`${cx}, ${cy}`}>
              {/* Track (full circle, faded) */}
              <Circle
                cx={cx}
                cy={cy}
                r={radius}
                stroke={trackColor}
                strokeWidth={stroke}
                fill="transparent"
              />
              {/* Fill (partial arc proportional to score) */}
              {hasScore && (
                <Circle
                  cx={cx}
                  cy={cy}
                  r={radius}
                  stroke={ringColor}
                  strokeWidth={stroke}
                  fill="transparent"
                  strokeDasharray={`${circumference}`}
                  strokeDashoffset={dashOffset}
                  strokeLinecap="round"
                />
              )}
            </G>
          </Svg>

          {/* Score number absolutely centered inside the SVG. */}
          <View style={[styles.numberOverlay, { width: size, height: size }]}>
            {loading && !hasScore ? (
              <Text style={[styles.numberText, { color: colors.text.muted }]}>
                …
              </Text>
            ) : hasScore ? (
              <Text style={[styles.numberText, { color: fgColor }]}>
                {Math.round(score)}
              </Text>
            ) : (
              <Text style={[styles.numberText, { color: colors.text.muted }]}>
                —
              </Text>
            )}
          </View>
        </View>

        <Text
          style={[
            styles.bandLabel,
            { fontSize: bandWordFontSize, color: bandWordColor },
          ]}
          numberOfLines={1}
        >
          {bandWordText}
        </Text>

        {/* Web hover tooltip — only renders on web AND only when
            we actually have a score to describe. Anchored above
            the circle so it doesn't overlap the band label. */}
        {Platform.OS === 'web' && hovered && hasScore && (
          <View style={styles.tooltip} pointerEvents="none">
            <Text style={styles.tooltipText}>{tooltipText}</Text>
          </View>
        )}
      </Pressable>

      <RiskScoreDrawer
        projectId={projectId}
        isAdmin={isAdmin}
        visible={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        initialScore={scoreDoc}
      />
    </>
  );
};

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    wrap: {
      alignItems: 'center',
      justifyContent: 'center',
      // Sit cleanly inline with badges. No margin — the parent row
      // (GlassListItem / project header) handles spacing.
    },
    wrapPressed: {
      opacity: 0.7,
    },
    numberOverlay: {
      position: 'absolute',
      top: 0, left: 0,
      alignItems: 'center',
      justifyContent: 'center',
    },
    numberText: {
      fontSize: 20,
      fontWeight: '700',
      lineHeight: 22,
    },
    title: {
      // V2.1.4 — title above the circle. Muted small caps so it
      // visually defers to the score number itself.
      fontWeight: '600',
      letterSpacing: 0.6,
      textTransform: 'uppercase',
      marginBottom: 4,
    },
    bandLabel: {
      // V2.1.4 — band-word ("LOW RISK" / "MODERATE RISK" / …)
      // sits below the circle, color-matched to the band.
      marginTop: 4,
      fontWeight: '700',
      letterSpacing: 0.8,
    },
    tooltip: {
      position: 'absolute',
      // V2.1.4 — tooltip anchors at the very top of the wrap
      // (above the title row) so it doesn't visually overlap
      // the title on hover.
      top: -22,
      paddingHorizontal: 8,
      paddingVertical: 3,
      backgroundColor: isDark ? 'rgba(0,0,0,0.85)' : 'rgba(15, 23, 42, 0.92)',
      borderRadius: borderRadius.sm,
    },
    tooltipText: {
      fontSize: 11,
      color: '#ffffff',
      fontWeight: '500',
    },
  });
}

export default RiskScoreCircle;
