import React, { useState, useEffect, useMemo } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  TextInput,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  Home,
  Building2,
  FileText,
  File,
  FolderOpen,
  Folder,
  Search,
  X,
  ChevronRight,
  LogOut,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import { GlassSkeleton } from '../../src/components/GlassSkeleton';
import OfflineNotice from '../../src/components/OfflineNotice';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import apiClient from '../../src/utils/api';
import { settleFetch } from '../../src/utils/offlineState';
import {
  cacheDocList,
  readCachedDocList,
  ensureCachedDocFile,
  warmDocCache,
} from '../../src/utils/docCache';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { semantic, withAlpha } from '../../src/styles/semanticColors';
import { useTheme } from '../../src/context/ThemeContext';
import { useIsWide } from '../../src/hooks/useIsDesktop';

import PDFViewer from '../../src/components/PDFViewer';

const dropboxAPI = {
  getProjectFiles: async (projectId) => {
    const response = await apiClient.get(`/api/projects/${projectId}/dropbox-files`);
    return response.data;
  },
};

const extOf = (filename) => String(filename || '').split('.').pop()?.toLowerCase() || '';
const isViewable = (filename) => extOf(filename) === 'pdf';

const getFileIcon = (filename) => {
  const ext = extOf(filename);
  if (['pdf'].includes(ext)) return { Icon: FileText, color: semantic.neutral };
  if (['doc', 'docx'].includes(ext)) return { Icon: FileText, color: '#3b82f6' };
  if (['xls', 'xlsx'].includes(ext)) return { Icon: FileText, color: semantic.neutral };
  return { Icon: File, color: '#94a3b8' };
};

const formatFileSize = (bytes) => {
  if (!bytes) return 'Unknown';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

/**
 * The folder a file lives in, from the Dropbox path the API already returns.
 *
 * The endpoint sends the full path ("/Approved Plans/DOB-Approved-Plans.pdf")
 * and this screen was rendering the basename ONLY — so an inspector asking for
 * "the access agreement" got an undifferentiated flat list and had to read
 * filenames. The folder names are the categories the GC already maintains
 * (Approved Plans, Access Agreements, Permits); grouping by them is free
 * structure we were throwing away.
 */
const UNFILED = 'Other Documents';
const folderOf = (file) => {
  const raw = String(file?.path || '');
  const parts = raw.split('/').filter(Boolean);
  parts.pop();                       // drop the filename
  if (!parts.length) return UNFILED;
  return parts[parts.length - 1];    // immediate parent folder
};

export default function SiteDocumentsScreen() {
  const { colors, isDark } = useTheme();
  const isWide = useIsWide();
  const s = useMemo(() => buildStyles(colors, isDark), [colors, isDark]);
  const router = useRouter();
  const { user, isAuthenticated, isLoading: authLoading, siteMode, siteProject, logout } = useAuth();

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [files, setFiles] = useState([]);
  const [query, setQuery] = useState('');
  const [pdfViewerVisible, setPdfViewerVisible] = useState(false);
  const [selectedPdfFile, setSelectedPdfFile] = useState(null);
  // 'ok' | 'offline' | 'error' — the discriminator that keeps a dead zone from
  // rendering the same "No Documents" an empty project renders.
  const [fetchState, setFetchState] = useState('ok');
  const offline = fetchState === 'offline';

  // Search matches the FOLDER as well as the filename, so "access" finds the
  // Access Agreements folder even when the files inside are named by address.
  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matched = q
      ? files.filter((f) => `${f.name || ''} ${folderOf(f)}`.toLowerCase().includes(q))
      : files;

    const byFolder = new Map();
    for (const f of matched) {
      const key = folderOf(f);
      if (!byFolder.has(key)) byFolder.set(key, []);
      byFolder.get(key).push(f);
    }
    // Folders alphabetical, unfiled last; files alphabetical within a folder.
    return [...byFolder.entries()]
      .sort(([a], [b]) => {
        if (a === UNFILED) return 1;
        if (b === UNFILED) return -1;
        return a.localeCompare(b);
      })
      .map(([folder, items]) => [
        folder,
        [...items].sort((x, y) => String(x.name || '').localeCompare(String(y.name || ''))),
      ]);
  }, [files, query]);

  const matchCount = groups.reduce((n, [, items]) => n + items.length, 0);

  useEffect(() => {
  if (!authLoading && isAuthenticated !== undefined) {
    if (!isAuthenticated) {
      router.replace('/login');
    } else if (isAuthenticated && !siteMode && siteProject === null) {
      // Only redirect if we're sure siteMode resolved
      router.replace('/');
    }
  }
}, [isAuthenticated, authLoading, siteMode, siteProject]);
  
  useEffect(() => {
    if (isAuthenticated && siteMode && siteProject?.id) {
      fetchDocuments();
    }
  }, [isAuthenticated, siteMode, siteProject]);

  const fetchDocuments = async () => {
    if (!siteProject?.id) return;
    const scopeKey = `site:${siteProject.id}`;

    setLoading(true);
    // Cache-FIRST: paint the saved list before the network is even attempted, so
    // a super in a cellar sees the real documents instead of a spinner that
    // resolves into a blank screen. The spinner has to come DOWN here too:
    // the body below is gated on `loading`, so a cached paint that leaves
    // `loading` true is painted behind the spinner and the super waits out the
    // whole network timeout to see documents that were already on the tablet.
    const cached = await readCachedDocList(scopeKey);
    if (cached.length) {
      setFiles(cached);
      setLoading(false);
    }

    const r = await settleFetch(() => dropboxAPI.getProjectFiles(siteProject.id));
    if (r.status === 'ok') {
      // The endpoint returns a BARE ARRAY (not {files:[...]}); reading
      // result.files left this [] always. Match the Array.isArray pattern
      // the other file consumers use.
      const list = Array.isArray(r.data) ? r.data : [];
      setFiles(list);
      setFetchState('ok');
      cacheDocList(scopeKey, list);
      // Fire-and-forget: pull the PDF bytes onto the tablet while there is
      // still signal. Never awaited — this must not hold the render path.
      warmDocCache(list.filter((f) => isViewable(f?.name)), { limit: 15 }).catch(() => {});
    } else {
      // NEVER blank the list on a failed load — the cached copy is the point.
      console.error('Failed to fetch documents:', r.error);
      setFetchState(r.status);
    }
    setLoading(false);
  };

  /**
   * Only PDFs can open — the tablet has an in-app PDF viewer and nothing else.
   * This used to `return` silently for every other type, so tapping a .docx
   * did nothing at all and read as a broken screen. Non-viewable files now say
   * so on the card and explain themselves on tap rather than swallowing it.
   *
   * ⚠️ .docx/.xlsx open through a REMOTE url in another app — there is no
   * offline story for them and we don't pretend otherwise.
   */
  const handleOpenFile = async (file) => {
    const label = (extOf(file?.name) || 'This file type').toUpperCase();

    if (!isViewable(file?.name)) {
      toast.info(
        'Can’t open on this device',
        offline
          ? `${label} files open over the network in another app — not available offline.`
          : `${label} files open on a computer. Plans and agreements are PDFs and open here.`,
      );
      return;
    }

    // Prefer the copy already on disk. iOS' WKWebView renders a local file://
    // straight through PDFKit, and PDFViewer already prefers `directUrl` — so
    // pointing that at the cached uri is the whole integration.
    const local = await ensureCachedDocFile({
      fileId: file?.id,
      cacheVersion: file?.cache_version ?? 0,
      remoteUrl: file?.r2_url || file?.directUrl,
      // A gate tablet never reaches sweepDocCache, so a fragment left by the
      // old download path would be served here for ever. The listed length is
      // what refuses it.
      expectedSize: file?.size,
    });

    // THE BYTES ON DISK WIN, ON EVERY PLATFORM. This used to read
    // `(Platform.OS === 'ios' || offline)`, and `offline` is `fetchState ===
    // 'offline'` — how the last list fetch went, not a live network signal. A
    // tablet that loaded this screen with signal and then lost it still reads
    // 'ok', so Android reached past the correct bytes on this tablet for a
    // remote URL that could not resolve. PDFViewer stages a local pdf.js copy
    // for `file://` sources.
    //
    // AND NOTHING IS GIVEN UP BY PREFERRING IT: Android no longer has a
    // remote viewer at all. PDFViewer renders every document from the
    // pdf.js copy staged on the device, and pulls the bytes to disk itself
    // if this has not — so handing it the cached uri only saves a round
    // trip it would otherwise make.
    if (local) {
      setSelectedPdfFile({ ...file, directUrl: local });
      setPdfViewerVisible(true);
      return;
    }

    if (offline) {
      toast.info(
        'Not saved on this tablet',
        'No saved copy of this document is on this tablet yet. Reconnect to load it.',
      );
      return;
    }

    setSelectedPdfFile(file);
    setPdfViewerVisible(true);
  };

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* Header */}
        <View style={s.header}>
          <View style={s.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<Home size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/site')}
            />
            <View style={s.siteBadge}>
              <Building2 size={14} strokeWidth={1.5} color={semantic.neutral} />
              <Text style={s.siteBadgeText}>SITE DEVICE</Text>
            </View>
            <Text style={s.projectName} numberOfLines={1}>
              {siteProject?.name || 'Project'}
            </Text>
          </View>
          <Pressable
            onPress={handleLogout}
            style={s.logoutBtn}
            hitSlop={12}
          >
            <LogOut size={18} strokeWidth={1.5} color="#64748b" />
          </Pressable>
        </View>

        {/* Title + search. An inspector arrives asking for a named document,
            not to browse — search is the primary control, so it sits beside the
            title rather than below the fold. */}
        <View style={[s.titleSection, isWide && s.titleSectionWide]}>
          <View>
            <Text style={s.titleLabel}>PROJECT</Text>
            <Text style={s.titleText}>Documents</Text>
          </View>
          <View style={[s.searchBox, isWide && s.searchBoxWide]}>
            <Search size={20} strokeWidth={1.5} color={colors.text.muted} />
            <TextInput
              style={s.searchInput}
              value={query}
              onChangeText={setQuery}
              placeholder="Search plans, agreements, permits…"
              placeholderTextColor={colors.text.muted}
              autoCorrect={false}
              accessibilityLabel="Search documents"
            />
            {query.length > 0 && (
              <Pressable
                onPress={() => setQuery('')}
                style={s.searchClear}
                hitSlop={12}
                accessibilityRole="button"
                accessibilityLabel="Clear search"
              >
                <X size={18} strokeWidth={2} color={colors.text.muted} />
              </Pressable>
            )}
          </View>
        </View>

        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {/* A failed load is NOT an empty project. Say which one it was. */}
          {!loading && fetchState !== 'ok' && (
            <OfflineNotice
              mode={fetchState}
              cachedCount={files.length}
              style={s.offlineBanner}
            />
          )}

          {loading ? (
            <View style={s.loadingContainer}>
              <GlassSkeleton width="100%" height={80} borderRadiusValue={borderRadius.xl} />
              <GlassSkeleton width="100%" height={80} borderRadiusValue={borderRadius.xl} />
              <GlassSkeleton width="100%" height={80} borderRadiusValue={borderRadius.xl} />
            </View>
          ) : matchCount > 0 ? (
            groups.map(([folder, items]) => (
              <View key={folder} style={s.folderBlock}>
                <View style={s.folderHeader}>
                  <Folder size={18} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={s.folderName}>{folder}</Text>
                  <Text style={s.folderCount}>{items.length}</Text>
                </View>
                {/* Grid, not a stack. Three columns at tablet width turns a
                    2.5-row scroll into a screenful of documents. */}
                <View style={[s.filesGrid, isWide && s.filesGridWide]}>
                  {items.map((file, index) => {
                    const { Icon, color } = getFileIcon(file.name);
                    const viewable = isViewable(file.name);
                    return (
                      <GlassCard
                        key={file.id || `${folder}-${index}`}
                        style={[s.fileCard, isWide && s.fileCardWide]}
                        onPress={() => handleOpenFile(file)}
                      >
                        {/* The row lives INSIDE the card. GlassCard applies the
                            `style` prop to its outer wrapper and renders
                            children into its own column-flex content layer, so
                            a flexDirection on the card never reaches them —
                            which is why these stacked vertically before. */}
                        <View style={s.fileRow}>
                          <View style={s.fileIcon}>
                            <Icon size={26} strokeWidth={1.5} color={color} />
                          </View>
                          <View style={s.fileInfo}>
                            <Text style={s.fileName} numberOfLines={2}>
                              {file.name}
                            </Text>
                            <View style={s.fileMetaRow}>
                              <Text style={s.fileSize}>{formatFileSize(file.size)}</Text>
                              {!viewable && (
                                <Text style={s.fileNotViewable}>
                                  {extOf(file.name).toUpperCase()} · opens on a computer
                                </Text>
                              )}
                            </View>
                          </View>
                          {/* Was a Download glyph with no onPress — decorative
                              chrome that looked like a control. The card opens
                              the file, so the affordance is an open chevron,
                              and only where opening does something. */}
                          {viewable && (
                            <ChevronRight size={22} strokeWidth={1.5} color={colors.text.muted} />
                          )}
                        </View>
                      </GlassCard>
                    );
                  })}
                </View>
              </View>
            ))
          ) : (query || fetchState === 'ok') ? (
            /* "No Documents" ONLY when the server actually answered with none —
               otherwise the banner above is the whole story. */
            <GlassCard style={s.emptyCard}>
              <FolderOpen size={48} strokeWidth={1} color={colors.text.subtle} />
              <Text style={s.emptyText}>
                {query ? 'No matching documents' : 'No Documents'}
              </Text>
              <Text style={s.emptySubtext}>
                {query
                  ? `Nothing matches “${query}”.`
                  : 'Documents will appear here when added'}
              </Text>
            </GlassCard>
          ) : null}
        </ScrollView>

        <PDFViewer
          visible={pdfViewerVisible}
          file={selectedPdfFile}
          projectId={siteProject?.id}
          onClose={() => { setPdfViewerVisible(false); setSelectedPdfFile(null); }}
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
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  headerLeft: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  // 44 minimum — this is operated with work gloves.
  logoutBtn: {
    width: 44,
    height: 44,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: borderRadius.md,
    backgroundColor: withAlpha('#ffffff', 0.05),
  },
  siteBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    backgroundColor: withAlpha('#94a3b8', 0.15),
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: withAlpha('#94a3b8', 0.3),
  },
  siteBadgeText: {
    ...typography.label,
    fontSize: 14,
    color: '#4ade80',
    letterSpacing: 1,
  },
  projectName: {
    fontSize: 18,
    fontWeight: '400',
    color: colors.text.primary,
    flex: 1,
  },
  titleSection: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    gap: spacing.md,
  },
  titleSectionWide: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    justifyContent: 'space-between',
  },
  titleLabel: {
    ...typography.label,
    fontSize: 14,
    color: colors.text.muted,
    marginBottom: spacing.xs,
  },
  titleText: {
    fontSize: 32,
    fontWeight: '200',
    color: colors.text.primary,
  },
  searchBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    minHeight: 52,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.glass.border,
    backgroundColor: colors.glass.background,
  },
  searchBoxWide: { width: 420 },
  searchInput: {
    flex: 1,
    fontSize: 17,
    color: colors.text.primary,
    paddingVertical: spacing.sm,
    outlineStyle: 'none',
  },
  searchClear: {
    width: 44,
    height: 44,
    alignItems: 'center',
    justifyContent: 'center',
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: spacing.lg,
  },
  loadingContainer: {
    gap: spacing.md,
  },
  offlineBanner: { marginBottom: spacing.md },
  folderBlock: { marginBottom: spacing.xl },
  folderHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  folderName: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.text.primary,
  },
  folderCount: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text.muted,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: borderRadius.full,
    backgroundColor: colors.glass.background,
    overflow: 'hidden',
  },
  filesGrid: {
    gap: spacing.md,
  },
  // Three across at tablet width. `gap` handles the gutters, so the basis is
  // just under a third and wrapping does the rest — no width arithmetic that
  // has to be kept in sync with the padding.
  filesGridWide: {
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  fileCard: {
    justifyContent: 'center',
  },
  // 31% basis + a 16pt gap fits three across at 1232pt of content and still
  // wraps cleanly to two on a narrower tablet.
  fileCardWide: {
    flexBasis: '31%',
    flexGrow: 1,
    maxWidth: '32%',
  },
  fileRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  fileIcon: {
    width: 48,
    height: 48,
    borderRadius: borderRadius.lg,
    backgroundColor: colors.glass.background,
    alignItems: 'center',
    justifyContent: 'center',
  },
  fileInfo: {
    flex: 1,
  },
  fileName: {
    fontSize: 17,
    fontWeight: '500',
    color: colors.text.primary,
    lineHeight: 22,
  },
  fileMetaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginTop: spacing.xs,
    flexWrap: 'wrap',
  },
  fileSize: {
    fontSize: 14,
    color: colors.text.muted,
  },
  fileNotViewable: {
    fontSize: 14,
    fontWeight: '600',
    color: semantic.neutral,
  },
  emptyCard: {
    alignItems: 'center',
    paddingVertical: spacing.xxl * 2,
    gap: spacing.md,
  },
  emptyText: {
    fontSize: 20,
    fontWeight: '500',
    color: colors.text.muted,
  },
  emptySubtext: {
    fontSize: 16,
    color: colors.text.muted,
  },
});
}
