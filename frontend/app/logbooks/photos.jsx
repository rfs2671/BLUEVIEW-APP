import React, { useCallback, useEffect, useState } from 'react';
import {
  View, Text, Pressable, Image, ScrollView, StyleSheet, ActivityIndicator,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { ArrowLeft, Camera, Image as ImageIcon, Clock, AlertTriangle } from 'lucide-react-native';
import * as ImagePicker from 'expo-image-picker';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { Card } from '../../src/components/logbookStepper/primitives';
import { buildStepperStyles } from '../../src/components/logbookStepper/styles';
import { useToast } from '../../src/components/Toast';
import { logbooksAPI } from '../../src/utils/api';
import { appendPhotoToFiledLog, persistPhoto } from '../../src/utils/logbookDrafts';
import compressUnderCap from '../../src/utils/compressPhoto';
import { photographsSection, typeCarriesActivityPhotos } from '../../src/utils/filedLogSummary';
import { isOpenForPhotoAppend } from '../../src/utils/logbookEditable';
import {
  shouldQueueError, queueFiledPhoto, getQueuedFiledPhotos,
  getRejectedFiledPhotos, clearRejectedFiledPhoto, drainFiledPhotoQueue,
} from '../../src/utils/filedPhotoQueue';
import { useT } from '../../src/i18n';
import { outdoor, spacing, borderRadius, typography } from '../../src/styles/theme';

/**
 * PHOTOGRAPHS FOR A LOG THAT IS ALREADY FILED.
 *
 * THE OPERATOR'S RULING, and the whole reason this is a screen of its own:
 * "adding a photo is not editing a log." Amend stays for correcting the
 * record. A filed log must offer photographs without walking the CP through a
 * form he cannot edit — so there is no editor here, no signature, no
 * amendment, and nothing that could reach the crews, headcounts, work or
 * weather he attested to. What goes over the wire is image bytes and two ids.
 *
 * IT READS THE SERVER'S DOCUMENT. `logbooksAPI.getById`, and the rows come
 * from `photographsSection` off that document — never from an editor's
 * reconciled list, where the roster merge has minted row ids the server has
 * never seen. A photograph aimed at an invented id reaches nothing, and the
 * server would answer 404 for a row that is plainly on the CP's screen.
 *
 * APPEND-ONLY. There is no remove control: deleting a photograph from a filed
 * record IS an amendment, and the lock bar on the log offers that path.
 * No reason is asked for and no count limit is consulted — a photograph is not
 * an assertion, and the per-subcontractor cap is a capture ergonomic rather
 * than a rule about how much evidence a filed record may carry.
 *
 * ── AND IT WORKS IN A CELLAR ────────────────────────────────────────────────
 *
 * Photographs are taken in cellars. When the upload cannot land because the
 * world is unreachable or storage is down, the photograph is HELD on this
 * device (filedPhotoQueue) and the CP is told THAT — with a warning, never a
 * success — because "added to the log" is a claim about the record and the
 * record has not changed. A 4xx is different in kind: it names this photograph,
 * so it is reported as a failure and never queued.
 */
export default function LogbookPhotosScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const logbookId = String(params.logbookId || params.logId || '');
  const toast = useToast();
  const t = useT('logbookPhotos');
  const s = React.useMemo(() => StyleSheet.create(buildStepperStyles()), []);

  const [log, setLog] = useState(null);
  const [loading, setLoading] = useState(true);
  const [readFailed, setReadFailed] = useState(false);
  const [busyRow, setBusyRow] = useState(null);
  // activity_id -> rows added THIS SESSION, each carrying the local uri so the
  // tile paints from this phone's own file. The report's photo URL is
  // positional and this list is not guaranteed to be the server's after a
  // write, so pointing at one would be a guess.
  const [added, setAdded] = useState({});
  const [queued, setQueued] = useState([]);
  const [rejected, setRejected] = useState([]);

  const refreshLocal = useCallback(async () => {
    setQueued(await getQueuedFiledPhotos(logbookId));
    setRejected(await getRejectedFiledPhotos(logbookId));
  }, [logbookId]);

  const load = useCallback(async () => {
    if (!logbookId) { setLoading(false); setReadFailed(true); return; }
    setLoading(true);
    try {
      const doc = await logbooksAPI.getById(logbookId);
      // The by-project read is paginated through this same client and answers
      // with an ARRAY; a shape check here is the difference between the record
      // and a screen that quietly says there is nothing on it.
      if (!doc || Array.isArray(doc) || typeof doc !== 'object') {
        setLog(null); setReadFailed(true);
      } else {
        setLog(doc); setReadFailed(false);
      }
    } catch (_e) {
      setLog(null); setReadFailed(true);
    } finally {
      setLoading(false);
    }
    await refreshLocal();
  }, [logbookId, refreshLocal]);

  useEffect(() => { load(); }, [load]);

  // A visit is also a chance to send what is held: he may have walked out of
  // the cellar and come straight back to this screen. The app-level drain
  // (app/_layout.jsx) is the one that must not be missed; this is opportunistic.
  useEffect(() => {
    let alive = true;
    drainFiledPhotoQueue()
      .then((r) => {
        if (!alive) return;
        refreshLocal();
        if (r && r.uploaded > 0) load();
      })
      .catch(() => {});
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [logbookId]);

  const section = photographsSection(log);
  const logType = (log && log.log_type) || null;
  const logId = String((log && (log.id || log._id)) || logbookId);

  const newPhotoId = () => `ap_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;

  /**
   * ONE PHOTOGRAPH, ONTO ONE ROW.
   *
   * NOT A SAVE, AND IT MUST NEVER BECOME ONE. It builds no payload, reads no
   * draft and calls no update — the ordinary route is 409
   * FILED_LOG_DATA_IMMUTABLE on this document, and re-entry through it is what
   * overwrote two daily_jobsite records at 588 Thomas.
   *
   * THE PHOTO ID IS MINTED ONCE, HERE, and it is the same id the queue holds
   * and the drain replays. The server's R2 key is a pure function of
   * (project, activity, photo), so a retry that re-minted the id would write a
   * SECOND object and the record would carry two tiles of one photograph. This
   * is the client's entire share of the idempotency contract.
   */
  const addPhotoToRow = async (activityId, rawUri, label) => {
    if (!logId || !activityId || !rawUri || busyRow) return;
    setBusyRow(activityId);
    const photoId = newPhotoId();
    try {
      let uri = rawUri;
      try {
        uri = (await compressUnderCap(rawUri)) || rawUri;
      } catch (_e) {
        // A full-size photograph is worse than a small one and infinitely
        // better than a lost one — the same trade the capture path makes.
      }
      try {
        uri = await persistPhoto(uri, photoId);
      } catch (_e) {
        // persistPhoto THROWS on a failed copy, and that throw is the whole
        // offline guarantee: nothing is uploaded or queued from a file the app
        // cannot prove it owns, because the OS will evict a cache path and the
        // queue would then hold a promise it cannot keep.
        toast.error(t('notSavedTitle'), t('notSavedBody'));
        return;
      }
      try {
        const res = await appendPhotoToFiledLog({
          logbookId: logId, activityId, photoId, uri,
        });
        setAdded((prev) => ({
          ...prev,
          [activityId]: [...(prev[activityId] || []), { ...res.photo, uri }],
        }));
        toast.success(t('addedTitle'), t('addedBody'));
      } catch (e) {
        if (shouldQueueError(e)) {
          // HELD, NOT FILED. The sentence is about the DEVICE, and it is a
          // WARNING: saying "added to the log" here would be the app claiming
          // something about a record the server has never been told about.
          await queueFiledPhoto({
            logbookId: logId, activityId, photoId, uri, logType, label,
          });
          await refreshLocal();
          toast.warning(t('queuedTitle'), t('queuedBody'));
          return;
        }
        // A 4xx NAMES THIS PHOTOGRAPH. A legacy row is told the truth: nothing
        // the client can send reaches it until an administrator runs the
        // backfill, so offering "try again" would be the app pretending
        // otherwise.
        toast.error(
          t('failedTitle'),
          e?.code === 'ACTIVITY_HAS_NO_IDENTITY' ? t('legacyRow') : t('failedBody'),
        );
      }
    } finally {
      setBusyRow(null);
    }
  };

  const pick = async (activityId, label, fromCamera) => {
    if (!activityId || busyRow) return;
    try {
      // On web there is no camera permission to ask for and no launchCamera
      // worth offering; the library picker is the one path that works.
      const useCamera = fromCamera && Platform.OS !== 'web';
      const perm = useCamera
        ? await ImagePicker.requestCameraPermissionsAsync()
        : await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (perm.status !== 'granted') {
        toast.warning(t('permissionTitle'), t('permissionBody'));
        return;
      }
      const result = useCamera
        ? await ImagePicker.launchCameraAsync({ quality: 0.6, base64: false })
        : await ImagePicker.launchImageLibraryAsync({
          mediaTypes: ImagePicker.MediaTypeOptions.Images, quality: 0.6, base64: false,
        });
      if (!result || result.canceled) return;
      const asset = (result.assets || [])[0];
      if (asset) await addPhotoToRow(activityId, asset.uri, label);
    } catch (_e) {
      toast.error(t('failedTitle'), t('failedBody'));
    }
  };

  const header = (
    <View style={s.header}>
      <Pressable
        style={s.headerBack}
        accessibilityRole="button"
        accessibilityLabel={t('back')}
        onPress={() => router.back()}
      >
        <ArrowLeft size={24} strokeWidth={2} color={outdoor.text} />
      </Pressable>
      <View style={s.headerText}>
        <Text style={s.headerTitle}>{t('screenTitle')}</Text>
        <Text style={s.headerSub}>
          {log ? `${String(log.log_type || '').replace(/_/g, ' ')} · ${String(log.date || '').slice(0, 10)}` : ''}
        </Text>
      </View>
    </View>
  );

  const body = () => {
    if (loading) {
      return (
        <View style={s.loadingCenter}>
          <ActivityIndicator size="large" color={outdoor.text} />
        </View>
      );
    }
    // A READ THAT FAILED IS NOT AN EMPTY RECORD, and it must not be drawn as
    // one: "no photographs" over a log this device could not read is a claim
    // about a record nobody here has seen.
    if (!log) {
      return (
        <Card s={s} style={ps.card}>
          <Text style={ps.title}>{t('unavailableTitle')}</Text>
          <Text style={ps.body}>{readFailed ? t('unavailableBody') : t('noLogBody')}</Text>
          <Pressable style={ps.ghostBtn} accessibilityRole="button" onPress={load}>
            <Text style={ps.ghostBtnText}>{t('retry')}</Text>
          </Pressable>
        </Card>
      );
    }
    // A DRAFT IS NOT A FILED LOG, AND THIS ROUTE IS NOT FOR ONE.
    //
    // The entry points only offer this screen on a filed record, but a typed
    // URL, a stale deep link and a back-stack entry are all real. The append
    // route writes STRAIGHT INTO the stored document, so a photograph put on a
    // draft this way is overwritten by the editor's own next PUT — it would
    // appear, and then quietly stop existing. The ordinary camera in the
    // editor is the way in on an open log.
    //
    // ASKED OF THE SHARED PREDICATE, which is where that rule and its one
    // exception are written together, rather than re-derived from `status`
    // here as a second copy that can drift.
    if (log && !isOpenForPhotoAppend(log)) {
      return (
        <Card s={s} style={ps.card}>
          <Text style={ps.title}>{t('notFiledTitle')}</Text>
          <Text style={ps.body}>{t('notFiledBody')}</Text>
        </Card>
      );
    }
    // The entry points only offer this for a photo-carrying type, but a typed
    // URL is a real thing. The refusal names the TYPE's schema rather than
    // pretending the log is empty.
    if (!typeCarriesActivityPhotos(logType) || !section) {
      return (
        <Card s={s} style={ps.card}>
          <Text style={ps.title}>{t('noPhotosTypeTitle')}</Text>
          <Text style={ps.body}>{t('noPhotosTypeBody')}</Text>
        </Card>
      );
    }

    const queuedFor = (id) => queued.filter((q) => q.activityId === id);

    return (
      <>
        <Card s={s} style={ps.card}>
          <Text style={ps.body}>{t('intro')}</Text>
        </Card>

        {rejected.length > 0 && (
          <Card s={s} style={ps.card}>
            <View style={ps.rowHead}>
              <AlertTriangle size={16} strokeWidth={2} color={outdoor.warn} />
              <Text style={ps.title}>{t('refusedTitle')}</Text>
            </View>
            {rejected.map((r) => (
              <View key={r.photoId} style={ps.rejectedRow}>
                <Text style={ps.body}>
                  {r.code === 'ACTIVITY_HAS_NO_IDENTITY' ? t('legacyRow') : t('refusedBody')}
                </Text>
                <Pressable
                  style={ps.ghostBtn}
                  accessibilityRole="button"
                  onPress={async () => {
                    await clearRejectedFiledPhoto(r.photoId);
                    await refreshLocal();
                  }}
                >
                  <Text style={ps.ghostBtnText}>{t('dismiss')}</Text>
                </Pressable>
              </View>
            ))}
          </Card>
        )}

        {section.rows.length === 0 && (
          <Card s={s} style={ps.card}>
            <Text style={ps.body}>{t('noRows')}</Text>
          </Card>
        )}

        {section.rows.map((row) => {
          const rowId = row.activity_id;
          const shots = (rowId && added[rowId]) || [];
          const held = rowId ? queuedFor(rowId) : [];
          const busy = busyRow === rowId;
          return (
            <Card key={rowId || `row_${row.activity_index}`} s={s} style={ps.card}>
              <Text style={ps.rowLabel}>{row.label || t('unnamedRow')}</Text>

              {(row.photos.length > 0 || shots.length > 0 || held.length > 0) && (
                <View style={ps.grid}>
                  {row.photos.map((p) => (
                    <View key={p.original_r2_key || p.photo_id || `s${p.photo_index}`} style={ps.thumbWrap}>
                      <Image
                        style={ps.thumb}
                        source={{
                          uri: logbooksAPI.getLogbookPhotoUrl(
                            logId, row.activity_index, p.photo_index,
                            'thumb', p.enhance_status || '',
                          ),
                        }}
                      />
                      {!!p.added_after_filing && (
                        <Text style={ps.badge}>{t('addedAfterFiling')}</Text>
                      )}
                    </View>
                  ))}
                  {shots.map((p) => (
                    <View key={p.original_r2_key || p.photo_id} style={ps.thumbWrap}>
                      <Image style={ps.thumb} source={{ uri: p.uri }} />
                      <Text style={ps.badge}>{t('addedAfterFiling')}</Text>
                    </View>
                  ))}
                  {held.map((q) => (
                    <View key={q.photoId} style={ps.thumbWrap}>
                      <Image style={ps.thumb} source={{ uri: q.uri }} />
                      <View style={ps.heldRow}>
                        <Clock size={12} strokeWidth={2} color={outdoor.textDim} />
                        <Text style={ps.badge}>{t('heldBadge')}</Text>
                      </View>
                    </View>
                  ))}
                </View>
              )}

              {!row.can_add ? (
                // NOTHING BACKFILLS THIS FROM THE CLIENT. No add control, and
                // the sentence names the remedy — an administrator running the
                // activity-identity backfill — rather than offering a retry
                // that cannot work.
                <Text style={ps.hint}>{t('legacyRow')}</Text>
              ) : (
                <View style={ps.actions}>
                  <Pressable
                    style={ps.primaryBtn}
                    accessibilityRole="button"
                    accessibilityState={{ disabled: busy }}
                    disabled={busy}
                    onPress={() => pick(rowId, row.label, true)}
                  >
                    {busy
                      ? <ActivityIndicator size="small" color={outdoor.textOnSelected} />
                      : <Camera size={22} strokeWidth={2} color={outdoor.textOnSelected} />}
                    <Text style={ps.primaryBtnText}>{t('takePhoto')}</Text>
                  </Pressable>
                  <Pressable
                    style={ps.ghostBtn}
                    accessibilityRole="button"
                    accessibilityState={{ disabled: busy }}
                    disabled={busy}
                    onPress={() => pick(rowId, row.label, false)}
                  >
                    <ImageIcon size={22} strokeWidth={2} color={outdoor.text} />
                    <Text style={ps.ghostBtnText}>{t('choosePhoto')}</Text>
                  </Pressable>
                </View>
              )}
            </Card>
          );
        })}
      </>
    );
  };

  return (
    <AnimatedBackground pinned>
      <SafeAreaView style={s.container} edges={['top']}>
        {header}
        <ScrollView style={s.scroll} contentContainerStyle={s.scrollContent}>
          {body()}
        </ScrollView>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

const ps = StyleSheet.create({
  card: { marginBottom: spacing.md },
  title: {
    fontSize: typography.sizes.md, fontWeight: '700', color: outdoor.text,
    marginBottom: spacing.xs,
  },
  body: {
    fontSize: typography.sizes.sm, color: outdoor.textSoft, lineHeight: 20,
  },
  hint: {
    fontSize: typography.sizes.dense, color: outdoor.textDim,
    marginTop: spacing.sm, lineHeight: 18,
  },
  rowHead: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  rowLabel: {
    fontSize: typography.sizes.md, fontWeight: '700', color: outdoor.text,
    marginBottom: spacing.sm,
  },
  rejectedRow: {
    borderTopWidth: 1, borderTopColor: outdoor.border,
    paddingTop: spacing.sm, marginTop: spacing.sm, gap: spacing.sm,
  },
  grid: {
    flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  thumbWrap: { width: 88 },
  thumb: {
    width: 88, height: 88, borderRadius: borderRadius.md,
    borderWidth: 1, borderColor: outdoor.border,
  },
  heldRow: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  badge: { fontSize: typography.sizes.fine, color: outdoor.textDim, marginTop: 2 },
  actions: { flexDirection: 'row', gap: spacing.sm },
  primaryBtn: {
    flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: spacing.sm, minHeight: 56, borderRadius: borderRadius.md,
    backgroundColor: outdoor.surfaceSelected,
  },
  primaryBtnText: {
    fontSize: typography.sizes.md, fontWeight: '700', color: outdoor.textOnSelected,
  },
  ghostBtn: {
    flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: spacing.sm, minHeight: 56, borderRadius: borderRadius.md,
    borderWidth: 1, borderColor: outdoor.border,
  },
  ghostBtnText: {
    fontSize: typography.sizes.md, fontWeight: '700', color: outdoor.text,
  },
});
