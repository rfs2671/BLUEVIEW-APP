import React, { useEffect, useMemo, useState } from 'react';
import {
  View, Text, Modal, Pressable, ScrollView, useWindowDimensions,
  ActivityIndicator,
} from 'react-native';
import { StyleSheet } from 'react-native';
import QRCode from 'react-native-qrcode-svg';
import { X, ChevronLeft, Wifi, Plus } from 'lucide-react-native';
import { buildCheckinUrl } from '../utils/nfcHelper';
import { projectsAPI } from '../utils/api';
import { readCachedProjectList } from '../utils/projectCache';
import { useAuth } from '../context/AuthContext';
import {
  spacing, borderRadius, typography, touchTarget, outdoor, outdoorShadow,
} from '../styles/theme';
// o50 is the app's existing disabled/busy dim, not a new value.
import { opacity } from '../styles/tokens';

/**
 * THE QR THE CP HOLDS UP WHEN A WORKER'S PHONE HAS NO NFC.
 *
 * WHY SHOWING A CODE CREATES NOTHING.
 *
 * The obvious build is a "virtual tag": generate an id, POST it as a new
 * nfc_tags row, encode that. It is wrong twice over. POST
 * /api/projects/{id}/nfc-tags is Depends(get_admin_user) — admin or owner —
 * so the CP standing at the gate cannot call it at all, and the moment it
 * needs a network round-trip it stops working on a site with no signal, which
 * is most of them below street level.
 *
 * A gate that has a tag on the post already HAS an active nfc_tags row. This
 * screen encodes THAT row's URL. Same tag_id, same project, same
 * location_description, and therefore the same check-in record — the only
 * difference is that the man scanned instead of tapped. Nothing is written
 * anywhere to show a code, and nothing needs an admin. (Minting a gate where
 * there is none is a different, explicit action - see further down.)
 *
 * It works offline because nfc_tags rides on ProjectResponse (server.py:2047)
 * and the CP's project list is already cached to AsyncStorage by
 * projectCache.js. The tag ids are in the CP's pocket before they reach the
 * gate. The WORKER still needs a connection to load the gate page — but that
 * was equally true of the tap, so a QR takes nothing away.
 *
 * THE EMPTY STATE IS NOT TERMINAL ANY MORE. A project with no registered tag
 * still has no URL to encode - /checkin/{p}/{t}/info 404s "Invalid check-in
 * link" without an ACTIVE row, and nothing this screen invents would change
 * that. But the CP can now MINT one, because the alternative was a site with
 * no compliant check-in and a 3301.11 record for the shift that cannot be
 * reconstructed afterwards.
 *
 * The server mints the id; this screen never sends one. It comes back
 * PROVISIONAL - QR-only, no chip in the field carries it - which is what the
 * admin sees flagged on the project screen. This needs the network: it is a
 * write, and the one case it exists for (no gate at all) is not the offline
 * case (a gate exists and the QR renders from cache).
 *
 * IT RESOLVES ITS OWN PROJECT. `project` is OPTIONAL: a host that already has
 * one passes it, and otherwise this reads the CP's cached project list and
 * filters it to their assigned projects — the same filter and the same
 * AsyncStorage cache /logbooks already uses, so it still renders with no
 * signal.
 *
 * That is not a convenience. This opens from CpNav, which is on every CP
 * screen, and no host can supply a project honestly: /settings has no project
 * state at all, and /documents has one filtered to Dropbox-enabled projects,
 * so a project without Dropbox is simply absent from it. A modal that took the
 * host's idea of "the current project" would silently show the wrong gate on
 * one screen and none on another.
 *
 * PRESENCE. A tap requires the phone to be at the post. A photograph of this
 * code does not — see the header comment on CHECKIN_BASE_URL and the ?m=qr
 * marker, which is what makes a scanned check-in queryable after the fact.
 */

// Pure black on pure white, not the outdoor palette. A QR is read by a camera
// resolving a contrast edge, not by a person: tinting either module colour
// costs scan margin in sunlight and buys nothing. The white is also the quiet
// zone — the four-module border the spec requires — which is why the code sits
// on its own padded card rather than directly on the sheet.
const QR_DARK = '#000000';
const QR_LIGHT = '#ffffff';

// Cap on the rendered code. Bigger is better outdoors right up until the code
// stops fitting a phone held at arm's length by a second person, which is the
// actual reading distance here.
const QR_MAX = 320;
const QR_MIN = 200;

export default function CheckinQrModal({ visible, onClose, project, onChanged }) {
  const { width } = useWindowDimensions();
  const { user } = useAuth();
  const [selected, setSelected] = useState(null);
  // Only used when no `project` was passed. Null while unresolved, [] once the
  // cache has been read and genuinely holds nothing for this CP.
  const [ownProjects, setOwnProjects] = useState(null);
  const [pickedProject, setPickedProject] = useState(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState(null);
  // The gate minted in THIS session. The parent's `project` comes from a
  // cached list that will not carry it until the next refetch, so the code has
  // to be renderable from what the create call returned or the CP mints a gate
  // and is shown the same empty screen.
  const [minted, setMinted] = useState(null);

  // Read on OPEN, not on mount. The nav renders this on every CP screen, so a
  // mount-time read would hit AsyncStorage on every navigation for a sheet
  // nobody opened.
  useEffect(() => {
    if (!visible || project) return;
    let cancelled = false;
    (async () => {
      const list = await readCachedProjectList();
      if (cancelled) return;
      const arr = Array.isArray(list) ? list : [];
      // The SAME scope rule as the CP's own project picker in
      // app/logbooks/index.jsx. Defence in depth — the backend is the real
      // gate — but a CP must not be shown a code for a site they are not on.
      const visibleProjects = user?.role === 'cp'
        ? arr.filter((p) => (user?.assigned_projects || []).includes(p.id || p._id))
        : arr;
      setOwnProjects(visibleProjects);
      // One project is the common case, and asking a man to pick from a list
      // of one while a worker waits is a question with a single answer.
      setPickedProject(visibleProjects.length === 1 ? visibleProjects[0] : null);
    })();
    return () => { cancelled = true; };
  }, [visible, project, user]);

  const activeProject = project || pickedProject;
  const projectId = activeProject?.id || activeProject?._id || null;
  // Distinguishes "still reading the cache" from "the cache holds nothing",
  // so a slow read is never rendered as "no check-in point registered".
  const resolving = !project && ownProjects === null;
  const needsProjectPick = !project && !pickedProject && (ownProjects?.length || 0) > 1;

  // Defensive: the cached project payload is whatever the server last sent, and
  // a row missing tag_id would render a QR pointing at /checkin/{p}/undefined.
  const tags = useMemo(() => {
    const raw = Array.isArray(activeProject?.nfc_tags) ? activeProject.nfc_tags : [];
    const clean = raw.filter((t) => t && typeof t.tag_id === 'string' && t.tag_id.trim());
    if (minted && !clean.some((t) => t.tag_id === minted.tag_id)) {
      return [...clean, minted];
    }
    return clean;
  }, [activeProject, minted]);

  const qrSize = Math.max(QR_MIN, Math.min(QR_MAX, width - spacing.xl * 4));

  const close = () => {
    setSelected(null);
    setCreateError(null);
    // Not ownProjects: re-reading the cache on every open would cost a read for
    // no new information. The PICK is cleared so a CP on two sites is asked
    // again next time rather than silently handed yesterday's gate.
    if (!project && (ownProjects?.length || 0) > 1) setPickedProject(null);
    setMinted(null);
    onClose?.();
  };

  const createPoint = async () => {
    if (!projectId || creating) return;
    setCreating(true);
    setCreateError(null);
    try {
      const res = await projectsAPI.bootstrapCheckinPoint(projectId, {});
      const row = { tag_id: res.tag_id, location: res.location_description, provisional: true };
      setMinted(row);
      setSelected(row);
      // Tell the parent to refetch, so the gate survives closing this sheet.
      onChanged?.();
    } catch (e) {
      // NAMED, NEVER SILENT. This is the one screen standing between a man at
      // a gate and no record of him being there; "nothing happened" is the
      // worst thing it can say.
      setCreateError(
        e?.response?.data?.detail
        || 'Could not create a check-in point. Check your connection and try again.',
      );
    } finally {
      setCreating(false);
    }
  };

  // One gate is the common case — a single entrance. Showing a picker with one
  // row on it would be a step that asks the CP a question with one answer, so
  // it is skipped and the code is shown directly.
  const only = tags.length === 1 ? tags[0] : null;
  const active = selected || only;

  const url = active && projectId
    ? buildCheckinUrl(projectId, active.tag_id, { method: 'qr' })
    : null;

  return (
    <Modal
      visible={!!visible}
      transparent
      animationType="slide"
      onRequestClose={close}
    >
      <View style={s.overlay}>
        <Pressable style={s.backdrop} onPress={close} accessibilityLabel="Close" />
        <View style={s.sheet}>
          <View style={s.header}>
            {(active && !only) || (!project && pickedProject && (ownProjects?.length || 0) > 1) ? (
              <Pressable
                onPress={() => (active && !only ? setSelected(null) : setPickedProject(null))}
                style={s.headerBtn}
                accessibilityRole="button"
                accessibilityLabel="Back to check-in points"
              >
                <ChevronLeft size={24} color={outdoor.text} />
              </Pressable>
            ) : <View style={s.headerSpacer} />}

            <Text style={s.title} numberOfLines={1}>
              {needsProjectPick
                ? 'Pick a project'
                : (active ? (active.location || 'Check-In Point') : 'Check-In QR')}
            </Text>

            <Pressable
              onPress={close}
              style={s.headerBtn}
              accessibilityRole="button"
              accessibilityLabel="Close"
            >
              <X size={24} color={outdoor.text} />
            </Pressable>
          </View>

          <ScrollView contentContainerStyle={s.body}>
            {resolving ? (
              <ActivityIndicator color={outdoor.text} />
            ) : needsProjectPick ? (
              <>
                <Text style={s.lead}>
                  You are on more than one project. Pick the site you are
                  standing on.
                </Text>
                {ownProjects.map((p) => (
                  <Pressable
                    key={p.id || p._id}
                    onPress={() => setPickedProject(p)}
                    style={s.row}
                    accessibilityRole="button"
                    accessibilityLabel={p.name || 'Project'}
                  >
                    <Wifi size={20} strokeWidth={1.5} color={outdoor.textDim} />
                    <View style={s.rowText}>
                      <Text style={s.rowTitle}>{p.name || 'Project'}</Text>
                      <Text style={s.rowSub} numberOfLines={1}>
                        {p.address || p.location || ''}
                      </Text>
                    </View>
                  </Pressable>
                ))}
              </>
            ) : !projectId ? (
              /* The cache was read and held nothing for this CP. Distinct from
                 `resolving` above, and from a project that simply has no gate
                 yet — this one cannot be fixed from here. */
              <View style={s.emptyBox}>
                <Wifi size={40} strokeWidth={1} color={outdoor.textDim} />
                <Text style={s.emptyTitle}>No project available</Text>
                <Text style={s.empty}>
                  Open your Dashboard once while online, then try again.
                </Text>
              </View>
            ) : tags.length === 0 ? (
              /* Not a failure to render — a project with no check-in point
                 registered. Name the fix; an admin has to register the tag,
                 and no code this screen could draw would work without one. */
              <View style={s.emptyBox}>
                <Wifi size={40} strokeWidth={1} color={outdoor.textDim} />
                <Text style={s.emptyTitle}>No check-in point registered</Text>
                <Text style={s.empty}>
                  This project has no check-in point, so nobody can check in at
                  all. Create one now and show its code — an admin can program a
                  physical tag for it later.
                </Text>

                <Pressable
                  onPress={createPoint}
                  disabled={creating}
                  style={[s.primaryBtn, creating && s.primaryBtnBusy]}
                  accessibilityRole="button"
                  accessibilityLabel="Create a check-in point"
                >
                  {creating ? (
                    <ActivityIndicator color={outdoor.textOnSelected} />
                  ) : (
                    <>
                      <Plus size={20} strokeWidth={2} color={outdoor.textOnSelected} />
                      <Text style={s.primaryBtnText}>Create check-in point</Text>
                    </>
                  )}
                </Pressable>

                {!!createError && (
                  <Text style={s.errorText}>{createError}</Text>
                )}
              </View>
            ) : !active ? (
              <>
                <Text style={s.lead}>
                  Pick the entrance the worker is standing at. The code carries
                  that entrance, the same as the tag on the post.
                </Text>
                {tags.map((t) => (
                  <Pressable
                    key={t.tag_id}
                    onPress={() => setSelected(t)}
                    style={s.row}
                    accessibilityRole="button"
                    accessibilityLabel={t.location || 'Check-In Point'}
                  >
                    <Wifi size={20} strokeWidth={1.5} color={outdoor.textDim} />
                    <View style={s.rowText}>
                      <Text style={s.rowTitle}>{t.location || 'Check-In Point'}</Text>
                      <Text style={s.rowSub} numberOfLines={1}>{t.tag_id}</Text>
                    </View>
                  </Pressable>
                ))}
              </>
            ) : (
              <>
                <Text style={s.lead}>
                  Have the worker open their camera and point it at this code.
                  It opens the same check-in as tapping the tag.
                </Text>

                {/* Turn the screen brightness up — this is read in daylight. */}
                <View style={s.qrCard}>
                  <QRCode
                    value={url}
                    size={qrSize}
                    color={QR_DARK}
                    backgroundColor={QR_LIGHT}
                    // Level M survives a scuffed screen and a shaky hand at
                    // this payload length without inflating the module count
                    // the way Q or H would.
                    ecl="M"
                  />
                </View>

                {/* The URL in plain text, because a camera that will not focus
                    is a real jobsite outcome and typing it is the fallback the
                    CP is left with. */}
                <Text style={s.urlLabel}>If the camera will not read it</Text>
                <Text style={s.url} selectable>{url}</Text>
              </>
            )}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  overlay: { flex: 1, justifyContent: 'flex-end' },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: outdoor.scrim },
  sheet: {
    maxHeight: '92%',
    backgroundColor: outdoor.backgroundMiddle,
    borderTopLeftRadius: borderRadius.xl,
    borderTopRightRadius: borderRadius.xl,
    ...outdoorShadow,
  },
  header: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderBottomWidth: 1, borderBottomColor: outdoor.line,
    backgroundColor: outdoor.surface,
    borderTopLeftRadius: borderRadius.xl,
    borderTopRightRadius: borderRadius.xl,
  },
  headerBtn: {
    minWidth: touchTarget.min, minHeight: touchTarget.min,
    alignItems: 'center', justifyContent: 'center',
    borderRadius: borderRadius.full,
  },
  headerSpacer: { minWidth: touchTarget.min },
  title: {
    flex: 1, textAlign: 'center',
    fontSize: typography.sizes.lg, fontWeight: '700', color: outdoor.text,
  },
  body: { padding: spacing.md, alignItems: 'center', gap: spacing.md },
  lead: {
    fontSize: typography.sizes.sm, color: outdoor.textSoft,
    textAlign: 'center', paddingHorizontal: spacing.sm,
  },
  qrCard: {
    backgroundColor: QR_LIGHT,
    padding: spacing.md,
    borderRadius: borderRadius.lg,
    ...outdoorShadow,
  },
  urlLabel: {
    fontSize: typography.sizes.fine, fontWeight: '600',
    color: outdoor.textDim, textTransform: 'uppercase',
  },
  url: {
    fontSize: typography.sizes.dense, color: outdoor.textSoft,
    textAlign: 'center', paddingHorizontal: spacing.sm,
  },
  row: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.md,
    minHeight: touchTarget.min,
    alignSelf: 'stretch',
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    backgroundColor: outdoor.surface,
    borderRadius: borderRadius.lg,
    borderWidth: 1, borderColor: outdoor.line,
  },
  rowText: { flex: 1 },
  rowTitle: {
    fontSize: typography.sizes.md, fontWeight: '600', color: outdoor.text,
  },
  rowSub: { fontSize: typography.sizes.fine, color: outdoor.textDim },
  emptyBox: { alignItems: 'center', gap: spacing.sm, paddingVertical: spacing.xl },
  primaryBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: spacing.sm,
    alignSelf: 'stretch',
    // The one action this screen is about, at the primary target size — a
    // gloved thumb outdoors, not a fingertip on a clean screen indoors.
    minHeight: touchTarget.primary,
    marginTop: spacing.md,
    paddingHorizontal: spacing.lg,
    backgroundColor: outdoor.surfaceSelected,
    borderRadius: borderRadius.lg,
  },
  primaryBtnBusy: { opacity: opacity.o50 },
  primaryBtnText: {
    fontSize: typography.sizes.md, fontWeight: '700', color: outdoor.textOnSelected,
  },
  errorText: {
    fontSize: typography.sizes.sm, color: outdoor.danger,
    textAlign: 'center', marginTop: spacing.sm,
  },
  emptyTitle: {
    fontSize: typography.sizes.md, fontWeight: '600', color: outdoor.text,
  },
  empty: {
    fontSize: typography.sizes.sm, color: outdoor.textSoft, textAlign: 'center',
  },
});
