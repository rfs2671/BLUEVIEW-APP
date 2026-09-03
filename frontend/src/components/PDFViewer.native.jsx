import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { View, Text, StyleSheet, Modal, Pressable, ActivityIndicator, Linking, TextInput, ScrollView, Dimensions, Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { X, Download, FileText, ExternalLink, MapPin, Send, Trash2, CheckCircle, Users } from 'lucide-react-native';
import { dropboxAPI, annotationsAPI, usersAPI } from '../utils/api';

// Build a stable document identifier for an annotation. Direct-upload files
// have empty `path` so we use a `file:{id}` sentinel that the backend
// treats as a first-class document_path key.
function documentKeyFor(file) {
  if (!file) return '';
  if (file.path) return file.path;
  const id = file.id || file._id;
  return id ? `file:${id}` : '';
}
import { useTheme } from '../context/ThemeContext';
import { useAuth } from '../context/AuthContext';
import { spacing } from '../styles/theme';
import { semantic, withAlpha } from '../styles/semanticColors';
import { ensurePdfJsViewer, localViewerUrlFor, pdfJsViewerDir } from '../utils/pdfjsViewer';
import { ensureCachedDocFile } from '../utils/docCache';
import {
  isLocalFileUri, authorizedPdfUrl, pdfSourcePlan, pdfCacheKey,
  PDF_SOURCE_NONE, PDF_SOURCE_LOCAL, PDF_SOURCE_DOWNLOAD,
} from '../utils/pdfSrc';

const API_BASE = process.env.EXPO_PUBLIC_API_URL || process.env.NEXT_PUBLIC_API_URL || 'https://api.levelog.com';

/* ─── PINCH-RELOAD PROBE ─────────────────────────────────────────────────
 *
 * MEASUREMENT, NOT A FIX. Flip to `true`, build to the tablet, reproduce the
 * pinch, read logcat. Ships `false`: with it off nothing below runs and the
 * component behaves exactly as it does today.
 *
 * WHAT IT IS FOR. Opening a 25-31 MB plan takes 20-30 s (settled: pdf.js
 * rasterising at MAX_CANVAS_PX over a four-viewport window — deliberate, and
 * not what this probe is about) and then every pinch-zoom reloads the WebView
 * and drops the operator back to page 1.
 *
 * TWO CANDIDATE MECHANISMS, AND THE LOG HAS TO TELL THEM APART:
 *
 *   A. REACT REBUILT THE SOURCE. `loadPdf` is keyed on the whole `file`
 *      object and opens with setUrl(null); a new `file` REFERENCE with
 *      identical fields therefore tears the url down, rebuilds
 *      `webViewSource`, and reloads. If this is it, a render is logged with
 *      `file` changing id, immediately before the reload.
 *
 *   B. NOTHING IN REACT MOVED. A pinch happens inside the WebView and
 *      delivers no touch event to React at all, so it is entirely possible
 *      the reload arrives with NO render logged — meaning the page reloaded
 *      itself, most likely because Android killed the renderer process under
 *      the canvas load. That is why `onRenderProcessGone` and `onLoadStart`
 *      are wired below: without them the log cannot separate A from B and the
 *      trip to the tablet has to be made twice.
 *
 * Read the two halves together. `viewer r<n>` lines are React; `webview` lines
 * are the page. A `webview loadStart` with no `viewer` line above it is B.
 */
const PDF_RELOAD_PROBE = false;

/**
 * IDENTITY, NOT VALUE — this is the entire point of the probe.
 *
 * The thing being hunted is a NEW OBJECT WITH THE SAME FIELDS. JSON.stringify
 * would report that as unchanged and hide it; so would printing the object.
 * A WeakMap keyed on the reference gives each distinct object a stable id for
 * as long as it lives, and a replacement gets a different one. Weak so the
 * probe never keeps a 30 MB-backed record alive.
 */
const probeIds = new WeakMap();
let probeNextId = 1;
function probeIdOf(v) {
  if (v === null) return 'null';
  if (v === undefined) return 'undefined';
  if (typeof v !== 'object' && typeof v !== 'function') return `=${String(v)}`;
  let id = probeIds.get(v);
  if (id === undefined) { id = probeNextId; probeNextId += 1; probeIds.set(v, id); }
  return `#${id}`;
}

/**
 * Turn whatever url the backend handed us into something THIS platform can
 * render, without ever letting the JWT off our own origin.
 *
 *   local `file://`  — already final. Never decorated with a token.
 *   iOS + remote     — WKWebView/PDFKit renders the PDF itself. It cannot set
 *                      an Authorization header, so our own proxy url carries
 *                      `?token=`; a foreign url is left bare. The request goes
 *                      to api.levelog.com and nowhere else.
 *   Android + remote — Android's WebView has NO PDF renderer, which is why a
 *                      viewer was ever wrapped around it. The bytes are pulled
 *                      to disk with the token in the Authorization HEADER
 *                      (docCache), and the pdf.js copy staged on this device
 *                      draws the local file. This is what replaced encoding a
 *                      token-bearing url into a viewer hosted by a third party.
 *
 * Returns a uri, or null when the bytes could not be put on disk — the caller
 * shows the error state. There is deliberately NO remote-viewer fallback: a
 * fallback is how the token got off the device in the first place.
 */
async function nativePdfUri(rawUrl, file) {
  const plan = pdfSourcePlan(rawUrl, Platform.OS);
  if (plan.kind === PDF_SOURCE_NONE) return null;
  if (plan.kind === PDF_SOURCE_LOCAL) return plan.uri;
  if (plan.kind === PDF_SOURCE_DOWNLOAD) {
    return ensureCachedDocFile({
      fileId: pdfCacheKey(file, rawUrl),
      cacheVersion: file?.cache_version ?? 0,
      remoteUrl: rawUrl,
    });
  }
  let token = null;
  try { token = await AsyncStorage.getItem('blueview_token'); } catch {}
  return authorizedPdfUrl(rawUrl, { apiBase: API_BASE, token });
}

/**
 * Two cases now, because Android's remote case no longer exists:
 *   iOS (any url)           — hand it straight to WKWebView/PDFKit. A local
 *                             `file://` already works there, which is why iOS
 *                             never needed a bundled viewer.
 *   Android (always local)  — the pdf.js copy staged on disk by pdfjsViewer.js.
 *                             `nativePdfUri` guarantees the url is a `file://`
 *                             by the time it gets here; anything else returns
 *                             null and the caller keeps the error state rather
 *                             than reaching for a viewer we do not host.
 */
function webViewSourceForPdf(pdfUrl, localViewerUri) {
  if (Platform.OS === 'ios') {
    // PDFKit via WKWebView: smooth native zoom/scroll.
    return { uri: pdfUrl };
  }
  // No staged viewer yet -> caller keeps showing the loader / error.
  if (!isLocalFileUri(pdfUrl) || !localViewerUri) return null;
  return { uri: localViewerUrlFor(localViewerUri, pdfUrl) };
}

export default function PDFViewer({ visible, file, projectId, onClose }) {
  const { colors } = useTheme();
  const { user } = useAuth();
  const [url, setUrl] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  // `file://` uri of the locally staged pdf.js viewer.html — Android only, and
  // now on EVERY Android open rather than only the offline ones. Null on iOS,
  // which renders PDFs through PDFKit and needs no viewer of ours.
  const [localViewerUri, setLocalViewerUri] = useState(null);
  const [errorHint, setErrorHint] = useState('');

  // Annotation state
  const [annotations, setAnnotations] = useState([]);
  const [pinModeActive, setPinModeActive] = useState(false);
  const [selectedAnnotation, setSelectedAnnotation] = useState(null);
  const [showNoteSheet, setShowNoteSheet] = useState(false);
  const [pendingPosition, setPendingPosition] = useState(null);
  const [newComment, setNewComment] = useState('');
  const [replyText, setReplyText] = useState('');
  const [containerLayout, setContainerLayout] = useState(null);

  // Memoize the WebView source so unrelated state updates (note sheet, reply
  // input, annotation taps) don't create a new object reference and force a
  // WebView reload. Without this, every pinch-zoom-induced re-render dropped
  // the user back to page 1.
  const webViewSource = useMemo(
    () => (url ? webViewSourceForPdf(url, localViewerUri) : null),
    [url, localViewerUri]
  );

  const isLocalPdf = isLocalFileUri(url);
  const needsLocalViewer = isLocalPdf && Platform.OS === 'android';

  // Stage the pdf.js viewer on disk the first time an Android device opens a
  // PDF. Cheap and memoised after that — it only copies two assets and writes
  // one HTML file. `url` is always a `file://` on Android by this point, so
  // this runs online as well as off.
  useEffect(() => {
    if (!visible || !needsLocalViewer) { setLocalViewerUri(null); return; }
    let mounted = true;
    setLoading(true);
    ensurePdfJsViewer()
      .then((res) => {
        if (!mounted) return;
        if (res?.ok) {
          setLocalViewerUri(res.viewerUri);
          setLoading(false);
          return;
        }
        // ⚠️ `assets-missing` means assets/pdfjs/*.txt is a placeholder
        // rather than a real pdf.js build. Since Android has no other way to
        // draw a PDF, that now stops viewing outright instead of falling back
        // to a viewer hosted elsewhere.
        setErrorHint(
          res?.reason === 'assets-missing'
            ? 'The PDF viewer is not installed in this build.'
            : 'The PDF viewer could not be prepared.'
        );
        setError(true);
        setLoading(false);
      })
      .catch(() => {
        if (!mounted) return;
        setErrorHint('The PDF viewer could not be prepared.');
        setError(true);
        setLoading(false);
      });
    return () => { mounted = false; };
  }, [visible, needsLocalViewer]);

  /**
   * ONE loader, for the first open AND for Try Again.
   *
   * Try Again used to be its own inline handler that called `setUrl(r.url)`
   * with the RAW response url — no absolutising, no auth — so a retry loaded a
   * bare relative `/api/...` path and failed every time. The button could not
   * work. Two paths to the same state is how that happened; there is now one.
   */
  const loadPdf = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError(false);
    setErrorHint('');
    setUrl(null);
    try {
      // Direct-upload files expose their URL on the record itself (either
      // `directUrl` pushed by construction-plans.jsx or the raw `r2_url`
      // from the list response). Only fall back to the Dropbox temp-link
      // endpoint for files that don't have a direct URL (i.e. Dropbox-
      // synced files whose `path` is still populated).
      let raw = file?.directUrl || file?.r2_url || null;
      if (!raw && file?.path) {
        const res = await dropboxAPI.getFileUrl(projectId, file.path);
        raw = res?.url || null;
      }
      if (!raw) { setError(true); setLoading(false); return; }

      const uri = await nativePdfUri(raw, file);
      if (!uri) {
        // Android only: the bytes could not be put on disk, and there is no
        // remote-viewer fallback by design.
        setErrorHint('This document could not be saved to this device for viewing.');
        setError(true);
        setLoading(false);
        return;
      }
      setUrl(uri);
      setLoading(false);
    } catch (_e) {
      setError(true);
      setLoading(false);
    }
  }, [projectId, file]);

  /* ─── PROBE: one line per render of this component ───────────────────
   *
   * Reports the identity of everything on the path from a prop to a WebView
   * reload — `file` -> `loadPdf` -> `url` -> `webViewSource` -> reload — and
   * names which of them moved since the previous render. Read the `changed=`
   * list first; it is the answer.
   *
   * IN AN EFFECT, NOT IN THE RENDER BODY, for two reasons: logging in render
   * is a side effect in a function React may call speculatively, and under a
   * double-invoking dev mode it would print every line twice and invite the
   * reader to see a re-render that never happened. No dep array, so it runs
   * after every commit — which is exactly the event being counted.
   */
  const probeRender = useRef(0);
  const probePrev = useRef(null);
  useEffect(() => {
    if (!PDF_RELOAD_PROBE) return;
    probeRender.current += 1;
    const probeNow = {
      file: probeIdOf(file),
      loadPdf: probeIdOf(loadPdf),
      webViewSource: probeIdOf(webViewSource),
      url: url === null || url === undefined ? String(url) : `…${String(url).slice(-28)}`,
      localViewerUri: localViewerUri === null || localViewerUri === undefined
        ? String(localViewerUri) : `…${String(localViewerUri).slice(-28)}`,
      visible: String(visible),
      projectId: probeIdOf(projectId),
      containerLayout: probeIdOf(containerLayout),
      loading: String(loading),
    };
    const prev = probePrev.current;
    const changed = prev
      ? Object.keys(probeNow).filter((k) => probeNow[k] !== prev[k])
      : ['FIRST-RENDER'];
    probePrev.current = probeNow;
    console.log(
      `[pdfprobe][viewer] r${probeRender.current} changed=[${changed.join(' ')}]`
      + ` file=${probeNow.file} loadPdf=${probeNow.loadPdf} src=${probeNow.webViewSource}`
      + ` url=${probeNow.url} viewerUri=${probeNow.localViewerUri}`
      + ` visible=${probeNow.visible} layout=${probeNow.containerLayout}`,
    );
  });

  useEffect(() => {
    if (visible) loadPdf();
  }, [visible, loadPdf]);

  // Load annotations — direct-upload files use `file:{id}` as the key.
  const docKey = documentKeyFor(file);
  const loadAnnotations = useCallback(async () => {
    if (!projectId || !docKey) return;
    try {
      const data = await annotationsAPI.getForDocument(projectId, docKey);
      setAnnotations(Array.isArray(data) ? data : (data.items || []));
    } catch (e) {
      console.error('Failed to load annotations:', e);
    }
  }, [projectId, docKey]);

  useEffect(() => {
    if (visible && docKey && projectId) {
      loadAnnotations();
    }
  }, [visible, docKey, projectId, loadAnnotations]);

  // Load the company roster for the recipient picker.
  const [companyRoster, setCompanyRoster] = useState([]);
  const [selectedRecipientIds, setSelectedRecipientIds] = useState([]);
  const [showRecipientPicker, setShowRecipientPicker] = useState(false);
  useEffect(() => {
    if (!visible) return;
    let mounted = true;
    usersAPI.companyRoster()
      .then((list) => { if (mounted) setCompanyRoster(list || []); })
      .catch(() => {});
    return () => { mounted = false; };
  }, [visible]);

  const toggleRecipient = useCallback((id) => {
    setSelectedRecipientIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  }, []);

  const handleOverlayPress = useCallback((e) => {
    if (!pinModeActive || !containerLayout) return;
    const { locationX, locationY } = e.nativeEvent;
    const x = locationX / containerLayout.width;
    const y = locationY / containerLayout.height;
    setPendingPosition({ x: Math.max(0, Math.min(1, x)), y: Math.max(0, Math.min(1, y)) });
    setPinModeActive(false);
    setShowNoteSheet(true);
    setNewComment('');
  }, [pinModeActive, containerLayout]);

  const handleCreateNote = useCallback(async () => {
    if (!pendingPosition) return;
    try {
      const payload = {
        project_id:  projectId,
        page_number: 1,
        position:    pendingPosition,
        comment:     newComment || '',
        recipients:  selectedRecipientIds.length ? selectedRecipientIds : 'all',
      };
      if (file?.id) payload.file_id = file.id;
      if (file?.path) payload.document_path = file.path;
      await annotationsAPI.create(payload);
      setShowNoteSheet(false);
      setPendingPosition(null);
      setNewComment('');
      setSelectedRecipientIds([]);
      setShowRecipientPicker(false);
      await loadAnnotations();
    } catch (e) {
      console.error('Failed to create annotation:', e);
    }
  }, [pendingPosition, projectId, file?.id, file?.path, newComment, selectedRecipientIds, loadAnnotations]);

  const handleReply = useCallback(async () => {
    if (!selectedAnnotation || !replyText.trim()) return;
    try {
      await annotationsAPI.reply(selectedAnnotation._id || selectedAnnotation.id, replyText.trim());
      setReplyText('');
      await loadAnnotations();
      const updated = await annotationsAPI.getForDocument(projectId, docKey);
      const list = Array.isArray(updated) ? updated : (updated.items || []);
      const found = list.find(a => (a._id || a.id) === (selectedAnnotation._id || selectedAnnotation.id));
      if (found) setSelectedAnnotation(found);
    } catch (e) {
      console.error('Failed to reply:', e);
    }
  }, [selectedAnnotation, replyText, projectId, file?.path, loadAnnotations]);

  const handleResolve = useCallback(async () => {
    if (!selectedAnnotation) return;
    try {
      await annotationsAPI.resolve(selectedAnnotation._id || selectedAnnotation.id);
      setSelectedAnnotation(null);
      await loadAnnotations();
    } catch (e) {
      console.error('Failed to resolve:', e);
    }
  }, [selectedAnnotation, loadAnnotations]);

  const handleDelete = useCallback(async () => {
    if (!selectedAnnotation) return;
    try {
      await annotationsAPI.delete(selectedAnnotation._id || selectedAnnotation.id);
      setSelectedAnnotation(null);
      await loadAnnotations();
    } catch (e) {
      console.error('Failed to delete:', e);
    }
  }, [selectedAnnotation, loadAnnotations]);

  const getMarkerColor = (annotation) => {
    if (annotation.status === 'resolved') return semantic.verified;
    const creatorId = annotation.created_by?._id || annotation.created_by?.id || annotation.created_by;
    const currentUserId = user?._id || user?.id;
    if (creatorId === currentUserId) return '#1565C0';
    return semantic.neutral;
  };

  const canDelete = (annotation) => {
    const creatorId = annotation.created_by?._id || annotation.created_by?.id || annotation.created_by;
    const currentUserId = user?._id || user?.id;
    return creatorId === currentUserId || user?.role === 'admin' || user?.role === 'owner';
  };

  if (!visible) return null;

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="fullScreen" onRequestClose={onClose}>
      <View style={[styles.container, { backgroundColor: '#050a12' }]}>
        {/* Top Bar */}
        <View style={styles.topBar}>
          <Pressable onPress={onClose} style={styles.iconBtn}>
            <X size={22} strokeWidth={1.5} color="#fff" />
          </Pressable>
          <Text numberOfLines={1} style={styles.fileName}>{file?.name || 'Document'}</Text>
          <View style={{ flex: 1 }} />
          <Pressable
            onPress={() => { setPinModeActive(!pinModeActive); setSelectedAnnotation(null); setShowNoteSheet(false); }}
            style={[styles.iconBtn, pinModeActive && { backgroundColor: '#3b82f6' }]}
          >
            <MapPin size={20} strokeWidth={1.5} color="#fff" />
          </Pressable>
          {/* A cached `file://` can't be handed to another app (Android throws
              FileUriExposedException), and there's nothing to open externally
              offline anyway. */}
          {url && !isLocalPdf && (
            <Pressable onPress={() => Linking.openURL(url)} style={styles.iconBtn}>
              <ExternalLink size={20} strokeWidth={1.5} color="#fff" />
            </Pressable>
          )}
        </View>

        {loading && (
          <View style={styles.center}>
            <ActivityIndicator size="large" color="#3b82f6" />
            <Text style={styles.loadingText}>Loading document...</Text>
          </View>
        )}

        {error && (
          <View style={styles.center}>
            <FileText size={48} strokeWidth={1} color="#64748b" />
            <Text style={styles.errorTitle}>Could not load document</Text>
            <Text style={styles.errorSub}>
              {errorHint || 'The file may be unavailable or corrupted.'}
            </Text>
            {url && !isLocalPdf && (
              <Pressable style={styles.actionBtn} onPress={() => Linking.openURL(url)}>
                <Text style={styles.actionText}>Open Externally</Text>
              </Pressable>
            )}
            {/* Retry runs the SAME loader the first open ran — resolving,
                authorising and (on Android) re-fetching the bytes. Hidden once
                `url` is a local file, where a retry would change nothing. */}
            {!isLocalPdf && (
              <Pressable style={[styles.actionBtn, { backgroundColor: withAlpha('#ffffff', 0.1) }]} onPress={loadPdf}>
                <Text style={styles.actionText}>Try Again</Text>
              </Pressable>
            )}
          </View>
        )}

        {/* `webViewSource` is null while the offline viewer is still staging —
            gate on it so the WebView is never mounted with a null source. */}
        {!loading && !error && url && webViewSource && (
          <View
            style={{ flex: 1 }}
            onLayout={(e) => setContainerLayout(e.nativeEvent.layout)}
          >
            {/* WebView for PDF — iOS uses PDFKit natively (smooth pinch-zoom);
                Android draws the on-device copy with the pdf.js staged by
                pdfjsViewer.js, since its WebView can't render PDFs on its
                own. */}
            {React.createElement(
              require('react-native-webview').default,
              {
                source: webViewSource,
                style: { flex: 1, backgroundColor: '#050a12' },
                originWhitelist: ['*', 'file://'],
                javaScriptEnabled: true,
                domStorageEnabled: true,
                mixedContentMode: 'always',
                // ── Local-file access ──────────────────────────────────────
                // Required for the offline viewer, and ONLY meaningful for it:
                //  allowFileAccess              — open a file:// url at all.
                //  allowFileAccessFromFileURLs  — THE critical one. The staged
                //    viewer.html is itself a file://, and pdf.js reads the PDF
                //    bytes with XHR; Android WebView blocks file:// -> file://
                //    XHR by default, which is precisely why a cached PDF used
                //    to render nothing.
                //  allowUniversalAccessFromFileURLs — some WebView builds gate
                //    the above behind this; harmless otherwise.
                // Scoped to the local case so a remote page is never granted
                // read access to the app's document directory.
                allowFileAccess: isLocalPdf,
                allowFileAccessFromFileURLs: isLocalPdf,
                allowUniversalAccessFromFileURLs: isLocalPdf,
                // iOS-only prop, and deliberately left unset on iOS: iOS loads
                // the PDF itself (PDFKit), where the default single-file read
                // access is correct — pointing it at the viewer directory would
                // instead REVOKE access to the PDF. It is set only for the
                // staged-viewer case, which needs directory-wide access so
                // viewer.html can load its sibling pdf.min.js.
                allowingReadAccessToURL: needsLocalViewer ? pdfJsViewerDir() : undefined,
                // Keep in-memory page cache across zoom/pan so the viewer
                // doesn't re-fetch when the user pinches.
                cacheEnabled: true,
                // Let the platform handle pinch-zoom + scrolling natively.
                scalesPageToFit: true,
                allowsBackForwardNavigationGestures: false,
                // iOS PDFKit needs this to let the user pinch-zoom freely.
                scrollEnabled: true,
                // Prevent the WebView from reloading on orientation/size change
                // (some Android builds re-mount the native view otherwise).
                androidLayerType: 'hardware',
                onError: () => setError(true),
                // The staged viewer reports its own failures (blocked XHR, a
                // corrupt file) — surface them instead of leaving a dark page.
                onMessage: (e) => {
                  let msg = null;
                  try { msg = JSON.parse(e?.nativeEvent?.data || '{}'); } catch (_err) { return; }
                  if (msg?.type === 'pdf-error') {
                    console.warn('Offline PDF viewer error:', msg.code, msg.detail);
                    setErrorHint(
                      msg.code === 'xhr-blocked'
                        ? 'This device blocked the saved copy from being read.'
                        : 'The saved copy of this document could not be rendered.'
                    );
                    setError(true);
                  }
                },
                /* ─── PROBE: the OTHER half of the question ────────────
                 * `onLoadStart` is the reload itself — ground truth that the
                 * page went back to the beginning, independent of anything
                 * React believes. `onRenderProcessGone` is the discriminator:
                 * if Android killed the renderer under the canvas load, the
                 * WebView comes back on its own and no dependency array had
                 * anything to do with it.
                 *
                 * Neither prop changes behaviour. react-native-webview always
                 * installs its own internal handler for both events and merely
                 * forwards to these when present, so with the flag off (they
                 * are not spread at all) and on (they only log), what the
                 * WebView does is identical.
                 */
                ...(PDF_RELOAD_PROBE ? {
                  onLoadStart: (e) => {
                    const u = String(e?.nativeEvent?.url || '');
                    console.log(`[pdfprobe][webview] loadStart url=…${u.slice(-40)}`);
                  },
                  onRenderProcessGone: (e) => {
                    console.log(
                      '[pdfprobe][webview] RENDER PROCESS GONE'
                      + ` didCrash=${String(e?.nativeEvent?.didCrash)}`
                      + ' — Android killed the page. NOT a React re-render.',
                    );
                  },
                } : {}),
                startInLoadingState: true,
                renderLoading: () => (
                  <View style={[styles.center, { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }]}>
                    <ActivityIndicator size="large" color="#3b82f6" />
                  </View>
                ),
              }
            )}

            {/* Pin mode overlay — captures taps */}
            {pinModeActive && (
              <Pressable
                style={styles.pinOverlay}
                onPress={handleOverlayPress}
              >
                <View style={styles.pinInstruction}>
                  <Text style={styles.pinInstructionText}>Tap anywhere to place a note</Text>
                </View>
              </Pressable>
            )}

            {/* Annotation markers */}
            {annotations.map((ann) => {
              const pos = ann.position || {};
              const annId = ann._id || ann.id;
              if (!containerLayout) return null;
              return (
                <Pressable
                  key={annId}
                  onPress={() => { if (!pinModeActive) { setSelectedAnnotation(ann); setShowNoteSheet(false); setReplyText(''); } }}
                  style={[
                    styles.marker,
                    {
                      left: (pos.x || 0) * containerLayout.width - 14,
                      top: (pos.y || 0) * containerLayout.height - 14,
                      backgroundColor: getMarkerColor(ann),
                    },
                  ]}
                >
                  <MapPin size={14} strokeWidth={2} color="#fff" />
                </Pressable>
              );
            })}
          </View>
        )}

        {/* Bottom sheet: Note creation */}
        {showNoteSheet && (
          <View style={styles.bottomSheet}>
            <Text style={styles.sheetTitle}>Plan Notes</Text>
            <Text style={styles.sheetSubtitle}>Add a note to this location</Text>
            <TextInput
              style={styles.sheetInput}
              placeholder="Add a comment (optional)"
              placeholderTextColor="#64748b"
              value={newComment}
              onChangeText={setNewComment}
              multiline
            />

            {/* Recipient picker */}
            <View style={{ marginTop: 10 }}>
              <Text style={{ color: '#94a3b8', fontSize: 11, fontWeight: '600', marginBottom: 5 }}>
                SEND TO
              </Text>
              <Pressable
                onPress={() => setShowRecipientPicker((v) => !v)}
                style={{
                  flexDirection: 'row', alignItems: 'center',
                  backgroundColor: withAlpha('#ffffff', 0.06),
                  borderWidth: 1, borderColor: withAlpha('#ffffff', 0.12),
                  borderRadius: 8, paddingVertical: 10, paddingHorizontal: 12,
                }}
              >
                <Users size={16} strokeWidth={1.5} color="#93c5fd" />
                <Text style={{ color: '#e2e8f0', fontSize: 14, marginLeft: 8, flex: 1 }}>
                  {selectedRecipientIds.length === 0
                    ? 'Everyone on the project'
                    : `${selectedRecipientIds.length} selected`}
                </Text>
                <Text style={{ color: '#64748b', fontSize: 12 }}>
                  {showRecipientPicker ? '▲' : '▼'}
                </Text>
              </Pressable>

              {showRecipientPicker && (
                <View
                  style={{
                    marginTop: 6, maxHeight: 180,
                    borderWidth: 1, borderColor: withAlpha('#ffffff', 0.1),
                    borderRadius: 8, backgroundColor: '#0b1220',
                  }}
                >
                  <ScrollView style={{ maxHeight: 180 }}>
                    <Pressable
                      onPress={() => setSelectedRecipientIds([])}
                      style={{
                        flexDirection: 'row', alignItems: 'center',
                        paddingHorizontal: 10, paddingVertical: 9,
                        borderBottomWidth: 1, borderBottomColor: withAlpha('#ffffff', 0.06),
                      }}
                    >
                      <View style={{
                        width: 18, height: 18, borderRadius: 4,
                        borderWidth: 1, borderColor: '#3b82f6',
                        backgroundColor: selectedRecipientIds.length === 0 ? '#3b82f6' : 'transparent',
                        marginRight: 10,
                      }} />
                      <Text style={{ color: '#e2e8f0', fontSize: 14 }}>Everyone</Text>
                    </Pressable>
                    {companyRoster.map((u) => {
                      const checked = selectedRecipientIds.includes(u.id);
                      return (
                        <Pressable
                          key={u.id}
                          onPress={() => toggleRecipient(u.id)}
                          style={{
                            flexDirection: 'row', alignItems: 'center',
                            paddingHorizontal: 10, paddingVertical: 9,
                            borderBottomWidth: 1, borderBottomColor: withAlpha('#ffffff', 0.04),
                          }}
                        >
                          <View style={{
                            width: 18, height: 18, borderRadius: 4,
                            borderWidth: 1, borderColor: '#3b82f6',
                            backgroundColor: checked ? '#3b82f6' : 'transparent',
                            marginRight: 10,
                          }} />
                          <View style={{ flex: 1 }}>
                            <Text style={{ color: '#e2e8f0', fontSize: 14 }}>{u.name}</Text>
                            {!!u.role && (
                              <Text style={{ color: '#64748b', fontSize: 11 }}>{u.role}</Text>
                            )}
                          </View>
                        </Pressable>
                      );
                    })}
                    {companyRoster.length === 0 && (
                      <Text style={{ color: '#64748b', fontSize: 12, padding: 14, textAlign: 'center' }}>
                        No other users on this company.
                      </Text>
                    )}
                  </ScrollView>
                </View>
              )}
            </View>

            <View style={styles.sheetActions}>
              <Pressable style={styles.sheetSendBtn} onPress={handleCreateNote}>
                <Send size={16} strokeWidth={1.5} color="#fff" />
                <Text style={styles.sheetSendText}>Send</Text>
              </Pressable>
              <Pressable style={styles.sheetCancelBtn} onPress={() => {
                setShowNoteSheet(false);
                setPendingPosition(null);
                setSelectedRecipientIds([]);
                setShowRecipientPicker(false);
              }}>
                <Text style={styles.sheetCancelText}>Cancel</Text>
              </Pressable>
            </View>
          </View>
        )}

        {/* Bottom sheet: Thread view */}
        {selectedAnnotation && !showNoteSheet && (
          <View style={styles.bottomSheet}>
            <View style={styles.sheetHeader}>
              <Text style={styles.sheetTitle}>Plan Notes</Text>
              <Pressable onPress={() => setSelectedAnnotation(null)}>
                <X size={20} strokeWidth={1.5} color="#94a3b8" />
              </Pressable>
            </View>

            <ScrollView style={styles.threadScroll} contentContainerStyle={{ paddingBottom: 8 }}>
              {/* Original comment */}
              <View style={styles.threadEntry}>
                <Text style={styles.threadAuthor}>
                  {selectedAnnotation.created_by?.full_name || selectedAnnotation.created_by?.name || 'User'}
                </Text>
                <Text style={styles.threadMessage}>{selectedAnnotation.comment || '(no comment)'}</Text>
                <Text style={styles.threadTime}>
                  {selectedAnnotation.created_at ? new Date(selectedAnnotation.created_at).toLocaleString() : ''}
                </Text>
              </View>

              {/* Thread replies */}
              {(selectedAnnotation.thread || []).map((entry, idx) => (
                <View key={idx} style={styles.threadEntry}>
                  <Text style={styles.threadAuthor}>{entry.user_name || 'User'}</Text>
                  <Text style={styles.threadMessage}>{entry.message}</Text>
                  <Text style={styles.threadTime}>
                    {entry.timestamp ? new Date(entry.timestamp).toLocaleString() : ''}
                  </Text>
                </View>
              ))}
            </ScrollView>

            {/* Reply input */}
            {selectedAnnotation.status !== 'resolved' && (
              <View style={styles.replyRow}>
                <TextInput
                  style={styles.replyInput}
                  placeholder="Reply..."
                  placeholderTextColor="#64748b"
                  value={replyText}
                  onChangeText={setReplyText}
                />
                <Pressable style={styles.replyBtn} onPress={handleReply}>
                  <Send size={16} strokeWidth={1.5} color="#fff" />
                </Pressable>
              </View>
            )}

            {/* Actions */}
            <View style={styles.threadActions}>
              {selectedAnnotation.status !== 'resolved' && (
                <Pressable style={styles.resolveBtn} onPress={handleResolve}>
                  <CheckCircle size={16} strokeWidth={1.5} color={semantic.verified} />
                  <Text style={styles.resolveBtnText}>Mark Resolved</Text>
                </Pressable>
              )}
              {canDelete(selectedAnnotation) && (
                <Pressable style={styles.deleteBtn} onPress={handleDelete}>
                  <Trash2 size={16} strokeWidth={1.5} color={semantic.neutral} />
                  <Text style={styles.deleteBtnText}>Delete</Text>
                </Pressable>
              )}
            </View>
          </View>
        )}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  topBar: { flexDirection: 'row', alignItems: 'center', paddingTop: 50, paddingBottom: 12, paddingHorizontal: 16, borderBottomWidth: 1, borderBottomColor: withAlpha('#ffffff', 0.1), gap: 12 },
  iconBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: withAlpha('#ffffff', 0.1), alignItems: 'center', justifyContent: 'center' },
  fileName: { color: '#e2e8f0', fontSize: 15, fontWeight: '600', maxWidth: 250 },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 32 },
  loadingText: { color: '#94a3b8', marginTop: 12, fontSize: 14 },
  errorTitle: { color: '#e2e8f0', fontSize: 18, fontWeight: '600', marginTop: 16 },
  errorSub: { color: '#64748b', fontSize: 14, marginTop: 8, textAlign: 'center' },
  actionBtn: { marginTop: 16, paddingHorizontal: 24, paddingVertical: 10, backgroundColor: '#3b82f6', borderRadius: 8 },
  actionText: { color: '#fff', fontSize: 14, fontWeight: '600' },

  // Pin mode overlay
  pinOverlay: {
    position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
    backgroundColor: 'rgba(59, 130, 246, 0.08)',
    justifyContent: 'flex-end', alignItems: 'center',
    paddingBottom: 32,
    zIndex: 10,
  },
  pinInstruction: { backgroundColor: withAlpha('#000000', 0.75), borderRadius: 8, paddingHorizontal: 20, paddingVertical: 10 },
  pinInstructionText: { color: '#fff', fontSize: 14 },

  // Annotation marker
  marker: {
    position: 'absolute',
    width: 28, height: 28, borderRadius: 14,
    borderWidth: 2, borderColor: '#fff',
    alignItems: 'center', justifyContent: 'center',
    zIndex: 20,
    elevation: 5,
    shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.35, shadowRadius: 4,
  },

  // Bottom sheet
  bottomSheet: {
    position: 'absolute', left: 0, right: 0, bottom: 0,
    backgroundColor: '#0f172a',
    borderTopLeftRadius: 16, borderTopRightRadius: 16,
    borderTopWidth: 1, borderTopColor: withAlpha('#ffffff', 0.1),
    padding: 20,
    maxHeight: '50%',
    zIndex: 50,
    elevation: 10,
    shadowColor: '#000', shadowOffset: { width: 0, height: -4 }, shadowOpacity: 0.3, shadowRadius: 8,
  },
  sheetHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  sheetTitle: { color: '#e2e8f0', fontSize: 17, fontWeight: '700', marginBottom: 4 },
  sheetSubtitle: { color: '#94a3b8', fontSize: 13, marginBottom: 12 },
  sheetInput: { backgroundColor: withAlpha('#ffffff', 0.06), borderWidth: 1, borderColor: withAlpha('#ffffff', 0.12), borderRadius: 8, padding: 12, color: '#e2e8f0', fontSize: 14, minHeight: 70, textAlignVertical: 'top' },
  sheetActions: { flexDirection: 'row', gap: 10, marginTop: 14 },
  sheetSendBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: '#3b82f6', paddingHorizontal: 18, paddingVertical: 10, borderRadius: 8 },
  sheetSendText: { color: '#fff', fontSize: 14, fontWeight: '600' },
  sheetCancelBtn: { paddingHorizontal: 18, paddingVertical: 10, borderRadius: 8, backgroundColor: withAlpha('#ffffff', 0.08) },
  sheetCancelText: { color: '#94a3b8', fontSize: 14, fontWeight: '600' },

  // Thread
  threadScroll: { maxHeight: 180, marginVertical: 8 },
  threadEntry: { marginBottom: 12, paddingBottom: 10, borderBottomWidth: 1, borderBottomColor: withAlpha('#ffffff', 0.06) },
  threadAuthor: { color: '#93c5fd', fontSize: 13, fontWeight: '600', marginBottom: 3 },
  threadMessage: { color: '#e2e8f0', fontSize: 14, lineHeight: 20 },
  threadTime: { color: '#475569', fontSize: 11, marginTop: 3 },
  replyRow: { flexDirection: 'row', gap: 8, marginTop: 8 },
  replyInput: { flex: 1, backgroundColor: withAlpha('#ffffff', 0.06), borderWidth: 1, borderColor: withAlpha('#ffffff', 0.12), borderRadius: 8, padding: 10, color: '#e2e8f0', fontSize: 14 },
  replyBtn: { width: 40, height: 40, borderRadius: 8, backgroundColor: '#3b82f6', alignItems: 'center', justifyContent: 'center' },
  threadActions: { flexDirection: 'row', gap: 12, marginTop: 12, paddingTop: 10, borderTopWidth: 1, borderTopColor: withAlpha('#ffffff', 0.08) },
  resolveBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8, backgroundColor: semantic.verifiedBg },
  resolveBtnText: { color: semantic.verified, fontSize: 13, fontWeight: '600' },
  deleteBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8, backgroundColor: semantic.criticalBg },
  deleteBtnText: { color: semantic.neutralStrong, fontSize: 13, fontWeight: '600' },
});
