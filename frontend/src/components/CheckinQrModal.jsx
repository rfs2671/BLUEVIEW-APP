import React, { useMemo, useState } from 'react';
import {
  View, Text, Modal, Pressable, ScrollView, useWindowDimensions,
} from 'react-native';
import { StyleSheet } from 'react-native';
import QRCode from 'react-native-qrcode-svg';
import { X, ChevronLeft, Wifi } from 'lucide-react-native';
import { buildCheckinUrl } from '../utils/nfcHelper';
import {
  spacing, borderRadius, typography, touchTarget, outdoor, outdoorShadow,
} from '../styles/theme';

/**
 * THE QR THE CP HOLDS UP WHEN A WORKER'S PHONE HAS NO NFC.
 *
 * WHY THIS CREATES NOTHING.
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
 * anywhere to show a code, and nothing needs an admin.
 *
 * It works offline because nfc_tags rides on ProjectResponse (server.py:2047)
 * and the CP's project list is already cached to AsyncStorage by
 * projectCache.js. The tag ids are in the CP's pocket before they reach the
 * gate. The WORKER still needs a connection to load the gate page — but that
 * was equally true of the tap, so a QR takes nothing away.
 *
 * WHAT IT CANNOT DO. A project with no registered tag has no URL to encode,
 * and there is nothing this screen can invent that the server would accept:
 * /checkin/{p}/{t}/info 404s "Invalid check-in link" without an ACTIVE row.
 * That case gets a plain empty state naming the fix, never a code that leads
 * a man to a dead end.
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

export default function CheckinQrModal({ visible, onClose, project }) {
  const { width } = useWindowDimensions();
  const [selected, setSelected] = useState(null);

  const projectId = project?.id || project?._id || null;

  // Defensive: the cached project payload is whatever the server last sent, and
  // a row missing tag_id would render a QR pointing at /checkin/{p}/undefined.
  const tags = useMemo(() => {
    const raw = Array.isArray(project?.nfc_tags) ? project.nfc_tags : [];
    return raw.filter((t) => t && typeof t.tag_id === 'string' && t.tag_id.trim());
  }, [project]);

  const qrSize = Math.max(QR_MIN, Math.min(QR_MAX, width - spacing.xl * 4));

  const close = () => {
    setSelected(null);
    onClose?.();
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
            {active && !only ? (
              <Pressable
                onPress={() => setSelected(null)}
                style={s.headerBtn}
                accessibilityRole="button"
                accessibilityLabel="Back to check-in points"
              >
                <ChevronLeft size={24} color={outdoor.text} />
              </Pressable>
            ) : <View style={s.headerSpacer} />}

            <Text style={s.title} numberOfLines={1}>
              {active ? (active.location || 'Check-In Point') : 'Check-In QR'}
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
            {!projectId ? (
              <Text style={s.empty}>No project selected.</Text>
            ) : tags.length === 0 ? (
              /* Not a failure to render — a project with no check-in point
                 registered. Name the fix; an admin has to register the tag,
                 and no code this screen could draw would work without one. */
              <View style={s.emptyBox}>
                <Wifi size={40} strokeWidth={1} color={outdoor.textDim} />
                <Text style={s.emptyTitle}>No check-in point registered</Text>
                <Text style={s.empty}>
                  This project has no check-in point yet, so there is no code to
                  show. Ask an admin to register one on the project.
                </Text>
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
  emptyTitle: {
    fontSize: typography.sizes.md, fontWeight: '600', color: outdoor.text,
  },
  empty: {
    fontSize: typography.sizes.sm, color: outdoor.textSoft, textAlign: 'center',
  },
});
