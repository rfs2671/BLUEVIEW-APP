import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  Image,
} from 'react-native';
import { useRouter, useFocusEffect } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ClipboardList,
  HardHat,
  ShieldCheck,
  Users,
  BookOpen,
  Building2,
  ChevronRight,
  CheckCircle,
  ChevronDown,
  Calendar,
  Bell,
  ShieldAlert,
  AlertTriangle,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import CpNav from '../../src/components/CpNav';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { useTheme } from '../../src/context/ThemeContext';
import { projectsAPI, logbooksAPI, cpProfileAPI, checkinsAPI, logbookTypesAPI, logbookActivationAPI } from '../../src/utils/api';
import { readCachedProjectList, cacheProjectList } from '../../src/utils/projectCache';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { semantic, withAlpha } from '../../src/styles/semanticColors';
import HeaderBrand from '../../src/components/HeaderBrand';
import BuildMarker from '../../src/components/BuildMarker';

// Icon mapping for dynamic logbook types from API
const ICON_MAP = {
  Building2, Users, HardHat, BookOpen, ShieldCheck, ClipboardList,
};

// Fallback LOG_TYPES for when API hasn't loaded yet
const FALLBACK_LOG_TYPES = [
  // P3: these two are CORE CP logbooks and were never role-gated — the grey was
  // only this hardcoded semantic.neutral, which read as disabled. Give them active
  // accents like the other logbook types so the CP sees them enabled.
  { key: 'daily_jobsite', label: 'Daily Jobsite Log', subtitle: 'NYC DOB 3301-02', icon: 'Building2', color: '#10b981', frequency: 'daily' },
  { key: 'preshift_signin', label: 'Pre-Shift Safety Meeting', subtitle: 'Daily sign-in', icon: 'Users', color: '#f59e0b', frequency: 'daily' },
  { key: 'toolbox_talk', label: 'Tool Box Talk', subtitle: 'OSHA — Weekly', icon: 'BookOpen', color: '#3b82f6', frequency: 'weekly' },
  { key: 'subcontractor_orientation', label: 'Subcontractor Safety Orientation', subtitle: 'First-time workers', icon: 'ShieldCheck', color: '#8b5cf6', frequency: 'as_needed' },
  { key: 'osha_log', label: 'OSHA Log Book', subtitle: 'Worker certifications', icon: 'ClipboardList', color: '#06b6d4', frequency: 'daily' },
  { key: 'scaffold_maintenance', label: 'Scaffold Maintenance Log', subtitle: 'NYC DOB — Daily', icon: 'HardHat', color: semantic.neutral, frequency: 'daily', conditional: 'scaffold_erected' },
];

/**
 * FIX 1 — name the SPECIFIC reasons behind the Check-In Review banner.
 *
 * The banner used to print a fixed "expired SST cards or workers with no trade
 * assigned" whatever the actual mix was, so a CP with one unknown SST card read
 * a sentence about expired cards. Counts come from the flagged endpoint's
 * existing flag_reasons; a check-in can carry more than one, so the parts do
 * not necessarily sum to the check-in count.
 *
 * SOFT surface: it links to the review screen and blocks nothing.
 */
function flaggedReasonSummary({ expired = 0, unknown = 0, needsTrade = 0 } = {}) {
  const parts = [];
  if (expired) parts.push(`${expired} expired SST card${expired > 1 ? 's' : ''}`);
  if (unknown) parts.push(`${unknown} unknown SST card${unknown > 1 ? 's' : ''}`);
  if (needsTrade) {
    parts.push(`${needsTrade} worker${needsTrade > 1 ? 's' : ''} with no trade assigned`);
  }
  // No reasons resolved (older rows, or a shape this build doesn't know) —
  // say that plainly rather than assert a reason that was never reported.
  if (!parts.length) return 'reason not reported';
  if (parts.length === 1) return parts[0];
  return `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`;
}

export default function LogBooksScreen() {
  const router = useRouter();
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
  const { isDark, colors } = useTheme();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [projects, setProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState(null);
  const [showProjectPicker, setShowProjectPicker] = useState(false);
  const [todayLogs, setTodayLogs] = useState({});
  const [notifications, setNotifications] = useState({ missing_toolbox_talk: [], unsigned_orientations: 0, unaffirmed_logbooks: 0, unaffirmed_logbook_refs: [], stale_unsigned_logbooks: 0, stale_unsigned_logbook_refs: [] });
  const [cpName, setCpName] = useState('');
  const [scaffoldActive, setScaffoldActive] = useState(false);
  const [toolboxDoneThisWeek, setToolboxDoneThisWeek] = useState(false);
  const [requiredLogbooks, setRequiredLogbooks] = useState(null); // dynamic from API
  // The server's logbook registry — labels, icons, colours and frequency for
  // all eleven types. FALLBACK_LOG_TYPES covers six and is what shows until
  // this lands; without it the five conditional forms could only ever render
  // under a key-cased placeholder label.
  const [logTypeCatalog, setLogTypeCatalog] = useState(null);
  // Task A: flagged check-in count across the CP's projects, so the Check-In
  // Review banner only shows when there's genuinely something to review (and
  // taps land on the first project that has items).
  // FIX 1: also tallied PER REASON, so the banner names what is actually
  // wrong instead of the generic "expired SST cards or workers with no trade
  // assigned" it used to print whatever the mix was. The reasons come from the
  // flagged endpoint's existing `flag_reasons` array — nothing new is stored.
  const [flagged, setFlagged] = useState({
    count: 0, projectId: null, expired: 0, unknown: 0, needsTrade: 0,
  });

  // The NEW YORK calendar date, not the UTC one. toISOString() rolls over at
  // 20:00 EDT (19:00 EST), so from 8pm every screen this navigates to was asking
  // the backend for TOMORROW: `today` is passed straight through as
  // ?date=... below, and /checkins-today bounds that date to Eastern midnight
  // (server.py get_day_range_est). An evening check-in therefore fell three
  // hours before the window the roster asked for and came back EMPTY, while the
  // CP-home badge — which counts with no day bound at all — still found it. That
  // is the count and the roster disagreeing.
  //
  // Same expression as checkinsAPI.getByDate (src/utils/api.js) and
  // useDailyLogs.js; en-CA formats as YYYY-MM-DD.
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' })
    .format(new Date());
  const todayFormatted = new Date().toLocaleDateString('en-US', {
    weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
  });

  const styles = buildStyles(colors, isDark);

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated) fetchInitial();
  }, [isAuthenticated]);

  // Task A: gate the Check-In Review banner on a real flagged count. The
  // /flagged endpoint already returns a per-project `count`; sum it across the
  // CP's visible projects and remember the first non-empty one to land on.
  // (Perf note: this is one request per project — fine at the small
  // project counts a CP has; a cross-project aggregate endpoint is the future
  // optimization if that grows.)
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!projects.length) {
        setFlagged({ count: 0, projectId: null, expired: 0, unknown: 0, needsTrade: 0 });
        return;
      }
      const results = await Promise.all(projects.map(async (p) => {
        const pid = p._id || p.id;
        try {
          const d = await checkinsAPI.getFlagged(pid);
          const items = d?.items || [];
          // Per-reason tally. A single check-in can carry more than one reason
          // (e.g. unknown SST AND no trade), so these need not sum to `c`.
          let expired = 0, unknown = 0, needsTrade = 0;
          for (const it of items) {
            const rs = it.flag_reasons || [];
            if (rs.includes('expired_sst')) expired += 1;
            if (rs.includes('unknown_sst')) unknown += 1;
            if (rs.includes('needs_trade')) needsTrade += 1;
          }
          return { pid, c: d?.count ?? items.length, expired, unknown, needsTrade };
        } catch (_e) { return { pid, c: 0, expired: 0, unknown: 0, needsTrade: 0 }; }
      }));
      if (cancelled) return;
      let total = 0, firstPid = null, expired = 0, unknown = 0, needsTrade = 0;
      for (const r of results) {
        if (r.c > 0) { total += r.c; if (!firstPid) firstPid = r.pid; }
        expired += r.expired; unknown += r.unknown; needsTrade += r.needsTrade;
      }
      setFlagged({ count: total, projectId: firstPid, expired, unknown, needsTrade });
    })();
    return () => { cancelled = true; };
  }, [projects]);

  // Refetch the selected project's logbook data whenever the hub regains
  // focus. Without this, returning here after submitting a logbook (e.g.
  // pre-shift calls router.back()) shows the stale pre-submit status —
  // "Draft" where it should now read "Done". Mirrors the useFocusEffect
  // pattern used by project/[id]/report-settings.jsx.
  useFocusEffect(
    React.useCallback(() => {
      if (isAuthenticated && selectedProject) {
        fetchProjectData(selectedProject._id || selectedProject.id);
      }
    }, [isAuthenticated, selectedProject])
  );

  // CP picker scope (defense-in-depth; backend is the real gate): a CP only sees
  // the project(s) they're assigned to, so they can't navigate to an unassigned
  // project's logbook. Other roles (admin/owner/superintendent) see all company
  // projects. Shared by the cache-first read AND the live read below.
  const filterVisibleProjects = (list) => {
    const arr = Array.isArray(list) ? list : [];
    return user?.role === 'cp'
      ? arr.filter(p => (user?.assigned_projects || []).includes(p.id || p._id))
      : arr;
  };

  const fetchInitial = async () => {
    // OFFLINE FIX (CP screen): the CP lands here (_layout.jsx routes role 'cp' to
    // /logbooks), NOT on the admin projects screen — so the proven cache-first
    // pattern (admin projects/index.jsx, app/index.jsx) has to live here too, or
    // the CP's picker blanks offline. Mirror it exactly:
    //   1) read the local cache first and paint immediately,
    //   2) write-through on every successful server load,
    //   3) on refresh failure KEEP the cached list (never blank it).
    // The old code did `getAll().catch(() => [])`, which SWALLOWED the offline
    // error into an empty list — the live CP blocker.
    const _cached = await readCachedProjectList();
    const cachedVisible = filterVisibleProjects(_cached);
    let picked = null;
    if (cachedVisible.length > 0) {
      setProjects(cachedVisible);
      picked = cachedVisible[0];
      setSelectedProject(picked);
      // Sub-reads all have their own offline `.catch` fallbacks, so this is safe
      // offline — it just shows empty logs until the CP drafts.
      fetchProjectData(picked._id || picked.id);
      setLoading(false);
    } else {
      setLoading(true);
    }

    try {
      // No `.catch(() => [])` here — let getAll REJECT offline so the outer catch
      // runs and keeps the cache, instead of silently overwriting it with [].
      const projectsData = await projectsAPI.getAll();
      const projectList = Array.isArray(projectsData) ? projectsData : [];
      cacheProjectList(projectList); // write-through (full list, role-agnostic key)
      const visibleProjects = filterVisibleProjects(projectList);
      setProjects(visibleProjects);

      cpProfileAPI.getProfile()
        .then(p => { if (p?.cp_name) setCpName(p.cp_name); })
        .catch(() => {});

      if (visibleProjects.length > 0 && !picked) {
        setSelectedProject(visibleProjects[0]);
        await fetchProjectData(visibleProjects[0]._id || visibleProjects[0].id);
      }
    } catch (error) {
      // Offline / refresh failure — KEEP the cached list already painted above.
      // Never setProjects([]) here: that is exactly the blank-offline bug.
      console.error('logbooks fetchInitial failed (keeping cache):', error);
      if (cachedVisible.length > 0) {
        toast.success('Offline', `Loaded ${cachedVisible.length} cached project${cachedVisible.length === 1 ? '' : 's'}`);
      } else {
        toast.error('Offline', 'No cached projects — open once online on this version first');
      }
    } finally {
      setLoading(false);
    }
  };

  const fetchProjectData = async (projectId) => {
    try {
      const [logs, notifs, scaffoldInfo, reqLogbooks, catalog] = await Promise.all([
        logbooksAPI.getByProject(projectId, null, today).catch(() => []),
        logbooksAPI.getNotifications(projectId).catch(() => ({ missing_toolbox_talk: [], unsigned_orientations: 0, unaffirmed_logbooks: 0, unaffirmed_logbook_refs: [], stale_unsigned_logbooks: 0, stale_unsigned_logbook_refs: [] })),
        logbooksAPI.getScaffoldInfo(projectId).catch(() => null),
        projectsAPI.getRequiredLogbooks(projectId).catch(() => null),
        logbookTypesAPI.getAll().catch(() => null),
      ]);

      const logMap = {};
      (Array.isArray(logs) ? logs : []).forEach(log => { logMap[log.log_type] = log; });
      setTodayLogs(logMap);
      setNotifications(notifs);

      // `required_logbooks`, NOT `logbooks`. The endpoint has always returned
      // `{project_id, project_class, classification_assessed, required_logbooks}`
      // and this read the key `logbooks`, which does not exist — so the state
      // was never set, the dynamic branch in getVisibleLogTypes never ran, and
      // the CP's list was ALWAYS the six hardcoded fallbacks. The resolved
      // required set has never once reached this screen. It also mapped
      // `l.log_type` over what are plain strings, so the branch was broken
      // twice over and neither half could be noticed while the other held.
      if (Array.isArray(reqLogbooks?.required_logbooks)) {
        setRequiredLogbooks(reqLogbooks);
      }
      if (Array.isArray(catalog) && catalog.length > 0) setLogTypeCatalog(catalog);

      const isScaffoldUp = scaffoldInfo?.scaffold_erected === true
        || (scaffoldInfo?.scaffold_erector && scaffoldInfo?.scaffold_erected !== false)
        || false;
      setScaffoldActive(isScaffoldUp);
      setToolboxDoneThisWeek(logMap['toolbox_talk']?.status === 'submitted');
    } catch (error) {
      console.error('Failed to fetch project logbooks:', error);
    }
  };

  const handleProjectSelect = async (project) => {
    setSelectedProject(project);
    setShowProjectPicker(false);
    setTodayLogs({});
    await fetchProjectData(project._id || project.id);
  };

  const handleOpenLog = (logType) => {
    if (!selectedProject) {
      toast.warning('Select Project', 'Please select a project first');
      return;
    }
    const projectId = selectedProject._id || selectedProject.id;
    router.push(`/logbooks/${logType}?projectId=${projectId}&date=${today}`);
  };

  // Deep-link the unaffirmed-signature alert to a logbook that needs the CP
  // signature affirmed. Refs come from the notifications payload (log_type +
  // date); we open the most recent one — after it's affirmed, the focus
  // refetch drops the count and the alert clears (or points at the next one).
  /**
   * Open the oldest day still waiting for a signature.
   *
   * OLDEST FIRST, not newest. The refs come back newest-first for the badge, so
   * this walks to the end: the day most likely to be forgotten is the one
   * furthest back, and it is also the one whose record has been sitting open
   * the longest.
   */
  const handleOpenStaleUnsigned = () => {
    const refs = notifications?.stale_unsigned_logbook_refs || [];
    if (!selectedProject || refs.length === 0) return;
    const projectId = selectedProject._id || selectedProject.id;
    const { log_type, date } = refs[refs.length - 1];
    router.push(`/logbooks/${log_type}?projectId=${projectId}&date=${date}`);
  };

  const handleOpenUnaffirmed = () => {
    const refs = notifications?.unaffirmed_logbook_refs || [];
    if (!selectedProject || refs.length === 0) return;
    const projectId = selectedProject._id || selectedProject.id;
    const { log_type, date } = refs[0];
    router.push(`/logbooks/${log_type}?projectId=${projectId}&date=${date}`);
  };

  const getLogStatus = (logTypeKey) => {
    const log = todayLogs[logTypeKey];
    if (!log) return 'pending';
    if (log.status === 'submitted') return 'submitted';
    return 'draft';
  };

  /**
   * Switch one conditional logbook on or off.
   *
   * ONE HANDLER FOR ALL OF THEM. The activations come from the server, which
   * reads LOGBOOK_TYPE_REGISTRY, so a fifth conditional type appears here with
   * no change to this screen. The scaffold toggle used to be the only one and
   * was written against its own endpoint and its own state variable; it now
   * goes through the same path as the other three.
   *
   * OPTIMISTIC, THEN CORRECTED BY THE SERVER'S OWN ANSWER. The response carries
   * the recomputed required set, so the list below cannot disagree with the
   * switch above it even for a frame — and a REFUSAL (hot work, from a CP)
   * puts the switch back rather than leaving it showing a state the server
   * never accepted.
   */
  const handleToggleLogbook = async (act) => {
    if (!selectedProject || !act) return;
    const projectId = selectedProject._id || selectedProject.id;
    const next = !act.active;
    setRequiredLogbooks((prev) => (prev ? {
      ...prev,
      activations: (prev.activations || []).map(
        (a) => (a.log_type === act.log_type ? { ...a, active: next } : a),
      ),
    } : prev));
    try {
      const res = await logbookActivationAPI.set(projectId, act.log_type, next);
      setRequiredLogbooks((prev) => (prev ? {
        ...prev,
        required_logbooks: Array.isArray(res?.required_logbooks)
          ? res.required_logbooks : prev.required_logbooks,
      } : prev));
      toast.success(
        next ? `${act.label} on` : `${act.label} off`,
        next
          ? 'It is now on your logbook list.'
          : 'Hidden until you switch it back on.',
      );
    } catch (e) {
      setRequiredLogbooks((prev) => (prev ? {
        ...prev,
        activations: (prev.activations || []).map(
          (a) => (a.log_type === act.log_type ? { ...a, active: act.active } : a),
        ),
      } : prev));
      // A 403 is the server saying this one is not the CP's to set. That is a
      // different sentence from "it did not save", and telling him the wrong
      // one is how a CP learns to distrust the screen.
      const refused = e?.response?.status === 403;
      toast.error(
        refused ? 'An admin sets this one' : 'Could not update',
        refused
          ? `${act.label} runs on a permit the office holds. Ask an admin to switch it on.`
          : 'Nothing changed. Check your signal and try again.',
      );
    }
  };

  const getVisibleLogTypes = () => {
    const requiredKeys = requiredLogbooks?.required_logbooks;
    if (Array.isArray(requiredKeys) && requiredKeys.length > 0) {
      // THE SERVER DECIDES WHAT IS REQUIRED. get_required_logbooks resolves it
      // from the project — §3310 class for the major-building pair, the site
      // toggles for the conditional four — and this screen renders that answer
      // rather than re-deriving one. The old local filtering below is what a
      // second model looks like: it decided weekly and as-needed types for
      // itself, and it decided them differently.
      //
      // Order is the server's, which is registry order.
      const byKey = {};
      [...(logTypeCatalog || []), ...FALLBACK_LOG_TYPES].forEach((t) => {
        if (t && t.key && !byKey[t.key]) byKey[t.key] = t;
      });
      return requiredKeys.map((key) => byKey[key] || {
        // A type the server requires and neither the registry nor the fallback
        // describes. It is still rendered — a required log the CP cannot open
        // is worse than an ugly label.
        key,
        label: key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
        subtitle: '',
        icon: 'ShieldCheck',
        color: semantic.neutral,
        frequency: 'daily',
      });
    }

    // Nothing from the server yet (first paint, or offline). Local filtering,
    // unchanged — it is a placeholder, not a second opinion.
    return FALLBACK_LOG_TYPES.filter((lt) => {
      if (lt.conditional === 'scaffold_erected') return scaffoldActive;
      if (lt.frequency === 'weekly') return !toolboxDoneThisWeek;
      if (lt.frequency === 'as_needed') return (notifications?.unsigned_orientations || 0) > 0;
      return true;
    });
  };

  // The conditional logbooks and their current state. Empty until the server
  // answers, which is why the block that renders them is gated on length —
  // an empty "On site today" heading over nothing is worse than no heading.
  const activations = requiredLogbooks?.activations || [];
  const staleUnsigned = notifications?.stale_unsigned_logbooks || 0;
  const missingToolbox = notifications?.missing_toolbox_talk || [];
  const unaffirmedLogbooks = notifications?.unaffirmed_logbooks || 0;
  const visibleLogs = getVisibleLogTypes();

  const StatusBadge = ({ status }) => {
    if (status === 'submitted') {
      return (
        <View style={[styles.badge, styles.badgeSubmitted]}>
          <CheckCircle size={12} strokeWidth={2} color={semantic.verified} />
          <Text style={[styles.badgeText, styles.badgeTextSubmitted]}>Done</Text>
        </View>
      );
    }
    if (status === 'draft') {
      return (
        <View style={[styles.badge, styles.badgeDraft]}>
          <Text style={[styles.badgeText, styles.badgeTextDraft]}>Draft</Text>
        </View>
      );
    }
    return (
      <View style={[styles.badge, styles.badgePending]}>
        <Text style={[styles.badgeText, styles.badgeTextPending]}>Pending</Text>
      </View>
    );
  };

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container} edges={['top']}>
        {/* Header */}
        <View style={styles.header}>
          <HeaderBrand />
        </View>

        <ScrollView
          style={styles.scrollView}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {/* ═══ SINGLE HERO CARD: title + CP banner + project + scaffold ═══ */}
          <GlassCard style={styles.heroCard}>
            {/* Title section */}
            <Text style={styles.titleLabel}>COMPLIANCE</Text>
            <Text style={styles.titleText}>Log Books</Text>
            <View style={styles.dateRow}>
              <Calendar size={14} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={styles.dateText}>{todayFormatted}</Text>
            </View>

            {/* CP name banner */}
            {cpName ? (
              <View style={styles.cpBannerRow}>
                <ShieldCheck size={16} strokeWidth={1.5} color="#3b82f6" />
                <Text style={styles.cpBannerText}>
                  Signing as <Text style={styles.cpBannerName}>{cpName}</Text>
                </Text>
              </View>
            ) : null}

            {/* Divider */}
            <View style={styles.heroDivider} />

            {/* Project selector */}
            <Pressable
              style={styles.projectSelector}
              onPress={() => setShowProjectPicker(!showProjectPicker)}
            >
              <View style={styles.projectSelectorLeft}>
                <IconPod size={40}>
                  <Building2 size={18} strokeWidth={1.5} color={colors.text.secondary} />
                </IconPod>
                <View>
                  <Text style={styles.projectSelectorLabel}>PROJECT</Text>
                  <Text style={styles.projectSelectorName}>
                    {selectedProject?.name || 'Select a project'}
                  </Text>
                </View>
              </View>
              <ChevronDown
                size={18}
                strokeWidth={1.5}
                color={colors.text.muted}
                style={{ transform: [{ rotate: showProjectPicker ? '180deg' : '0deg' }] }}
              />
            </Pressable>

            {/* Project dropdown — inside the hero card */}
            {showProjectPicker && (
              <View style={styles.projectDropdown}>
                {projects.map((p) => (
                  <Pressable
                    key={p._id || p.id}
                    style={[
                      styles.projectOption,
                      (p._id || p.id) === (selectedProject?._id || selectedProject?.id) &&
                        styles.projectOptionActive,
                    ]}
                    onPress={() => handleProjectSelect(p)}
                  >
                    <Text style={styles.projectOptionText}>{p.name}</Text>
                    {(p._id || p.id) === (selectedProject?._id || selectedProject?.id) && (
                      <CheckCircle size={16} strokeWidth={1.5} color={semantic.verified} />
                    )}
                  </Pressable>
                ))}
              </View>
            )}

            {/* WHAT IS ON SITE TODAY — one row per conditional logbook.
                Rendered from the server's `activations`, which come off
                LOGBOOK_TYPE_REGISTRY, so a fifth conditional type appears here
                on its own. Was a single hardcoded scaffold row. */}
            {selectedProject && activations.length > 0 && (
              <>
                <View style={styles.heroDivider} />
                <Text style={styles.toggleGroupTitle}>On site today</Text>
                {activations.map((act) => {
                  const mine = act.activated_by !== 'admin';
                  return (
                    <View key={act.log_type} style={styles.scaffoldToggleRow}>
                      <HardHat size={18} strokeWidth={1.5} color={semantic.neutral} />
                      <View style={{ flex: 1 }}>
                        <Text style={styles.scaffoldToggleTitle}>{act.label}</Text>
                        <Text style={styles.scaffoldToggleDesc}>
                          {/* THREE STATES, not two. "Off, and not yours to
                              switch on" is a different fact from "off" — a CP
                              hunting for the hot-work log needs to know it
                              exists and who turns it on, not to find a dead
                              control. */}
                          {act.active
                            ? 'On — it is on your logbook list'
                            : (mine
                              ? 'Off — switch on when it starts'
                              : 'Off — an admin switches this one on')}
                        </Text>
                      </View>
                      <Pressable
                        onPress={() => (mine
                          ? handleToggleLogbook(act)
                          : toast.warning(
                            'An admin sets this one',
                            `${act.label} runs on a permit the office holds.`,
                          ))}
                        style={[styles.toggleBtn, act.active && styles.toggleBtnActive,
                          !mine && styles.toggleBtnLocked]}
                      >
                        <Text style={[styles.toggleBtnText, act.active && styles.toggleBtnTextActive]}>
                          {act.active ? 'ON' : 'OFF'}
                        </Text>
                      </Pressable>
                    </View>
                  );
                })}
              </>
            )}
          </GlassCard>

          {/* Missing toolbox talk alert */}
          {missingToolbox.length > 0 && (
            <GlassCard style={styles.notifCard}>
              <View style={styles.notifHeader}>
                <Bell size={16} strokeWidth={1.5} color={semantic.attention} />
                <Text style={styles.notifTitle}>
                  {missingToolbox.length} worker{missingToolbox.length > 1 ? 's' : ''} missing Tool Box Talk this week
                </Text>
              </View>
              {/* The parentheses are CONDITIONAL. The company is per-project
                  and can legitimately be absent — an unpaired worker — and
                  "Andre Duval ()" reads as a rendering fault rather than as
                  missing data. No company, no brackets. */}
              {missingToolbox.slice(0, 3).map((w, i) => (
                <Text key={i} style={styles.notifWorker}>
                  • {w.worker_name}{w.company ? ` (${w.company})` : ''}
                </Text>
              ))}
              {missingToolbox.length > 3 && (
                <Text style={styles.notifMore}>+{missingToolbox.length - 3} more</Text>
              )}
              <GlassButton
                title="Open Tool Box Talk"
                onPress={() => handleOpenLog('toolbox_talk')}
                style={styles.notifBtn}
              />
            </GlassCard>
          )}

          {/* Unaffirmed-signature alert — a filed logbook whose CP signature was
              inherited but never affirmed for that document. Same attention
              channel as the toolbox alert; an honest deficiency, not a block. */}
          {unaffirmedLogbooks > 0 && (
            <Pressable onPress={handleOpenUnaffirmed}>
              <GlassCard style={styles.notifCard}>
                <View style={styles.notifHeader}>
                  <AlertTriangle size={16} strokeWidth={1.5} color={semantic.attention} />
                  <Text style={styles.notifTitle}>
                    {unaffirmedLogbooks} logbook{unaffirmedLogbooks > 1 ? 's' : ''} filed without an affirmed signature
                  </Text>
                </View>
                <Text style={styles.notifWorker}>
                  Tap to open and affirm the signature for that document.
                </Text>
              </GlassCard>
            </Pressable>
          )}

          {/* THE CLASSIFICATION WAS NEVER SET, so the required set failed
              CLOSED and both major-building logs are on the list below.
              Saying so is half the ruling: get_required_logbooks includes them
              because it cannot rule them out, and a CP who is shown two logs
              his site plainly does not need, with no reason given, learns to
              distrust the list. Reuses the same attention channel as the two
              alerts above rather than adding a fourth treatment (see the
              exception-surface drift note in followups.md). */}
          {requiredLogbooks && requiredLogbooks.classification_assessed === false && (
            <GlassCard style={styles.notifCard}>
              <View style={styles.notifHeader}>
                <AlertTriangle size={16} strokeWidth={1.5} color={semantic.attention} />
                <Text style={styles.notifTitle}>
                  Building classification not set
                </Text>
              </View>
              <Text style={styles.notifWorker}>
                Nobody has recorded this project&apos;s storeys, height or footprint,
                so the app cannot tell whether it is a major building. The
                Concrete Operations and SSC/SSM logs are listed until it does.
                An admin sets this on the project.
              </Text>
            </GlassCard>
          )}

          {/* A DAY THAT WAS WORKED AND NEVER SIGNED. The end-of-day sweep
              freezes yesterday's SIGNED narratives and leaves these open on
              purpose — sealing a record nobody attested to is worse than
              leaving it open — so it is an unfinished obligation, and the CP
              is the only person who can finish it.

              SAME TREATMENT as the unaffirmed-signature card directly above,
              deliberately. That card is the closest thing this screen has: a
              record that exists and lacks the CP's attestation, tappable,
              deep-linking to the log. A fourth variant is what followups.md
              already logs this screen for. */}
          {staleUnsigned > 0 && (
            <Pressable onPress={handleOpenStaleUnsigned}>
              <GlassCard style={styles.notifCard}>
                <View style={styles.notifHeader}>
                  <AlertTriangle size={16} strokeWidth={1.5} color={semantic.attention} />
                  <Text style={styles.notifTitle}>
                    {staleUnsigned} day{staleUnsigned > 1 ? 's' : ''} worked but never signed
                  </Text>
                </View>
                <Text style={styles.notifWorker}>
                  These logs are still open and still yours to finish. Tap to
                  open the oldest one and sign it.
                </Text>
              </GlassCard>
            </Pressable>
          )}

          {/* Check-in review entry point. Lives here because /logbooks/* is
              the only area a CP is allowed on (see the guard in _layout.jsx),
              so this is how a CP reaches the approve / send-home decision
              from their own login. */}
          {flagged.count > 0 && (
            <Pressable onPress={() => router.push(
              flagged.projectId ? `/logbooks/review?projectId=${flagged.projectId}` : '/logbooks/review'
            )}>
              <GlassCard style={styles.notifCard}>
                <View style={styles.notifHeader}>
                  <ShieldAlert size={16} strokeWidth={1.5} color={semantic.attention} />
                  <Text style={styles.notifTitle}>Check-In Review</Text>
                </View>
                <Text style={styles.notifWorker}>
                  {flagged.count} check-in{flagged.count > 1 ? 's' : ''} to review — {flaggedReasonSummary(flagged)}
                </Text>
              </GlassCard>
            </Pressable>
          )}

          {/* Log book cards */}
          {loading ? (
            <View style={styles.loadingCenter}>
              <ActivityIndicator size="large" color={colors.text.primary} />
              <Text style={styles.loadingText}>Loading log books...</Text>
            </View>
          ) : (
            <View style={styles.logList}>
              <Text style={styles.sectionLabel}>TODAY'S LOG BOOKS</Text>

              {visibleLogs.length === 0 ? (
                <GlassCard style={styles.emptyCard}>
                  <CheckCircle size={32} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={styles.emptyText}>All caught up! No logbooks needed right now.</Text>
                </GlassCard>
              ) : (
                visibleLogs.map((logType) => {
                  const Icon = typeof logType.icon === 'string' ? (ICON_MAP[logType.icon] || ClipboardList) : logType.icon;
                  const status = getLogStatus(logType.key);
                  return (
                    <Pressable
                      key={logType.key}
                      onPress={() => handleOpenLog(logType.key)}
                      style={({ pressed }) => [styles.logCard, pressed && styles.logCardPressed]}
                    >
                      <View style={[styles.logIcon, { backgroundColor: logType.bg || (logType.color + '26') }]}>
                        <Icon size={22} strokeWidth={1.5} color={logType.color} />
                      </View>
                      <View style={styles.logInfo}>
                        <Text style={styles.logLabel}>{logType.label}</Text>
                        <Text style={styles.logSubtitle}>{logType.subtitle}</Text>
                      </View>
                      <View style={styles.logRight}>
                        <StatusBadge status={status} />
                        <ChevronRight size={16} strokeWidth={1.5} color={colors.text.muted} />
                      </View>
                    </Pressable>
                  );
                })
              )}

              {toolboxDoneThisWeek && (
                <Pressable
                  onPress={() => handleOpenLog('toolbox_talk')}
                  style={({ pressed }) => [styles.logCard, styles.logCardDone, pressed && styles.logCardPressed]}
                >
                  <View style={[styles.logIcon, { backgroundColor: 'rgba(59, 130, 246, 0.15)' }]}>
                    <BookOpen size={22} strokeWidth={1.5} color="#3b82f6" />
                  </View>
                  <View style={styles.logInfo}>
                    <Text style={styles.logLabel}>Tool Box Talk</Text>
                    <Text style={styles.logSubtitle}>Completed this week</Text>
                  </View>
                  <View style={styles.logRight}>
                    <StatusBadge status="submitted" />
                    <ChevronRight size={16} strokeWidth={1.5} color={colors.text.muted} />
                  </View>
                </Pressable>
              )}
            </View>
          )}

          {/* Completion bar */}
          {!loading && selectedProject && (
            <GlassCard style={styles.summaryCard}>
              <Text style={styles.summaryTitle}>Today's Completion</Text>
              <View style={styles.summaryRow}>
                {(() => {
                  const submitted = visibleLogs.filter(lt => getLogStatus(lt.key) === 'submitted').length;
                  const total = visibleLogs.length;
                  const pct = total > 0 ? Math.round((submitted / total) * 100) : 0;
                  return (
                    <>
                      <View style={styles.summaryBar}>
                        <View style={[styles.summaryBarFill, { width: `${pct}%` }]} />
                      </View>
                      <Text style={styles.summaryCount}>{submitted}/{total}</Text>
                    </>
                  );
                })()}
              </View>
            </GlassCard>
          )}

          {/* Running-bundle self-report — lets a CP-role user confirm which JS is
              live on THEIR screen (they can't reach the admin screen's marker). */}
          <BuildMarker />
        </ScrollView>

        <CpNav />
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  const divider = isDark ? withAlpha('#ffffff', 0.05) : withAlpha('#000000', 0.06);

  return StyleSheet.create({
    container: { flex: 1 },
    header: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    },
    logoText: {
      ...typography.label, fontSize: 18, color: colors.text.primary, letterSpacing: 6,
    },
    scrollView: { flex: 1 },
    scrollContent: { padding: spacing.lg, paddingBottom: 120 },

    // ── Hero card (single merged card) ──
    heroCard: { marginBottom: spacing.md },
    titleLabel: { ...typography.label, color: colors.text.muted, marginBottom: spacing.xs },
    titleText: { fontSize: 32, fontWeight: '200', color: colors.text.primary, marginBottom: spacing.xs },
    dateRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
    dateText: { fontSize: 13, color: colors.text.muted },

    cpBannerRow: {
      flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
      marginTop: spacing.md,
    },
    cpBannerText: { fontSize: 14, color: colors.text.secondary },
    cpBannerName: { color: colors.text.primary, fontWeight: '500' },

    heroDivider: {
      height: 1, backgroundColor: divider,
      marginVertical: spacing.md,
    },

    projectSelector: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      paddingVertical: spacing.sm,
    },
    projectSelectorLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
    projectSelectorLabel: { ...typography.label, color: colors.text.muted, marginBottom: 2 },
    projectSelectorName: { fontSize: 15, color: colors.text.primary, fontWeight: '500' },
    projectDropdown: {
      marginTop: spacing.sm, borderRadius: borderRadius.lg, overflow: 'hidden',
      borderWidth: 1, borderColor: divider,
    },
    projectOption: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      padding: spacing.md,
      borderBottomWidth: 1, borderBottomColor: divider,
    },
    projectOptionActive: { backgroundColor: 'rgba(59, 130, 246, 0.1)' },
    projectOptionText: { fontSize: 15, color: colors.text.primary },

    // ── Scaffold toggle (inside hero card) ──
    toggleGroupTitle: {
      fontSize: 12, fontWeight: '600', color: colors.text.muted,
      textTransform: 'uppercase', letterSpacing: 1, marginBottom: spacing.sm,
    },
    scaffoldToggleRow: {
      flexDirection: 'row', alignItems: 'center', gap: spacing.md,
      paddingVertical: spacing.xs,
    },
    scaffoldToggleTitle: { fontSize: 14, fontWeight: '500', color: colors.text.primary },
    scaffoldToggleDesc: { fontSize: 12, color: colors.text.muted, marginTop: 2 },
    toggleBtn: {
      paddingHorizontal: spacing.md, paddingVertical: spacing.xs,
      borderRadius: borderRadius.md,
      borderWidth: 1, borderColor: colors.border.medium,
      backgroundColor: isDark ? withAlpha('#ffffff', 0.05) : withAlpha('#000000', 0.04),
    },
    // A control that is not this user's to press reads as unavailable rather
    // than as OFF — it still responds, and what it says is who owns it.
    toggleBtnLocked: { opacity: 0.5 },
    toggleBtnActive: {
      backgroundColor: semantic.attentionBg,
      borderColor: semantic.attentionBorder,
    },
    toggleBtnText: { fontSize: 12, fontWeight: '600', color: colors.text.muted },
    toggleBtnTextActive: { color: semantic.attention },

    notifCard: {
      marginBottom: spacing.md, padding: spacing.md,
      backgroundColor: semantic.attentionBg, borderColor: semantic.attentionBorder,
    },
    notifHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm },
    notifTitle: { fontSize: 14, fontWeight: '500', color: semantic.attention, flex: 1 },
    notifWorker: { fontSize: 13, color: colors.text.secondary, marginBottom: 2, paddingLeft: spacing.sm },
    notifMore: { fontSize: 12, color: colors.text.muted, paddingLeft: spacing.sm, marginBottom: spacing.sm },
    notifBtn: { marginTop: spacing.sm },

    loadingCenter: { alignItems: 'center', paddingVertical: spacing.xxl, gap: spacing.md },
    loadingText: { fontSize: 14, color: colors.text.muted },
    sectionLabel: { ...typography.label, color: colors.text.muted, marginBottom: spacing.md, marginTop: spacing.sm },
    logList: { gap: spacing.sm, marginBottom: spacing.lg },

    logCard: {
      flexDirection: 'row', alignItems: 'center',
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.xl,
      borderWidth: 1, borderColor: colors.glass.border,
      padding: spacing.md, gap: spacing.md,
    },
    logCardDone: { opacity: 0.5 },
    logCardPressed: { opacity: 0.8 },
    logIcon: { width: 48, height: 48, borderRadius: borderRadius.lg, alignItems: 'center', justifyContent: 'center' },
    logInfo: { flex: 1 },
    logLabel: { fontSize: 15, fontWeight: '500', color: colors.text.primary, marginBottom: 2 },
    logSubtitle: { fontSize: 12, color: colors.text.muted },
    logRight: { alignItems: 'flex-end', gap: spacing.xs },

    badge: {
      flexDirection: 'row', alignItems: 'center', gap: 4,
      paddingHorizontal: spacing.sm, paddingVertical: 3, borderRadius: borderRadius.full,
    },
    badgeSubmitted: { backgroundColor: semantic.verifiedBg },
    badgeDraft: { backgroundColor: semantic.attentionBg },
    badgePending: { backgroundColor: isDark ? withAlpha('#ffffff', 0.06) : withAlpha('#000000', 0.04) },
    badgeText: { fontSize: 11, fontWeight: '500' },
    badgeTextSubmitted: { color: semantic.verified },
    badgeTextDraft: { color: '#fbbf24' },
    badgeTextPending: { color: colors.text.muted },

    emptyCard: { alignItems: 'center', padding: spacing.xl, gap: spacing.md },
    emptyText: { fontSize: 14, color: colors.text.muted, textAlign: 'center' },

    summaryCard: { padding: spacing.md },
    summaryTitle: { fontSize: 13, color: colors.text.muted, marginBottom: spacing.sm },
    summaryRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
    summaryBar: {
      flex: 1, height: 6,
      backgroundColor: isDark ? withAlpha('#ffffff', 0.08) : withAlpha('#000000', 0.06),
      borderRadius: 3, overflow: 'hidden',
    },
    summaryBarFill: { height: '100%', backgroundColor: semantic.verified, borderRadius: 3 },
    summaryCount: { fontSize: 14, fontWeight: '500', color: colors.text.secondary },
  });
}
