import React, { useState, useEffect, useRef, useCallback } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator, TextInput, ScrollView } from 'react-native';
import { X, Download, FileText, MapPin, Send, Trash2, CheckCircle, Users } from 'lucide-react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { dropboxAPI, annotationsAPI, usersAPI } from '../utils/api';

// Build a stable document identifier for an annotation. Direct-upload files
// have an empty `path` so `file.path` alone would cause every project's
// direct-uploaded annotations to collide under the empty string. Use the
// file's id as the sentinel in that case (`file:{id}`) — the backend
// treats this pattern as a first-class document_path key.
function documentKeyFor(file) {
  if (!file) return '';
  if (file.path) return file.path;
  const id = file.id || file._id;
  return id ? `file:${id}` : '';
}

const API_BASE = process.env.EXPO_PUBLIC_API_URL || process.env.NEXT_PUBLIC_API_URL || 'https://api.levelog.com';

// Resolve a URL returned by the backend into something an <iframe src> can load.
// Handles three shapes: relative `/api/...` (backend-proxy), absolute backend proxy,
// or any other absolute URL (already presigned / Dropbox / R2 public). Backend-proxy
// URLs get a `?token=` query param appended so the iframe request is authenticated.
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
import { useTheme } from '../context/ThemeContext';
import { useAuth } from '../context/AuthContext';
import { spacing } from '../styles/theme';

export default function PDFViewerWeb({ visible, file, projectId, onClose }) {
  const { colors } = useTheme();
  const { user } = useAuth();
  const [url, setUrl] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  // Annotation state
  const [annotations, setAnnotations] = useState([]);
  const [pinModeActive, setPinModeActive] = useState(false);
  const [selectedAnnotation, setSelectedAnnotation] = useState(null);
  const [showNotePanel, setShowNotePanel] = useState(false);
  const [pendingPosition, setPendingPosition] = useState(null);
  const [newComment, setNewComment] = useState('');
  const [replyText, setReplyText] = useState('');
  // Recipient picker: null means "Everyone in the company".
  const [companyRoster, setCompanyRoster] = useState([]);
  const [selectedRecipientIds, setSelectedRecipientIds] = useState([]); // empty = 'all'
  const [showRecipientPicker, setShowRecipientPicker] = useState(false);
  const containerRef = useRef(null);

  useEffect(() => {
    if (visible && projectId) {
      setLoading(true);
      setError(false);
      // Direct-upload path: r2_url is already a backend-proxy URL or presigned URL.
      if (file?.directUrl || file?.r2_url) {
        resolvePdfSrc(file.directUrl || file.r2_url).then(src => { setUrl(src); setLoading(false); });
      } else if (file?.path) {
        dropboxAPI.getFileUrl(projectId, file.path)
          .then(async res => { setUrl(await resolvePdfSrc(res.url)); setLoading(false); })
          .catch(() => { setError(true); setLoading(false); });
      } else {
        setError(true);
        setLoading(false);
      }
    }
    return () => { setUrl(null); };
  }, [visible, file, projectId]);

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

  // Load the company roster once when the viewer first opens so the
  // recipient picker can show real names.
  useEffect(() => {
    if (!visible) return;
    let mounted = true;
    usersAPI.companyRoster()
      .then((list) => { if (mounted) setCompanyRoster(list || []); })
      .catch(() => { /* silent — picker just shows Everyone-only */ });
    return () => { mounted = false; };
  }, [visible]);

  const handleContainerClick = useCallback((e) => {
    if (!pinModeActive) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    setPendingPosition({ x: Math.max(0, Math.min(1, x)), y: Math.max(0, Math.min(1, y)) });
    setPinModeActive(false);
    setShowNotePanel(true);
    setNewComment('');
  }, [pinModeActive]);

  const handleCreateNote = useCallback(async () => {
    if (!pendingPosition) return;
    try {
      // Build the payload: prefer file_id for direct-upload files (stable
      // across renames/R2 key changes), fall back to document_path.
      const payload = {
        project_id: projectId,
        page_number: 1,
        position: pendingPosition,
        comment: newComment || '',
        recipients: selectedRecipientIds.length ? selectedRecipientIds : 'all',
      };
      if (file?.id) payload.file_id = file.id;
      if (file?.path) payload.document_path = file.path;
      await annotationsAPI.create(payload);
      setShowNotePanel(false);
      setPendingPosition(null);
      setNewComment('');
      setSelectedRecipientIds([]);
      setShowRecipientPicker(false);
      await loadAnnotations();
    } catch (e) {
      console.error('Failed to create annotation:', e);
    }
  }, [pendingPosition, projectId, file?.id, file?.path, newComment, selectedRecipientIds, loadAnnotations]);

  const toggleRecipient = useCallback((id) => {
    setSelectedRecipientIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  }, []);

  const handleReply = useCallback(async () => {
    if (!selectedAnnotation || !replyText.trim()) return;
    try {
      await annotationsAPI.reply(selectedAnnotation._id || selectedAnnotation.id, replyText.trim());
      setReplyText('');
      await loadAnnotations();
      // Refresh selected annotation
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
    <View style={styles.overlay}>
      {/* Top Bar */}
      <View style={styles.topBar}>
        <Pressable onPress={onClose} style={styles.closeBtn}>
          <X size={22} strokeWidth={1.5} color="#fff" />
        </Pressable>
        <Text numberOfLines={1} style={styles.fileName}>{file?.name || 'Document'}</Text>
        <View style={{ flex: 1 }} />
        <Pressable
          onPress={() => { setPinModeActive(!pinModeActive); setSelectedAnnotation(null); setShowNotePanel(false); }}
          style={[styles.closeBtn, pinModeActive && { backgroundColor: '#3b82f6' }]}
        >
          <MapPin size={20} strokeWidth={1.5} color="#fff" />
        </Pressable>
        {url && (
          <Pressable onPress={() => window.open(url, '_blank')} style={styles.closeBtn}>
            <Download size={20} strokeWidth={1.5} color="#fff" />
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
          <Pressable style={styles.retryBtn} onPress={() => { setError(false); setLoading(true); dropboxAPI.getFileUrl(projectId, file.path).then(r => { setUrl(r.url); setLoading(false); }).catch(() => { setError(true); setLoading(false); }); }}>
            <Text style={styles.retryText}>Try Again</Text>
          </Pressable>
        </View>
      )}

      {!loading && !error && url && (
        <View style={{ flex: 1, flexDirection: 'row' }}>
          {/* PDF container with annotations overlay */}
          <div
            ref={containerRef}
            onClick={handleContainerClick}
            style={{
              flex: 1,
              position: 'relative',
              cursor: pinModeActive ? 'crosshair' : 'default',
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            <iframe
              src={url}
              style={{
                flex: 1,
                width: '100%',
                height: '100%',
                border: 'none',
                pointerEvents: pinModeActive ? 'none' : 'auto',
              }}
              title={file?.name || 'PDF'}
            />

            {/* Pin mode overlay */}
            {pinModeActive && (
              <div style={{
                position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
                backgroundColor: 'rgba(59, 130, 246, 0.08)',
                display: 'flex', alignItems: 'flex-end', justifyContent: 'center',
                paddingBottom: 32,
                zIndex: 10,
              }}>
                <div style={{
                  backgroundColor: 'rgba(0,0,0,0.75)', borderRadius: 8,
                  padding: '10px 20px',
                }}>
                  <Text style={{ color: '#fff', fontSize: 14 }}>Tap anywhere to place a note</Text>
                </div>
              </div>
            )}

            {/* Annotation markers */}
            {annotations.map((ann) => {
              const pos = ann.position || {};
              const annId = ann._id || ann.id;
              return (
                <div
                  key={annId}
                  onClick={(e) => { e.stopPropagation(); if (!pinModeActive) { setSelectedAnnotation(ann); setShowNotePanel(false); setReplyText(''); } }}
                  style={{
                    position: 'absolute',
                    left: `${(pos.x || 0) * 100}%`,
                    top: `${(pos.y || 0) * 100}%`,
                    width: 28, height: 28,
                    borderRadius: 14,
                    backgroundColor: getMarkerColor(ann),
                    border: '2px solid #fff',
                    boxShadow: '0 2px 6px rgba(0,0,0,0.35)',
                    transform: 'translate(-50%, -50%)',
                    cursor: 'pointer',
                    zIndex: 20,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}
                >
                  <MapPin size={14} strokeWidth={2} color="#fff" />
                </div>
              );
            })}
          </div>

          {/* Note creation panel (right side) */}
          {showNotePanel && (
            <View style={styles.sidePanel}>
              <Text style={styles.panelTitle}>Plan Notes</Text>
              <Text style={styles.panelSubtitle}>Add a note to this location</Text>
              <TextInput
                style={styles.textInput}
                placeholder="Add a comment (optional)"
                placeholderTextColor="#64748b"
                value={newComment}
                onChangeText={setNewComment}
                multiline
              />

              {/* Recipient picker */}
              <View style={{ marginTop: 12 }}>
                <Text style={{ color: '#94a3b8', fontSize: 12, fontWeight: '600', marginBottom: 6 }}>
                  SEND TO
                </Text>
                <Pressable
                  onPress={() => setShowRecipientPicker((v) => !v)}
                  style={{
                    flexDirection: 'row', alignItems: 'center',
                    backgroundColor: 'rgba(255,255,255,0.06)',
                    borderWidth: 1, borderColor: 'rgba(255,255,255,0.12)',
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
                      marginTop: 6, maxHeight: 220,
                      borderWidth: 1, borderColor: 'rgba(255,255,255,0.1)',
                      borderRadius: 8, backgroundColor: '#0b1220',
                    }}
                  >
                    <ScrollView style={{ maxHeight: 220 }}>
                      {/* "Everyone" option — clearing the list */}
                      <Pressable
                        onPress={() => { setSelectedRecipientIds([]); }}
                        style={{
                          flexDirection: 'row', alignItems: 'center',
                          paddingHorizontal: 10, paddingVertical: 9,
                          borderBottomWidth: 1, borderBottomColor: 'rgba(255,255,255,0.06)',
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
                              borderBottomWidth: 1, borderBottomColor: 'rgba(255,255,255,0.04)',
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

              <View style={styles.panelActions}>
                <Pressable style={styles.sendBtn} onPress={handleCreateNote}>
                  <Send size={16} strokeWidth={1.5} color="#fff" />
                  <Text style={styles.sendBtnText}>Send</Text>
                </Pressable>
                <Pressable style={styles.cancelBtn} onPress={() => {
                  setShowNotePanel(false);
                  setPendingPosition(null);
                  setSelectedRecipientIds([]);
                  setShowRecipientPicker(false);
                }}>
                  <Text style={styles.cancelBtnText}>Cancel</Text>
                </Pressable>
              </View>
            </View>
          )}

          {/* Thread panel (right side) */}
          {selectedAnnotation && !showNotePanel && (
            <View style={styles.sidePanel}>
              <View style={styles.panelHeader}>
                <Text style={styles.panelTitle}>Plan Notes</Text>
                <Pressable onPress={() => setSelectedAnnotation(null)}>
                  <X size={20} strokeWidth={1.5} color="#94a3b8" />
                </Pressable>
              </View>

              <ScrollView style={styles.threadScroll}>
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
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  overlay: { position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 9999, backgroundColor: '#050a12', display: 'flex', flexDirection: 'column' },
  topBar: { flexDirection: 'row', alignItems: 'center', padding: 12, paddingHorizontal: 16, borderBottomWidth: 1, borderBottomColor: 'rgba(255,255,255,0.1)', gap: 12 },
  closeBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: 'rgba(255,255,255,0.1)', alignItems: 'center', justifyContent: 'center' },
  fileName: { color: '#e2e8f0', fontSize: 15, fontWeight: '600', maxWidth: 400 },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 32 },
  loadingText: { color: '#94a3b8', marginTop: 12, fontSize: 14 },
  errorTitle: { color: '#e2e8f0', fontSize: 18, fontWeight: '600', marginTop: 16 },
  errorSub: { color: '#64748b', fontSize: 14, marginTop: 8, textAlign: 'center' },
  retryBtn: { marginTop: 20, paddingHorizontal: 24, paddingVertical: 10, backgroundColor: '#3b82f6', borderRadius: 8 },
  retryText: { color: '#fff', fontSize: 14, fontWeight: '600' },

  // Side panel
  sidePanel: { width: 340, backgroundColor: '#0f172a', borderLeftWidth: 1, borderLeftColor: 'rgba(255,255,255,0.1)', padding: 20 },
  panelHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 },
  panelTitle: { color: '#e2e8f0', fontSize: 17, fontWeight: '700', marginBottom: 4 },
  panelSubtitle: { color: '#94a3b8', fontSize: 13, marginBottom: 16 },
  textInput: { backgroundColor: 'rgba(255,255,255,0.06)', borderWidth: 1, borderColor: 'rgba(255,255,255,0.12)', borderRadius: 8, padding: 12, color: '#e2e8f0', fontSize: 14, minHeight: 80, textAlignVertical: 'top' },
  panelActions: { flexDirection: 'row', gap: 10, marginTop: 16 },
  sendBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: '#3b82f6', paddingHorizontal: 18, paddingVertical: 10, borderRadius: 8 },
  sendBtnText: { color: '#fff', fontSize: 14, fontWeight: '600' },
  cancelBtn: { paddingHorizontal: 18, paddingVertical: 10, borderRadius: 8, backgroundColor: 'rgba(255,255,255,0.08)' },
  cancelBtnText: { color: '#94a3b8', fontSize: 14, fontWeight: '600' },

  // Thread
  threadScroll: { flex: 1, marginTop: 12 },
  threadEntry: { marginBottom: 16, paddingBottom: 12, borderBottomWidth: 1, borderBottomColor: 'rgba(255,255,255,0.06)' },
  threadAuthor: { color: '#93c5fd', fontSize: 13, fontWeight: '600', marginBottom: 4 },
  threadMessage: { color: '#e2e8f0', fontSize: 14, lineHeight: 20 },
  threadTime: { color: '#475569', fontSize: 11, marginTop: 4 },
  replyRow: { flexDirection: 'row', gap: 8, marginTop: 12 },
  replyInput: { flex: 1, backgroundColor: 'rgba(255,255,255,0.06)', borderWidth: 1, borderColor: 'rgba(255,255,255,0.12)', borderRadius: 8, padding: 10, color: '#e2e8f0', fontSize: 14 },
  replyBtn: { width: 40, height: 40, borderRadius: 8, backgroundColor: '#3b82f6', alignItems: 'center', justifyContent: 'center' },
  threadActions: { flexDirection: 'row', gap: 12, marginTop: 16, paddingTop: 12, borderTopWidth: 1, borderTopColor: 'rgba(255,255,255,0.08)' },
  resolveBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8, backgroundColor: 'rgba(34,197,94,0.12)' },
  resolveBtnText: { color: '#22c55e', fontSize: 13, fontWeight: '600' },
  deleteBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8, backgroundColor: 'rgba(239,68,68,0.12)' },
  deleteBtnText: { color: '#ef4444', fontSize: 13, fontWeight: '600' },
});
