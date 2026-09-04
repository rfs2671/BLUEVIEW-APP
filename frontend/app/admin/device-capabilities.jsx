/**
 * WHAT THIS WEBVIEW CAN DO — a two-minute read, on any device, offline.
 *
 * WHY IT IS PERMANENT TOOLING AND NOT A ONE-OFF. The architecture questions in
 * front of the plan viewer all turn on device capabilities: can a Worker be
 * built from a blob: URL, can wasm instantiate, how large a canvas actually
 * allocates, how fast a binary reads off storage. Every one of those varies by
 * device and by System WebView version, and the site device — a locked-down
 * tablet that may never take a Play Store update — drifts further from a
 * current phone every month. The question recurs, so the answer should cost
 * two minutes rather than a report.
 *
 * IT DOES NOT USE THE FEATURE FLAG, DELIBERATELY. The render probe is gated on
 * `pdf_viewer_probe`, which is fetched from the server at app boot. The site
 * device is offline by design and may go a long time without a flag refresh —
 * so a capability read that depended on one would be unavailable on the device
 * the answers matter most for. This runs off a url parameter against assets
 * already staged on disk.
 *
 * IT IS THE VIEWER'S OWN CODE. `viewer.html?caps=1` runs the same six
 * measurement functions the probe runs, from the same file. A separate
 * capability page would drift, and two devices could then no longer be
 * compared line for line — which is the entire purpose.
 *
 * NOT LINKED FROM NAVIGATION. Admin-gated and reachable by route. It is an
 * instrument, not a feature.
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  View, Text, StyleSheet, Pressable, ScrollView, ActivityIndicator, Share, Platform,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { WebView } from 'react-native-webview';
import { ArrowLeft, Share2, RefreshCw } from 'lucide-react-native';
import { useTheme } from '../../src/context/ThemeContext';
import { useAuth } from '../../src/context/AuthContext';
import { spacing, borderRadius } from '../../src/styles/theme';
import { semantic, withAlpha } from '../../src/styles/semanticColors';
import { ensurePdfJsViewer, pdfJsViewerDir } from '../../src/utils/pdfjsViewer';

// The six the read produces, in the order the reporting wants them. `wasm` and
// `binread` are first because they gate the packed-file design regardless of
// what happens to tiling.
const ORDER = ['wasm', 'binread', 'blobworker', 'workersrc', 'canvas-lim', 'env'];

export default function DeviceCapabilitiesScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { user } = useAuth();

  const [viewerUri, setViewerUri] = useState(null);
  const [stageError, setStageError] = useState('');
  const [readings, setReadings] = useState({});
  const [done, setDone] = useState(false);
  const [runId, setRunId] = useState(0);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  const stage = useCallback(async () => {
    setReadings({});
    setDone(false);
    setStageError('');
    setViewerUri(null);
    const res = await ensurePdfJsViewer();
    if (!alive.current) return;
    if (!res?.ok) {
      // `assets-missing` is a real and recoverable state — the pdf.js build is
      // a human step — so name it rather than showing a blank page.
      setStageError(res?.reason || 'stage-failed');
      return;
    }
    setViewerUri(res.viewerUri);
  }, []);

  useEffect(() => { stage(); }, [stage, runId]);

  const onMessage = useCallback((e) => {
    let msg = null;
    try { msg = JSON.parse(e?.nativeEvent?.data || '{}'); } catch (_err) { return; }
    if (msg?.type !== 'pdf-probe') return;
    if (msg.probe === 'caps') { setDone(true); return; }
    setReadings((prev) => ({ ...prev, [msg.probe]: msg.data }));
  }, []);

  const report = useCallback(() => {
    const lines = [
      `LeveLog device capability read`,
      `platform: ${Platform.OS} ${Platform.Version}`,
      `account: ${user?.email || user?.id || 'unknown'} (${user?.role || 'unknown'})`,
      `at: ${new Date().toISOString()}`,
      '',
    ];
    for (const k of ORDER) {
      if (readings[k]) lines.push(`${k}: ${JSON.stringify(readings[k])}`);
    }
    for (const k of Object.keys(readings)) {
      if (!ORDER.includes(k)) lines.push(`${k}: ${JSON.stringify(readings[k])}`);
    }
    return lines.join('\n');
  }, [readings, user]);

  // iOS never renders a plan through this viewer — WKWebView hands a PDF to
  // PDFKit — so there is nothing here for it to measure. Saying so is more use
  // than an empty screen.
  const iosNote = Platform.OS === 'ios';

  return (
    <SafeAreaView style={s.container} edges={['top']}>
      <View style={s.topBar}>
        <Pressable onPress={() => router.back()} style={s.iconBtn} accessibilityRole="button" accessibilityLabel="Back">
          <ArrowLeft size={22} strokeWidth={1.5} color={colors.text.primary} />
        </Pressable>
        <Text style={s.title}>Device capabilities</Text>
        <View style={{ flex: 1 }} />
        <Pressable onPress={() => setRunId((n) => n + 1)} style={s.iconBtn} accessibilityRole="button" accessibilityLabel="Run again">
          <RefreshCw size={19} strokeWidth={1.5} color={colors.text.primary} />
        </Pressable>
        <Pressable
          onPress={() => Share.share({ title: 'Device capabilities', message: report() }).catch(() => {})}
          style={s.iconBtn}
          accessibilityRole="button"
          accessibilityLabel="Share readings"
        >
          <Share2 size={19} strokeWidth={1.5} color={colors.text.primary} />
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={s.body}>
        <Text style={s.lede}>
          What this device&#39;s WebView can do. Runs offline against the staged
          viewer; no document is opened and nothing is sent anywhere until you
          tap share.
        </Text>

        {iosNote && (
          <View style={s.note}>
            <Text style={s.noteText}>
              This device renders plans through PDFKit, not the bundled viewer,
              so these measurements do not apply to it.
            </Text>
          </View>
        )}

        {!!stageError && (
          <View style={[s.note, { borderColor: semantic.criticalBorder }]}>
            <Text style={s.noteText}>
              {stageError === 'assets-missing'
                ? 'The bundled pdf.js build is not present on this device, so there is nothing staged to measure.'
                : `The viewer could not be staged (${stageError}).`}
            </Text>
          </View>
        )}

        {!stageError && !done && (
          <View style={s.row}>
            <ActivityIndicator size="small" color={semantic.neutral} />
            <Text style={s.rowText}>Reading…</Text>
          </View>
        )}

        {ORDER.filter((k) => readings[k]).map((k) => (
          <View key={k} style={s.card}>
            <Text style={s.cardTitle}>{k}</Text>
            <Text style={s.cardBody} selectable>{JSON.stringify(readings[k], null, 2)}</Text>
          </View>
        ))}

        {done && (
          <Text style={s.doneText}>
            Read complete. Share sends the whole run as text.
          </Text>
        )}
      </ScrollView>

      {/* OFFSCREEN, NOT HIDDEN. A WebView with display:none is not guaranteed
          to execute on Android, and this one's whole job is to execute. One
          pixel, parked outside the visible area. */}
      {!!viewerUri && !iosNote && (
        <View style={s.offscreen} pointerEvents="none">
          <WebView
            key={runId}
            source={{ uri: `${viewerUri}?caps=1` }}
            originWhitelist={['file://', '*']}
            allowFileAccess
            allowFileAccessFromFileURLs
            allowUniversalAccessFromFileURLs
            allowingReadAccessToURL={pdfJsViewerDir()}
            javaScriptEnabled
            onMessage={onMessage}
            style={{ width: 1, height: 1 }}
          />
        </View>
      )}
    </SafeAreaView>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    container: { flex: 1, backgroundColor: colors.background?.primary || '#050a12' },
    topBar: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.sm,
      borderBottomWidth: 1,
      borderBottomColor: colors.glass.border,
    },
    iconBtn: { padding: spacing.sm, borderRadius: borderRadius.md },
    title: { fontSize: 17, fontWeight: '600', color: colors.text.primary },
    body: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xl },
    lede: { fontSize: 14, lineHeight: 20, color: colors.text.secondary },
    note: {
      borderWidth: 1,
      borderColor: colors.glass.border,
      borderRadius: borderRadius.lg,
      padding: spacing.md,
      backgroundColor: colors.glass.background,
    },
    noteText: { fontSize: 13, lineHeight: 19, color: colors.text.secondary },
    row: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
    rowText: { fontSize: 14, color: colors.text.secondary },
    card: {
      borderWidth: 1,
      borderColor: colors.glass.border,
      borderRadius: borderRadius.lg,
      padding: spacing.md,
      backgroundColor: colors.glass.background,
      gap: spacing.xs,
    },
    cardTitle: {
      fontSize: 12,
      fontWeight: '700',
      letterSpacing: 0.5,
      color: colors.text.muted,
      textTransform: 'uppercase',
    },
    cardBody: {
      fontSize: 12,
      lineHeight: 17,
      color: colors.text.primary,
      fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
    },
    doneText: { fontSize: 13, color: semantic.verified },
    offscreen: {
      position: 'absolute',
      left: -10,
      top: -10,
      width: 1,
      height: 1,
      opacity: 0,
    },
  });
}
