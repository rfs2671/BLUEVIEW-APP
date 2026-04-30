/**
 * FilingStatusCard
 * ════════════════
 * MR.7. Live status panel for an active filing_job (the cloud-side
 * state machine introduced in MR.6). Polls
 *   GET /api/permit-renewals/{permit_renewal_id}/filing-jobs
 * every 5 seconds, picks the most-recent job, and renders:
 *   • a status badge (queued / claimed / in_progress / filed /
 *     completed / failed / cancelled)
 *   • a vertical timeline of audit_log entries
 *   • CAPTCHA / 2FA prompt panel when the worker raised a challenge
 *   • DOB confirmation number + "View on DOB NOW" deep-link on completed
 *   • failure_reason + Retry/Cancel on failed
 *   • Cancel button on non-terminal statuses
 *
 * Polling cadence: 5 seconds. Stops automatically when:
 *   - status reaches a terminal state (completed / failed / cancelled)
 *   - the component unmounts
 *
 * No websockets / SSE / react-query — keeps the surface minimal for
 * v1. If a future commit moves to push-based updates, the polling
 * effect is the only thing that needs to change; the render contract
 * is independent of how we receive the doc.
 *
 * Props:
 *   permitRenewalId   — the parent renewal _id; used in API paths
 *   initialJob        — the latest filing_job from the parent's
 *                       initial fetch. May be null (no jobs yet).
 *   onJobUpdate       — callback fired whenever we receive an updated
 *                       job from polling. Lets the parent re-render
 *                       (e.g. swap History row state, hide File button).
 *   onTerminal        — callback fired once when status transitions
 *                       to a terminal state. Lets the parent toast +
 *                       re-fetch the renewal record.
 *   onRetryRequested  — callback to invoke /file again. Parent owns
 *                       the enqueue logic; this card just signals.
 */

import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  Linking,
  Image,
  TextInput,
} from 'react-native';
import {
  CheckCircle,
  AlertTriangle,
  Clock,
  Loader,
  XCircle,
  ExternalLink,
  RefreshCw,
  Send,
  ShieldCheck,
} from 'lucide-react-native';
import { spacing, borderRadius, typography } from '../../styles/theme';
import { useTheme } from '../../context/ThemeContext';
import apiClient from '../../utils/api';

// ── Constants ──────────────────────────────────────────────────────

const POLL_INTERVAL_MS = 5_000;

// Mirrors backend/server.py FILING_JOB_TERMINAL_STATUSES. If the
// backend adds a new terminal status, update this set or the polling
// will loop forever on it.
const TERMINAL_STATUSES = new Set([
  'filed',      // DOB accepted, awaiting expiry stamp (MR.8 watcher transitions to completed)
  'completed',  // DOB stamped expiry, fully done
  'failed',
  'cancelled',
]);

// MR.8: when the dob_approval_watcher transitions a renewal to
// completed, it also flips the FilingJob to status=completed AND
// appends a renewal_confirmed_in_dob audit event with metadata
// {old_expiration, new_expiration}. The card uses the audit event
// to surface the new expiration without an extra round-trip.
const RENEWAL_CONFIRMED_EVENT_TYPE = 'renewal_confirmed_in_dob';
const STUCK_AT_DOB_EVENT_TYPE = 'stuck_at_dob';
const FILED_EVENT_TYPE = 'filed';

const findLatestEventByType = (job, eventType) => {
  if (!job?.audit_log) return null;
  for (let i = job.audit_log.length - 1; i >= 0; i--) {
    if (job.audit_log[i].event_type === eventType) return job.audit_log[i];
  }
  return null;
};

// DOB NOW landing page — operator navigates manually because the
// deep-link flow doesn't carry session context (research 2026-04-29).
const DOB_NOW_PORTAL_URL = 'https://a810-dobnow.nyc.gov/Publish/Index.html#!/';

// ── Status badge config ────────────────────────────────────────────

const STATUS_BADGE = {
  queued:      { label: 'Queued',           color: '#6b7280', bg: '#6b728020', Icon: Clock },
  claimed:     { label: 'Agent Picked Up',  color: '#3b82f6', bg: '#3b82f620', Icon: Loader },
  in_progress: { label: 'Filing in Progress', color: '#f59e0b', bg: '#f59e0b20', Icon: Loader },
  filed:       { label: 'Filed — Awaiting DOB', color: '#10b981', bg: '#10b98120', Icon: ShieldCheck },
  completed:   { label: 'Completed',        color: '#10b981', bg: '#10b98120', Icon: CheckCircle },
  failed:      { label: 'Failed',           color: '#ef4444', bg: '#ef444420', Icon: XCircle },
  cancelled:   { label: 'Cancelled',        color: '#6b7280', bg: '#6b728020', Icon: XCircle },
};

// User-facing labels for audit_log event_type values. The taxonomy
// is a deliberate superset of FilingJobStatus values so the worker
// can also record handler-level events (claimed, started, captcha_required,
// 2fa_required, operator_response, stale_claim_recovered, etc.) without
// inventing new status entries.
const EVENT_TYPE_LABEL = {
  queued:                          'Job queued',
  claimed:                         'Agent picked up',
  started:                         'Filing started',
  filed:                           'Filed at DOB NOW',
  completed:                       'Completed',
  failed:                          'Filing failed',
  cancelled:                       'Cancelled',
  cancellation_requested:          'Cancellation requested',
  stale_claim_recovered:           'Stale claim recovered',
  retry_limit_exceeded:            'Retry limit exceeded',
  captcha_required:                'CAPTCHA required',
  '2fa_required':                  '2FA required',
  operator_response:               'Operator submitted response',
  non_critical_unmappable_fields:  'Non-critical fields skipped',
  renewal_confirmed_in_dob:        'Renewal confirmed by DOB',
  stuck_at_dob:                    'Stuck at DOB (>14 days)',
};

const formatEventType = (et) => EVENT_TYPE_LABEL[et] || (et ? String(et) : 'Event');

// ── Timestamp helpers ──────────────────────────────────────────────

const formatTime = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '—';
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
};

// ── Audit-log helpers ──────────────────────────────────────────────

const isOpenChallenge = (job, challengeKind) => {
  // A challenge is "open" if the most recent challenge event of the
  // given kind has NOT been answered by a subsequent operator_response
  // event whose metadata.response_kind matches. We walk the audit_log
  // newest-to-oldest looking for the answer first; if we find a
  // challenge before finding the answer, it's still open.
  if (!job?.audit_log) return false;
  const expectedAnswerKind =
    challengeKind === 'captcha_required' ? 'captcha_response' : '2fa_response';

  // Walk newest first.
  for (let i = job.audit_log.length - 1; i >= 0; i--) {
    const ev = job.audit_log[i];
    if (
      ev.event_type === 'operator_response' &&
      ev.metadata?.response_kind === expectedAnswerKind
    ) {
      // Found a response newer than any challenge of this kind.
      return false;
    }
    if (ev.event_type === challengeKind) {
      // Found the challenge before any response — still open.
      return true;
    }
  }
  return false;
};

const findLatestChallengeEvent = (job, challengeKind) => {
  if (!job?.audit_log) return null;
  for (let i = job.audit_log.length - 1; i >= 0; i--) {
    if (job.audit_log[i].event_type === challengeKind) {
      return job.audit_log[i];
    }
  }
  return null;
};

// ── Main component ─────────────────────────────────────────────────

const FilingStatusCard = ({
  permitRenewalId,
  initialJob,
  onJobUpdate,
  onTerminal,
  onRetryRequested,
}) => {
  const { colors } = useTheme();
  const s = buildStyles(colors);

  const [job, setJob] = useState(initialJob || null);
  const [polling, setPolling] = useState(false);
  const [confirmCancelOpen, setConfirmCancelOpen] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  // Refs for stable polling across renders + cleanup on unmount.
  const intervalRef = useRef(null);
  const onTerminalFiredRef = useRef(false);

  const status = job?.status;
  const filingJobId = job?.id || job?._id;
  const isTerminal = status && TERMINAL_STATUSES.has(status);

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    setPolling(false);
  }, []);

  // Polling effect. Re-establishes when permitRenewalId changes; tears
  // down on unmount or once status is terminal.
  useEffect(() => {
    if (!permitRenewalId) return undefined;
    if (isTerminal) {
      stopPolling();
      return undefined;
    }

    let cancelled = false;

    const tick = async () => {
      try {
        setPolling(true);
        const resp = await apiClient.get(
          `/api/permit-renewals/${permitRenewalId}/filing-jobs`
        );
        if (cancelled) return;
        const jobs = resp.data?.filing_jobs || [];
        // The endpoint already sorts newest-first; take [0]. If the
        // operator just enqueued a NEW job (rare during an active
        // poll, but possible if they used Retry), that latest one
        // becomes the focus.
        const latest = jobs[0] || null;
        setJob(latest);
        if (latest && typeof onJobUpdate === 'function') {
          onJobUpdate(latest);
        }
        if (
          latest &&
          TERMINAL_STATUSES.has(latest.status) &&
          !onTerminalFiredRef.current &&
          typeof onTerminal === 'function'
        ) {
          onTerminalFiredRef.current = true;
          onTerminal(latest);
        }
      } catch (e) {
        // Soft fail — keep polling. A transient 5xx on the backend
        // shouldn't kill the panel.
        if (!cancelled) {
          console.warn('[FilingStatusCard] poll failed:', e?.message || e);
        }
      } finally {
        if (!cancelled) setPolling(false);
      }
    };

    // Fire immediately so the first render reflects the freshest
    // server state, then settle into the interval.
    tick();
    intervalRef.current = setInterval(tick, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      stopPolling();
    };
    // We intentionally exclude `isTerminal` from deps so the effect
    // doesn't re-run on every job mutation; the early-return above
    // handles the terminal case via the next render's setup.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [permitRenewalId, stopPolling]);

  // If status flips to terminal mid-effect (through state update),
  // explicitly tear down the interval.
  useEffect(() => {
    if (isTerminal) {
      stopPolling();
    }
  }, [isTerminal, stopPolling]);

  const handleCancel = async () => {
    if (!filingJobId) return;
    setCancelling(true);
    try {
      const resp = await apiClient.delete(
        `/api/permit-renewals/${permitRenewalId}/filing-jobs/${filingJobId}`
      );
      // Two response shapes: hard-cancel (queued) returns `cancelled: true`,
      // soft-cancel (in-flight) returns `cancellation_requested: true`.
      // Re-fetch on next tick — we don't try to merge the response here.
      // If the user is on a soft-cancel path, the UI shows
      // "Cancellation requested..." until the worker reports back.
      if (resp.data?.cancelled) {
        // Optimistic update to cancelled.
        setJob((prev) => prev ? { ...prev, status: 'cancelled' } : prev);
      } else if (resp.data?.cancellation_requested) {
        setJob((prev) => prev ? { ...prev, cancellation_requested: true } : prev);
      }
    } catch (e) {
      console.warn('[FilingStatusCard] cancel failed:', e?.message || e);
    } finally {
      setCancelling(false);
      setConfirmCancelOpen(false);
    }
  };

  const handleViewOnDOBNow = () => {
    Linking.openURL(DOB_NOW_PORTAL_URL).catch(() => {
      console.warn('[FilingStatusCard] could not open DOB NOW portal');
    });
  };

  const handleRetry = () => {
    if (typeof onRetryRequested === 'function') {
      onRetryRequested();
    }
  };

  // ── Render branches ──────────────────────────────────────────────

  if (!job) {
    return (
      <View style={s.cardEmpty}>
        <ActivityIndicator size="small" color={colors.text.muted} />
        <Text style={s.emptyText}>Loading filing status…</Text>
      </View>
    );
  }

  const badge = STATUS_BADGE[status] || STATUS_BADGE.queued;
  const BadgeIcon = badge.Icon;

  // CAPTCHA / 2FA panel state — derived from audit_log.
  const captchaOpen = isOpenChallenge(job, 'captcha_required');
  const tfaOpen = isOpenChallenge(job, '2fa_required');
  const captchaEvent = captchaOpen ? findLatestChallengeEvent(job, 'captcha_required') : null;
  const tfaEvent = tfaOpen ? findLatestChallengeEvent(job, '2fa_required') : null;

  // MR.8 — derived state for the post-filed tracking surface.
  // Even when the FilingJob.status hasn't been flipped yet (the
  // dob_approval_watcher might run after the worker reports filed),
  // a renewal_confirmed_in_dob audit event is the authoritative
  // signal that DOB has stamped the new expiration. Surface it.
  const renewalConfirmedEvent = findLatestEventByType(job, RENEWAL_CONFIRMED_EVENT_TYPE);
  const stuckAtDob = !!findLatestEventByType(job, STUCK_AT_DOB_EVENT_TYPE);
  const filedEvent = findLatestEventByType(job, FILED_EVENT_TYPE);
  const newExpiration = renewalConfirmedEvent?.metadata?.new_expiration
    || job.new_expiration_date
    || null;

  // Days the filing has been sitting in DOB's queue. Computed from
  // the `filed` audit event timestamp — that's the moment DOB
  // processing started counting. Falls back to filed_at on the doc
  // if the event taxonomy ever shifts.
  const daysInDobQueue = (() => {
    const startIso = filedEvent?.timestamp || job.filed_at || null;
    if (!startIso) return null;
    const startMs = new Date(startIso).getTime();
    if (Number.isNaN(startMs)) return null;
    const days = Math.max(
      0,
      Math.floor((Date.now() - startMs) / (24 * 60 * 60 * 1000))
    );
    return days;
  })();

  return (
    <View style={s.card}>
      {/* Header: status badge + filing-job ID */}
      <View style={s.header}>
        <View style={[s.badge, { backgroundColor: badge.bg, borderColor: badge.color }]}>
          <BadgeIcon size={13} color={badge.color} />
          <Text style={[s.badgeText, { color: badge.color }]}>{badge.label}</Text>
        </View>
        {polling && !isTerminal && (
          <View style={s.pollingDot}>
            <ActivityIndicator size="small" color={colors.text.muted} />
          </View>
        )}
      </View>

      {/* Cancellation-requested banner (soft cancel in-flight) */}
      {job.cancellation_requested && !isTerminal && (
        <View style={s.bannerWarn}>
          <AlertTriangle size={14} color="#f59e0b" />
          <Text style={s.bannerText}>
            Cancellation requested. Waiting for the agent to acknowledge…
          </Text>
        </View>
      )}

      {/* CAPTCHA prompt — when worker raised one and operator hasn't responded */}
      {captchaOpen && (
        <OperatorChallengePrompt
          kind="captcha"
          eventType="captcha_response"
          permitRenewalId={permitRenewalId}
          filingJobId={filingJobId}
          challengeEvent={captchaEvent}
          onSubmitted={(updated) => setJob(updated)}
          colors={colors}
          styles={s}
        />
      )}

      {/* 2FA prompt — same pattern */}
      {tfaOpen && (
        <OperatorChallengePrompt
          kind="2fa"
          eventType="2fa_response"
          permitRenewalId={permitRenewalId}
          filingJobId={filingJobId}
          challengeEvent={tfaEvent}
          onSubmitted={(updated) => setJob(updated)}
          colors={colors}
          styles={s}
        />
      )}

      {/* MR.8 — Completed renewal summary. Renders for both
          status==='completed' AND for the case where the watcher
          flipped a stale filed → completed before the next polling
          tick caught up: renewalConfirmedEvent is the authoritative
          signal even if status string is lagging. */}
      {(status === 'completed' || renewalConfirmedEvent) && (
        <View style={s.completedBlock}>
          <View style={[s.bannerInfo, { borderColor: '#10b98180', backgroundColor: '#10b98125' }]}>
            <ShieldCheck size={16} color="#10b981" />
            <Text style={[s.bannerText, { color: '#065f46', fontFamily: typography.semibold }]}>
              Permit renewed!
            </Text>
          </View>
          {newExpiration && (
            <View style={s.confirmationRow}>
              <Text style={s.confirmationLabel}>New Expiration</Text>
              <Text style={s.confirmationValue}>{newExpiration}</Text>
            </View>
          )}
          {job.dob_confirmation_number && (
            <View style={s.confirmationRow}>
              <Text style={s.confirmationLabel}>DOB Confirmation</Text>
              <Text style={s.confirmationValue}>
                {job.dob_confirmation_number}
              </Text>
            </View>
          )}
          <Pressable style={s.outlineButton} onPress={handleViewOnDOBNow}>
            <ExternalLink size={14} color={colors.text.primary} />
            <Text style={s.outlineButtonText}>View on DOB NOW</Text>
          </Pressable>
        </View>
      )}

      {/* Filed (awaiting DOB approval): bridge to MR.8 messaging.
          Only render when there's NO renewal_confirmed_in_dob event
          yet — once the watcher confirms, the completed block above
          takes over even before the FilingJob.status flips. */}
      {status === 'filed' && !renewalConfirmedEvent && (
        <View style={s.filedBlock}>
          <View style={s.bannerInfo}>
            <Clock size={14} color="#10b981" />
            <Text style={s.bannerText}>
              Filing submitted. DOB processing typically takes 5–10 business days.
              We'll watch for the renewed expiration date and update this record
              automatically.
            </Text>
          </View>
          {/* MR.8: surface the days-in-queue counter so the operator
              can see at a glance whether the filing is on the normal
              5–10 day track or starting to look stuck. */}
          {typeof daysInDobQueue === 'number' && (
            <View style={s.queueRow}>
              <Text style={s.queueLabel}>Days in DOB Queue</Text>
              <Text style={[
                s.queueValue,
                stuckAtDob && { color: '#f59e0b' },
              ]}>
                {daysInDobQueue}
              </Text>
            </View>
          )}
          {/* Stuck-at-DOB warning surfaced when the watcher has
              already flagged the renewal (>14 days) and we haven't
              received a confirmation yet. */}
          {stuckAtDob && (
            <View style={s.bannerWarn}>
              <AlertTriangle size={14} color="#f59e0b" />
              <Text style={s.bannerText}>
                This filing has been sitting at DOB longer than usual.
                Consider checking DOB NOW directly — the agent can't
                un-stick a filing that DOB hasn't processed.
              </Text>
            </View>
          )}
        </View>
      )}

      {/* Failed: reason + Retry / Cancel */}
      {status === 'failed' && (
        <View style={s.failedBlock}>
          {job.failure_reason && (
            <Text style={s.failureReason}>
              Failure reason: {job.failure_reason}
            </Text>
          )}
          <View style={s.failedActions}>
            <Pressable style={s.primaryButton} onPress={handleRetry}>
              <RefreshCw size={14} color="#fff" />
              <Text style={s.primaryButtonText}>Retry Filing</Text>
            </Pressable>
          </View>
        </View>
      )}

      {/* Audit-log timeline */}
      <View style={s.timelineWrap}>
        <Text style={s.timelineHeader}>Activity</Text>
        <View style={s.timeline}>
          {(job.audit_log || []).map((ev, i) => {
            const isLast = i === (job.audit_log || []).length - 1;
            return (
              <View key={i} style={s.timelineRow}>
                <View style={s.timelineDotColumn}>
                  <View
                    style={[
                      s.timelineDot,
                      { backgroundColor: badge.color },
                    ]}
                  />
                  {!isLast && <View style={s.timelineLine} />}
                </View>
                <View style={s.timelineContent}>
                  <Text style={s.timelineEventType}>
                    {formatEventType(ev.event_type)}
                  </Text>
                  <Text style={s.timelineDetail}>{ev.detail}</Text>
                  <Text style={s.timelineTime}>
                    {formatTime(ev.timestamp)} · {ev.actor}
                  </Text>
                </View>
              </View>
            );
          })}
          {(job.audit_log || []).length === 0 && (
            <Text style={s.timelineEmpty}>No events yet.</Text>
          )}
        </View>
      </View>

      {/* Cancel button — only on non-terminal, not already requested */}
      {!isTerminal && !job.cancellation_requested && (
        <View style={s.cancelRow}>
          {confirmCancelOpen ? (
            <View style={s.confirmCancelInline}>
              <Text style={s.confirmCancelText}>Cancel this filing?</Text>
              <View style={s.confirmCancelButtons}>
                <Pressable
                  style={s.outlineButton}
                  onPress={() => setConfirmCancelOpen(false)}
                  disabled={cancelling}
                >
                  <Text style={s.outlineButtonText}>Keep filing</Text>
                </Pressable>
                <Pressable
                  style={[s.dangerButton, cancelling && s.buttonDisabled]}
                  onPress={handleCancel}
                  disabled={cancelling}
                >
                  {cancelling ? (
                    <ActivityIndicator size="small" color="#fff" />
                  ) : (
                    <>
                      <XCircle size={14} color="#fff" />
                      <Text style={s.dangerButtonText}>Yes, cancel</Text>
                    </>
                  )}
                </Pressable>
              </View>
            </View>
          ) : (
            <Pressable
              style={s.cancelLink}
              onPress={() => setConfirmCancelOpen(true)}
            >
              <Text style={s.cancelLinkText}>Cancel filing</Text>
            </Pressable>
          )}
        </View>
      )}
    </View>
  );
};

// ── OperatorChallengePrompt subcomponent ───────────────────────────

const OperatorChallengePrompt = ({
  kind,
  eventType,
  permitRenewalId,
  filingJobId,
  challengeEvent,
  onSubmitted,
  colors,
  styles: s,
}) => {
  const [value, setValue] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async () => {
    if (!value.trim()) {
      setError('Required');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const resp = await apiClient.post(
        `/api/permit-renewals/${permitRenewalId}/filing-jobs/${filingJobId}/operator-input`,
        { event_type: eventType, value: value.trim() }
      );
      if (typeof onSubmitted === 'function' && resp.data) {
        onSubmitted(resp.data);
      }
      setValue('');
    } catch (e) {
      setError(e?.response?.data?.detail?.message || 'Submission failed');
    } finally {
      setSubmitting(false);
    }
  };

  const captchaImageB64 = challengeEvent?.metadata?.captcha_image_b64;
  const channel = challengeEvent?.metadata?.channel; // for 2FA — sms / email

  return (
    <View style={s.challengeBlock}>
      <View style={s.challengeHeader}>
        <AlertTriangle size={14} color="#f59e0b" />
        <Text style={s.challengeTitle}>
          {kind === 'captcha' ? 'CAPTCHA required' : '2FA code required'}
        </Text>
      </View>
      {kind === 'captcha' && captchaImageB64 && (
        <Image
          source={{ uri: `data:image/png;base64,${captchaImageB64}` }}
          style={s.captchaImage}
          resizeMode="contain"
        />
      )}
      {kind === '2fa' && channel && (
        <Text style={s.challengeHint}>
          Code sent via {channel}. Enter the code from your{' '}
          {channel === 'sms' ? 'phone' : 'email'}.
        </Text>
      )}
      <TextInput
        style={s.challengeInput}
        value={value}
        onChangeText={(t) => {
          setValue(t);
          if (error) setError(null);
        }}
        placeholder={kind === 'captcha' ? 'Type the characters above' : 'Enter code'}
        placeholderTextColor={colors.text.muted}
        autoCapitalize="characters"
        autoCorrect={false}
      />
      {error && <Text style={s.challengeError}>{error}</Text>}
      <Pressable
        style={[s.primaryButton, submitting && s.buttonDisabled]}
        onPress={handleSubmit}
        disabled={submitting}
      >
        {submitting ? (
          <ActivityIndicator size="small" color="#fff" />
        ) : (
          <>
            <Send size={14} color="#fff" />
            <Text style={s.primaryButtonText}>Submit</Text>
          </>
        )}
      </Pressable>
    </View>
  );
};

// ── Styles ─────────────────────────────────────────────────────────

function buildStyles(colors) {
  return StyleSheet.create({
    card: {
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.lg,
      padding: spacing.lg,
      marginTop: spacing.sm,
      borderWidth: 1,
      borderColor: colors.glass.border,
      gap: spacing.md,
    },
    cardEmpty: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
      padding: spacing.md,
    },
    emptyText: {
      fontFamily: typography.regular,
      fontSize: 13,
      color: colors.text.muted,
    },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
    },
    badge: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      paddingHorizontal: 10,
      paddingVertical: 4,
      borderRadius: borderRadius.sm,
      borderWidth: 1,
    },
    badgeText: {
      fontFamily: typography.semibold,
      fontSize: 12,
      letterSpacing: 0.3,
    },
    pollingDot: {
      opacity: 0.5,
    },

    // ── banners ───────────────────────────────────────────────────
    bannerWarn: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: 8,
      padding: spacing.sm,
      backgroundColor: '#f59e0b15',
      borderRadius: borderRadius.md,
      borderWidth: 1,
      borderColor: '#f59e0b40',
    },
    bannerInfo: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: 8,
      padding: spacing.sm,
      backgroundColor: '#10b98115',
      borderRadius: borderRadius.md,
      borderWidth: 1,
      borderColor: '#10b98140',
    },
    bannerText: {
      flex: 1,
      fontFamily: typography.regular,
      fontSize: 12,
      color: colors.text.secondary,
      lineHeight: 18,
    },

    // ── completed block ───────────────────────────────────────────
    completedBlock: {
      gap: spacing.sm,
    },
    // ── filed block (MR.8) ────────────────────────────────────────
    filedBlock: {
      gap: spacing.sm,
    },
    queueRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingVertical: spacing.xs,
      paddingHorizontal: spacing.md,
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.md,
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    queueLabel: {
      fontFamily: typography.regular,
      fontSize: 12,
      color: colors.text.muted,
    },
    queueValue: {
      fontFamily: typography.semibold,
      fontSize: 14,
      color: colors.text.primary,
    },
    confirmationRow: {
      paddingVertical: spacing.sm,
      paddingHorizontal: spacing.md,
      backgroundColor: '#10b98115',
      borderRadius: borderRadius.md,
      borderWidth: 1,
      borderColor: '#10b98140',
    },
    confirmationLabel: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: colors.text.muted,
      letterSpacing: 0.3,
      marginBottom: 2,
    },
    confirmationValue: {
      fontFamily: typography.semibold,
      fontSize: 16,
      color: colors.text.primary,
    },

    // ── failed block ──────────────────────────────────────────────
    failedBlock: {
      gap: spacing.sm,
      padding: spacing.sm,
      backgroundColor: '#ef444415',
      borderRadius: borderRadius.md,
      borderWidth: 1,
      borderColor: '#ef444440',
    },
    failureReason: {
      fontFamily: typography.regular,
      fontSize: 12,
      color: '#ef4444',
      lineHeight: 18,
    },
    failedActions: {
      flexDirection: 'row',
      gap: spacing.sm,
    },

    // ── timeline ──────────────────────────────────────────────────
    timelineWrap: {
      gap: spacing.sm,
    },
    timelineHeader: {
      fontFamily: typography.semibold,
      fontSize: 12,
      color: colors.text.muted,
      letterSpacing: 0.5,
    },
    timeline: {
      gap: spacing.sm,
    },
    timelineRow: {
      flexDirection: 'row',
      gap: spacing.sm,
    },
    timelineDotColumn: {
      width: 16,
      alignItems: 'center',
    },
    timelineDot: {
      width: 10,
      height: 10,
      borderRadius: 5,
      marginTop: 4,
    },
    timelineLine: {
      flex: 1,
      width: 2,
      backgroundColor: colors.glass.border,
      marginTop: 4,
      marginBottom: -4,
    },
    timelineContent: {
      flex: 1,
      paddingBottom: spacing.sm,
    },
    timelineEventType: {
      fontFamily: typography.semibold,
      fontSize: 13,
      color: colors.text.primary,
    },
    timelineDetail: {
      fontFamily: typography.regular,
      fontSize: 12,
      color: colors.text.secondary,
      marginTop: 2,
    },
    timelineTime: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: colors.text.muted,
      marginTop: 4,
    },
    timelineEmpty: {
      fontFamily: typography.regular,
      fontSize: 12,
      color: colors.text.muted,
      fontStyle: 'italic',
    },

    // ── challenge ─────────────────────────────────────────────────
    challengeBlock: {
      gap: spacing.sm,
      padding: spacing.md,
      backgroundColor: '#f59e0b15',
      borderRadius: borderRadius.md,
      borderWidth: 1,
      borderColor: '#f59e0b40',
    },
    challengeHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
    },
    challengeTitle: {
      fontFamily: typography.semibold,
      fontSize: 13,
      color: '#f59e0b',
    },
    challengeHint: {
      fontFamily: typography.regular,
      fontSize: 12,
      color: colors.text.secondary,
    },
    captchaImage: {
      width: '100%',
      height: 80,
      backgroundColor: '#fff',
      borderRadius: borderRadius.sm,
    },
    challengeInput: {
      borderWidth: 1,
      borderColor: colors.glass.border,
      borderRadius: borderRadius.md,
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.sm,
      fontFamily: typography.regular,
      fontSize: 14,
      color: colors.text.primary,
      backgroundColor: colors.glass.background,
    },
    challengeError: {
      fontFamily: typography.regular,
      fontSize: 11,
      color: '#ef4444',
    },

    // ── buttons ───────────────────────────────────────────────────
    primaryButton: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 6,
      paddingVertical: spacing.sm + 2,
      paddingHorizontal: spacing.md,
      borderRadius: borderRadius.md,
      backgroundColor: '#3b82f6',
    },
    primaryButtonText: {
      fontFamily: typography.semibold,
      fontSize: 13,
      color: '#fff',
      letterSpacing: 0.3,
    },
    outlineButton: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 6,
      paddingVertical: spacing.sm,
      paddingHorizontal: spacing.md,
      borderRadius: borderRadius.md,
      borderWidth: 1,
      borderColor: colors.glass.border,
      backgroundColor: 'transparent',
    },
    outlineButtonText: {
      fontFamily: typography.semibold,
      fontSize: 13,
      color: colors.text.primary,
    },
    dangerButton: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 6,
      paddingVertical: spacing.sm,
      paddingHorizontal: spacing.md,
      borderRadius: borderRadius.md,
      backgroundColor: '#ef4444',
    },
    dangerButtonText: {
      fontFamily: typography.semibold,
      fontSize: 13,
      color: '#fff',
    },
    buttonDisabled: {
      opacity: 0.6,
    },

    // ── cancel row ────────────────────────────────────────────────
    cancelRow: {
      paddingTop: spacing.sm,
      borderTopWidth: 1,
      borderTopColor: colors.glass.border,
    },
    cancelLink: {
      alignItems: 'center',
      paddingVertical: spacing.xs,
    },
    cancelLinkText: {
      fontFamily: typography.regular,
      fontSize: 12,
      color: colors.text.muted,
      textDecorationLine: 'underline',
    },
    confirmCancelInline: {
      gap: spacing.sm,
    },
    confirmCancelText: {
      fontFamily: typography.medium,
      fontSize: 13,
      color: colors.text.primary,
      textAlign: 'center',
    },
    confirmCancelButtons: {
      flexDirection: 'row',
      gap: spacing.sm,
      justifyContent: 'center',
    },
  });
}

export default FilingStatusCard;
