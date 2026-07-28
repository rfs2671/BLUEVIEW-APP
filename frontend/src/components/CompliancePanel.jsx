/**
 * PR #15D / PR #15D.1 — DOB Enforcement Forecast panel.
 *
 * Renders the Phase 1 Predictive Inference Engine output for a
 * single project: 3-horizon violation forecasts (7d / 14d / 30d)
 * with cohort-baseline comparisons, colour-coded by hazard ratio
 * (Lock L6 — 5-tier mapping via hazardRatioToColorTier).
 *
 * PR #15D.1 — copy rewrite to GC-readable vocabulary (no absolute
 * percentages on the surface; 5-tier verdict labels via
 * tierToVerdictLabel; hazard-ratio chips with directional arrows;
 * borough/project-type humanisation via the shared displayHelpers
 * util). Cohort baseline label is parsed client-side via
 * parseBaselineLabel — see Stage 1 Probe E for the Option X
 * justification.
 *
 * Hard rules pinned by Stage 5 spot-check spec + PR #15D locks:
 *   • Feature flag — useFeatureFlag('pr15d_prediction') is the
 *     FIRST hook in this component (rules-of-hooks pattern, same
 *     idiom as RiskScoreCircle / RiskScoreDrawer). Flag OFF →
 *     return null BEFORE any other state, effect, or fetch.
 *   • L6 — colour each horizon row from
 *     project_prob_<n>d / anchored_baseline.prob_<n>d via
 *     hazardRatioToColorTier. NEVER colour from the raw probability.
 *   • L7 — last_validated_timestamp older than 24h → soft-stale
 *     chip; > 48h → hard-stale chip. Panel always renders.
 *   • L8 / B-SERIALIZE — confidence.badge is computed server-side
 *     in serialize_prediction_cache_to_response. The client must
 *     NOT derive its own; just render what the API returns.
 *   • Q3 / Q5 cold-start UX — when badge === 'cold_start', the
 *     panel shows the educational disclaimer copy pinned by the
 *     PR #15D Stage 5 spec, NOT the standard "limited sample"
 *     treatment. Explains why prob_30d can be ~50% for cohorts
 *     like Bronx full_demo without alarming the operator.
 *   • F2 — no Jest/RNTL tests for this component (no FE test infra
 *     in this repo). Backend tests cover the API contract; manual
 *     visual smoke (Stage 9) validates the rendering.
 *
 * Render states:
 *   1. flag OFF       — returns null (no fetch, no render)
 *   2. loading        — ActivityIndicator inside GlassCard header
 *   3. error          — muted "couldn't load" line, no crash
 *   4. unavailable    — prediction_available=false (no fit yet)
 *   5. cold_start     — educational disclaimer, plus the 3 horizon
 *                       rows colored against the cohort baseline
 *   6. ready          — 3 horizon rows with 5-tier colored chips
 */

import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ActivityIndicator,
  Pressable,
} from 'react-native';
import { useRouter } from 'expo-router';
import {
  Shield, AlertTriangle, Clock, Info,
  ArrowUp, ArrowDown, Minus,
  ChevronDown, ChevronUp,
} from 'lucide-react-native';
import { GlassCard, IconPod } from './GlassCard';
import DefconHeader from './DefconHeader';
import { useFeatureFlag } from '../hooks/useFeatureFlag';
import { useTheme } from '../context/ThemeContext';
import { semantic, border, surface, text } from '../styles/semanticColors';
import { spacing, borderRadius, typography } from '../styles/theme';
import { projectsAPI, dobAPI } from '../utils/api';
import {
  hazardRatioToColorTier,
  tierToStatusColor,
  hazardRatioToDirection,
  tierToVerdictLabel,
} from '../utils/hazardRatioColor';
import {
  projectTypeLabel,
  boroughLabel,
  parseBaselineLabel,
} from '../utils/displayHelpers';

// ── Helpers ──────────────────────────────────────────────────────

function _formatPct(p) {
  if (p === null || p === undefined) return '—';
  const v = Number(p);
  if (!Number.isFinite(v)) return '—';
  // < 0.5% renders as "<0.5%" to avoid the misleading "0%" for
  // small-but-nonzero probabilities (op feedback in Stage 1 design).
  if (v > 0 && v < 0.005) return '<0.5%';
  return `${(v * 100).toFixed(1)}%`;
}

function _safeRatio(prob, baseline) {
  if (prob === null || prob === undefined) return null;
  if (baseline === null || baseline === undefined) return null;
  const b = Number(baseline);
  if (!Number.isFinite(b) || b <= 0) return null;
  const p = Number(prob);
  if (!Number.isFinite(p)) return null;
  return p / b;
}

function _hoursSince(isoOrDate) {
  if (!isoOrDate) return null;
  const t = new Date(isoOrDate).getTime();
  if (Number.isNaN(t)) return null;
  return (Date.now() - t) / 3_600_000;
}

// PR #15D.1 — titleCase + parseBaselineLabel moved to
// frontend/src/utils/displayHelpers.js (shared with RiskScoreDrawer).

// PR #15D.1 lock C8 + D7 — badge resolver. Reads ONLY
// confidence.badge from the server response (no client-side
// sample_size logic; the server already encodes that decision via
// B-SERIALIZE in compute_confidence_badge). Returns both a short
// chip label and a one-line inline tooltip text rendered as muted
// secondary copy under the header (D5 — no native hover idiom on
// React Native, so we surface the explanation inline rather than
// in a popover).
function _badgeInfo(badge) {
  if (badge === 'cold_start') {
    return {
      label:   'Calibrating',
      tooltip: 'Personalized forecast not yet available. Showing '
             + 'baseline for similar projects.',
    };
  }
  if (badge === 'limited_peer_sample') {
    return {
      label:   'Smaller peer group',
      tooltip: 'Based on fewer than 100 similar projects. Forecast '
             + 'still calibrating.',
    };
  }
  return { label: null, tooltip: null };
}

// ── HorizonRow ───────────────────────────────────────────────────
// PR #15D.1 lock D6 — one row per horizon, restructured to drop the
// absolute probability + 'vs N%' from the surface. Renders:
//   • verdict label (lock C3 — 'Below typical' / 'Tracking normal' /
//     'Elevated' / 'Watch closely' / 'High risk this period' / '—')
//     coloured per the 5-tier L6 palette.
//   • hazard-ratio chip (lock C4 — '{N.N}× typical' with directional
//     lucide arrow per hazardRatioToDirection's ±10% dead-band).
// Per Q1 + Q3 locks: ratios below 0.1× render as '< 0.1× typical'
// (parallel to _formatPct's <0.5% floor); null/unavailable ratios
// render only '—' with no chip suffix or arrow icon.

function HorizonRow({ label, prob, baseline, colors }) {
  const ratio = _safeRatio(prob, baseline);
  const tier = hazardRatioToColorTier(ratio);
  const { fg, bg } = tierToStatusColor(tier);
  const verdict = tierToVerdictLabel(tier);
  const direction = hazardRatioToDirection(ratio);

  // Q1 / Q3 — chip body. Null ratio → bare em-dash, no '× typical'.
  // Ratios below 0.1× hit a '<0.1× typical' floor (parallel to the
  // existing percentage floor at _formatPct).
  let chipText;
  let showArrow;
  if (ratio === null) {
    chipText = '—';
    showArrow = false;
  } else if (ratio < 0.1) {
    chipText = '< 0.1× typical';
    showArrow = true;
  } else {
    chipText = `${ratio.toFixed(1)}× typical`;
    showArrow = true;
  }

  // Lucide icon selection — only rendered when the ratio is numeric.
  let ArrowIcon = null;
  if (showArrow) {
    if (direction === 'up')        ArrowIcon = ArrowUp;
    else if (direction === 'down') ArrowIcon = ArrowDown;
    else                           ArrowIcon = Minus;
  }

  return (
    <View style={styles.row}>
      <Text style={[styles.horizonLabel, { color: colors.text.secondary }]}>
        {label}
      </Text>
      <View style={styles.rowRight}>
        <Text style={[styles.verdictLabel, { color: fg }]}>
          {verdict}
        </Text>
        <View style={[styles.ratioChip, { backgroundColor: bg }]}>
          <View style={styles.ratioChipRow}>
            {ArrowIcon && (
              <ArrowIcon size={11} strokeWidth={2} color={fg} />
            )}
            <Text style={[styles.ratioChipText, { color: fg }]}>
              {chipText}
            </Text>
          </View>
        </View>
      </View>
    </View>
  );
}

// ── Cold-start educational disclaimer (lock C6) ──────────────────
// Two paragraphs:
//   1. Explains why no personalised prediction exists yet, naming
//      the borough + project-type cohort the baseline is drawn from.
//   2. Explains that a 1.0× hazard ratio means "matches typical" —
//      defuses the common misread of a high absolute prob_30d.
// Interpolation uses boroughLabel + projectTypeLabel so 'BROOKLYN'
// renders as 'Brooklyn' and 'major_alt_with_enlargement' as
// 'major alteration' (C5 mapping table).

function ColdStartDisclaimer({ borough, projectType, colors }) {
  const boroughText = boroughLabel(borough);
  const projectTypeText = projectTypeLabel(projectType);
  // If both pieces parsed cleanly, build the qualified cohort phrase
  // ('Brooklyn full demolition'); else fall back to the generic
  // 'similar' so the sentence still reads naturally.
  const cohortPhrase = (boroughText && projectTypeText)
    ? `${boroughText} ${projectTypeText}`
    : 'similar';
  return (
    <View style={[
      styles.disclaimer,
      { backgroundColor: colors.glass.background,
        borderColor: colors.border.subtle },
    ]}>
      <View style={styles.disclaimerHeader}>
        <Info size={14} strokeWidth={1.5} color={colors.status.caution} />
        <Text style={[
          styles.disclaimerTitle,
          { color: colors.status.caution },
        ]}>
          Personalized forecast not yet available
        </Text>
      </View>
      <Text style={[styles.disclaimerBody, { color: colors.text.secondary }]}>
        Personalized forecast unavailable for this project. The
        values shown are the citywide baseline for similar
        {' '}{cohortPhrase} projects. As this project accrues filings
        and time, a personalized forecast will replace these baseline
        values.
      </Text>
      <Text style={[styles.disclaimerBody, { color: colors.text.muted }]}>
        Note: baseline rates can appear high when the project type
        historically draws frequent DOB enforcement. A 1.0× hazard
        ratio means this project matches the typical rate for
        similar projects — it is not necessarily a warning.
      </Text>
    </View>
  );
}

// ── Main component ───────────────────────────────────────────────

export default function CompliancePanel({ projectId }) {
  // Rules-of-hooks pinned: useFeatureFlag MUST be the FIRST hook in
  // this component. Same idiom as RiskScoreCircle. When the flag is
  // off we return null BEFORE useTheme / useState / useEffect run,
  // so v1 users never trigger the prediction fetch.
  const flagOn = useFeatureFlag('pr15d_prediction');
  const { colors } = useTheme();
  const router = useRouter();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  // Phase 1 Week 11-12 PR-B — Defcon status fetched in parallel with
  // the prediction. Render is non-blocking: if the call fails the
  // header simply doesn't appear; the horizon-row UI still loads.
  const [defcon, setDefcon] = useState(null);
  // PR #49 — "Show details" expandable. Default collapsed: the panel
  // shows ONE primary forecast above-fold; the 7/14/30 grid + the long
  // cold-start disclaimer live behind this toggle.
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!flagOn || !projectId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    projectsAPI.getPrediction(projectId)
      .then((resp) => {
        if (cancelled) return;
        setData(resp);
      })
      .catch((err) => {
        if (cancelled) return;
        // 404 / 403 / 5xx — the panel is non-critical, so we degrade
        // gracefully rather than poisoning the whole project page.
        setError(err?.response?.status || 'error');
        setData(null);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [flagOn, projectId]);

  // Phase 1 Week 11-12 PR-B — Defcon status fetch (independent of the
  // prediction call so a Defcon failure doesn't break the forecast UI
  // and vice-versa).
  useEffect(() => {
    if (!flagOn || !projectId) return;
    let cancelled = false;
    projectsAPI.getDefconStatus(projectId)
      .then((resp) => { if (!cancelled) setDefcon(resp); })
      .catch(() => { if (!cancelled) setDefcon(null); });
    return () => { cancelled = true; };
  }, [flagOn, projectId]);

  // ── Standing-open exposure for THIS project ──────────────────────
  // The forecast model is deliberately blind to standing open items: it
  // scores ACUTE signals (active SWO, CLASS-1 in 7d, CLASS-2 in 14d,
  // complaint clustering in 30d, hazard ratio). That makes a "NORMAL"
  // verdict reachable while the project still carries open violations —
  // a present fact the forecast never looked at.
  //
  // We do NOT feed this into the model (present facts and future
  // prediction stay separate). It is used at the DISPLAY layer only, to
  // stop the panel leading with a reassurance that contradicts what the
  // project's own exposure tiles say two rows above.
  //
  // Source is dob-summary — the SAME endpoint the exposure tiles read.
  // This must never read /risk-score: that model is shelved and this
  // component has no business un-shelving it.
  const [openExposure, setOpenExposure] = useState(null);
  useEffect(() => {
    if (!flagOn || !projectId) return undefined;
    let cancelled = false;
    dobAPI.getSummary(projectId)
      .then((resp) => {
        if (!cancelled) setOpenExposure(resp?.by_project?.[projectId] || null);
      })
      .catch(() => { if (!cancelled) setOpenExposure(null); });
    return () => { cancelled = true; };
  }, [flagOn, projectId]);

  // ── State 1 — flag OFF (return null, no render, no fetch) ────
  if (!flagOn) return null;

  // ── State 2 — loading ────────────────────────────────────────
  if (loading) {
    return (
      <GlassCard style={styles.card}>
        <View style={styles.header}>
          <IconPod>
            <Shield size={18} strokeWidth={1.5} color={colors.iconPod.iconColor} />
          </IconPod>
          <Text style={[styles.title, { color: colors.text.primary }]}>
            DOB Enforcement Forecast
          </Text>
        </View>
        <View style={styles.center}>
          <ActivityIndicator color={colors.text.muted} />
        </View>
      </GlassCard>
    );
  }

  // ── State 3 — error ──────────────────────────────────────────
  if (error || !data) {
    return (
      <GlassCard style={styles.card}>
        <View style={styles.header}>
          <IconPod>
            <Shield size={18} strokeWidth={1.5} color={colors.iconPod.iconColor} />
          </IconPod>
          <Text style={[styles.title, { color: colors.text.primary }]}>
            DOB Enforcement Forecast
          </Text>
        </View>
        <Text style={[styles.muted, { color: colors.text.muted }]}>
          Forecast unavailable right now. Refresh the page or try again
          later.
        </Text>
      </GlassCard>
    );
  }

  const {
    prediction_available: predictionAvailable,
    horizons,
    anchored_baseline: anchoredBaseline,
    confidence,
    metadata,
  } = data;

  // ── State 4 — unavailable (no fit yet) ───────────────────────
  // Calibrating is a NON-event: there is nothing to act on, so it renders as a
  // single quiet strip (icon + one line) rather than a hero card. The full card
  // returns below once there is a real forecast to show.
  if (!predictionAvailable) {
    return (
      <View style={[styles.calibratingStrip, { borderColor: border.subtle, backgroundColor: surface.card }]}>
        <Shield size={14} strokeWidth={1.5} color={semantic.neutral} />
        <Text numberOfLines={1} style={[styles.calibratingText, { color: text.secondary }]}>
          DOB Enforcement Forecast — calibrating, ready within 24h
        </Text>
      </View>
    );
  }

  // ── Staleness — L7 ───────────────────────────────────────────
  const hoursStale = _hoursSince(metadata?.last_validated_timestamp);
  const isHardStale = hoursStale !== null && hoursStale > 48;
  const isSoftStale = hoursStale !== null && hoursStale > 24 && !isHardStale;

  const badgeInfo = _badgeInfo(confidence?.badge);
  const sampleSize = confidence?.sample_size;
  const baselineLabel = anchoredBaseline?.label;
  const isColdStart = confidence?.badge === 'cold_start';
  const parsedLabel = parseBaselineLabel(baselineLabel);

  // C5 + Q2 — cohort footer text. Render only when both borough +
  // projectType extracted AND sample_size is a non-negative number;
  // otherwise suppress the whole footer line (Q2 lock — missing N
  // alongside a present label is unusual data, render nothing).
  const hasSampleSize =
    typeof sampleSize === 'number' && sampleSize >= 0;
  const showCohortFooter =
    hasSampleSize && parsedLabel.borough && parsedLabel.projectType;
  const cohortFooterText = showCohortFooter
    ? `Based on ${sampleSize} similar ${boroughLabel(parsedLabel.borough)} `
      + `${projectTypeLabel(parsedLabel.projectType)} projects`
    : null;

  // ── PR #49 — single adaptive primary forecast ────────────────
  // Horizon adapts to SWO state: 30 days when a recent SWO suppresses
  // near-term enforcement, else 14. Backend computes the field; default
  // to 14 if it's absent (legacy response / older backend).
  const primaryHorizon = data.recommended_primary_horizon || 14;
  const isThirty = primaryHorizon === 30;
  const primaryProb = isThirty ? horizons?.prob_30d : horizons?.prob_14d;
  const primaryBaseline = isThirty
    ? anchoredBaseline?.prob_30d
    : anchoredBaseline?.prob_14d;
  const primaryRatio = _safeRatio(primaryProb, primaryBaseline);
  const primaryTier = hazardRatioToColorTier(primaryRatio);
  const { fg: primaryFg, bg: primaryBg } = tierToStatusColor(primaryTier);
  const primaryVerdict = tierToVerdictLabel(primaryTier);
  const primaryDirection = hazardRatioToDirection(primaryRatio);
  const primaryHorizonLabel = isThirty ? 'Next 30 Days' : 'Next 14 Days';

  // Chip body — mirrors HorizonRow's Q1/Q3 floor logic.
  let primaryChipText;
  let primaryShowArrow;
  if (primaryRatio === null) {
    primaryChipText = '—';
    primaryShowArrow = false;
  } else if (primaryRatio < 0.1) {
    primaryChipText = '< 0.1× typical';
    primaryShowArrow = true;
  } else {
    primaryChipText = `${primaryRatio.toFixed(1)}× typical`;
    primaryShowArrow = true;
  }
  let PrimaryArrowIcon = null;
  if (primaryShowArrow) {
    if (primaryDirection === 'up')        PrimaryArrowIcon = ArrowUp;
    else if (primaryDirection === 'down') PrimaryArrowIcon = ArrowDown;
    else                                  PrimaryArrowIcon = Minus;
  }

  // ── Contradiction guard (display layer only) ─────────────────
  // Which exposure counts as contradiction-worthy: OPEN VIOLATIONS and OPEN
  // COMPLAINTS — present, unresolved DOB matters. `permits_expiring` is
  // deliberately NOT in the trigger: an expiring permit is a future deadline,
  // not an open enforcement fact, so it does not contradict a forward-looking
  // "no acute signals" reading (and it already has its own attention-colored
  // tile). Change this set here if that judgement shifts.
  const openViolations = Number(openExposure?.open_violations) || 0;
  const openComplaints = Number(openExposure?.open_complaints) || 0;
  const hasOpenExposure = openViolations > 0 || openComplaints > 0;
  const suppressReassurance = defcon?.tier === 'NORMAL' && hasOpenExposure;

  const exposureTone = openViolations > 0 ? 'critical' : 'attention';
  const exposureSummary = [
    openViolations > 0
      ? `${openViolations} open violation${openViolations === 1 ? '' : 's'}`
      : null,
    openComplaints > 0
      ? `${openComplaints} open complaint${openComplaints === 1 ? '' : 's'}`
      : null,
  ].filter(Boolean).join('  ·  ');

  // ── State 5 — cold start ─────────────────────────────────────
  // Same treatment as state 4 above: a project still calibrating has no
  // forecast to act on, so it gets one quiet line rather than a hero card.
  // Previously this state rendered the FULL card — title, "Calibrating" badge,
  // the two-line "Personalized forecast not yet available…" tooltip and the
  // "Not enough project history yet…" one-liner — several hundred px of
  // chrome restating that there is nothing to show.
  //
  // The DefconHeader is NOT part of the forecast and is deliberately kept: it
  // is the suppress-not-blend contradiction guard, and when the project has
  // standing open exposure it leads with that exposure. Silencing a calibrating
  // forecast must never silence real open violations. DefconHeader carries its
  // own card styling, so it renders correctly outside the GlassCard.
  if (isColdStart) {
    return (
      <>
        {defcon?.tier && (
          <DefconHeader
            tier={defcon.tier}
            exposureSummary={suppressReassurance ? exposureSummary : null}
            exposureTone={suppressReassurance ? exposureTone : null}
            primaryReason={defcon.primary_reason}
            lastEvaluatedAt={defcon.last_evaluated_at}
            onPressWhy={() => router.push(`/project/${projectId}/defcon`)}
          />
        )}
        <View style={[styles.calibratingStrip, { borderColor: border.subtle, backgroundColor: surface.card }]}>
          <Shield size={14} strokeWidth={1.5} color={semantic.neutral} />
          <Text numberOfLines={1} style={[styles.calibratingText, { color: text.secondary }]}>
            DOB Enforcement Forecast — calibrating, ready within 24h
          </Text>
        </View>
      </>
    );
  }

  // ── State 6 — ready (standard) ───────────────────────────────
  return (
    <GlassCard style={styles.card}>
      {/* Phase 1 Week 11-12 PR-B — Defcon tier header. Only renders
          when the defcon-status endpoint returned a tier; failures
          and missing data degrade silently to the existing UI. */}
      {defcon?.tier && (
        <DefconHeader
          tier={defcon.tier}
          // Suppress-not-blend: when the tier is the reassuring NORMAL but the
          // project carries standing open exposure, DefconHeader leads with the
          // exposure instead and demotes the forecast to context. ELEVATED /
          // IMMEDIATE are already non-reassuring and pass through untouched.
          exposureSummary={suppressReassurance ? exposureSummary : null}
          exposureTone={suppressReassurance ? exposureTone : null}
          primaryReason={defcon.primary_reason}
          lastEvaluatedAt={defcon.last_evaluated_at}
          onPressWhy={() => router.push(`/project/${projectId}/defcon`)}
        />
      )}
      {/* PR #49 L3 — header restructured to a vertical stack so the
          title never wraps mid-word competing with the badge. Title on
          its own full-width row; badge (if any) on the line below. */}
      <View style={styles.header}>
        <IconPod>
          <Shield size={18} strokeWidth={1.5} color={colors.iconPod.iconColor} />
        </IconPod>
        <Text
          style={[styles.title, { color: colors.text.primary }]}
          numberOfLines={1}
          adjustsFontSizeToFit
          minimumFontScale={0.85}
        >
          DOB Enforcement Forecast
        </Text>
      </View>
      {badgeInfo.label && (
        <View style={styles.badgeRow}>
          <View style={[
            styles.badge,
            { backgroundColor: colors.status.cautionBg },
          ]}>
            <Text style={[
              styles.badgeText,
              { color: colors.status.caution },
            ]}>
              {badgeInfo.label}
            </Text>
          </View>
        </View>
      )}

      {/* C8 + D5 — inline tooltip rendered below the header in
          muted secondary copy (no native hover idiom on React
          Native). Only renders when a badge is shown. */}
      {badgeInfo.tooltip && (
        <Text style={[styles.badgeTooltip, { color: colors.text.muted }]}>
          {badgeInfo.tooltip}
        </Text>
      )}

      {/* PR #51 — cold-start one-liner (operator: "personalized message
          way too long, need to be one liner"). L1: the full educational
          copy + per-horizon grid are no longer shown for cold-start at
          all — that data is the cohort baseline, not a personalized
          prediction, so surfacing it ("Tracking -1 1.0× typical") was
          engineer-voice leak. */}
      {/* The cold-start one-liner that used to live here is gone: cold start
          now returns the calibrating strip above and never reaches this card. */}

      {/* PR #51 L1 — the primary forecast + hazard-ratio chip + expandable
          7/14/30 grid + footer. The !isColdStart guard is now always true
          (cold start returns the strip above); kept rather than unwrapped so
          this stays a one-line diff instead of re-indenting the whole block. */}
      {!isColdStart && (
        <>
      {/* PR #49 — single primary forecast (one horizon, one verdict,
          one hazard-ratio chip). L1 adaptive horizon. */}
      <View style={styles.primaryBlock}>
        <Text style={[styles.primaryHorizonLabel, { color: colors.text.muted }]}>
          {primaryHorizonLabel.toUpperCase()}
        </Text>
        {/* Demoted to body weight when the project has open exposure: a
            headline-weight "Tracking normal" next to visible open violations
            reads as a competing verdict even though it is forward-looking.
            The line still renders (nothing is hidden) — it just stops
            shouting. With no open exposure there is nothing to compete with,
            so it keeps its full prominence. */}
        <Text
          style={[
            suppressReassurance ? styles.primaryVerdictDemoted : styles.primaryVerdict,
            { color: primaryFg },
          ]}
        >
          {primaryVerdict}
        </Text>
        <View style={[
          styles.ratioChip,
          { backgroundColor: primaryBg, alignSelf: 'flex-start' },
        ]}>
          <View style={styles.ratioChipRow}>
            {PrimaryArrowIcon && (
              <PrimaryArrowIcon size={12} strokeWidth={2} color={primaryFg} />
            )}
            <Text style={[styles.ratioChipText, { color: primaryFg }]}>
              {primaryChipText}
            </Text>
          </View>
        </View>
        {/* SWO suppression note — only when the 30-day window is in
            effect because of a recent stop-work order. */}
        {isThirty && (
          <Text style={[styles.suppressionNote, { color: colors.text.muted }]}>
            A recent stop-work order suppresses near-term enforcement, so
            this forecast uses a 30-day window.
          </Text>
        )}
      </View>

      {/* PR #49 L2 — "Show details" reveals the full 7/14/30 grid (and
          the long cold-start disclaimer). Collapsed by default. */}
      <Pressable
        onPress={() => setExpanded((v) => !v)}
        style={styles.detailsToggle}
        accessibilityRole="button"
        accessibilityLabel={expanded ? 'Hide forecast details' : 'Show forecast details'}
        hitSlop={8}
      >
        <Text style={[styles.detailsToggleText, { color: colors.text.secondary }]}>
          {expanded ? 'Hide details' : 'Show details'}
        </Text>
        {expanded
          ? <ChevronUp size={14} strokeWidth={1.5} color={colors.text.secondary} />
          : <ChevronDown size={14} strokeWidth={1.5} color={colors.text.secondary} />}
      </Pressable>

      {expanded && (
        <View style={styles.detailsBody}>
          {/* C6 — full educational disclaimer for cold-start fits. */}
          {isColdStart && (
            <ColdStartDisclaimer
              borough={parsedLabel.borough}
              projectType={parsedLabel.projectType}
              colors={colors}
            />
          )}
          {/* C2 — three horizon rows, Title Case per the lock copy. */}
          <HorizonRow
            label="Next 7 Days"
            prob={horizons?.prob_7d}
            baseline={anchoredBaseline?.prob_7d}
            colors={colors}
          />
          <HorizonRow
            label="Next 14 Days"
            prob={horizons?.prob_14d}
            baseline={anchoredBaseline?.prob_14d}
            colors={colors}
          />
          <HorizonRow
            label="Next 30 Days"
            prob={horizons?.prob_30d}
            baseline={anchoredBaseline?.prob_30d}
            colors={colors}
          />
        </View>
      )}

      {/* Footer — cohort baseline phrase (C5) + staleness chip (L7).
          Cohort phrase suppressed entirely when sample_size or the
          parsed label is missing (Q2 lock). */}
      <View style={[
        styles.footer,
        { borderTopColor: colors.border.subtle },
      ]}>
        {cohortFooterText && (
          <Text style={[styles.footerLabel, { color: colors.text.muted }]}>
            {cohortFooterText}
          </Text>
        )}
        {(isSoftStale || isHardStale) && (
          <View style={styles.staleRow}>
            {isHardStale
              ? <AlertTriangle size={12} strokeWidth={1.5}
                  color={colors.status.error} />
              : <Clock size={12} strokeWidth={1.5}
                  color={colors.status.caution} />
            }
            <Text style={[
              styles.staleText,
              { color: isHardStale
                  ? colors.status.error
                  : colors.status.caution },
            ]}>
              {isHardStale
                ? `Forecast last refreshed ${Math.round(hoursStale)}h ago — over 48h stale`
                : `Forecast last refreshed ${Math.round(hoursStale)}h ago`}
            </Text>
          </View>
        )}
      </View>
        </>
      )}
    </GlassCard>
  );
}

// ── Styles ───────────────────────────────────────────────────────

const styles = StyleSheet.create({
  card: {
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  title: {
    ...typography.h3,
    flex: 1,
  },
  // PR #49 L3 — badge moved onto its own line below the title so it
  // never competes for horizontal space (the cause of the mid-word
  // wrap). Left-aligned chip directly under the header row.
  badgeRow: {
    flexDirection: 'row',
    marginBottom: spacing.sm,
  },
  badge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: borderRadius.sm,
  },
  badgeText: {
    ...typography.label,
    fontSize: 10,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: spacing.sm,
  },
  horizonLabel: {
    ...typography.body,
    flexShrink: 1,
  },
  rowRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  // PR #15D.1 — verdict label (lock C3) replaces the prior
  // probValue + baselineValue styles. Coloured per L6 tier at the
  // call site; falls back to text.muted when ratio is null.
  verdictLabel: {
    ...typography.body,
    fontWeight: '600',
    flexShrink: 1,
    textAlign: 'right',
  },
  ratioChip: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: borderRadius.sm,
    alignItems: 'center',
  },
  // C4 — flex row inside the chip for the lucide arrow icon +
  // ratio text. Small gap keeps the arrow visually attached.
  ratioChipRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  ratioChipText: {
    ...typography.label,
    fontSize: 11,
    letterSpacing: 0.5,
    textTransform: 'none',
  },
  // C8 + D5 — inline tooltip below the header badge. Sits in the
  // muted secondary tone so it reads as supplementary copy, not as
  // a separate data row.
  badgeTooltip: {
    ...typography.small,
    fontSize: 12,
    lineHeight: 16,
    marginBottom: spacing.sm,
  },
  // PR #49 — short cold-start line shown above the primary forecast.
  // The full educational disclaimer is revealed via "Show details".
  coldStartShort: {
    ...typography.small,
    fontSize: 12,
    lineHeight: 16,
    marginBottom: spacing.sm,
  },
  // PR #49 — single primary forecast block. Horizon sub-label +
  // prominent verdict + hazard-ratio chip, stacked.
  primaryBlock: {
    paddingVertical: spacing.sm,
    gap: spacing.xs,
  },
  primaryHorizonLabel: {
    ...typography.label,
    fontSize: 11,
    letterSpacing: 1.5,
  },
  primaryVerdict: {
    ...typography.h2,
    fontWeight: '600',
  },
  // Same color/token, body weight instead of h2 — used when open exposure
  // is present so the forecast reads as context, not a headline verdict.
  primaryVerdictDemoted: {
    ...typography.body,
    fontSize: 14,
    lineHeight: 18,
    fontWeight: '600',
  },
  suppressionNote: {
    ...typography.small,
    fontSize: 12,
    lineHeight: 16,
    marginTop: spacing.xs,
  },
  // PR #49 — "Show details" expandable toggle row.
  detailsToggle: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingVertical: spacing.sm,
  },
  detailsToggleText: {
    ...typography.label,
    fontSize: 11,
    letterSpacing: 1,
  },
  detailsBody: {
    marginTop: spacing.xs,
  },
  footer: {
    marginTop: spacing.sm,
    paddingTop: spacing.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
    gap: spacing.xs,
  },
  footerLabel: {
    ...typography.small,
  },
  staleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  staleText: {
    ...typography.small,
    fontSize: 12,
  },
  center: {
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.lg,
  },
  // Calibrating strip — one line, no hero card (empty state must be small).
  calibratingStrip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    borderWidth: 1,
    borderRadius: borderRadius.md,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    marginBottom: spacing.md,
  },
  calibratingText: { flex: 1, fontSize: 12 },
  muted: {
    ...typography.body,
    paddingVertical: spacing.sm,
  },
  disclaimer: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: borderRadius.md,
    padding: spacing.sm,
    marginBottom: spacing.sm,
    gap: spacing.xs,
  },
  disclaimerHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginBottom: 2,
  },
  disclaimerTitle: {
    ...typography.label,
    fontSize: 11,
    letterSpacing: 0.5,
  },
  disclaimerBody: {
    ...typography.small,
    fontSize: 12,
    lineHeight: 16,
  },
});
