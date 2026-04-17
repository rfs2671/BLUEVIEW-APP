import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { View, Text, StyleSheet, Modal, Pressable, ActivityIndicator, Linking, TextInput, ScrollView, Dimensions, Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { X, Download, FileText, ExternalLink, MapPin, Send, Trash2, CheckCircle } from 'lucide-react-native';
import { dropboxAPI, annotationsAPI } from '../utils/api';
import { useTheme } from '../context/ThemeContext';
import { useAuth } from '../context/AuthContext';
import { spacing } from '../styles/theme';

const API_BASE = process.env.EXPO_PUBLIC_API_URL || process.env.NEXT_PUBLIC_API_URL || 'https://api.levelog.com';

// Resolve whatever URL the backend gave us into something a native WebView can render.
// Backend-proxy paths (`/api/projects/.../files/.../content`) get upgraded to an
// absolute api.levelog.com URL and carry a `?token=` JWT so the stream endpoint
// accepts the request (WebViews can't set Authorization headers).
async function resolvePdfSrc(rawUrl) {
  if (!rawUrl) return null;
  let abs = rawUrl;
  if (rawUrl.startsWith('/')) abs = `${API_BASE}${rawUrl}`;
  if (abs.includes('/api/projects/') && abs.includes('/files/') && abs.endsWith('/content')) {
    try {
      const tok = await AsyncStorage.getItem('blueview_token');
      if (tok) abs += (abs.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(tok);
    } catch {}
  }
  return abs;
}

// On Android, WebView can't natively render PDFs — we wrap the URL in
// Mozilla's hosted pdf.js viewer. On iOS, WKWebView renders application/pdf
// content natively via PDFKit with smooth pinch/zoom/pan, so we load the
// PDF URL directly.
function pdfJsViewerUrl(pdfUrl) {
  return `https://mozilla.github.io/pdf.js/web/viewer.html?file=${encodeURIComponent(pdfUrl)}`;
}

function webViewSourceForPdf(pdfUrl) {
  if (Platform.OS === 'ios') {
    // PDFKit via WKWebView: smooth native zoom/scroll.
    return { uri: pdfUrl };
  }
  // Android: pdf.js fallback.
  return { uri: pdfJsViewerUrl(pdfUrl) };
}

export default function PDFViewer({ visible, file, projectId, onClose }) {
  const { colors } = useTheme();
  const { user } = useAuth();
  const [url, setUrl] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

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
  const webViewSource = useMemo(() => (url ? webViewSourceForPdf(url) : null), [url]);

  useEffect(() => {
    if (visible && projectId) {
      setLoading(true);
      setError(false);
      setUrl(null);
      // Direct-upload files expose their URL on the record itself (either
      // `directUrl` pushed by construction-plans.jsx or the raw `r2_url`
      // from the list response). Only fall back to the Dropbox temp-link
      // endpoint for files that don't have a direct URL (i.e. Dropbox-
      // synced files whose `path` is still populated).
      if (file?.directUrl || file?.r2_url) {
        resolvePdfSrc(file.directUrl || file.r2_url)
          .then(src => { setUrl(src); setLoading(false); })
          .catch(() => { setError(true); setLoading(false); });
      } else if (file?.path) {
        dropboxAPI.getFileUrl(projectId, file.path)
          .then(async res => { setUrl(await resolvePdfSrc(res.url)); setLoading(false); })
          .catch(() => { setError(true); setLoading(false); });
      } else {
        setError(true);
        setLoading(false);
      }
    }
  }, [visible, file, projectId]);

  // Load annotations
  const loadAnnotations = useCallback(async () => {
    if (!projectId || !file?.path) return;
    try {
      const data = await annotationsAPI.getForDocument(projectId, file.path);
      setAnnotations(Array.isArray(data) ? data : (data.items || []));
    } catch (e) {
      console.error('Failed to load annotations:', e);
    }
  }, [projectId, file?.path]);

  useEffect(() => {
    if (visible && file?.path && projectId) {
      loadAnnotations();
    }
  }, [visible, file, projectId, loadAnnotations]);

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
      await annotationsAPI.create({
        project_id: projectId,
        document_path: file.path,
        page_number: 1,
        position: pendingPosition,
        comment: newComment || '',
        recipients: 'all',
      });
      setShowNoteSheet(false);
      setPendingPosition(null);
      setNewComment('');
      await loadAnnotations();
    } catch (e) {
      console.error('Failed to create annotation:', e);
    }
  }, [pendingPosition, projectId, file?.path, newComment, loadAnnotations]);

  const handleReply = useCallback(async () => {
    if (!selectedAnnotation || !replyText.trim()) return;
    try {
      await annotationsAPI.reply(selectedAnnotation._id || selectedAnnotation.id, replyText.trim());
      setReplyText('');
      await loadAnnotations();
      const updated = await annotationsAPI.getForDocument(projectId, file.path);
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
    if (annotation.status === 'resolved') return '#22c55e';
    const creatorId = annotation.created_by?._id || annotation.created_by?.id || annotation.created_by;
    const currentUserId = user?._id || user?.id;
    if (creatorId === currentUserId) return '#1565C0';
    return '#f59e0b';
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
          {url && (
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
            <Text style={styles.errorSub}>The file may be unavailable or corrupted.</Text>
            {url && (
              <Pressable style={styles.actionBtn} onPress={() => Linking.openURL(url)}>
                <Text style={styles.actionText}>Open Externally</Text>
              </Pressable>
            )}
            <Pressable style={[styles.actionBtn, { backgroundColor: 'rgba(255,255,255,0.1)' }]} onPress={() => { setError(false); setLoading(true); dropboxAPI.getFileUrl(projectId, file.path).then(r => { setUrl(r.url); setLoading(false); }).catch(() => { setError(true); setLoading(false); }); }}>
              <Text style={styles.actionText}>Try Again</Text>
            </Pressable>
          </View>
        )}

        {!loading && !error && url && (
          <View
            style={{ flex: 1 }}
            onLayout={(e) => setContainerLayout(e.nativeEvent.layout)}
          >
            {/* WebView for PDF — iOS uses PDFKit natively (smooth pinch-zoom);
                Android wraps the URL in pdf.js since its WebView can't render
                PDFs on its own. */}
            {React.createElement(
              require('react-native-webview').default,
              {
                source: webViewSource,
                style: { flex: 1, backgroundColor: '#050a12' },
                originWhitelist: ['*'],
                javaScriptEnabled: true,
                domStorageEnabled: true,
                mixedContentMode: 'always',
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
            <View style={styles.sheetActions}>
              <Pressable style={styles.sheetSendBtn} onPress={handleCreateNote}>
                <Send size={16} strokeWidth={1.5} color="#fff" />
                <Text style={styles.sheetSendText}>Send</Text>
              </Pressable>
              <Pressable style={styles.sheetCancelBtn} onPress={() => { setShowNoteSheet(false); setPendingPosition(null); }}>
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
                  <CheckCircle size={16} strokeWidth={1.5} color="#22c55e" />
                  <Text style={styles.resolveBtnText}>Mark Resolved</Text>
                </Pressable>
              )}
              {canDelete(selectedAnnotation) && (
                <Pressable style={styles.deleteBtn} onPress={handleDelete}>
                  <Trash2 size={16} strokeWidth={1.5} color="#ef4444" />
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
  topBar: { flexDirection: 'row', alignItems: 'center', paddingTop: 50, paddingBottom: 12, paddingHorizontal: 16, borderBottomWidth: 1, borderBottomColor: 'rgba(255,255,255,0.1)', gap: 12 },
  iconBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: 'rgba(255,255,255,0.1)', alignItems: 'center', justifyContent: 'center' },
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
  pinInstruction: { backgroundColor: 'rgba(0,0,0,0.75)', borderRadius: 8, paddingHorizontal: 20, paddingVertical: 10 },
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
    borderTopWidth: 1, borderTopColor: 'rgba(255,255,255,0.1)',
    padding: 20,
    maxHeight: '50%',
    zIndex: 50,
    elevation: 10,
    shadowColor: '#000', shadowOffset: { width: 0, height: -4 }, shadowOpacity: 0.3, shadowRadius: 8,
  },
  sheetHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  sheetTitle: { color: '#e2e8f0', fontSize: 17, fontWeight: '700', marginBottom: 4 },
  sheetSubtitle: { color: '#94a3b8', fontSize: 13, marginBottom: 12 },
  sheetInput: { backgroundColor: 'rgba(255,255,255,0.06)', borderWidth: 1, borderColor: 'rgba(255,255,255,0.12)', borderRadius: 8, padding: 12, color: '#e2e8f0', fontSize: 14, minHeight: 70, textAlignVertical: 'top' },
  sheetActions: { flexDirection: 'row', gap: 10, marginTop: 14 },
  sheetSendBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: '#3b82f6', paddingHorizontal: 18, paddingVertical: 10, borderRadius: 8 },
  sheetSendText: { color: '#fff', fontSize: 14, fontWeight: '600' },
  sheetCancelBtn: { paddingHorizontal: 18, paddingVertical: 10, borderRadius: 8, backgroundColor: 'rgba(255,255,255,0.08)' },
  sheetCancelText: { color: '#94a3b8', fontSize: 14, fontWeight: '600' },

  // Thread
  threadScroll: { maxHeight: 180, marginVertical: 8 },
  threadEntry: { marginBottom: 12, paddingBottom: 10, borderBottomWidth: 1, borderBottomColor: 'rgba(255,255,255,0.06)' },
  threadAuthor: { color: '#93c5fd', fontSize: 13, fontWeight: '600', marginBottom: 3 },
  threadMessage: { color: '#e2e8f0', fontSize: 14, lineHeight: 20 },
  threadTime: { color: '#475569', fontSize: 11, marginTop: 3 },
  replyRow: { flexDirection: 'row', gap: 8, marginTop: 8 },
  replyInput: { flex: 1, backgroundColor: 'rgba(255,255,255,0.06)', borderWidth: 1, borderColor: 'rgba(255,255,255,0.12)', borderRadius: 8, padding: 10, color: '#e2e8f0', fontSize: 14 },
  replyBtn: { width: 40, height: 40, borderRadius: 8, backgroundColor: '#3b82f6', alignItems: 'center', justifyContent: 'center' },
  threadActions: { flexDirection: 'row', gap: 12, marginTop: 12, paddingTop: 10, borderTopWidth: 1, borderTopColor: 'rgba(255,255,255,0.08)' },
  resolveBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8, backgroundColor: 'rgba(34,197,94,0.12)' },
  resolveBtnText: { color: '#22c55e', fontSize: 13, fontWeight: '600' },
  deleteBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8, backgroundColor: 'rgba(239,68,68,0.12)' },
  deleteBtnText: { color: '#ef4444', fontSize: 13, fontWeight: '600' },
});
