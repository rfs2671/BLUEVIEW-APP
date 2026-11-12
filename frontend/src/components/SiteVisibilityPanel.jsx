import React, { useEffect, useRef, useState } from 'react';
import { View, Text, Pressable, Switch, StyleSheet, ActivityIndicator } from 'react-native';
import { ChevronLeft, ChevronRight, Folder, FileText } from 'lucide-react-native';
import { useTheme } from '../context/ThemeContext';
import { dropboxAPI } from '../utils/api';
import { spacing, typography } from '../styles/theme';

/**
 * WHAT THE GATE TABLET SHOWS, ONE FOLDER AT A TIME.
 *
 * Two screens inside one card, and nothing else to learn:
 *
 *   ALL FOLDERS   each folder has one switch -- on the tablet or not -- and a
 *                 line saying how much of it is shown. Tapping the row opens it.
 *   ONE FOLDER    the same switch at the top, then every file in the folder
 *                 with its own switch. "Show all" / "Hide all" for the long ones.
 *
 * EVERY SWITCH SAVES WHEN IT IS FLIPPED. There used to be a "Save visibility"
 * button under the folder ticks; a person who ticked and closed the sheet lost
 * the change without being told. A failed save puts the switch back and says so.
 *
 * Admin only: the endpoints behind it refuse anyone else, and a refused read
 * simply leaves the card off the sheet.
 */
export default function SiteVisibilityPanel({ projectId, toast, style }) {
  const { colors } = useTheme();
  const s = buildStyles(colors);

  const [folders, setFolders] = useState([]);
  const [selected, setSelected] = useState([]);
  const [hiddenCounts, setHiddenCounts] = useState({});
  const [open, setOpen] = useState(null);          // folder name, or null for the list
  const [files, setFiles] = useState(null);        // files of the open folder
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [status, setStatus] = useState('');        // '', 'saving', 'saved'
  const savedTimer = useRef(null);

  const load = async () => {
    if (!projectId) return;
    try {
      const data = await dropboxAPI.getSiteDeviceSubfolders(projectId);
      setFolders(Array.isArray(data?.subfolders) ? data.subfolders : []);
      setSelected(Array.isArray(data?.selected) ? data.selected : []);
      setHiddenCounts(data?.hidden_counts && typeof data.hidden_counts === 'object' ? data.hidden_counts : {});
    } catch (_e) {
      setFolders([]);
    }
  };
  useEffect(() => { load(); }, [projectId]);
  useEffect(() => () => clearTimeout(savedTimer.current), []);

  const isOn = (name) => selected.some((x) => x.toLowerCase() === String(name).toLowerCase());

  const flash = (state) => {
    clearTimeout(savedTimer.current);
    setStatus(state);
    if (state === 'saved') savedTimer.current = setTimeout(() => setStatus(''), 1800);
  };

  const fail = (e) => {
    flash('');
    if (toast) toast.error('Not saved', e?.response?.data?.detail || 'Check the connection and try again.');
  };

  // ── folder switch ────────────────────────────────────────────────────────
  const setFolder = async (name, on) => {
    const before = selected;
    const next = on
      ? [...selected.filter((x) => x.toLowerCase() !== name.toLowerCase()), name]
      : selected.filter((x) => x.toLowerCase() !== name.toLowerCase());
    setSelected(next);
    flash('saving');
    try {
      await dropboxAPI.setSiteDeviceSubfolders(projectId, next);
      flash('saved');
    } catch (e) {
      setSelected(before);
      fail(e);
    }
  };

  // ── one folder's files ───────────────────────────────────────────────────
  const openFolder = async (name) => {
    setOpen(name);
    setFiles(null);
    setLoadingFiles(true);
    try {
      const data = await dropboxAPI.getSiteDeviceFolderFiles(projectId, name);
      setFiles(Array.isArray(data?.files) ? data.files : []);
    } catch (_e) {
      setFiles([]);
      if (toast) toast.error('Could not load files', 'Check the connection and try again.');
    } finally {
      setLoadingFiles(false);
    }
  };

  const saveHidden = async (nextFiles) => {
    const before = files;
    setFiles(nextFiles);
    flash('saving');
    try {
      const hidden = nextFiles.filter((f) => f.hidden).map((f) => f.path);
      await dropboxAPI.setSiteDeviceHiddenFiles(projectId, open, hidden);
      setHiddenCounts((prev) => {
        const out = { ...prev };
        if (hidden.length) out[open] = hidden.length; else delete out[open];
        return out;
      });
      flash('saved');
    } catch (e) {
      setFiles(before);
      fail(e);
    }
  };

  const setFile = (path, shown) => saveHidden(files.map((f) => (f.path === path ? { ...f, hidden: !shown } : f)));
  const setAll = (shown) => saveHidden(files.map((f) => ({ ...f, hidden: !shown })));

  if (folders.length === 0) return null;

  const statusText = status === 'saving' ? 'Saving…' : status === 'saved' ? 'Saved' : '';
  const sw = (value, onChange, label, disabled) => (
    <Switch
      value={value}
      onValueChange={onChange}
      disabled={disabled}
      trackColor={{ false: colors.glass.border, true: colors.switchOn }}
      thumbColor={colors.switchThumb}
      activeThumbColor={colors.switchThumb}
      accessibilityLabel={label}
    />
  );

  const folderLine = (name) => {
    if (!isOn(name)) return 'Not on the tablet';
    const n = hiddenCounts[name] || 0;
    return n ? `On the tablet · ${n} file${n === 1 ? '' : 's'} hidden` : 'On the tablet · all files';
  };

  // ── ONE FOLDER ───────────────────────────────────────────────────────────
  if (open) {
    const on = isOn(open);
    const shown = (files || []).filter((f) => !f.hidden).length;
    return (
      <View style={[s.card, style]}>
        <View style={s.topRow}>
          <Pressable onPress={() => setOpen(null)} hitSlop={10} style={s.back} accessibilityRole="button" accessibilityLabel="All folders">
            <ChevronLeft size={18} strokeWidth={1.8} color={colors.text.muted} />
            <Text style={s.backText}>All folders</Text>
          </Pressable>
          <Text style={s.status}>{statusText}</Text>
        </View>

        <View style={s.folderHead}>
          <Folder size={20} strokeWidth={1.6} color={colors.text.primary} />
          <Text style={s.folderTitle} numberOfLines={2}>{open}</Text>
          {sw(on, (v) => setFolder(open, v), `Show ${open} on the site tablet`)}
        </View>

        {!on ? (
          <Text style={s.hint}>Turn this folder on to choose which of its files the site tablet shows.</Text>
        ) : loadingFiles || files === null ? (
          <ActivityIndicator style={{ marginVertical: spacing.lg }} color={colors.text.muted} />
        ) : files.length === 0 ? (
          <Text style={s.hint}>No files in this folder yet.</Text>
        ) : (
          <>
            <View style={s.countRow}>
              <Text style={s.count}>{shown} of {files.length} files shown</Text>
              <View style={s.allLinks}>
                <Pressable onPress={() => setAll(true)} hitSlop={8} disabled={shown === files.length}>
                  <Text style={[s.link, shown === files.length && s.linkOff]}>Show all</Text>
                </Pressable>
                <Pressable onPress={() => setAll(false)} hitSlop={8} disabled={shown === 0}>
                  <Text style={[s.link, shown === 0 && s.linkOff]}>Hide all</Text>
                </Pressable>
              </View>
            </View>
            {files.map((f) => (
              <View key={f.path} style={s.fileRow}>
                <FileText size={18} strokeWidth={1.5} color={f.hidden ? colors.text.subtle : colors.text.primary} />
                <Text style={[s.fileName, f.hidden && s.fileHidden]} numberOfLines={2}>{f.name}</Text>
                {sw(!f.hidden, (v) => setFile(f.path, v), `Show ${f.name} on the site tablet`)}
              </View>
            ))}
          </>
        )}
      </View>
    );
  }

  // ── ALL FOLDERS ──────────────────────────────────────────────────────────
  return (
    <View style={[s.card, style]}>
      <View style={s.topRow}>
        <Text style={s.label}>VISIBLE ON SITE DEVICES</Text>
        <Text style={s.status}>{statusText}</Text>
      </View>
      <Text style={s.hint}>Switch a folder on to show it on the site tablet. Tap a folder to choose its files.</Text>
      {folders.map((name) => (
        <View key={name} style={s.folderRow}>
          <Pressable
            onPress={() => openFolder(name)}
            style={({ pressed }) => [s.folderOpen, pressed && { opacity: 0.6 }]}
            accessibilityRole="button"
            accessibilityLabel={`Open ${name}`}
          >
            <Folder size={20} strokeWidth={1.6} color={isOn(name) ? colors.text.primary : colors.text.subtle} />
            <View style={s.folderText}>
              <Text style={s.folderName} numberOfLines={1}>{name}</Text>
              <Text style={s.folderSub}>{folderLine(name)}</Text>
            </View>
            <ChevronRight size={18} strokeWidth={1.8} color={colors.text.muted} />
          </Pressable>
          {sw(isOn(name), (v) => setFolder(name, v), `Show ${name} on the site tablet`)}
        </View>
      ))}
    </View>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    card: { marginBottom: spacing.md, paddingVertical: spacing.md },
    topRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: spacing.sm },
    label: { ...typography.label, color: colors.text.muted },
    status: { fontSize: 13, color: colors.text.muted },
    hint: { fontSize: 13, lineHeight: 18, color: colors.text.muted, marginBottom: spacing.md },
    folderRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
      paddingVertical: spacing.sm,
      borderTopWidth: StyleSheet.hairlineWidth,
      borderTopColor: colors.glass.border,
    },
    folderOpen: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: spacing.md, minHeight: 48 },
    folderText: { flex: 1 },
    folderName: { fontSize: 15, fontWeight: '600', color: colors.text.primary },
    folderSub: { fontSize: 12, color: colors.text.muted, marginTop: 2 },
    back: { flexDirection: 'row', alignItems: 'center', gap: 4, minHeight: 32 },
    backText: { fontSize: 14, color: colors.text.muted },
    folderHead: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, marginBottom: spacing.md },
    folderTitle: { flex: 1, fontSize: 18, fontWeight: '700', color: colors.text.primary },
    countRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: spacing.sm },
    count: { fontSize: 13, color: colors.text.muted },
    allLinks: { flexDirection: 'row', gap: spacing.lg },
    link: { fontSize: 14, fontWeight: '600', color: colors.text.primary, textDecorationLine: 'underline' },
    linkOff: { opacity: 0.35 },
    fileRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
      minHeight: 48,
      paddingVertical: spacing.xs,
      borderTopWidth: StyleSheet.hairlineWidth,
      borderTopColor: colors.glass.border,
    },
    fileName: { flex: 1, fontSize: 14, color: colors.text.primary },
    fileHidden: { color: colors.text.subtle, textDecorationLine: 'line-through' },
  });
}
