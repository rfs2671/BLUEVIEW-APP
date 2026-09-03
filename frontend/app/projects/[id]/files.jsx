import React, { useState, useEffect, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  Linking,
  TextInput,
  Platform,
  Image,
  Modal,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  Cloud,
  FileText,
  Image as ImageIcon,
  File,
  Download,
  Eye,
  RefreshCw,
  Search,
  Filter,
  Check,
  Clock,
  HardDrive,
  Folder,
  FolderOpen,
  CheckCircle,
  AlertCircle,
  Upload,
  Trash2,
  ChevronLeft,
  ChevronRight,
  Unlink,
  X,
} from 'lucide-react-native';
import * as DocumentPicker from 'expo-document-picker';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard, StatCard, IconPod } from '../../../src/components/GlassCard';
import GlassButton from '../../../src/components/GlassButton';
import GlassInput from '../../../src/components/GlassInput';
import { GlassSkeleton } from '../../../src/components/GlassSkeleton';
import OfflineNotice from '../../../src/components/OfflineNotice';
import { useToast } from '../../../src/components/Toast';
import { useAuth } from '../../../src/context/AuthContext';
import { dropboxAPI, projectsAPI } from '../../../src/utils/api';
import { settleFetch } from '../../../src/utils/offlineState';
import { mayCacheList } from '../../../src/utils/dropboxSyncState';
import {
  UNFILED, folderLabel, groupByFolder, collidingNames, isColliding,
  treeHeadline, COLLISION_NOTE,
} from '../../../src/utils/dropboxTree';
import {
  listCachedDocs, cachedDocName, freeDiskBytes, cacheDocFile, sweepDocCache,
} from '../../../src/utils/docCache';
import {
  readinessOf, saveQueue, megabytes, hasRoomFor,
  READY_UNCHECKED, READY_ALL, READY_PARTIAL, READY_NONE,
} from '../../../src/utils/offlineReadiness';
import { cacheProject, readCachedProject } from '../../../src/utils/projectCache';
import {
  cacheDocList,
  readCachedDocList,
  ensureCachedDocFile,
  warmDocCache,
} from '../../../src/utils/docCache';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';
import { semantic, withAlpha } from '../../../src/styles/semanticColors';
import { useTheme } from '../../../src/context/ThemeContext';

import PDFViewer from '../../../src/components/PDFViewer';
import HeaderBrand from '../../../src/components/HeaderBrand';
import ConfirmDialog from '../../../src/components/ConfirmDialog';

const DROPBOX_BLUE = '#0061FF';

/* ─── PINCH-RELOAD PROBE (parent half) ───────────────────────────────────
 *
 * KEEP IN STEP WITH THE SAME-NAMED FLAG IN src/components/PDFViewer.native.jsx.
 * Both halves must be on together or the log answers nothing: the viewer's
 * half says "my `file` prop is a different object now", and only this half can
 * say whether THIS SCREEN minted that object or whether it appeared without
 * anyone here asking for one.
 *
 * Ships `false`. With it off nothing below runs.
 */
const PDF_RELOAD_PROBE = false;

const extOf = (filename) => String(filename || '').split('.').pop()?.toLowerCase() || '';
// PDFs are the only type with an offline story — everything else is handed to
// another app via a REMOTE url and cannot open without a connection.
const isPdf = (filename) => extOf(filename) === 'pdf';

// The on-disk name for a file row. Built through docCache so the strip and the
// cache cannot disagree about what "saved" means.
const nameOfFile = (f) => cachedDocName(f?.id || f?._id, f?.cache_version ?? 0);

// File type icons and colors
const getFileTypeInfo = (filename) => {
  const ext = filename.split('.').pop()?.toLowerCase();
  
  const typeMap = {
    pdf: { icon: FileText, color: semantic.neutral, label: 'PDF' },
    doc: { icon: FileText, color: '#3b82f6', label: 'DOC' },
    docx: { icon: FileText, color: '#3b82f6', label: 'DOCX' },
    xls: { icon: FileText, color: semantic.neutral, label: 'XLS' },
    xlsx: { icon: FileText, color: semantic.neutral, label: 'XLSX' },
    png: { icon: ImageIcon, color: '#8b5cf6', label: 'PNG' },
    jpg: { icon: ImageIcon, color: '#8b5cf6', label: 'JPG' },
    jpeg: { icon: ImageIcon, color: '#8b5cf6', label: 'JPEG' },
    gif: { icon: ImageIcon, color: '#8b5cf6', label: 'GIF' },
    dwg: { icon: File, color: semantic.neutral, label: 'DWG' },
    dxf: { icon: File, color: semantic.neutral, label: 'DXF' },
  };

  // `colors` is not in scope here — this helper is module-level, not a
  // component. semantic.neutral IS colors.text.muted (a getter over the
  // active theme), and is what every neutral entry in typeMap above already
  // uses, so the unknown-extension fallback now renders what it always
  // meant to rather than throwing.
  return typeMap[ext] || { icon: File, color: semantic.neutral, label: ext?.toUpperCase() || 'FILE' };
};

// Format file size
const formatFileSize = (bytes) => {
  if (!bytes) return 'Unknown size';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

export default function ProjectFilesScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [project, setProject] = useState(null);
  const [files, setFiles] = useState([]);
  // WHAT IS ACTUALLY ON THE DISK. Re-read rather than remembered: a stored
  // "saved" flag goes stale the moment a drawing changes in Dropbox and bumps
  // its cache_version, and the strip would then promise something untrue at the
  // exact moment it matters.
  const [cachedNames, setCachedNames] = useState(new Set());
  const [savingAll, setSavingAll] = useState(false);
  const [saveProgress, setSaveProgress] = useState({ done: 0, total: 0, failed: 0 });
  const [searchQuery, setSearchQuery] = useState('');
  const [filterType, setFilterType] = useState('all'); // all, pdf, image, document
  const [lastSynced, setLastSynced] = useState(null);
  const [syncStatus, setSyncStatus] = useState('idle'); // idle, syncing, success, error
  const [pdfViewerVisible, setPdfViewerVisible] = useState(false);
  const [selectedPdfFile, setSelectedPdfFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [fileToDelete, setFileToDelete] = useState(null);
  const [deleting, setDeleting] = useState(false);
  // 'ok' | 'offline' | 'error'. This screen used to swallow the failure with
  // `.catch(() => [])`, which rendered a silent blank plan list.
  const [fetchState, setFetchState] = useState('ok');
  const offline = fetchState === 'offline';

  // ── Linking lives on THIS screen now ───────────────────────────────────
  // dropbox-settings.jsx was a second screen for one field. Plans and
  // documents were never two things -- they are one Dropbox tree -- and the
  // folder that tree comes from is not a separate subject from the tree.
  //
  // LINKED-NESS IS `bool(project.dropbox_folder_path)` AND NOTHING ELSE.
  // There is no `dropboxEnabled` state here. The old screen carried one, fed
  // by a Switch, which made linked-ness a thing the UI remembered as well as a
  // thing the server stored -- two sources of truth for one field, with the
  // Switch's off-position quietly meaning "unlink". `dropbox_enabled` and
  // `dropbox_folder` on the project document are dead in the same way: written
  // once by create_project, read by three screens, never written again.
  const [showFolderPicker, setShowFolderPicker] = useState(false);
  const [folders, setFolders] = useState([]);
  const [currentPath, setCurrentPath] = useState('');
  const [loadingFolders, setLoadingFolders] = useState(false);
  const [linking, setLinking] = useState(false);
  const [confirmUnlink, setConfirmUnlink] = useState(false);
  const [unlinking, setUnlinking] = useState(false);

  // Site-device visibility -- which top-level subfolders the kiosk role may
  // see. Empty selection = the kiosk sees nothing.
  const [siteDeviceSubfolders, setSiteDeviceSubfolders] = useState([]);
  const [siteDeviceSelected, setSiteDeviceSelected] = useState([]);
  const [savingSiteVisibility, setSavingSiteVisibility] = useState(false);

  /**
   * THE ONE ROLE PREDICATE ON THIS SCREEN. Every admin-gated control below
   * uses this and nothing else.
   *
   * WIDE, because it has to match `get_admin_user`, which is what actually
   * authorises the endpoints these controls call:
   *
   *     if current_user.get("role") not in ["admin", "owner"]:
   *         raise HTTPException(403, "Admin access required")
   *
   * An `owner` is a role, not a platform-operator flag — `is_platform_operator`
   * is explicitly "never inferred from role" — and the server admits it
   * everywhere a company admin is admitted.
   *
   * THREE PREDICATES USED TO LIVE IN THIS FILE and they disagreed in the worst
   * possible direction. `canDelete` and the per-row delete button were the wide
   * form; the Upload/Sync action bar was `role === 'admin'`. So an owner could
   * DELETE a file and could not UPLOAD one — the narrow guard sat on the safe
   * controls and the wide guard on the destructive one. That split predates the
   * one-screen redesign; it is closed here rather than carried forward.
   */
  const isAdmin = ['owner', 'admin'].includes(String(user?.role || '').toLowerCase());
  const linkedFolder = project?.dropbox_folder_path || null;

  const scopeKey = `plans:${projectId}`;

  /* ─── PROBE: did this screen mint a new file object, or just re-render? ──
   *
   * THE DISTINCTION IS THE WHOLE QUESTION. `selectedPdfFile` is state set only
   * inside handleViewFile, so its identity SHOULD survive every re-render of
   * this screen — and this screen re-renders plenty on its own (the disk
   * re-read after a background warm, a sweep completing, a sync finishing).
   * If the viewer reports a new `file` id and no mint is logged here in the
   * same breath, the object did not come from a tap and the fault is not a
   * stale dependency array.
   *
   * A sequence number rather than a render index: the mint happens during an
   * event, the render it causes lands after, and comparing "minted" against
   * "seen" survives batching.
   */
  const probeRenderCount = useRef(0);
  const probeMintSeq = useRef(0);
  const probeSeenSeq = useRef(0);
  useEffect(() => {
    if (!PDF_RELOAD_PROBE) return;
    probeRenderCount.current += 1;
    const minted = probeMintSeq.current !== probeSeenSeq.current;
    probeSeenSeq.current = probeMintSeq.current;
    console.log(
      `[pdfprobe][files] r${probeRenderCount.current} `
      + (minted
        ? `AFTER setSelectedPdfFile(#${probeMintSeq.current})`
        : 're-render, no new selectedPdfFile')
      + ` visible=${pdfViewerVisible} selected=${selectedPdfFile ? (selectedPdfFile.name || '(unnamed)') : 'null'}`,
    );
  });

  /** Announce every object handed to the viewer, and say which branch made it. */
  const probeMint = (where, f) => {
    if (!PDF_RELOAD_PROBE) return;
    probeMintSeq.current += 1;
    console.log(
      `[pdfprobe][files] setSelectedPdfFile(#${probeMintSeq.current}) via ${where}`
      + ` name=${f?.name || '(none)'}`,
    );
  };

  // Redirect if not authenticated
  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  // Fetch data
  useEffect(() => {
    if (isAuthenticated && projectId) {
      fetchData();
    }
  }, [isAuthenticated, projectId]);

  /**
   * Write-through: a list read refreshes the offline copy — UNLESS a sync is
   * in flight, in which case what we just read may not be the whole list.
   *
   * THIS IS THE DEFECT EVERYTHING ELSE IN THIS CHANGE EXISTS FOR.
   * POST /sync-dropbox returns as soon as the background task is SCHEDULED, so
   * the read that follows it catches the sync partway through. Caching that
   * gave the CP a saved-for-offline list that was a strict SUBSET of the
   * project, and he found out in a cellar.
   *
   * WHY NOT THE OBVIOUS HEURISTIC — "don't replace a longer list with a
   * shorter one"? Because a shorter list is often CORRECT. Files are deleted
   * from Dropbox, folders get re-pointed, the site-device allow-list changes.
   * A rule that refuses to shrink would pin deleted drawings on a device for
   * ever and call it caching. Length cannot tell "halfway through a sync" from
   * "there are genuinely fewer files now" — only the sync knows, so the sync is
   * asked.
   *
   * THE BYTES ARE STILL WARMED EITHER WAY. The files in a partial list are real
   * files; pulling them down early is useful and costs nothing. It is only the
   * LIST — the thing that decides what the CP believes he has — that waits.
   */
  /** Re-read the disk. Cheap: one directory listing, not a stat per file. */
  const refreshCachedNames = async () => {
    try { setCachedNames(await listCachedDocs()); } catch (_e) { /* reads as none */ }
  };

  /**
   * SAVE ALL — the control that makes a promise.
   *
   * The background warm stays, and it is useful, but it can never tell the CP
   * he is ready because it never knew it was asked. He is deciding whether to
   * walk into a cellar; only an action he took, with a definite answer, can
   * support that decision.
   *
   * UNCAPPED, unlike the background warm's limit of 15. If he asked for all of
   * them he gets all of them.
   */
  const handleSaveAll = async () => {
    if (savingAll) return;
    const queue = saveQueue({ files, cachedNames, nameOf: nameOfFile });
    if (queue.length === 0) return;

    // ROOM CHECKED BEFORE THE FIRST BYTE, not on file 9 of 15. `null` means the
    // device would not say, and an unknown must not block him.
    const needed = queue.reduce((n, f) => n + (Number(f?.size) || 0), 0);
    const room = hasRoomFor(needed, await freeDiskBytes());
    if (room === false) {
      toast.error(
        'Not enough space',
        `Saving these plans needs about ${megabytes(needed)} MB and this device is nearly full. Free some space and try again.`,
      );
      return;
    }

    setSavingAll(true);
    setSaveProgress({ done: 0, total: queue.length, failed: 0 });
    let done = 0;
    let failed = 0;
    for (const f of queue) {
      const got = await cacheDocFile({
        fileId: f.id || f._id,
        cacheVersion: f.cache_version ?? 0,
        remoteUrl: f.r2_url || f.directUrl,
        // The length the listing already gave us, so a transfer cut short on
        // site wifi is rejected instead of saved as a plan that opens blank.
        expectedSize: f?.size,
      });
      if (got) done += 1; else failed += 1;
      setSaveProgress({ done, total: queue.length, failed });
      // Re-read as it goes, so the per-row marks fill in while he watches
      // rather than all at the end.
      await refreshCachedNames();
    }
    setSavingAll(false);

    if (failed === 0) {
      toast.success('Saved', `${done} plan${done === 1 ? '' : 's'} saved on this device.`);
    } else {
      toast.error(
        'Some plans did not save',
        `${done} saved, ${failed} failed. Tap Save for offline again to retry just those.`,
      );
    }
  };

  const adoptFiles = (list, { mayCache = true } = {}) => {
    const arr = Array.isArray(list) ? list : [];
    setFiles(arr);
    setFetchState('ok');
    if (mayCache) {
      cacheDocList(scopeKey, arr);
      // HOUSEKEEPING, ONLY BEHIND A LIST WE JUST TRUSTED ENOUGH TO STORE.
      // Removes superseded versions ({id}.1.pdf once {id}.2.pdf lands) and
      // files no project's list mentions any more. Keyed on the union of ALL
      // cached lists, because the cache directory is flat and shared -- see
      // sweepDocCache. Fire-and-forget: a failed sweep must not disturb the
      // screen, and it resolves every ambiguity toward keeping.
      sweepDocCache().then(refreshCachedNames).catch(() => {});
    }
    // Fire-and-forget byte warm — the plans land on disk while there is signal.
    // Then re-read the disk so the strip reflects what the warm achieved rather
    // than what it attempted.
    warmDocCache(arr.filter((f) => isPdf(f?.name)), { limit: 15 })
      .then(refreshCachedNames)
      .catch(() => {});
    refreshCachedNames();
  };

  const fetchData = async () => {
    setLoading(true);

    // Cache-FIRST so the plan list is on screen before the network is tried.
    //
    // AND DROP THE SPINNER HERE. The whole screen body is gated on `loading`,
    // so painting the cached list while `loading` is still true paints it
    // behind a spinner: offline, the CP watched the spinner for the full
    // socket timeout and only then saw plans that had been in hand the entire
    // time. The list is real the moment it is read — say so. Same order as
    // site/logbooks.jsx.
    const cached = await readCachedDocList(scopeKey);
    if (cached.length) {
      setFiles(cached);
      setLoading(false);
    }

    const [projRes, filesRes] = await Promise.all([
      settleFetch(() => projectsAPI.getById(projectId)),
      settleFetch(() => dropboxAPI.getProjectFiles(projectId)),
    ]);

    // The project document carries the sync summary, so whichever copy we end
    // up using is the one that decides whether the list may be cached.
    let effectiveProject = null;
    if (projRes.status === 'ok' && projRes.data) {
      effectiveProject = projRes.data;
      setProject(projRes.data);
      setLastSynced(projRes.data?.dropbox_last_synced);
      cacheProject(projRes.data);
    } else {
      // Prefer the cached project over a blind re-fetch — the header name and
      // `dropbox_folder_path` (which picks the empty state below) come from it.
      const cachedProject = await readCachedProject(projectId);
      if (cachedProject) {
        effectiveProject = cachedProject;
        setProject(cachedProject);
        setLastSynced(cachedProject?.dropbox_last_synced);
      }
    }

    if (filesRes.status === 'ok') {
      adoptFiles(filesRes.data, {
        mayCache: mayCacheList(effectiveProject?.dropbox_sync),
      });
    } else {
      // KEEP the cached list. The old `.catch(() => [])` here is exactly the
      // silent blank this screen is being fixed for.
      console.error('Failed to fetch data:', filesRes.error);
      setFetchState(filesRes.status);
    }

    if (isAdmin && effectiveProject?.dropbox_folder_path) {
      fetchSiteDeviceVisibility();
    }

    setLoading(false);
  };

  const handleSync = async () => {
    setSyncing(true);
    setSyncStatus('syncing');
    try {
      // sync-dropbox returns as soon as the background task is scheduled, and
      // carries the recursive Dropbox count with it. The list read below is
      // therefore a MID-SYNC read: it is what we hold right now, not the result
      // of the sync. Say the target rather than implying the copy is complete.
      const res = await dropboxAPI.syncProject(projectId);
      const filesData = await dropboxAPI.getProjectFiles(projectId);
      // NOT CACHED, AND NO RECORD NEEDS CONSULTING: we started the sync one
      // line ago, so this read is mid-sync by construction. Asking the server
      // would only race its own stamp.
      adoptFiles(filesData, { mayCache: false });
      setLastSynced(new Date().toISOString());
      setSyncStatus('success');
      const target = Number.isFinite(res?.file_count) ? res.file_count : null;
      toast.success(
        'Sync started',
        target === null
          ? 'Files are being copied from Dropbox.'
          : `Copying ${target} file${target === 1 ? '' : 's'} from Dropbox. This list fills in as they arrive.`,
      );
    } catch (error) {
      console.error('Failed to sync:', error);
      setSyncStatus('error');
      toast.error('Sync Error', error.response?.data?.detail || 'Could not sync files');
    } finally {
      setSyncing(false);
      setTimeout(() => setSyncStatus('idle'), 3000);
    }
  };

  // ── Folder picker ──────────────────────────────────────────────────────
  const fetchFolders = async (path = '') => {
    setLoadingFolders(true);
    try {
      const foldersData = await dropboxAPI.getFolders(path);
      setFolders(Array.isArray(foldersData) ? foldersData : []);
      setCurrentPath(path);
    } catch (error) {
      console.error('Failed to fetch folders:', error);
      toast.error('Error', 'Could not load Dropbox folders');
      setFolders([]);
    } finally {
      setLoadingFolders(false);
    }
  };

  const openFolderPicker = () => {
    setShowFolderPicker(true);
    fetchFolders(linkedFolder || '');
  };

  /**
   * THE CLASS, NOT THE ONE CONTROL. '' and '/' both mean "the whole Dropbox"
   * to link_dropbox_to_project, and the sync lists RECURSIVELY -- so a root
   * link copies every file the company owns into one project. The picker has
   * no control at depth 0, and this guard means a new call site cannot
   * reintroduce one by passing a falsy path.
   */
  const handleSelectFolder = async (folderPath) => {
    const target = (folderPath || '').trim();
    if (!target || target === '/') {
      toast.error('Pick a folder', 'A project cannot be linked to all of Dropbox.');
      return;
    }
    setLinking(true);
    try {
      await dropboxAPI.linkToProject(projectId, target);
      setProject((p) => (p ? { ...p, dropbox_folder_path: target } : p));
      setShowFolderPicker(false);
      toast.success('Linked', `This project now reads from ${target}.`);
      handleSync();
      if (isAdmin) fetchSiteDeviceVisibility();
    } catch (error) {
      console.error('Failed to link folder:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not link folder');
    } finally {
      setLinking(false);
    }
  };

  /**
   * UNLINK IS ITS OWN CONTROL, AND IT SENDS null.
   *
   * It used to be the off-position of a Switch labelled "Enable Dropbox",
   * which is not a label for deleting a link. It also has to send null and
   * nothing else: link_dropbox_to_project reads null as "unlink" but reads ''
   * and '/' as "link to the ROOT of the Dropbox scope", so the value that
   * looks most like clearing a field is the one that links the project to the
   * company's entire Dropbox.
   *
   * What it does and does not delete is stated on the dialog, not here, because
   * the person pressing it is the one who needs to know.
   */
  const handleUnlink = async () => {
    setUnlinking(true);
    try {
      await dropboxAPI.linkToProject(projectId, null);
      setProject((p) => (p ? { ...p, dropbox_folder_path: null } : p));
      setSiteDeviceSubfolders([]);
      setSiteDeviceSelected([]);
      setConfirmUnlink(false);
      toast.success('Unlinked', 'This project no longer reads from Dropbox.');
    } catch (error) {
      console.error('Failed to unlink:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not unlink the folder');
    } finally {
      setUnlinking(false);
    }
  };

  // ── Site-device visibility ─────────────────────────────────────────────
  const fetchSiteDeviceVisibility = async () => {
    if (!projectId) return;
    try {
      const data = await dropboxAPI.getSiteDeviceSubfolders(projectId);
      setSiteDeviceSubfolders(Array.isArray(data?.subfolders) ? data.subfolders : []);
      setSiteDeviceSelected(Array.isArray(data?.selected) ? data.selected : []);
    } catch (e) {
      // Admin-only endpoint; a non-admin gets 403 and simply sees no card.
      console.warn('Site device visibility load failed:', e?.message);
      setSiteDeviceSubfolders([]);
      setSiteDeviceSelected([]);
    }
  };

  const toggleSiteSubfolder = (name) => {
    if (!isAdmin) return;
    setSiteDeviceSelected((prev) => {
      const low = (name || '').toLowerCase();
      const has = prev.some((x) => x.toLowerCase() === low);
      return has ? prev.filter((x) => x.toLowerCase() !== low) : [...prev, name];
    });
  };

  const handleSaveSiteVisibility = async () => {
    if (!isAdmin) return;
    setSavingSiteVisibility(true);
    try {
      await dropboxAPI.setSiteDeviceSubfolders(projectId, siteDeviceSelected);
      toast.success(
        'Saved',
        siteDeviceSelected.length === 0
          ? 'Site devices will see no files from this project.'
          : `Site devices can see ${siteDeviceSelected.length} folder(s).`,
      );
    } catch (e) {
      console.error('Save site visibility failed:', e);
      toast.error('Error', e.response?.data?.detail || 'Could not save');
    } finally {
      setSavingSiteVisibility(false);
    }
  };

  const fetchFiles = async () => {
    const r = await settleFetch(() => dropboxAPI.getProjectFiles(projectId));
    if (r.status === 'ok') {
      adoptFiles(r.data);
    } else {
      // Keep the list that is already on screen; a refresh that fails must not
      // erase the plans the user can still see.
      console.error('Failed to refresh files:', r.error);
      setFetchState(r.status);
    }
  };

  const handleUploadFile = async () => {
    let pickedName = 'file';
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: 'application/pdf',
        copyToCacheDirectory: true,
      });
      if (result.canceled) return;
      const file = result.assets?.[0];
      if (!file) {
        toast.error('Upload Error', 'No file was selected');
        return;
      }
      pickedName = file.name || 'file.pdf';

      setUploading(true);
      toast.info('Uploading', `Uploading ${pickedName}...`);

      // Build FormData. On web, expo-document-picker exposes the native File
      // via `file.file` — prefer that over `fetch(file.uri).blob()` which adds
      // an extra hop (and fails silently if the blob URL was revoked).
      const formData = new FormData();
      if (Platform.OS === 'web') {
        let blob = file.file;  // native File instance if available
        if (!blob) {
          if (!file.uri) {
            throw new Error('Web upload: no file.file or file.uri provided by picker');
          }
          try {
            const resp = await fetch(file.uri);
            if (!resp.ok) throw new Error(`fetch(${file.uri}) returned ${resp.status}`);
            blob = await resp.blob();
          } catch (fetchErr) {
            throw new Error(`Could not read picked file: ${fetchErr.message || fetchErr}`);
          }
        }
        if (!blob || (blob.size === 0)) {
          throw new Error('Picked file is empty (0 bytes)');
        }
        formData.append('file', blob, pickedName);
      } else {
        formData.append('file', {
          uri: file.uri,
          name: pickedName,
          type: 'application/pdf',
        });
      }

      await dropboxAPI.uploadFile(projectId, formData);
      toast.success('Uploaded', `${pickedName} uploaded successfully`);
      fetchFiles(); // refresh the file list
    } catch (error) {
      // Surface the real reason so the user sees more than "Could not upload file".
      console.error('Upload failed:', error);
      const detail =
        error?.response?.data?.detail ||
        error?.response?.statusText ||
        error?.message ||
        (typeof error === 'string' ? error : null) ||
        'Could not upload file';
      toast.error('Upload Error', detail);
    } finally {
      setUploading(false);
    }
  };

  const handleViewFile = async (file) => {
    const ext = extOf(file.name);
    if (ext === 'pdf') {
      // Prefer the copy already on disk. PDFViewer prefers `directUrl`, so
      // pointing that at the cached uri is the whole integration — and iOS'
      // WKWebView renders a local file:// through PDFKit with no network.
      const local = await ensureCachedDocFile({
        fileId: file?.id || file?._id,
        cacheVersion: file?.cache_version ?? 0,
        remoteUrl: file?.r2_url || file?.directUrl,
        expectedSize: file?.size,
      });

      // THE BYTES ON DISK WIN, ON EVERY PLATFORM. This used to read
      // `(Platform.OS === 'ios' || offline)`, and `offline` is
      // `fetchState === 'offline'` — a record of how the LAST list fetch went,
      // not a live network signal. The realistic sequence is: load the screen
      // on the street (fetchState 'ok'), Save for offline, walk down into the
      // cellar, tap a plan. `offline` is still 'ok', so Android skipped the
      // correct bytes sitting on this phone and reached for a remote URL that
      // could not resolve. PDFViewer stages a local pdf.js copy for `file://`
      // sources, so Android renders the cached copy fine; there is no reason
      // to consult the network when the file is already here.
      //
      // AND NOTHING IS GIVEN UP BY PREFERRING IT: Android no longer has a
      // remote viewer at all. PDFViewer renders every document from the
      // pdf.js copy staged on the device, and pulls the bytes to disk itself
      // if this has not — so handing it the cached uri only saves a round
      // trip it would otherwise make.
      if (local) {
        probeMint('cached-local', file);
        setSelectedPdfFile({ ...file, directUrl: local });
        setPdfViewerVisible(true);
        return;
      }

      if (offline) {
        toast.info(
          'Not saved on this device',
          'No saved copy of this plan is on this device yet. Reconnect to load it.',
        );
        return;
      }

      // If file has r2_url, pass it directly instead of calling getFileUrl
      //
      // NOTE FOR THE PROBE READER: the else-branch here passes the ROW OBJECT
      // ITSELF, not a copy. Its identity is then the identity of an element of
      // `files`, which adoptFiles replaces wholesale on every list refresh —
      // so a `file` id change reported by the viewer means something different
      // depending on which of these two branches opened the document. The log
      // says which.
      probeMint(file.r2_url ? 'remote-r2 (fresh object)' : 'remote (ROW OBJECT, not a copy)', file);
      setSelectedPdfFile(file.r2_url ? { ...file, directUrl: file.r2_url } : file);
      setPdfViewerVisible(true);
      return;
    }

    // ⚠️ NON-PDF LIMIT: .docx/.xlsx are handed to another app via a REMOTE url.
    // There is no offline path for them, so don't let the tap just fail.
    if (offline) {
      toast.info(
        'Not available offline',
        `${(ext || 'This file type').toUpperCase()} files open in another app over the network. Reconnect to open ${file.name}.`,
      );
      return;
    }

    try {
      const { url } = await dropboxAPI.getFileUrl(projectId, file.path);
      if (url) {
        await Linking.openURL(url);
      } else {
        toast.error('Error', 'Could not get file URL');
      }
    } catch (error) {
      console.error('Failed to get file URL:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not open file');
    }
  };

  const handleDownloadFile = async (file) => {
    // Downloading hands a REMOTE url to the OS — there is nothing to hand it
    // offline, cached bytes or not. Don't dead-end the tap.
    if (offline) {
      toast.info('Not available offline', 'Downloads need a connection. Reconnect and try again.');
      return;
    }
    try {
      // Direct-upload files carry their download URL on the record itself;
      // only fall back to the Dropbox temp-link endpoint for synced files.
      let url = file.directUrl || file.r2_url || null;
      if (url && url.startsWith('/')) {
        const tok = (typeof window !== 'undefined' && window.localStorage)
          ? window.localStorage.getItem('blueview_token')
          : null;
        const base = process.env.EXPO_PUBLIC_API_URL || 'https://api.levelog.com';
        url = base + url + (url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(tok || '');
      }
      if (!url && file.path) {
        const res = await dropboxAPI.getFileUrl(projectId, file.path);
        url = res?.url;
      }
      if (url) {
        await Linking.openURL(url);
        toast.success('Download', 'File download started');
      } else {
        toast.error('Error', 'No download URL available for this file');
      }
    } catch (error) {
      console.error('Failed to download:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not download file');
    }
  };

  // Opens the themed confirmation modal. Actual delete happens in confirmDeleteFile().
  const handleDeleteFile = (file) => {
    const canDelete = isAdmin;
    if (!canDelete) {
      toast.error('Not allowed', 'Only company owners or admins can delete files.');
      return;
    }
    setFileToDelete(file);
  };

  const confirmDeleteFile = async () => {
    if (!fileToDelete || deleting) return;
    const file = fileToDelete;
    setDeleting(true);
    try {
      await dropboxAPI.deleteFile(projectId, file.id);
      toast.success('Deleted', `${file.name} permanently deleted`);
      setFileToDelete(null);
      fetchFiles();
    } catch (error) {
      console.error('Delete failed:', error);
      toast.error('Delete Error', error.response?.data?.detail || 'Could not delete file');
    } finally {
      setDeleting(false);
    }
  };

  // Filter files
  // Recomputed whenever the list or the disk changes. Cheap: a set membership
  // test per file over a Set built by one directory read.
  const readiness = readinessOf({
    files, cachedNames, nameOf: nameOfFile, sync: project?.dropbox_sync,
  });

  const filteredFiles = files.filter((file) => {
    // Search filter
    if (searchQuery && !file.name?.toLowerCase().includes(searchQuery.toLowerCase())) {
      return false;
    }

    // Type filter
    if (filterType !== 'all') {
      const ext = file.name?.split('.').pop()?.toLowerCase();
      if (filterType === 'pdf' && ext !== 'pdf') return false;
      if (filterType === 'image' && !['png', 'jpg', 'jpeg', 'gif'].includes(ext)) return false;
      if (filterType === 'document' && !['doc', 'docx', 'xls', 'xlsx'].includes(ext)) return false;
    }

    return true;
  });

  // BOTH NUMBERS FROM THIS LIST. `POST /sync-dropbox` also returns a
  // file_count, taken from a recursive Dropbox listing while the copy into
  // project_files is still running -- correct about Dropbox, wrong about the
  // tree below. Borrowing it for half the sentence would make "412 files in 9
  // folders" true of neither. It climbs as rows arrive, which is what it means.
  const fileGroups = groupByFolder(filteredFiles);
  const collisions = collidingNames(files);
  const headline = treeHeadline(filteredFiles, lastSynced);

  const filterOptions = [
    { key: 'all', label: 'All Files' },
    { key: 'pdf', label: 'PDFs' },
    { key: 'image', label: 'Images' },
    { key: 'document', label: 'Documents' },
  ];

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* Header */}
        <View style={s.header}>
          <View style={s.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.back()}
            />
            <HeaderBrand />
          </View>
        </View>

        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {/* Title */}
          <View style={s.titleSection}>
            <Text style={s.titleLabel}>{project?.name || 'PROJECT'}</Text>
            <Text style={s.titleText}>Files</Text>
          </View>

          {loading ? (
            <View style={s.loadingContainer}>
              <GlassSkeleton width="100%" height={60} style={s.mb12} />
              <GlassSkeleton width="100%" height={80} style={s.mb12} />
              <GlassSkeleton width="100%" height={80} style={s.mb12} />
              <GlassSkeleton width="100%" height={80} />
            </View>
          ) : (
            <>
              {/* Action bar */}
              {isAdmin && (
                <View style={{ flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.md }}>
                  <Pressable
                    onPress={handleUploadFile}
                    disabled={uploading}
                    style={({ pressed }) => [
                      { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8,
                        paddingVertical: 14, borderRadius: 12, backgroundColor: 'rgba(59,130,246,0.15)',
                        borderWidth: 1, borderColor: 'rgba(59,130,246,0.3)' },
                      pressed && { opacity: 0.7 },
                      uploading && { opacity: 0.5 },
                    ]}
                  >
                    <Upload size={18} strokeWidth={1.5} color="#3b82f6" />
                    <Text style={{ color: '#3b82f6', fontSize: 14, fontWeight: '600' }}>
                      {uploading ? 'Uploading...' : 'Upload PDF'}
                    </Text>
                  </Pressable>
                  {project?.dropbox_folder_path ? (
                    <Pressable
                      onPress={handleSync}
                      disabled={syncing}
                      style={({ pressed }) => [
                        { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8,
                          paddingVertical: 14, borderRadius: 12, backgroundColor: withAlpha('#ffffff', 0.05),
                          borderWidth: 1, borderColor: withAlpha('#ffffff', 0.1) },
                        pressed && { opacity: 0.7 },
                        syncing && { opacity: 0.5 },
                      ]}
                    >
                      <RefreshCw size={18} strokeWidth={1.5} color={colors.text.secondary} />
                      <Text style={{ color: colors.text.secondary, fontSize: 14, fontWeight: '600' }}>
                        {syncing ? 'Syncing...' : 'Sync Dropbox'}
                      </Text>
                    </Pressable>
                  ) : (
                    <Pressable
                      onPress={openFolderPicker}
                      style={({ pressed }) => [
                        { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8,
                          paddingVertical: 14, borderRadius: 12, backgroundColor: withAlpha('#ffffff', 0.05),
                          borderWidth: 1, borderColor: withAlpha('#ffffff', 0.1) },
                        pressed && { opacity: 0.7 },
                      ]}
                    >
                      <Folder size={18} strokeWidth={1.5} color={colors.text.muted} />
                      <Text style={{ color: colors.text.muted, fontSize: 14, fontWeight: '600' }}>
                        Link Dropbox Folder
                      </Text>
                    </Pressable>
                  )}
                </View>
              )}

              {/* ── LINKED FOLDER ────────────────────────────────────────
                  One row, one field. Linked-ness is bool(dropbox_folder_path),
                  so there is nothing here to fall out of step with the server. */}
              <GlassCard style={s.linkCard}>
                <Text style={s.cardLabel}>DROPBOX FOLDER</Text>
                {linkedFolder ? (
                  <>
                    <Pressable
                      onPress={isAdmin ? openFolderPicker : undefined}
                      disabled={!isAdmin}
                      style={({ pressed }) => [
                        s.linkedRow, pressed && isAdmin && { opacity: 0.7 },
                      ]}
                    >
                      <FolderOpen size={20} strokeWidth={1.5} color={DROPBOX_BLUE} />
                      <Text style={s.linkedPath} numberOfLines={2}>{linkedFolder}</Text>
                      {isAdmin && (
                        <ChevronRight size={18} strokeWidth={1.5} color={colors.text.muted} />
                      )}
                    </Pressable>
                    {isAdmin && (
                      <Pressable
                        onPress={() => setConfirmUnlink(true)}
                        accessibilityRole="button"
                        style={({ pressed }) => [s.unlinkBtn, pressed && { opacity: 0.7 }]}
                      >
                        <Unlink size={16} strokeWidth={1.5} color={semantic.neutral} />
                        <Text style={s.unlinkText}>Unlink this folder</Text>
                      </Pressable>
                    )}
                  </>
                ) : (
                  <View style={s.notLinkedRow}>
                    <Text style={s.notLinkedInline}>Not linked</Text>
                    {isAdmin && (
                      <GlassButton
                        title="Choose a folder"
                        icon={<Folder size={16} strokeWidth={1.5} color={colors.text.primary} />}
                        onPress={openFolderPicker}
                      />
                    )}
                  </View>
                )}
              </GlassCard>

              {/* Site-device visibility. Lives beside the folder it scopes. */}
              {/* NOT gated on linkedFolder. A project whose files all arrived
                  through the app has no Dropbox folder, and the server now
                  offers those files a folder to be ticked by — gating the card
                  on a Dropbox link left that the one project where nothing
                  could ever be made visible. The card renders whenever the
                  server offers something selectable. */}
              {isAdmin && siteDeviceSubfolders.length > 0 && (
                <GlassCard style={s.linkCard}>
                  <Text style={s.cardLabel}>VISIBLE ON SITE DEVICES</Text>
                  <Text style={s.siteHint}>
                    Kiosks see only the folders ticked here. With none ticked they
                    see no files from this project. Files uploaded in the app are
                    ticked as "Uploaded in App".
                  </Text>
                  {siteDeviceSubfolders.map((name) => {
                    const on = siteDeviceSelected.some(
                      (x) => x.toLowerCase() === name.toLowerCase());
                    return (
                      <Pressable
                        key={name}
                        onPress={() => toggleSiteSubfolder(name)}
                        style={({ pressed }) => [s.siteRow, pressed && { opacity: 0.7 }]}
                      >
                        {on
                          ? <CheckCircle size={18} strokeWidth={1.5} color={semantic.verified} />
                          : <Folder size={18} strokeWidth={1.5} color={colors.text.subtle} />}
                        <Text style={s.siteName}>{name}</Text>
                      </Pressable>
                    );
                  })}
                  <GlassButton
                    title={savingSiteVisibility ? 'Saving…' : 'Save visibility'}
                    onPress={handleSaveSiteVisibility}
                    loading={savingSiteVisibility}
                  />
                </GlassCard>
              )}

              {/* A failed load is not an empty project. Disclose which it was,
                  above the list (or the absence of one) it describes. */}
              {fetchState !== 'ok' && (
                <OfflineNotice
                  mode={fetchState}
                  cachedCount={files.length}
                  style={s.mb12}
                />
              )}

              {/* File list or empty state — the "No Files" cards render ONLY
                  when the server actually answered with none. */}
              {fetchState !== 'ok' ? null : files.length === 0 && !project?.dropbox_folder_path ? (
                <GlassCard style={s.notLinkedCard}>
                  <Cloud size={48} strokeWidth={1} color={colors.text.muted} />
                  <Text style={s.notLinkedTitle}>No Files Yet</Text>
                  <Text style={s.notLinkedDesc}>
                    Upload PDFs directly or choose a Dropbox folder to sync files for this project.
                  </Text>
                </GlassCard>
              ) : files.length === 0 ? (
                <GlassCard style={s.notLinkedCard}>
                  <Cloud size={48} strokeWidth={1} color={colors.text.muted} />
                  <Text style={s.notLinkedTitle}>No Files Found</Text>
                  <Text style={s.notLinkedDesc}>
                    Tap sync to pull files from Dropbox, or upload a PDF directly.
                  </Text>
                </GlassCard>
              ) : null}

              {/* Search and Filter */}
              <View style={s.searchRow}>
                <View style={s.searchContainer}>
                  <GlassInput
                    value={searchQuery}
                    onChangeText={setSearchQuery}
                    placeholder="Search files..."
                    leftIcon={<Search size={18} strokeWidth={1.5} color={colors.text.subtle} />}
                  />
                </View>
              </View>

              {/* Filter Tabs */}
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                style={s.filterScroll}
                contentContainerStyle={s.filterContainer}
              >
                {filterOptions.map((option) => (
                  <Pressable
                    key={option.key}
                    onPress={() => setFilterType(option.key)}
                    style={[
                      s.filterTab,
                      filterType === option.key && s.filterTabActive,
                    ]}
                  >
                    <Text
                      style={[
                        s.filterTabText,
                        filterType === option.key && s.filterTabTextActive,
                      ]}
                    >
                      {option.label}
                    </Text>
                  </Pressable>
                ))}
              </ScrollView>

              {/* ── OFFLINE READINESS ────────────────────────────────────
                  The sentence the CP acts on before he goes underground.
                  Computed from the DISK on every render, never from a stored
                  flag: a flag goes stale the moment a drawing changes in
                  Dropbox and bumps its cache_version, and it would then promise
                  something untrue at the exact moment it matters. */}
              {readiness.state === READY_UNCHECKED ? (
                <View style={s.readyStrip}>
                  <Text style={s.readyTextMuted}>
                    {readiness.neverSynced
                      ? 'Not checked yet — sync this project to see which plans are saved on this device.'
                      : 'Not checked yet — the last sync did not finish, so what is saved here cannot be confirmed.'}
                  </Text>
                </View>
              ) : readiness.state === READY_ALL ? (
                <View style={s.readyStrip}>
                  <Check size={16} strokeWidth={2} color={semantic.verified} />
                  <Text style={s.readyTextOk}>
                    All {readiness.savable} plan{readiness.savable === 1 ? '' : 's'} saved on this device
                  </Text>
                </View>
              ) : (
                <View style={s.readyStrip}>
                  <View style={{ flex: 1 }}>
                    <Text style={s.readyText}>
                      {readiness.state === READY_NONE
                        ? `No plans saved on this device · ${megabytes(readiness.bytesRemaining)} MB`
                        : `${readiness.saved} of ${readiness.savable} saved · ${megabytes(readiness.bytesRemaining)} MB to go`}
                    </Text>
                  </View>
                  <Pressable
                    onPress={handleSaveAll}
                    disabled={savingAll || offline}
                    accessibilityRole="button"
                    style={({ pressed }) => [
                      s.saveAllBtn,
                      pressed && { opacity: 0.7 },
                      (savingAll || offline) && { opacity: 0.5 },
                    ]}
                  >
                    <Text style={s.saveAllText}>
                      {savingAll
                        ? `Saving ${saveProgress.done} of ${saveProgress.total}...`
                        : 'Save for offline'}
                    </Text>
                  </Pressable>
                </View>
              )}

              {/* OUT OF THE DENOMINATOR, WITH THE REASON. These files failed
                  their R2 upload during the sync, so there are no bytes to
                  fetch and retrying cannot help. Counting them would mean the
                  CP can never reach a clean state, and a number that can never
                  be satisfied is one he learns to ignore. */}
              {readiness.unsavable > 0 && (
                <Text style={s.readyUnsavable}>
                  {readiness.unsavable} plan{readiness.unsavable === 1 ? '' : 's'} cannot be saved —
                  {readiness.unsavable === 1 ? ' it did' : ' they did'} not finish syncing from Dropbox.
                  Sync again to try to repair {readiness.unsavable === 1 ? 'it' : 'them'}.
                </Text>
              )}

              {/* NEVER A BARE COUNT UNDER AN AMBIGUOUS LABEL. The sentence
                  names both quantities and says what the timestamp refers to;
                  both numbers are derived from the list rendered below it. */}
              <Text style={s.filesCount}>{headline}</Text>

              {/* Files List */}
              <View style={s.filesList}>
                {filteredFiles.length > 0 ? (
                  fileGroups.map(([folderPath, groupFiles]) => (
                  <View key={folderPath} style={s.folderGroup}>
                    <View style={s.folderGroupHeader}>
                      <Folder size={14} strokeWidth={1.5} color={DROPBOX_BLUE} />
                      <Text style={s.folderGroupName} numberOfLines={1}>
                        {folderLabel(folderPath)}
                      </Text>
                      <Text style={s.folderGroupCount}>
                        {groupFiles.length} file{groupFiles.length === 1 ? '' : 's'}
                      </Text>
                    </View>
                    {folderPath !== UNFILED && folderLabel(folderPath) !== folderPath && (
                      <Text style={s.folderGroupPath} numberOfLines={1}>{folderPath}</Text>
                    )}
                  {groupFiles.map((file, index) => {
                    const typeInfo = getFileTypeInfo(file.name || '');
                    const FileIcon = typeInfo.icon;

                    return (
                      <Pressable
                        key={file.path || index}
                        style={({ pressed }) => [
                          s.fileItem,
                          pressed && s.fileItemPressed,
                        ]}
                        onPress={() => handleViewFile(file)}
                      >
                        {/* File Icon */}
                        <View
                          style={[
                            s.fileIconContainer,
                            { backgroundColor: `${typeInfo.color}15` },
                          ]}
                        >
                          <FileIcon size={22} strokeWidth={1.5} color={typeInfo.color} />
                          <Text style={[s.fileTypeLabel, { color: typeInfo.color }]}>
                            {typeInfo.label}
                          </Text>
                        </View>

                        {/* File Info */}
                        <View style={s.fileInfo}>
                          <Text style={s.fileName} numberOfLines={1}>
                            {file.name}
                          </Text>
                          <View style={s.fileMeta}>
                            <Text style={s.fileMetaText}>
                              {formatFileSize(file.size)}
                            </Text>
                            {file.modified && (
                              <>
                                <Text style={s.fileMetaDot}>•</Text>
                                <Text style={s.fileMetaText}>
                                  {new Date(file.modified).toLocaleDateString()}
                                </Text>
                              </>
                            )}
                          </View>
                          {/* THE TREE MUST NOT CLAIM THESE ARE TWO FILES.
                              The sync writes R2 under
                              {'{'}company{'}'}/{'{'}project{'}'}/{'{'}filename{'}'} from a
                              RECURSIVE listing, so the folder is not in the
                              key: two rows in two folders sharing a filename
                              are one object, and both open whichever copied
                              last. A flat list hid it; a tree renders them side
                              by side, which is a stronger claim than the data
                              supports. The key is the backend's to fix. */}
                          {isColliding(file, collisions) && (
                            <Text style={s.collisionNote}>{COLLISION_NOTE}</Text>
                          )}
                        </View>

                        {/* Actions */}
                        <View style={s.fileActions}>
                          <Pressable
                            onPress={(e) => {
                              e.stopPropagation();
                              handleViewFile(file);
                            }}
                            style={s.fileActionBtn}
                          >
                            <Eye size={18} strokeWidth={1.5} color={colors.text.muted} />
                          </Pressable>
                          <Pressable
                            onPress={(e) => {
                              e.stopPropagation();
                              handleDownloadFile(file);
                            }}
                            style={s.fileActionBtn}
                          >
                            <Download size={18} strokeWidth={1.5} color={colors.text.muted} />
                          </Pressable>
                          {isAdmin && (
                            <Pressable
                              onPress={(e) => {
                                e.stopPropagation();
                                handleDeleteFile(file);
                              }}
                              style={s.fileActionBtn}
                            >
                              <Trash2 size={18} strokeWidth={1.5} color={semantic.neutral} />
                            </Pressable>
                          )}
                        </View>
                      </Pressable>
                    );
                  })}
                  </View>
                  ))
                ) : (searchQuery || filterType !== 'all' || fetchState === 'ok') ? (
                  <View style={s.emptyFiles}>
                    <FolderOpen size={48} strokeWidth={1} color={colors.text.subtle} />
                    <Text style={s.emptyText}>
                      {searchQuery || filterType !== 'all'
                        ? 'No files match your search'
                        : 'No files in this folder'}
                    </Text>
                    {/* Syncing needs the network — don't offer it when the last
                        load already told us there isn't any. */}
                    {fetchState === 'ok' && (
                      <GlassButton
                        title="Sync from Dropbox"
                        icon={<RefreshCw size={16} strokeWidth={1.5} color={colors.text.primary} />}
                        onPress={handleSync}
                        loading={syncing}
                      />
                    )}
                  </View>
                ) : null}
              </View>
            </>
          )}
        </ScrollView>

        <PDFViewer
          visible={pdfViewerVisible}
          file={selectedPdfFile}
          projectId={projectId}
          onClose={() => { setPdfViewerVisible(false); setSelectedPdfFile(null); }}
        />

        {/* ── FOLDER PICKER ─────────────────────────────────────────────
            PICKER ONLY, NO TYPED PATH. Nobody types a Dropbox path, and the
            one who tries types it wrong -- the old free-text field on
            project/[id].jsx accepted anything and reported the server's
            rejection as the user's fault. */}
        <Modal
          visible={showFolderPicker}
          transparent
          animationType="fade"
          onRequestClose={() => setShowFolderPicker(false)}
        >
          <View style={s.modalOverlay}>
            <Pressable style={s.modalBackdrop} onPress={() => setShowFolderPicker(false)} />
            <GlassCard style={s.pickerCard}>
              <View style={s.pickerHeader}>
                <Text style={s.pickerTitle}>Choose a Dropbox folder</Text>
                <Pressable onPress={() => setShowFolderPicker(false)} accessibilityRole="button">
                  <X size={20} strokeWidth={1.5} color={colors.text.muted} />
                </Pressable>
              </View>

              <View style={s.currentPathRow}>
                {!!currentPath && (
                  <Pressable
                    onPress={() => fetchFolders(currentPath.split('/').slice(0, -1).join('/'))}
                    style={s.backBtn}
                  >
                    <ChevronLeft size={18} strokeWidth={1.5} color={colors.text.muted} />
                    <Text style={s.backText}>Back</Text>
                  </Pressable>
                )}
                <Text style={s.currentPathText} numberOfLines={1}>
                  {currentPath || '/ (Root)'}
                </Text>
              </View>

              {/* ROOT IS NOT A PROJECT FOLDER, and the reason is on screen.
                  At depth 0 currentPath is '', which the server reads as "link
                  to the root of the Dropbox scope". The sync lists RECURSIVELY,
                  so a root link copies every file the company owns into this
                  one project. There is no control here to press -- the branch
                  states why instead of rendering a disabled button with no
                  explanation. */}
              {currentPath ? (
                <Pressable
                  onPress={() => handleSelectFolder(currentPath)}
                  disabled={linking}
                  style={({ pressed }) => [
                    s.selectCurrentBtn,
                    pressed && { opacity: 0.7 },
                    linking && { opacity: 0.5 },
                  ]}
                >
                  <CheckCircle size={18} strokeWidth={1.5} color={semantic.verified} />
                  <Text style={s.selectCurrentText}>
                    {linking ? 'Linking…' : 'Link this folder'}
                  </Text>
                </Pressable>
              ) : (
                <View style={s.selectRootBlocked}>
                  <Text style={s.selectRootBlockedText}>
                    Open a folder to link it. A project cannot be linked to all of
                    Dropbox — every file your company stores would be copied into
                    this project.
                  </Text>
                </View>
              )}

              <ScrollView style={s.pickerList}>
                {loadingFolders ? (
                  <ActivityIndicator size="small" color={colors.text.primary} style={s.mb12} />
                ) : folders.length > 0 ? (
                  folders.map((folder, index) => (
                    <Pressable
                      key={folder.path || index}
                      onPress={() => fetchFolders(folder.path)}
                      style={({ pressed }) => [s.folderItem, pressed && { opacity: 0.7 }]}
                    >
                      <Folder size={18} strokeWidth={1.5} color={DROPBOX_BLUE} />
                      <Text style={s.folderName} numberOfLines={1}>{folder.name}</Text>
                      <ChevronRight size={16} strokeWidth={1.5} color={colors.text.subtle} />
                    </Pressable>
                  ))
                ) : (
                  <Text style={s.noFolders}>No subfolders here</Text>
                )}
              </ScrollView>
            </GlassCard>
          </View>
        </Modal>

        {/* SAYS WHAT IT DOES AND WHAT IT DOES NOT DELETE. Unlinking clears one
            field; it does not touch Dropbox, and it does not remove the files
            already copied into this project. Someone who believes it deletes
            their drawings will not press it, and someone who believes it
            cleans up will be surprised later. */}
        <ConfirmDialog
          visible={confirmUnlink}
          title="Unlink this Dropbox folder?"
          message={
            linkedFolder
              ? `This project will stop reading from ${linkedFolder}.`
              : 'This project will stop reading from Dropbox.'
          }
          details={[
            'Nothing in your Dropbox is changed or deleted',
            'Files already synced into this project stay, and stay openable',
            'New or changed files in Dropbox will no longer arrive here',
            'You can link the same folder again at any time',
          ]}
          confirmLabel={unlinking ? 'Unlinking…' : 'Unlink folder'}
          cancelLabel="Keep it linked"
          destructive
          onConfirm={handleUnlink}
          onCancel={() => { if (!unlinking) setConfirmUnlink(false); }}
        />

        <ConfirmDialog
          visible={!!fileToDelete}
          title="Delete this file?"
          message={fileToDelete ? `You are about to permanently delete "${fileToDelete.name}".` : ''}
          details={[
            'Removes the file from Cloudflare R2 storage',
            'Removes the database record and any annotations',
            'This action cannot be undone',
          ]}
          confirmLabel={deleting ? 'Deleting…' : 'Delete permanently'}
          cancelLabel="Cancel"
          destructive
          onConfirm={confirmDeleteFile}
          onCancel={() => { if (!deleting) setFileToDelete(null); }}
        />
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
  container: {
    flex: 1,
  },
  linkCard: {
    marginBottom: spacing.md,
    padding: spacing.lg,
  },
  cardLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.md,
  },
  linkedRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  linkedPath: {
    flex: 1,
    fontSize: 15,
    color: colors.text.primary,
  },
  unlinkBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginTop: spacing.md,
    paddingVertical: spacing.sm,
  },
  unlinkText: {
    fontSize: 14,
    fontWeight: '600',
    color: semantic.neutral,
  },
  notLinkedRow: {
    gap: spacing.md,
  },
  notLinkedInline: {
    fontSize: 15,
    color: colors.text.muted,
  },
  siteHint: {
    fontSize: 13,
    lineHeight: 18,
    color: colors.text.muted,
    marginBottom: spacing.md,
  },
  siteRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    paddingVertical: spacing.sm,
  },
  siteName: {
    flex: 1,
    fontSize: 14,
    color: colors.text.primary,
  },
  folderGroup: {
    marginBottom: spacing.lg,
  },
  folderGroupHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.sm,
  },
  folderGroupName: {
    flex: 1,
    ...typography.label,
    color: colors.text.secondary,
  },
  folderGroupCount: {
    fontSize: 12,
    color: colors.text.subtle,
  },
  folderGroupPath: {
    fontSize: 11,
    color: colors.text.subtle,
    marginBottom: spacing.sm,
  },
  collisionNote: {
    fontSize: 12,
    lineHeight: 16,
    color: semantic.neutral,
    marginTop: 4,
  },
  modalOverlay: {
    flex: 1,
    justifyContent: 'center',
    padding: spacing.lg,
  },
  modalBackdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0,0,0,0.6)',
  },
  pickerCard: {
    padding: spacing.lg,
    maxHeight: '80%',
  },
  pickerHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.md,
  },
  pickerTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.text.primary,
  },
  currentPathRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginBottom: spacing.md,
  },
  backBtn: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  backText: {
    fontSize: 14,
    color: colors.text.muted,
  },
  currentPathText: {
    flex: 1,
    fontSize: 13,
    color: colors.text.muted,
  },
  selectCurrentBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    paddingVertical: 12,
    borderRadius: borderRadius.md,
    backgroundColor: withAlpha('#ffffff', 0.06),
    borderWidth: 1,
    borderColor: withAlpha('#ffffff', 0.12),
    marginBottom: spacing.md,
  },
  selectCurrentText: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text.primary,
  },
  selectRootBlocked: {
    padding: spacing.md,
    borderRadius: borderRadius.md,
    backgroundColor: withAlpha('#ffffff', 0.04),
    marginBottom: spacing.md,
  },
  selectRootBlockedText: {
    fontSize: 13,
    lineHeight: 18,
    color: colors.text.muted,
  },
  pickerList: {
    maxHeight: 320,
  },
  folderItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    paddingVertical: 12,
  },
  folderName: {
    flex: 1,
    fontSize: 15,
    color: colors.text.primary,
  },
  noFolders: {
    fontSize: 14,
    color: colors.text.subtle,
    paddingVertical: spacing.md,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: withAlpha('#ffffff', 0.08),
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  logoText: {
    ...typography.label,
    color: colors.text.muted,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: spacing.lg,
    paddingBottom: 120,
  },
  titleSection: {
    marginBottom: spacing.lg,
  },
  titleLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.sm,
  },
  titleText: {
    fontSize: 36,
    fontWeight: '200',
    color: colors.text.primary,
    letterSpacing: -0.5,
  },
  loadingContainer: {
    paddingVertical: spacing.md,
  },
  mb12: {
    marginBottom: spacing.sm,
  },
  notLinkedCard: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
    gap: spacing.md,
    // Gap before the search bar below so the empty-state card isn't cramped.
    marginBottom: spacing.lg,
  },
  notLinkedTitle: {
    fontSize: 20,
    fontWeight: '500',
    color: colors.text.primary,
  },
  notLinkedDesc: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
    maxWidth: 280,
  },
  configureBtn: {
    marginTop: spacing.md,
  },
  syncBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  syncInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  syncIndicator: {
    width: 36,
    height: 36,
    borderRadius: borderRadius.full,
    backgroundColor: 'rgba(0, 97, 255, 0.1)', /* brand: Dropbox - intentional, not a token */
    alignItems: 'center',
    justifyContent: 'center',
  },
  syncIndicatorSyncing: {
    backgroundColor: 'rgba(0, 97, 255, 0.2)', /* brand: Dropbox - intentional, not a token */
  },
  syncIndicatorSuccess: {
    backgroundColor: semantic.verifiedBg,
  },
  syncIndicatorError: {
    backgroundColor: semantic.criticalBg,
  },
  syncLabel: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
  },
  syncTime: {
    fontSize: 12,
    color: colors.text.muted,
  },
  searchRow: {
    marginBottom: spacing.md,
  },
  searchContainer: {
    flex: 1,
  },
  filterScroll: {
    marginBottom: spacing.md,
  },
  filterContainer: {
    gap: spacing.sm,
    paddingRight: spacing.lg,
  },
  filterTab: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  filterTabActive: {
    backgroundColor: withAlpha('#ffffff', 0.15),
    borderColor: withAlpha('#ffffff', 0.3),
  },
  filterTabText: {
    fontSize: 13,
    fontWeight: '500',
    color: colors.text.muted,
  },
  filterTabTextActive: {
    color: colors.text.primary,
  },
  filesCount: {
    fontSize: 13,
    color: colors.text.muted,
    marginBottom: spacing.md,
  },

  // ── Offline readiness strip ────────────────────────────────────────────
  // Sits directly above the list it describes. Full touch target on the
  // action: this is a gloved thumb, outdoors, deciding whether to go down.
  readyStrip: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
    paddingVertical: spacing.sm, paddingHorizontal: spacing.md,
    marginBottom: spacing.sm, borderRadius: 12,
    backgroundColor: withAlpha('#ffffff', 0.05),
    borderWidth: 1, borderColor: withAlpha('#ffffff', 0.1),
    minHeight: 56,
  },
  readyText: { flex: 1, fontSize: 13, fontWeight: '600', color: colors.text.secondary },
  readyTextOk: { flex: 1, fontSize: 13, fontWeight: '600', color: semantic.verified },
  readyTextMuted: { flex: 1, fontSize: 13, color: colors.text.muted, lineHeight: 18 },
  saveAllBtn: {
    minHeight: 44, justifyContent: 'center',
    paddingHorizontal: spacing.md, borderRadius: 999,
    borderWidth: 1, borderColor: 'rgba(59,130,246,0.3)',
    backgroundColor: 'rgba(59,130,246,0.15)',
  },
  saveAllText: { fontSize: 13, fontWeight: '700', color: '#3b82f6' },
  readyUnsavable: {
    fontSize: 12, color: colors.text.muted, lineHeight: 17,
    marginBottom: spacing.sm,
  },
  filesList: {
    gap: spacing.sm,
  },
  fileItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.md,
    transition: 'all 0.2s ease',
  },
  fileItemPressed: {
    backgroundColor: withAlpha('#ffffff', 0.12),
  },
  fileIconContainer: {
    width: 56,
    height: 56,
    borderRadius: borderRadius.lg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  fileTypeLabel: {
    fontSize: 9,
    fontWeight: '700',
    marginTop: 2,
  },
  fileInfo: {
    flex: 1,
  },
  fileName: {
    fontSize: 15,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: 4,
  },
  fileMeta: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  fileMetaText: {
    fontSize: 12,
    color: colors.text.muted,
  },
  fileMetaDot: {
    marginHorizontal: spacing.xs,
    color: colors.text.subtle,
  },
  fileActions: {
    flexDirection: 'row',
    gap: spacing.xs,
  },
  fileActionBtn: {
    width: 36,
    height: 36,
    borderRadius: borderRadius.md,
    backgroundColor: colors.glass.background,
    alignItems: 'center',
    justifyContent: 'center',
  },
  emptyFiles: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
    gap: spacing.md,
  },
  emptyText: {
    fontSize: 15,
    color: colors.text.muted,
    textAlign: 'center',
  },
});
}
