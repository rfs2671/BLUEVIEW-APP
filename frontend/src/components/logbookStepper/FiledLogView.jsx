import React from 'react';
import {
  View, Text, Pressable, Image, StyleSheet, ActivityIndicator,
} from 'react-native';
import { useRouter } from 'expo-router';
import { Camera, Lock, FileCheck2 } from 'lucide-react-native';
import { Card } from './primitives';
import {
  summarizeFiledLog, photographsSection, filedAttestation,
} from '../../utils/filedLogSummary';
import { logbooksAPI } from '../../utils/api';
// ONE CATALOGUE FOR THE FILED-LOG SURFACE. This component and
// app/logbooks/photos.jsx are two halves of one affordance, and two catalogues
// for one affordance is how they come to say different things about the same
// record — which is the failure `logbookViewRenderers.test.cjs` already holds
// three surfaces equal to prevent.
import { useT } from '../../i18n';
import { outdoor, spacing, borderRadius, typography } from '../../styles/theme';

/**
 * A FILED LOG, RENDERED AS A RECORD RATHER THAN AS A DISABLED FORM.
 *
 * THE RULING: "a filed record is not being composed, so rendering it as a
 * disabled form is what makes the photo panel read as an exception." Every
 * editor used to render its five paginated steps behind pointerEvents='none'
 * when the log was locked — a form with STEP 3 OF 5 over the top, every field
 * greyed, and no way to tell a finished record from an abandoned draft. This
 * replaces that for all twelve types, which is the intent and not a side
 * effect.
 *
 * WHAT IT SHOWS: what was filed, who signed it and when, and — only where the
 * type has them — the photographs. Amend is NOT here: LogbookLockBar renders
 * below this and keeps its required reason and its editable child exactly as
 * it did, which is what makes it read as the secondary action it is.
 *
 * IT IS A VIEW. No text entry, no signature pad, no save of any kind. The
 * ordinary update route answers 409 FILED_LOG_DATA_IMMUTABLE on this document
 * and should: re-entry through it is what silently overwrote two daily_jobsite
 * records at 588 Thomas.
 *
 * AND IT HAS NO REMOVE CONTROL. Deleting a photograph from a filed record IS
 * an amendment, and the lock bar below already offers that path.
 *
 * ── THE PHOTOGRAPHS SECTION IS NOT DECIDED HERE ────────────────────────────
 *
 * `photographsSection` owns the three-state rule and the reasoning behind it
 * (absence vs. an empty state, and why the decision is the log TYPE's schema
 * rather than whether `data.activities` happens to be there). A second copy of
 * that rule in this file is exactly how the three states get collapsed back
 * into two, so this file asks and renders and decides nothing.
 *
 * ── AND ADDING ONE IS A DIFFERENT SCREEN ───────────────────────────────────
 *
 * The Add control routes to /logbooks/photos. Adding a photograph is not
 * editing a log, so it does not happen inside the thing that renders the log —
 * and that screen, not this one, owns the camera, the offline queue and the
 * per-row refusals.
 */
export default function FiledLogView({
  s,
  // The SERVER's document. Optional: when absent and a logId is present this
  // fetches it, which is what lets eleven editors that hold no such state
  // render a filed view without eleven changes. Never local editor state —
  // withActivityIds has minted ids there that the server has never seen.
  filedLog = null,
  logId = null,
  logType = null,
}) {
  const router = useRouter();
  const t = useT('logbookPhotos');
  const [fetched, setFetched] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [readFailed, setReadFailed] = React.useState(false);

  const needsFetch = !filedLog && !!logId;

  React.useEffect(() => {
    if (!needsFetch) return undefined;
    let alive = true;
    setLoading(true);
    setReadFailed(false);
    logbooksAPI.getById(logId)
      .then((doc) => {
        if (!alive) return;
        // The by-project read is paginated elsewhere in this app and returns an
        // ARRAY through the same client; a defensive shape check here is the
        // difference between a filed view and a blank one.
        setFetched(doc && !Array.isArray(doc) && typeof doc === 'object' ? doc : null);
        if (!doc || Array.isArray(doc)) setReadFailed(true);
      })
      .catch(() => { if (alive) setReadFailed(true); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [needsFetch, logId]);

  const doc = filedLog || fetched;
  // The type is the SCHEMA fact and it must survive a failed read: a document
  // that did not come back still has a known type, and the photographs rule is
  // decided from the type.
  const effectiveType = (doc && doc.log_type) || logType || null;

  if (loading) {
    return (
      <View style={fs.loadingBox}>
        <ActivityIndicator size="small" color={outdoor.text} />
      </View>
    );
  }

  // A READ THAT DID NOT COME BACK IS NOT AN EMPTY RECORD. Saying "nothing was
  // filed" over a log this device could not read is the same lie as an
  // editable blank form over one that may already be filed.
  if (!doc) {
    return (
      <Card s={s} style={fs.card}>
        <View style={fs.titleRow}>
          <Lock size={18} strokeWidth={2} color={outdoor.textDim} />
          <Text style={fs.title}>{t('filedTitle')}</Text>
        </View>
        <Text style={fs.body}>
          {readFailed ? t('filedUnreadable') : t('filedReadOnly')}
        </Text>
      </Card>
    );
  }

  const att = filedAttestation(doc);
  const { fields, groups } = summarizeFiledLog(doc);
  const photos = photographsSection({ ...doc, log_type: effectiveType });
  const openPhotos = () => router.push(
    `/logbooks/photos?logbookId=${encodeURIComponent(String(doc.id || doc._id || logId))}`,
  );

  return (
    <View>
      {/* ── WHAT THIS IS ──────────────────────────────────────────────── */}
      <Card s={s} style={fs.card}>
        <View style={fs.titleRow}>
          <FileCheck2 size={18} strokeWidth={2} color={outdoor.text} />
          <Text style={fs.title}>{t('filedTitle')}</Text>
        </View>
        <Text style={fs.body}>{t('filedIntro')}</Text>
        {att.signed ? (
          <Text style={fs.meta}>
            {att.signerName
              ? `${t('signedBy')} ${att.signerName}`
              : t('signedNoName')}
            {att.filedAt ? ` · ${String(att.filedAt).slice(0, 10)}` : ''}
          </Text>
        ) : (
          // NOT "signed by <cp_name>". cp_name is prefilled from the profile
          // long before anyone signs, and printing it as a signature would be
          // a fabricated attestation on a compliance record.
          <Text style={fs.meta}>{t('filedUnsigned')}</Text>
        )}
        {!!att.isAmendment && (
          <Text style={fs.meta}>
            {`${t('amendmentLabel')}${att.amendmentReason ? ` · ${att.amendmentReason}` : ''}`}
          </Text>
        )}
      </Card>

      {/* ── WHAT WAS FILED ────────────────────────────────────────────── */}
      {fields.length > 0 && (
        <Card s={s} style={fs.card}>
          {fields.map((f) => (
            <View key={f.label} style={fs.fieldRow}>
              <Text style={fs.fieldLabel}>{f.label}</Text>
              <Text style={fs.fieldValue}>{f.value}</Text>
            </View>
          ))}
        </Card>
      )}

      {groups.map((g) => (
        <Card key={g.key} s={s} style={fs.card}>
          <Text style={fs.sectionTitle}>{g.label}</Text>
          {g.rows.map((row, i) => (
            <View key={`${g.key}_${i}`} style={fs.groupRow}>
              <Text style={fs.groupRowTitle}>{row.label}</Text>
              {row.fields.map((f) => (
                <View key={`${g.key}_${i}_${f.label}`} style={fs.fieldRow}>
                  <Text style={fs.fieldLabel}>{f.label}</Text>
                  <Text style={fs.fieldValue}>{f.value}</Text>
                </View>
              ))}
            </View>
          ))}
        </Card>
      ))}

      {/* ── PHOTOGRAPHS: PRESENT, OR ABSENT ENTIRELY ──────────────────── */}
      {/* `photos === null` is state 1 and renders NOTHING. Not an empty
          state: an absent section makes no claim, and "no photographs yet"
          on a toolbox talk claims a place for them that the record does not
          have. See photographsSection. */}
      {!!photos && (
        <Card s={s} style={fs.card}>
          <Text style={fs.sectionTitle}>{t('sectionTitle')}</Text>
          {photos.empty ? (
            <Text style={fs.body}>{t('noneAttached')}</Text>
          ) : (
            photos.rows.filter((r) => r.photos.length > 0).map((r) => (
              <View key={r.activity_id || `row_${r.activity_index}`} style={fs.groupRow}>
                {!!r.label && <Text style={fs.groupRowTitle}>{r.label}</Text>}
                <View style={fs.grid}>
                  {r.photos.map((p) => (
                    <View key={p.original_r2_key || p.photo_id || p.photo_index} style={fs.thumbWrap}>
                      <Image
                        style={fs.thumb}
                        source={{
                          uri: logbooksAPI.getLogbookPhotoUrl(
                            doc.id || doc._id || logId,
                            r.activity_index, p.photo_index,
                            'thumb', p.enhance_status || '',
                          ),
                        }}
                      />
                      {!!p.added_after_filing && (
                        <Text style={fs.badge}>{t('addedAfterFiling')}</Text>
                      )}
                    </View>
                  ))}
                </View>
              </View>
            ))
          )}
          {/* ADDING ONE IS A DIFFERENT SCREEN. No stepper, no amendment. */}
          <Pressable
            style={fs.addBtn}
            accessibilityRole="button"
            accessibilityLabel={t('addPhotographs')}
            onPress={openPhotos}
          >
            <Camera size={20} strokeWidth={2} color={outdoor.textOnSelected} />
            <Text style={fs.addBtnText}>{t('addPhotographs')}</Text>
          </Pressable>
          {!!photos.remediable && (
            <Text style={fs.hint}>{t('legacyRow')}</Text>
          )}
        </Card>
      )}
    </View>
  );
}

const fs = StyleSheet.create({
  loadingBox: { paddingVertical: spacing.xl, alignItems: 'center' },
  card: { marginBottom: spacing.md },
  titleRow: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
    marginBottom: spacing.xs,
  },
  title: {
    fontSize: typography.sizes.md, fontWeight: '700', color: outdoor.text,
  },
  sectionTitle: {
    fontSize: typography.sizes.md, fontWeight: '700', color: outdoor.text,
    marginBottom: spacing.sm,
  },
  body: {
    fontSize: typography.sizes.sm, color: outdoor.textSoft, lineHeight: 20,
  },
  meta: {
    fontSize: typography.sizes.sm, color: outdoor.textDim, marginTop: spacing.xs,
  },
  hint: {
    fontSize: typography.sizes.dense, color: outdoor.textDim,
    marginTop: spacing.sm, lineHeight: 18,
  },
  fieldRow: { marginBottom: spacing.sm },
  fieldLabel: {
    fontSize: typography.sizes.fine, color: outdoor.textDim,
    textTransform: 'uppercase', letterSpacing: 0.5,
  },
  fieldValue: { fontSize: typography.sizes.md, color: outdoor.text },
  groupRow: {
    borderTopWidth: 1, borderTopColor: outdoor.border,
    paddingTop: spacing.sm, marginTop: spacing.sm,
  },
  groupRowTitle: {
    fontSize: typography.sizes.sm, fontWeight: '700', color: outdoor.text,
    marginBottom: spacing.xs,
  },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  thumbWrap: { width: 88 },
  thumb: {
    width: 88, height: 88, borderRadius: borderRadius.md,
    borderWidth: 1, borderColor: outdoor.border,
  },
  badge: {
    fontSize: typography.sizes.fine, color: outdoor.textDim, marginTop: 2,
  },
  addBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: spacing.sm, marginTop: spacing.md,
    minHeight: 56, borderRadius: borderRadius.md,
    backgroundColor: outdoor.surfaceSelected,
  },
  addBtnText: {
    fontSize: typography.sizes.md, fontWeight: '700',
    color: outdoor.textOnSelected,
  },
});
