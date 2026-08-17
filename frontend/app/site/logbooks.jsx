import React, { useState, useEffect } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Image,
  Linking, Platform,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft, ClipboardList, BookOpen, Users, FileText,
  Building2, Calendar, CheckCircle, ChevronRight, ChevronDown,
  CloudSun, Clock, MapPin, Wrench, ShieldCheck, Eye, Truck,
  AlertTriangle, Pen, XCircle, Download, Share2, Lock,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import SiteNav from '../../src/components/SiteNav';
import OfflineNotice from '../../src/components/OfflineNotice';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { useInspectorLock } from '../../src/context/InspectorLockContext';
import { logbooksAPI } from '../../src/utils/api';
import {
  cacheDocList, readCachedDocList, ensureCachedDocFile, warmDocCache,
} from '../../src/utils/docCache';
import { settleFetch } from '../../src/utils/offlineState';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { semantic, withAlpha } from '../../src/styles/semanticColors';
import { useTheme } from '../../src/context/ThemeContext';
import { useT } from '../../src/i18n';

// EVERY submitted log type this project can file. The list used to stop at
// three, and the tab filter is `l.log_type === activeTab` — so the other eight
// types were fetched by /logbooks/project/{id}/submitted, cached to the device,
// and then had no tab that could show them. An inspector on the site device
// could not reach a hot work permit, a crane log or an orientation record at
// all. Labels resolve through src/i18n at render (`labelKey`), not here:
// module scope is evaluated once at import, before a locale can be set.
const LOG_TABS = [
  { key: 'daily_jobsite', labelKey: 'tabDailyJobsite', icon: ClipboardList, color: '#3b82f6' },
  { key: 'toolbox_talk', labelKey: 'tabToolboxTalk', icon: BookOpen, color: '#8b5cf6' },
  { key: 'preshift_signin', labelKey: 'tabPreshift', icon: Users, color: semantic.neutral },
  { key: 'hot_work', labelKey: 'tabHotWork', icon: AlertTriangle, color: '#8b5cf6' },
  { key: 'crane_operations', labelKey: 'tabCrane', icon: Truck, color: '#3b82f6' },
  { key: 'excavation_monitoring', labelKey: 'tabExcavation', icon: Eye, color: semantic.neutral },
  { key: 'concrete_operations', labelKey: 'tabConcrete', icon: Wrench, color: '#3b82f6' },
  { key: 'scaffold_maintenance', labelKey: 'tabScaffold', icon: ShieldCheck, color: '#8b5cf6' },
  { key: 'ssc_daily_safety_log', labelKey: 'tabSsc', icon: ClipboardList, color: semantic.neutral },
  { key: 'osha_log', labelKey: 'tabOsha', icon: FileText, color: '#3b82f6' },
  { key: 'subcontractor_orientation', labelKey: 'tabOrientation', icon: Users, color: '#8b5cf6' },
];

// How many days of submitted records we keep on the device. AsyncStorage is
// not a filesystem — an unbounded write on a long-running project eventually
// fails, and a failed write means NOTHING is here in the dead zone.
const CACHE_DATE_LIMIT = 60;

// ⚠️ ANDROID LIMIT — PDFViewer.native.jsx renders Android PDFs through a
// REMOTE viewer (mozilla.github.io/pdf.js), so on Android there is nothing on
// the device that can draw a cached PDF until a viewer ships in a native
// build. We still cache the bytes (ready for that build); offline we say this
// plainly rather than opening a viewer that will spin forever.
const ANDROID_OFFLINE_PDF_MSG =
  'PDF viewing offline requires the next app update — the record is listed above and its PDF is saved on this device.';

// Roster check-in time -> "7:42 AM". The toolbox roster carries the four
// §3301.12.3 fields (name, title, company, date/time); this renders the time.
// Falls back to the raw value rather than printing an error onto a record an
// inspector is reading.
const rosterClock = (v) => {
  if (!v) return '—';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return String(v).slice(0, 16);
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
};

// A stored activity photo has more than one copy, and which ones exist changes
// over the record's life. `base64` is the full-size original; the backend drops
// it when the log is FINALIZED, and only after R2 has confirmed both
// derivatives (server.py _purge_finalized_photo_base64). `thumb_base64` is the
// ~400px copy written in its place and never removed.
const inlinePhoto = (b64) => (
  !b64 ? null : (b64.startsWith('data:') ? b64 : `data:image/jpeg;base64,${b64}`)
);

// THIS SCREEN IS READ OFFLINE (docCache, OfflineNotice), so an inline copy
// always beats a URL — an inspector in a dead zone must still see the photo.
// The served thumbnail is the rung below, for a record whose full-size copy is
// gone; `uri` is a path on the CP's own phone and stays last, where it was.
const logbookPhotoUri = (photo, log, activityIndex, photoIndex) => {
  if (!photo) return null;
  return inlinePhoto(photo.base64)
    || inlinePhoto(photo.thumb_base64)
    || logbooksAPI.getLogbookPhotoUrl(
      log?.id || log?._id, activityIndex, photoIndex, 'thumb', photo.enhance_status || '',
    )
    || photo.uri
    || null;
};

export default function SiteLogbooksViewer() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading, siteMode, siteProject } = useAuth();
  const { isLocked, unlock } = useInspectorLock();
  const toast = useToast();
  const t = useT('logbookView');
  const tabLabel = (key) => {
    const tab = LOG_TABS.find((x) => x.key === key);
    return tab ? t(tab.labelKey) : key;
  };

  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('daily_jobsite');
  const [logsByDate, setLogsByDate] = useState({});
  const [expandedDate, setExpandedDate] = useState(null);
  // 'ok' | 'offline' | 'error' — how the LAST server read went. This is the
  // whole point of the screen: a failed read must NEVER render as "No
  // Submitted Logs", which tells a DOB inspector no compliance records exist.
  const [fetchState, setFetchState] = useState('ok');

  // Inspector Mode — plain toggle, no PIN. Releasing it restores full
  // navigation and drops the device back on the site dashboard.
  const handleExitInspector = async () => {
    await unlock();
    router.replace('/site');
  };

  useEffect(() => {
    if (authLoading) return;
    if (!isAuthenticated) {
      router.replace('/login');
    } else if (!siteMode) {
      router.replace('/');
    }
  }, [isAuthenticated, authLoading, siteMode]);

  useEffect(() => {
    if (isAuthenticated && siteMode && siteProject?.id) {
      fetchLogbooks();
    }
  }, [isAuthenticated, siteMode, siteProject]);

  // ===========================================================================
  //  LIST — cache-first, and a failed read NEVER empties the screen
  // ===========================================================================

  const scopeKey = siteProject?.id ? `site_logbooks:${siteProject.id}` : '';

  // cacheDocList only stores arrays, so the {date: logs} map round-trips as an
  // array of {date, logs} entries.
  const datesToList = (dates) => Object.entries(dates || {})
    .map(([date, logs]) => ({ date, logs: Array.isArray(logs) ? logs : [] }))
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, CACHE_DATE_LIMIT);

  const listToDates = (list) => {
    const out = {};
    for (const entry of (Array.isArray(list) ? list : [])) {
      if (entry?.date && Array.isArray(entry.logs)) out[entry.date] = entry.logs;
    }
    return out;
  };

  // Inline activity photos are base64 blobs — megabytes each. If the full
  // write is rejected, drop them and keep the compliance TEXT, which is what
  // an inspector is actually reading.
  const stripPhotoBlobs = (list) => list.map((entry) => ({
    date: entry.date,
    logs: (entry.logs || []).map((log) => {
      const activities = log?.data?.activities;
      if (!Array.isArray(activities)) return log;
      return {
        ...log,
        data: {
          ...log.data,
          activities: activities.map((act) => (
            Array.isArray(act?.photos)
              ? { ...act, photos: act.photos.map(({ base64, ...rest }) => rest) }
              : act
          )),
        },
      };
    }),
  }));

  const writeListThrough = async (list) => {
    if (await cacheDocList(scopeKey, list)) return;
    await cacheDocList(scopeKey, stripPhotoBlobs(list));
  };

  const flattenLogs = (dates) => Object.values(dates || {}).flat();

  // Immutable once submitted, but an amendment bumps updated_at — key the
  // cached bytes on it so a corrected record re-downloads instead of serving
  // a stale PDF.
  const pdfVersion = (log) => String(log?.updated_at || log?.submitted_at || log?.created_at || '0');

  // 🔒 Relative API paths only. The JWT rides in the Authorization HEADER
  // (docCache does this), never in a URL — a URL-borne token leaks into
  // browser history, the share sheet and crash logs.
  const logPdfPath = (logbookId) => `/api/reports/logbook/${logbookId}/pdf`;
  const dayPdfPath = (date) => `/api/reports/project/${siteProject?.id}/date/${date}/pdf`;

  const fetchLogbooks = async () => {
    setLoading(true);

    // 1. CACHE FIRST — paint whatever this device already holds before the
    //    network is touched, so a dead zone shows records immediately.
    const cachedDates = listToDates(await readCachedDocList(scopeKey));
    if (Object.keys(cachedDates).length > 0) {
      setLogsByDate(cachedDates);
      setLoading(false);
    }

    // 2. Then refresh. On failure we KEEP the cached list — the old
    //    `setLogsByDate({})` was the bug: offline it rendered a confident
    //    "No Submitted Logs" to a DOB inspector.
    const r = await settleFetch(() => logbooksAPI.getSubmitted(siteProject.id));
    setFetchState(r.status);

    if (r.status === 'ok') {
      const dates = r.data?.dates || {};
      setLogsByDate(dates);
      const list = datesToList(dates);
      writeListThrough(list).catch(() => {});

      // 3. Fire-and-forget: put each submitted log's PDF on disk so the
      //    bytes are here in the dead zone. NOT awaited — never on the
      //    render path.
      const submitted = flattenLogs(dates).filter(l => l.status === 'submitted' && (l.id || l._id));
      warmDocCache(submitted, {
        idOf: (l) => l.id || l._id,
        versionOf: pdfVersion,
        urlOf: (l) => logPdfPath(l.id || l._id),
      }).catch(() => {});
    } else {
      console.warn(
        `Logbooks load ${r.status} — keeping ${Object.keys(cachedDates).length} cached date(s)`,
        r.error,
      );
    }

    setLoading(false);
  };

  // ===========================================================================
  //  PDF handlers — local file only, no token in any URL
  // ===========================================================================

  const notify = (type, title, message) => {
    if (toast && typeof toast[type] === 'function') toast[type](title, message);
    else console.warn(`${title}: ${message}`);
  };

  // Hand the OS a LOCAL file. iOS previews a file:// PDF directly; Android
  // goes through expo-sharing's FileProvider. Nothing token-bearing leaves
  // the app.
  const openLocalPdf = async (uri, filename) => {
    const Sharing = require('expo-sharing');
    if (await Sharing.isAvailableAsync()) {
      await Sharing.shareAsync(uri, {
        mimeType: 'application/pdf', UTI: 'com.adobe.pdf', dialogTitle: filename,
      });
      return true;
    }
    if (Platform.OS === 'ios') {
      await Linking.openURL(uri);
      return true;
    }
    return false;
  };

  const handleViewLogPdf = async (log, date) => {
    const logbookId = log?.id || log?._id;
    if (!logbookId) return;
    try {
      const local = await ensureCachedDocFile({
        fileId: logbookId,
        cacheVersion: pdfVersion(log),
        remoteUrl: logPdfPath(logbookId),
      });
      if (!local) {
        notify('warning', 'PDF not on this device',
          'This PDF has not been saved here yet — reconnect to download it. The record itself is shown above.');
        return;
      }
      // ⚠️ ANDROID LIMIT — see ANDROID_OFFLINE_PDF_MSG.
      if (Platform.OS === 'android' && fetchState === 'offline') {
        notify('info', 'Saved on this device', ANDROID_OFFLINE_PDF_MSG);
        return;
      }
      const filename = `LeveLog_${log.log_type || 'log'}_${log.date || date}.pdf`;
      if (!(await openLocalPdf(local, filename))) {
        notify('warning', 'Cannot open PDF here', ANDROID_OFFLINE_PDF_MSG);
      }
    } catch (e) {
      console.error('PDF open failed:', e);
      notify('error', 'Could not open PDF', 'The record is shown above.');
    }
  };

  const handleShareLogPdf = async (log, date) => {
    const logbookId = log?.id || log?._id;
    if (!logbookId) return;
    try {
      const local = await ensureCachedDocFile({
        fileId: logbookId,
        cacheVersion: pdfVersion(log),
        remoteUrl: logPdfPath(logbookId),
      });
      if (!local) {
        notify('warning', 'PDF not on this device', 'Reconnect to download this PDF before sharing it.');
        return;
      }
      const filename = `LeveLog_${log.log_type || 'log'}_${log.date || date}.pdf`;
      if (!(await openLocalPdf(local, filename))) {
        notify('warning', 'Sharing unavailable', 'This device cannot share files.');
      }
    } catch (e) {
      console.error('PDF share failed:', e);
      notify('error', 'Could not share PDF', 'The record is shown above.');
    }
  };

  const handleCombinedPdf = async (date) => {
    if (!siteProject?.id) return;
    try {
      // The full-day report is generated server-side, so offline it exists
      // only if a previous open cached it. Same header auth, same local open.
      // Version it on the newest log of the day so an amendment re-downloads.
      const dayVersion = (logsByDate?.[date] || []).map(pdfVersion).sort().pop() || date;
      const local = await ensureCachedDocFile({
        fileId: `day_${siteProject.id}_${date}`,
        cacheVersion: dayVersion,
        remoteUrl: dayPdfPath(date),
      });
      if (!local) {
        notify('warning', 'Full day report unavailable offline',
          'This combined report is built on the server — reconnect to generate it. The individual records are shown below.');
        return;
      }
      if (Platform.OS === 'android' && fetchState === 'offline') {
        notify('info', 'Saved on this device', ANDROID_OFFLINE_PDF_MSG);
        return;
      }
      if (!(await openLocalPdf(local, `LeveLog_FullDay_${date}.pdf`))) {
        notify('warning', 'Cannot open PDF here', ANDROID_OFFLINE_PDF_MSG);
      }
    } catch (e) {
      console.error('Combined PDF failed:', e);
      notify('error', 'Could not open report', 'The individual records are shown below.');
    }
  };

  // Filter logs by active tab
  const filteredDates = {};
  for (const [date, logs] of Object.entries(logsByDate)) {
    const matching = logs.filter(l => l.log_type === activeTab);
    if (matching.length > 0) {
      filteredDates[date] = matching;
    }
  }

  const sortedDates = Object.keys(filteredDates).sort((a, b) => b.localeCompare(a));
  // Records actually on screen for this tab — what the offline banner reports.
  const visibleLogCount = Object.values(filteredDates).reduce((n, logs) => n + logs.length, 0);

  const formatDate = (dateStr) => {
    try {
      return new Date(dateStr + 'T12:00:00').toLocaleDateString('en-US', {
        weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
      });
    } catch {
      return dateStr;
    }
  };

  // ===========================================================================
  //  Helper components for full document rendering
  // ===========================================================================

  const SignatureBlock = ({ signature, label }) => {
    if (!signature) return null;
    let base64Data = null;
    let signerName = '';
    if (typeof signature === 'string') {
      base64Data = signature;
    } else if (typeof signature === 'object') {
      base64Data = signature.data || signature.paths || null;
      signerName = signature.signer_name || '';
    }
    return (
      <View style={{ marginTop: spacing.sm }}>
        <Text style={{ fontSize: 14, fontWeight: '700', color: colors.text.muted, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>
          {label}{signerName ? ` — ${signerName}` : ''}
        </Text>
        {base64Data && typeof base64Data === 'string' ? (
          <Image
            source={{ uri: base64Data.startsWith('data:') ? base64Data : `data:image/png;base64,${base64Data}` }}
            style={{ width: 200, height: 60, borderRadius: 6, borderWidth: 1, borderColor: withAlpha('#ffffff', 0.1), backgroundColor: withAlpha('#ffffff', 0.05) }}
            resizeMode="contain"
          />
        ) : signerName ? (
          <Text style={{ fontSize: 15, color: colors.text.secondary, fontStyle: 'italic' }}>{signerName} (signed)</Text>
        ) : null}
      </View>
    );
  };

  const DocInfoRow = ({ icon: Icon, text }) => (
    <View style={s.docInfoRow}>
      {Icon ? <Icon size={16} strokeWidth={1.5} color={colors.text.muted} /> : null}
      <Text style={s.docInfoText}>{text}</Text>
    </View>
  );

  const DocSectionLabel = ({ icon: Icon, label, color }) => (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.xs, marginTop: spacing.md, marginBottom: spacing.xs }}>
      {Icon && <Icon size={16} strokeWidth={1.5} color={color || colors.text.muted} />}
      <Text style={{ fontSize: 14, fontWeight: '700', color: color || colors.text.muted, textTransform: 'uppercase', letterSpacing: 0.5 }}>{label}</Text>
    </View>
  );

  const DocTableRow = ({ cells, isHeader }) => (
    <View style={{
      flexDirection: 'row',
      borderBottomWidth: 1,
      borderBottomColor: isHeader ? withAlpha('#ffffff', 0.12) : withAlpha('#ffffff', 0.04),
      paddingVertical: isHeader ? spacing.sm : spacing.sm,
      backgroundColor: isHeader ? withAlpha('#ffffff', 0.04) : 'transparent',
    }}>
      {cells.map((cell, i) => (
        <Text key={i} style={{
          flex: cell.flex || 1,
          fontSize: isHeader ? 14 : 16,
          fontWeight: isHeader ? '700' : '400',
          color: isHeader ? colors.text.muted : colors.text.secondary,
          textTransform: isHeader ? 'uppercase' : 'none',
          letterSpacing: isHeader ? 0.5 : 0,
          paddingHorizontal: spacing.sm,
        }} numberOfLines={3}>
          {cell.text}
        </Text>
      ))}
    </View>
  );

  // ===========================================================================
  //  FULL DOCUMENT RENDERERS
  // ===========================================================================

  const renderDailyJobsite = (log) => {
    const data = log.data || {};
    const activities = data.activities || [];
    const equipmentOnSite = data.equipment_on_site || {};
    const checklistItems = data.checklist_items || {};
    const observations = data.observations || [];
    const visitorsDeliveries = data.visitors_deliveries || '';
    const equipList = Object.entries(equipmentOnSite).filter(([_, v]) => v).map(([k]) => k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())).join(', ');
    const checkList = Object.entries(checklistItems).filter(([_, v]) => v).map(([k]) => k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())).join(', ');

    return (
      <View style={s.docContent}>
        <View style={s.docInfoBox}>
          {data.project_address && <DocInfoRow icon={MapPin} text={data.project_address} />}
          <DocInfoRow icon={CloudSun} text={`${data.weather || 'N/A'} ${data.weather_temp || ''}${data.weather_wind ? ` — Wind: ${data.weather_wind}` : ''}`} />
          {(data.time_in || data.time_out) && <DocInfoRow icon={Clock} text={`Time In: ${data.time_in || 'N/A'}  |  Time Out: ${data.time_out || 'N/A'}`} />}
          {data.areas_visited && <DocInfoRow icon={Eye} text={`Areas Visited: ${data.areas_visited}`} />}
        </View>

        {data.general_description && (
          <>
            <DocSectionLabel icon={FileText} label="General Description" color="#3b82f6" />
            <Text style={s.docParagraph}>{data.general_description}</Text>
          </>
        )}

        {activities.length > 0 && (
          <>
            <DocSectionLabel icon={Wrench} label="Activity Details" color="#3b82f6" />
            <DocTableRow isHeader cells={[
              { text: 'Crew / Company', flex: 1.5 }, { text: 'Workers', flex: 0.6 },
              { text: 'Description', flex: 2 }, { text: 'Location', flex: 1 },
            ]} />
            {activities.map((act, i) => (
              <React.Fragment key={i}>
                <DocTableRow cells={[
                  // crew_id, NOT crew_name — the CP types a crew IDENTIFIER
                  // (daily_jobsite.jsx EMPTY_ACTIVITY `crew_id`, auto-seeded
                  // C1/C2/...). crew_name has no writer anywhere in the repo,
                  // so this cell showed company only on every record.
                  { text: `${act.crew_id || ''} ${act.company || 'Unknown'}`.trim(), flex: 1.5 },
                  { text: String(act.num_workers || 0), flex: 0.6 },
                  { text: act.work_description || 'N/A', flex: 2 },
                  { text: act.work_locations || 'N/A', flex: 1 },
                ]} />
                {(act.photos || []).length > 0 && (
                  <View style={s.photoRow}>
                    {act.photos.map((photo, pi) => {
                      const uri = logbookPhotoUri(photo, log, i, pi);
                      if (!uri) return null;
                      return <Image key={pi} source={{ uri }} style={s.activityPhoto} resizeMode="cover" />;
                    })}
                  </View>
                )}
              </React.Fragment>
            ))}
          </>
        )}

        {equipList ? (<><DocSectionLabel icon={Wrench} label="Equipment on Site" color={semantic.neutral} /><Text style={s.docParagraph}>{equipList}</Text></>) : null}
        {checkList ? (<><DocSectionLabel icon={ShieldCheck} label="Inspected" color={semantic.neutral} /><Text style={s.docParagraph}>{checkList}</Text></>) : null}

        {observations.length > 0 && observations.some(o => o.description?.trim()) && (
          <>
            <DocSectionLabel icon={AlertTriangle} label="Safety Observations" color={semantic.neutral} />
            <DocTableRow isHeader cells={[{ text: 'Description', flex: 2 }, { text: 'Responsible', flex: 1 }, { text: 'Remedy', flex: 1.5 }]} />
            {observations.filter(o => o.description?.trim()).map((obs, i) => (
              <DocTableRow key={i} cells={[{ text: obs.description || '', flex: 2 }, { text: obs.responsible_party || '', flex: 1 }, { text: obs.remedy || '', flex: 1.5 }]} />
            ))}
          </>
        )}

        {visitorsDeliveries ? (<><DocSectionLabel icon={Truck} label="Visitors / Deliveries" color="#8b5cf6" /><Text style={s.docParagraph}>{visitorsDeliveries}</Text></>) : null}

        <View style={s.signatureSection}>
          <View style={s.signatureDivider} />
          <SignatureBlock signature={log.cp_signature} label="Competent Person (CP)" />
          {log.cp_name && !log.cp_signature && <Text style={s.signedByName}>CP: {log.cp_name}</Text>}
          <SignatureBlock signature={data.superintendent_signature} label="Superintendent" />
        </View>
      </View>
    );
  };

  const renderToolboxTalk = (log) => {
    const data = log.data || {};
    const topics = data.checked_topics || {};
    const topicList = Object.entries(topics).filter(([_, v]) => v).map(([k]) => k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()));
    const attendees = data.attendees || [];
  // `added_from` — see backend/server.py:_attendee_source_label. Only the two
  // CP-asserted provenances mark; 'gate' and an absent value do not.
  const cpAdded = (a) => a && (a.added_from === 'weekly_gap' || a.added_from === 'manual');

    return (
      <View style={s.docContent}>
        <View style={s.docInfoBox}>
          {data.location && <DocInfoRow icon={MapPin} text={`Location: ${data.location}`} />}
          {data.company_name && <DocInfoRow icon={Building2} text={`Company: ${data.company_name}`} />}
          {data.performed_by && <DocInfoRow icon={Users} text={`Performed By: ${data.performed_by}`} />}
          {data.meeting_time && <DocInfoRow icon={Clock} text={`Time: ${data.meeting_time}`} />}
        </View>

        <DocSectionLabel icon={BookOpen} label={`Topics (${topicList.length})`} color="#8b5cf6" />
        {topicList.length > 0 ? (
          <View style={s.topicChips}>
            {topicList.map((topic, i) => (
              <View key={i} style={s.topicChip}>
                <CheckCircle size={10} strokeWidth={2} color="#8b5cf6" />
                <Text style={s.topicChipText}>{topic}</Text>
              </View>
            ))}
          </View>
        ) : <Text style={s.docParagraph}>None</Text>}

        <DocSectionLabel icon={Users} label={`Attendees (${attendees.length})`} color="#8b5cf6" />
        {attendees.length > 0 && (
          <>
            {/* ROSTER, not a worker attestation. "Present" is a CP-marked
                boolean — workers are not required to sign a toolbox talk. The
                CP signature over this roster is the legal attestation
                (NYC DOB §3301.12.3 / OSHA 29 CFR 1926.21). The column used to
                read "Signed", which told an inspector the opposite. */}
            <DocTableRow isHeader cells={[{ text: 'Name', flex: 1.5 }, { text: 'Title', flex: 1 }, { text: 'Company', flex: 1 }, { text: 'In', flex: 0.8 }, { text: 'Present', flex: 0.7 }]} />
            {attendees.map((a, i) => (
              <DocTableRow key={i} cells={[{ text: `${a.name || 'Unknown'}${a.gate_confirmed ? ' †' : ''}${cpAdded(a) ? ' ‡' : ''}`, flex: 1.5 }, { text: a.title || '—', flex: 1 }, { text: a.company || '', flex: 1 }, { text: rosterClock(a.time), flex: 0.8 }, { text: a.signed ? '✓' : '—', flex: 0.7 }]} />
            ))}
            {/* The PDF carries gate-confirm as its own column; this phone-width
                viewer would be unreadable at 6 columns, so it rides as a dagger
                on the name with a legend. Same data either way. */}
            {attendees.some(a => a.gate_confirmed) && (
              <Text style={s.rosterLegend}>
                † Confirmed attending at gate check-in (optional; not a required signature)
              </Text>
            )}
            {/* WHOSE CLAIM PUT HIM HERE. The gate saying a man was on site and
                the CP saying a man attended are different assertions, and a
                roster that renders them identically is the stronger one lending
                its authority to the weaker.

                COMPRESSED TO A MARKER, for the same reason gate-confirm is: at
                phone width this table cannot carry a sixth column. The PDF
                splits `weekly_gap` from `manual` in its own column; here they
                share one mark, because the distinction that matters on a
                narrow screen is gate-versus-CP. A row filed before the field
                existed carries no mark — we do not know, and guessing would be
                the false confidence this exists to remove. */}
            {attendees.some(cpAdded) && (
              <Text style={s.rosterLegend}>
                ‡ Added by the CP — not a gate check-in today
              </Text>
            )}
          </>
        )}

        {attendees.some(a => a.worker_signature || a.signature) && (
          <>
            <DocSectionLabel icon={Pen} label="Worker Signatures" color={semantic.neutral} />
            <View style={s.workerSigGrid}>
              {attendees.filter(a => a.worker_signature || a.signature).map((a, i) => (
                <View key={i} style={s.workerSigCard}>
                  <Text style={s.workerSigName}>{a.name || 'Unknown'}</Text>
                  <Image
                    source={{ uri: (a.worker_signature || a.signature || '').startsWith('data:') ? (a.worker_signature || a.signature) : `data:image/png;base64,${a.worker_signature || a.signature}` }}
                    style={s.workerSigImage} resizeMode="contain"
                  />
                </View>
              ))}
            </View>
          </>
        )}

        <View style={s.signatureSection}>
          <View style={s.signatureDivider} />
          <SignatureBlock signature={log.cp_signature} label="Competent Person (CP)" />
          {log.cp_name && !log.cp_signature && <Text style={s.signedByName}>CP: {log.cp_name}</Text>}
        </View>
      </View>
    );
  };

  const renderPreshiftSignin = (log) => {
    const data = log.data || {};
    const workers = (data.workers || []).filter(w => w.name?.trim());

    return (
      <View style={s.docContent}>
        <View style={s.docInfoBox}>
          {data.company && <DocInfoRow icon={Building2} text={`Company: ${data.company}`} />}
          {data.project_location && <DocInfoRow icon={MapPin} text={`Location: ${data.project_location}`} />}
          <DocInfoRow icon={Users} text={`Total Workers: ${data.total_count || workers.length}`} />
        </View>

        <DocSectionLabel icon={Users} label={`Workers (${workers.length})`} color={semantic.neutral} />
        {workers.length > 0 && (
          <>
            <DocTableRow isHeader cells={[
              { text: 'Name', flex: 1.5 }, { text: 'Company', flex: 1 }, { text: 'OSHA #', flex: 0.8 },
              { text: 'Injury', flex: 0.5 }, { text: 'PPE', flex: 0.5 },
            ]} />
            {workers.map((w, i) => (
              <DocTableRow key={i} cells={[
                { text: w.name || '', flex: 1.5 }, { text: w.company || '', flex: 1 },
                { text: w.osha_number || 'N/A', flex: 0.8 }, { text: w.had_injury || '—', flex: 0.5 },
                { text: w.inspected_ppe || '—', flex: 0.5 },
              ]} />
            ))}
          </>
        )}

        {workers.some(w => w.worker_signature) && (
          <>
            <DocSectionLabel icon={Pen} label="Worker Signatures" color={semantic.neutral} />
            <View style={s.workerSigGrid}>
              {workers.filter(w => w.worker_signature).map((w, i) => (
                <View key={i} style={s.workerSigCard}>
                  <Text style={s.workerSigName}>{w.name}</Text>
                  <Image
                    source={{ uri: w.worker_signature.startsWith('data:') ? w.worker_signature : `data:image/png;base64,${w.worker_signature}` }}
                    style={s.workerSigImage} resizeMode="contain"
                  />
                </View>
              ))}
            </View>
          </>
        )}

        {workers.some(w => !w.worker_signature) && (
          <View style={s.unsignedBlock}>
            <Text style={s.unsignedLabel}>Not Signed: </Text>
            <Text style={s.unsignedNames}>{workers.filter(w => !w.worker_signature).map(w => w.name).join(', ')}</Text>
          </View>
        )}

        <View style={s.signatureSection}>
          <View style={s.signatureDivider} />
          <SignatureBlock signature={log.cp_signature} label="Competent Person (CP)" />
          {log.cp_name && !log.cp_signature && <Text style={s.signedByName}>CP: {log.cp_name}</Text>}
        </View>
      </View>
    );
  };

  // ===========================================================================
  //  THE OTHER EIGHT TYPES
  //
  //  These fell through to a literal "No data available", so the record a DOB
  //  inspector opened on the site device was BLANK for hot work, crane,
  //  excavation, concrete, scaffold, the SSC daily log, the OSHA/SST log and
  //  subcontractor orientation. Payload keys come from the editor that writes
  //  each one (cited per renderer) and match the PDF renderer
  //  (server.py generate_single_logbook_html) key for key.
  // ===========================================================================

  // ABSENT IS STATED, NEVER IMPLIED. A key the CP never filled renders
  // "— Not recorded" — the same words the PDF/report surface already prints
  // for the same fact (server.py generate_combined_report). One record must
  // not read differently on two compliance surfaces, and a blank is ambiguous:
  // an inspector cannot tell whether the field was never asked or asked and
  // left unanswered.
  //
  // TWO KINDS OF ABSENCE, and they are NOT the same:
  //   (a) a FIELD missing from a section that IS rendered -> "— Not recorded"
  //   (b) a ROW missing from a repeating list (load_entries,
  //       adjacent_buildings, slump_tests, osha entries) -> DROPPED. A row
  //       that does not exist is not an unrecorded field, and printing one
  //       would invent a record of work nobody logged.
  // A whole SECTION whose payload is entirely absent stays absent too.
  //
  // false and 0 ARE captured values and do render.
  const hasVal = (d, key) => {
    if (!d || typeof d !== 'object' || !(key in d)) return false;
    const v = d[key];
    if (typeof v === 'boolean') return true;
    if (v === null || v === undefined) return false;
    if (typeof v === 'string') return v.trim() !== '';
    if (Array.isArray(v)) return v.length > 0;
    if (typeof v === 'object') return Object.keys(v).length > 0;
    return true;
  };

  // Booleans render as glyphs, matching the attendee "Present" column above —
  // and sidestepping a Yes/No pair whose Spanish "No" is the English word.
  const flag = (v) => (v ? '✓' : '✕');

  // Fallback label for a map key with no entry in the label list. A snake_case
  // key is title-cased; anything else is rendered VERBATIM — the kiosk keys its
  // orientation checklist by the item's full English sentence
  // (backend/checkin.html:674-687), and title-casing a sentence mangles it.
  const keyLabel = (k) => {
    const str = String(k);
    return (str.includes('_') || !str.includes(' '))
      ? str.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
      : str;
  };

  // Info rows for every field on the form, in the order given. Case (a): a key
  // the CP never filled still gets its row, reading "— Not recorded", so an
  // inspector can see WHICH questions went unanswered. The exception is the
  // whole-section case — if not one spec is on the document there is no
  // section to annotate and the box is not rendered at all.
  const DocFields = ({ data, specs }) => {
    if (!specs.some(([key]) => hasVal(data, key))) return null;
    return (
      <View style={s.docInfoBox}>
        {specs.map(([key, label, fmt]) => (
          <DocInfoRow
            key={key}
            text={`${label}: ${hasVal(data, key)
              ? (fmt ? fmt(data[key]) : data[key])
              : t('fNotRecorded')}`}
          />
        ))}
      </View>
    );
  };

  // A sparse toggle map over a FIXED checklist — case (a). The editors seed
  // these as {} and write a key only once the CP taps it, so `present and
  // false` is an explicit no while `absent` is untouched: an untouched item
  // reads "— Not recorded", never a silent ✕. An absent or empty map is a
  // whole absent section and renders nothing.
  //
  // The full checklist is only asserted once the map is keyed the way the
  // in-app editor keys it. The kiosk keys its orientation checklist by the
  // item's full English SENTENCE (backend/checkin.html:674-687), so a map
  // carrying none of the known keys renders only what it carries.
  const ToggleTable = ({ map, items, title, colLabel, icon }) => {
    if (!map || typeof map !== 'object' || Array.isArray(map)) return null;
    const labels = Object.fromEntries(items);
    const known = new Set(items.map(([k]) => k));
    const anyKnown = items.some(([k]) => k in map);
    const order = (anyKnown ? items.map(([k]) => k) : [])
      .concat(Object.keys(map).filter((k) => !known.has(k)));
    if (order.length === 0) return null;
    return (
      <>
        <DocSectionLabel icon={icon || ShieldCheck} label={title} color={semantic.neutral} />
        <DocTableRow isHeader cells={[{ text: colLabel, flex: 3 }, { text: t('fConfirmed'), flex: 0.8 }]} />
        {order.map((k) => (
          <DocTableRow key={k} cells={[
            { text: labels[k] || keyLabel(k), flex: 3 },
            { text: k in map ? flag(map[k]) : t('fNotRecorded'), flex: 0.8 },
          ]} />
        ))}
      </>
    );
  };

  // A row list — case (b). An entirely untouched EMPTY_* seed row is DROPPED
  // rather than rendered as a line of "— Not recorded": a row that does not
  // exist is not an unrecorded field. Inside a row that DOES exist, a missing
  // cell stays empty — the row itself is the record.
  const RowTable = ({ title, icon, headers, rows }) => {
    if (!rows.length) return null;
    return (
      <>
        <DocSectionLabel icon={icon} label={title} color={semantic.neutral} />
        <DocTableRow isHeader cells={headers} />
        {rows.map((cells, i) => <DocTableRow key={i} cells={cells} />)}
      </>
    );
  };

  const CpSignature = ({ log, label }) => (
    <View style={s.signatureSection}>
      <View style={s.signatureDivider} />
      <SignatureBlock signature={log.cp_signature} label={label || 'Competent Person (CP)'} />
      {log.cp_name && !log.cp_signature && <Text style={s.signedByName}>CP: {log.cp_name}</Text>}
    </View>
  );

  // frontend/app/logbooks/hot_work.jsx:189-199 (save); PRECAUTION_ITEMS :28-36
  const renderHotWork = (log) => {
    const data = log.data || {};
    const specs = [
      ['work_type', t('hwWorkType')],
      ['location', t('fLocation')],
      ['worker_name', t('fWorker')],
      ['worker_cert_number', t('hwWorkerCert')],
      ['start_time', t('hwStart')],
      ['end_time', t('hwEnd')],
      ['fire_watch_name', t('hwFireWatch')],
      // The editor captures NO real fire-watch end time — it DERIVES this as
      // work end + 30 min (hotWorkModel.calcFireWatchEnd). FDNY can require 60, so it is
      // labelled as the computed default rather than asserted as recorded.
      ['fire_watch_end_time', t('hwFireWatchUntil'), (v) => `${v} ${t('hwFireWatchDefault')}`],
    ];
    return (
      <View style={s.docContent}>
        <DocFields data={data} specs={specs} />
        <ToggleTable
          map={data.precautions}
          items={[
            ['area_cleared', t('p_area_cleared')],
            ['fire_extinguisher_present', t('p_fire_extinguisher_present')],
            ['sprinklers_operational', t('p_sprinklers_operational')],
            ['combustibles_covered', t('p_combustibles_covered')],
            ['fire_watch_assigned', t('p_fire_watch_assigned')],
            ['ventilation_adequate', t('p_ventilation_adequate')],
            ['permit_posted', t('p_permit_posted')],
          ]}
          title={t('hwPrecautions')}
          colLabel={t('hwPrecaution')}
          icon={AlertTriangle}
        />
        <CpSignature log={log} />
      </View>
    );
  };

  // src/utils/craneOperationsModel.js — draftBody decides the payload shape,
  // PRE_OP_CHECKLIST_ITEMS the fifteen keys, EMPTY_LOAD_ENTRY the lift row.
  // The keys below are asserted against that model by
  // src/utils/portedFormPayloads.test.cjs.
  const renderCraneOperations = (log) => {
    const data = log.data || {};
    // load_weight / radius are unit-less strings as the operator typed them —
    // the editor captures no unit, so none is shown.
    const lifts = (data.load_entries || [])
      .filter((le) => le && ['time', 'description', 'load_weight', 'radius'].some((k) => hasVal(le, k)))
      .map((le) => [
        { text: le.time || '', flex: 0.8 },
        { text: le.description || '', flex: 2 },
        { text: le.load_weight || '', flex: 1 },
        { text: le.radius || '', flex: 0.8 },
      ]);
    return (
      <View style={s.docContent}>
        <DocFields data={data} specs={[
          ['crane_type', t('crType')],
          ['crane_id', t('crId')],
          ['operator_name', t('crOperator')],
          ['operator_license', t('crLicense')],
        ]} />
        <ToggleTable
          map={data.pre_operation_checklist}
          items={[
            ['wire_ropes', t('c_wire_ropes')],
            ['hooks_latches', t('c_hooks_latches')],
            ['brakes', t('c_brakes')],
            ['outriggers', t('c_outriggers')],
            ['load_chart', t('c_load_chart')],
            ['boom_condition', t('c_boom_condition')],
            ['anti_two_block', t('c_anti_two_block')],
            ['fire_extinguisher', t('c_fire_extinguisher')],
            ['signals_reviewed', t('c_signals_reviewed')],
            ['area_barricaded', t('c_area_barricaded')],
            ['wind_speed_checked', t('c_wind_speed_checked')],
            ['power_lines_clear', t('c_power_lines_clear')],
            ['load_weight_known', t('c_load_weight_known')],
            ['rigging_inspected', t('c_rigging_inspected')],
            ['swing_radius_clear', t('c_swing_radius_clear')],
          ]}
          title={t('crPreOp')}
          colLabel={t('fItem')}
        />
        <RowTable
          title={t('crLiftLog')}
          icon={Truck}
          headers={[
            { text: t('fTime'), flex: 0.8 }, { text: t('fDescription'), flex: 2 },
            { text: t('crLoadWeight'), flex: 1 }, { text: t('crRadius'), flex: 0.8 },
          ]}
          rows={lifts}
        />
        <CpSignature log={log} />
      </View>
    );
  };

  // src/utils/excavationMonitoringModel.js — draftBody decides the payload
  // shape and is the ONE place `delta` and vibration_over_threshold are
  // derived. The keys below are asserted against that model by
  // src/utils/portedFormPayloads.test.cjs.
  const renderExcavationMonitoring = (log) => {
    const data = log.data || {};
    const thr = String(data.vibration_threshold || '').trim();
    const cur = String(data.vibration_current || '').trim();
    // The over-threshold flag is only meaningful ALONGSIDE a reading. Without
    // both readings the STATUS reads "— Not recorded" — a bare "Within
    // threshold" over no measurement is a finding the CP never made. With
    // NEITHER reading there is no vibration section to annotate at all.
    const showStatus = !!thr && !!cur && hasVal(data, 'vibration_over_threshold');
    // Units and per-reading timestamps are NOT captured, so no unit rides in
    // the headers and there is no time column.
    const points = (data.adjacent_buildings || [])
      .filter((b) => b && ['address', 'baseline_reading', 'current_reading', 'delta'].some((k) => hasVal(b, k)))
      .map((b) => [
        { text: b.address || '', flex: 1.6 },
        { text: b.baseline_reading || '', flex: 1 },
        { text: b.current_reading || '', flex: 1 },
        { text: b.delta || '', flex: 1 },
      ]);
    return (
      <View style={s.docContent}>
        <DocFields data={data} specs={[
          ['excavation_depth', t('exDepth')],
          ['soil_type', t('exSoil')],
          ['protection_system', t('exProtection')],
          ['groundwater_observed', t('exGroundwater'), flag],
          ['atmospheric_testing', t('exAtmospheric'), flag],
        ]} />
        {(!!thr || !!cur) && (
          <>
            <DocSectionLabel icon={AlertTriangle} label={t('exVibration')} color={semantic.neutral} />
            <View style={s.docInfoBox}>
              <DocInfoRow text={`${t('exThreshold')}: ${thr || t('fNotRecorded')}`} />
              <DocInfoRow text={`${t('exCurrent')}: ${cur || t('fNotRecorded')}`} />
              <DocInfoRow text={`${t('fStatus')}: ${showStatus
                ? (data.vibration_over_threshold ? t('exOver') : t('exWithin'))
                : t('fNotRecorded')}`}
              />
            </View>
          </>
        )}
        <RowTable
          title={t('exPoints')}
          icon={MapPin}
          headers={[
            { text: t('fLocation'), flex: 1.6 }, { text: t('exBaseline'), flex: 1 },
            { text: t('exCurrent'), flex: 1 }, { text: t('exMovement'), flex: 1 },
          ]}
          rows={points}
        />
        <CpSignature log={log} />
      </View>
    );
  };

  // src/utils/concreteOperationsModel.js — draftBody decides the payload
  // shape, FORMWORK_ITEMS the four keys, EMPTY_SLUMP_TEST the slump row.
  // The keys below are asserted against that model by
  // src/utils/portedFormPayloads.test.cjs.
  const renderConcreteOperations = (log) => {
    const data = log.data || {};
    // `pass` is TRI-STATE (EMPTY_SLUMP_TEST seeds it null). Null renders as
    // nothing — never as a Fail the CP did not record.
    const slumps = (data.slump_tests || [])
      .filter((st) => st && (String(st.time || '').trim() || String(st.value || '').trim() || st.pass !== null && st.pass !== undefined))
      .map((st) => [
        { text: st.time || '', flex: 1 },
        { text: st.value || '', flex: 1 },
        { text: st.pass === true ? t('coPass') : st.pass === false ? t('coFail') : '', flex: 1 },
      ]);
    return (
      <View style={s.docContent}>
        <DocFields data={data} specs={[
          ['pour_location', t('coPour')],
          ['concrete_supplier', t('coSupplier')],
          ['mix_design', t('coMix')],
          // volume_ordered / temperature are unit-less as entered.
          ['volume_ordered', t('coVolume')],
          ['weather_conditions', t('fWeather')],
          ['temperature', t('fTemperature')],
        ]} />
        <RowTable
          title={t('coSlumpTests')}
          icon={ClipboardList}
          headers={[
            { text: t('fTime'), flex: 1 }, { text: t('coSlump'), flex: 1 },
            { text: t('coResult'), flex: 1 },
          ]}
          rows={slumps}
        />
        <ToggleTable
          map={data.formwork_checklist}
          items={[
            ['shores_plumb', t('fw_shores_plumb')],
            ['bracing_adequate', t('fw_bracing_adequate')],
            ['formwork_clean', t('fw_formwork_clean')],
            ['no_gaps', t('fw_no_gaps')],
          ]}
          title={t('coFormwork')}
          colLabel={t('fItem')}
        />
        <CpSignature log={log} />
      </View>
    );
  };

  // frontend/app/logbooks/scaffold_maintenance.jsx:194
  //   const data = { general_info: generalInfo, answers };
  // GENERAL_INFO_FIELDS :27-36 (+ shed_type :38/:89); MAINTENANCE_QUESTIONS
  // :41-61; ANSWER_OPTIONS :63 = YES / NO / N/A
  const SCAFFOLD_QUESTIONS = () => [
    ['signs_on_parapets', t('q_signs_on_parapets')],
    ['base_plates_mudsills', t('q_base_plates_mudsills')],
    ['scaffold_pins_bolts', t('q_scaffold_pins_bolts')],
    ['legs_poles_plumb', t('q_legs_poles_plumb')],
    ['tie_ins_spaced', t('q_tie_ins_spaced')],
    ['cross_braces', t('q_cross_braces')],
    ['pipe_clamps_tight', t('q_pipe_clamps_tight')],
    ['window_jacks_tight', t('q_window_jacks_tight')],
    ['planks_secured', t('q_planks_secured')],
    ['decking_planks_condition', t('q_decking_planks_condition')],
    ['deck_fully_planked', t('q_deck_fully_planked')],
    ['gaps_open_spaces', t('q_gaps_open_spaces')],
    ['guardrails_toe_boards', t('q_guardrails_toe_boards')],
    ['netting_extension', t('q_netting_extension')],
    ['netting_secured', t('q_netting_secured')],
    ['parapet_height', t('q_parapet_height')],
    ['lights_working', t('q_lights_working')],
    ['deck_clean', t('q_deck_clean')],
    ['drawings_on_site', t('q_drawings_on_site')],
  ];

  const renderScaffoldMaintenance = (log) => {
    const data = log.data || {};
    const gi = data.general_info || {};
    const answers = data.answers || {};
    const questions = SCAFFOLD_QUESTIONS();
    const labels = Object.fromEntries(questions);
    const known = new Set(questions.map(([k]) => k));
    // Answers are YES / NO / N/A strings. An N/A the CP CHOSE is a real answer
    // and shows as chosen; an UNANSWERED question reads "— Not recorded",
    // never a silent NO. A form with no answers at all is a whole absent
    // section and drops the table.
    const anyAnswered = questions.some(([k]) => hasVal(answers, k));
    const order = (anyAnswered ? questions.map(([k]) => k) : [])
      .concat(Object.keys(answers).filter((k) => !known.has(k) && hasVal(answers, k)));
    const rows = order.map((k) => [
      { text: labels[k] || keyLabel(k), flex: 3 },
      { text: hasVal(answers, k) ? String(answers[k]) : t('fNotRecorded'), flex: 0.8 },
    ]);
    return (
      <View style={s.docContent}>
        {/* general_info.drawings_on_site is a dead duplicate of the answers
            question of the same key — only the answer is rendered. */}
        <DocFields data={gi} specs={[
          ['scaffold_erector', t('scErector')],
          ['renters_name', t('scRenter')],
          ['permit_number', t('scPermit')],
          ['phone', t('scPhone')],
          ['installation_date', t('scInstall')],
          ['expiration_date', t('scExpiration')],
          ['scaffold_height', t('scHeight')],
          ['num_platforms', t('scPlatforms')],
          ['shed_type', t('scShedType')],
        ]} />
        <RowTable
          title={t('scChecklist')}
          icon={ShieldCheck}
          headers={[{ text: t('scQuestion'), flex: 3 }, { text: t('scAnswer'), flex: 0.8 }]}
          rows={rows}
        />
        <CpSignature log={log} />
      </View>
    );
  };

  // src/utils/sscDailySafetyLogModel.js — draftBody decides the payload shape,
  // COMPLIANCE_FLAGS the five keys and NARRATIVE_FIELDS the three prompts.
  // The keys below are asserted against that model by
  // src/utils/portedFormPayloads.test.cjs.
  const renderSscDailySafetyLog = (log) => {
    const data = log.data || {};
    // The five compliance toggles are a fixed list: once ANY of them is on the
    // document the rest read "— Not recorded" rather than dropping out of the
    // table. None at all is a whole absent section.
    const FLAGS = [
      ['incidents_reported', t('s_incidents_reported')],
      ['safety_meetings_held', t('s_safety_meetings_held')],
      ['fire_protection_in_place', t('s_fire_protection_in_place')],
      ['housekeeping_satisfactory', t('s_housekeeping_satisfactory')],
      ['ppe_compliance', t('s_ppe_compliance')],
    ];
    const flags = FLAGS.some(([k]) => hasVal(data, k)) ? FLAGS : [];
    // An unwritten narrative reads "— Not recorded", never an asserted "none"
    // that could pass for a negative finding the CP never made.
    const NARRATIVE = [
      ['site_conditions', t('sscSiteConditions')],
      ['safety_violations_observed', t('sscViolations')],
      ['corrective_actions_taken', t('sscCorrective')],
    ];
    // Incident detail is only meaningful when an incident was reported — but
    // if one WAS, a missing detail is an unanswered question, not silence.
    const showIncident = !!data.incidents_reported;
    const narrative = (showIncident || NARRATIVE.some(([k]) => hasVal(data, k)))
      ? NARRATIVE : [];
    return (
      <View style={s.docContent}>
        <DocFields data={data} specs={[
          ['project_address', t('sscAddress')],
          ['ssp_number', t('sscSsp')],
          ['weather', t('fWeather')],
          ['workers_on_site_count', t('sscWorkers')],
        ]} />
        {flags.length > 0 && (
          <>
            <DocSectionLabel icon={ShieldCheck} label={t('sscCompliance')} color={semantic.neutral} />
            <DocTableRow isHeader cells={[{ text: t('fItem'), flex: 3 }, { text: t('fStatus'), flex: 0.8 }]} />
            {flags.map(([k, label]) => (
              <DocTableRow key={k} cells={[
                { text: label, flex: 3 },
                { text: hasVal(data, k) ? flag(data[k]) : t('fNotRecorded'), flex: 0.8 },
              ]} />
            ))}
            {/* These five are ToggleRows seeded false, so a rendered "off" may
                be an untouched default and not a deliberate negative finding.
                Say so — the same caveat the PDF renderer prints. */}
            <Text style={s.rosterLegend}>{t('sscDefaultNote')}</Text>
          </>
        )}
        {(narrative.length > 0 || showIncident) && (
          <>
            <DocSectionLabel icon={FileText} label={t('sscNarrative')} color={semantic.neutral} />
            {narrative.map(([k, label]) => (
              <Text key={k} style={s.docParagraph}>
                {`${label}: ${hasVal(data, k) ? data[k] : t('fNotRecorded')}`}
              </Text>
            ))}
            {showIncident && (
              <Text style={s.docParagraph}>
                {`${t('sscIncidentDetails')}: ${hasVal(data, 'incident_details')
                  ? data.incident_details : t('fNotRecorded')}`}
              </Text>
            )}
          </>
        )}
        <CpSignature log={log} />
      </View>
    );
  };

  // frontend/app/logbooks/osha_log.jsx:200  data: { entries }; EMPTY_ENTRY :28-37
  // NOTE vs generate_combined_report: that renderer adds a Review column by
  // joining each row to the worker's LIVE certifications. That is a database
  // read, not a payload key — this screen renders the stored snapshot as
  // stored, with no invented review state.
  const renderOshaLog = (log) => {
    const data = log.data || {};
    const rows = (data.entries || [])
      .filter((e) => e && ['worker_name', 'company', 'certification_type', 'card_number', 'expiration']
        .some((k) => hasVal(e, k)))
      .map((e) => [
        { text: e.worker_name || '', flex: 1.5 },
        { text: e.company || '', flex: 1 },
        { text: e.certification_type || '', flex: 1 },
        { text: e.card_number || '', flex: 1 },
        { text: e.expiration || '', flex: 1 },
        { text: e.signed ? '✓' : '', flex: 0.5 },
      ]);
    return (
      <View style={s.docContent}>
        <RowTable
          title={t('tabOsha')}
          icon={FileText}
          headers={[
            { text: t('fWorker'), flex: 1.5 }, { text: t('fCompany'), flex: 1 },
            { text: t('oshaCertType'), flex: 1 }, { text: t('oshaCard'), flex: 1 },
            { text: t('oshaExpiration'), flex: 1 }, { text: t('oshaSigned'), flex: 0.5 },
          ]}
          rows={rows}
        />
        <CpSignature log={log} />
      </View>
    );
  };

  // ONE DOCUMENT PER WORKER. Payload keys:
  // frontend/app/logbooks/subcontractor_orientation.jsx:472-483 (manual entry)
  // and backend/server.py:9900-9912 (kiosk registration) write the same names.
  // Checklist labels: ORIENTATION_SECTIONS, subcontractor_orientation.jsx:49-87
  const ORIENTATION_ITEMS = () => [
    ['hard_hats', t('o_hard_hats')],
    ['safety_boots', t('o_safety_boots')],
    ['safety_glasses', t('o_safety_glasses')],
    ['high_vis', t('o_high_vis')],
    ['no_horseplay', t('o_no_horseplay')],
    ['report_hazards', t('o_report_hazards')],
    ['fall_protection_required', t('o_fall_protection_required')],
    ['harness_inspection', t('o_harness_inspection')],
    ['ladder_safety', t('o_ladder_safety')],
    ['scaffold_rules', t('o_scaffold_rules')],
    ['emergency_exits', t('o_emergency_exits')],
    ['first_aid', t('o_first_aid')],
    ['emergency_contact', t('o_emergency_contact')],
    ['incident_reporting', t('o_incident_reporting')],
    ['no_drugs_alcohol', t('o_no_drugs_alcohol')],
    ['sign_in_out', t('o_sign_in_out')],
    ['authorized_areas', t('o_authorized_areas')],
    ['housekeeping', t('o_housekeeping')],
  ];

  const renderSubcontractorOrientation = (log) => {
    const data = log.data || {};
    // The kiosk writes {checked, checked_at} per item and keys it by the item's
    // full English sentence (backend/checkin.html:674-687, 1574-1579); the
    // in-app editor writes key -> bool. Both shapes render. An item the
    // editor's map does not carry reads "— Not recorded"; a map keyed the
    // kiosk way carries none of the known keys, so it renders only its own
    // sentences rather than 18 fabricated absences.
    const checklist = data.checklist;
    const items = ORIENTATION_ITEMS();
    const labels = Object.fromEntries(items);
    const known = new Set(items.map(([k]) => k));
    const isMap = !!checklist && typeof checklist === 'object' && !Array.isArray(checklist);
    const anyKnown = isMap && items.some(([k]) => k in checklist);
    const order = isMap
      ? (anyKnown ? items.map(([k]) => k) : [])
        .concat(Object.keys(checklist).filter((k) => !known.has(k)))
      : [];
    const checkedOf = (v) => (v && typeof v === 'object' ? !!v.checked : !!v);
    const rows = order.map((k) => [
      { text: labels[k] || keyLabel(k), flex: 3 },
      { text: k in checklist ? flag(checkedOf(checklist[k])) : t('fNotRecorded'), flex: 0.8 },
    ]);
    return (
      <View style={s.docContent}>
        <DocFields data={data} specs={[
          ['worker_name', t('fWorker')],
          ['worker_trade', t('orTrade')],
          ['worker_company', t('fCompany')],
          ['osha_number', t('orOsha')],
          ['orientation_number', t('orNumber')],
          ['language_provided', t('orLanguage')],
          ['completed_at', t('orCompleted'), (v) => String(v).slice(0, 19).replace('T', ' ')],
        ]} />
        <RowTable
          title={t('orTopics')}
          icon={ShieldCheck}
          headers={[{ text: t('orTopic'), flex: 3 }, { text: t('orReviewed'), flex: 0.8 }]}
          rows={rows}
        />
        {/* LOAD-BEARING: worker_signature is written as null on manual entries
            (subcontractor_orientation.jsx:481). Key present and empty => say
            UNSIGNED, so an unattested acknowledgment is never presented as
            complete. Key absent entirely => say nothing. */}
        {'worker_signature' in data && (
          data.worker_signature
            ? <SignatureBlock signature={data.worker_signature} label={t('orAck')} />
            : (
              <View style={s.unsignedBlock}>
                <Text style={s.unsignedLabel}>{`${t('orAck')}: `}</Text>
                <Text style={s.unsignedNames}>{t('orUnsigned')}</Text>
              </View>
            )
        )}
        <CpSignature log={log} label={t('orConductedBy')} />
      </View>
    );
  };

  const renderLogContent = (log) => {
    if (log.log_type === 'daily_jobsite') return renderDailyJobsite(log);
    if (log.log_type === 'toolbox_talk') return renderToolboxTalk(log);
    if (log.log_type === 'preshift_signin') return renderPreshiftSignin(log);
    if (log.log_type === 'hot_work') return renderHotWork(log);
    if (log.log_type === 'crane_operations') return renderCraneOperations(log);
    if (log.log_type === 'excavation_monitoring') return renderExcavationMonitoring(log);
    if (log.log_type === 'concrete_operations') return renderConcreteOperations(log);
    if (log.log_type === 'scaffold_maintenance') return renderScaffoldMaintenance(log);
    if (log.log_type === 'ssc_daily_safety_log') return renderSscDailySafetyLog(log);
    if (log.log_type === 'osha_log') return renderOshaLog(log);
    if (log.log_type === 'subcontractor_orientation') return renderSubcontractorOrientation(log);
    return <Text style={s.logField}>No data available</Text>;
  };

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* Header — back button hidden while Inspector Mode is engaged
            (the inspector must not leave the read-only logbooks tab). */}
        <View style={s.header}>
          {!isLocked && (
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/site')}
            />
          )}
          <View style={{ flex: 1 }}>
            <Text style={s.headerTitle}>Log Books</Text>
            <Text style={s.headerSub}>Submitted Records</Text>
          </View>
        </View>

        {/* Inspector Mode banner — read-only notice + exit control. */}
        {isLocked && (
          <View style={s.inspectorBanner}>
            <Lock size={16} strokeWidth={1.5} color="#f59e0b" />
            <Text style={s.inspectorBannerText}>Inspector Mode — read only</Text>
            <Pressable
              style={s.exitBtn}
              onPress={handleExitInspector}
              accessibilityRole="button"
              accessibilityLabel="Exit Inspector Mode"
            >
              <Text style={s.exitBtnText}>Exit Inspector Mode</Text>
            </Pressable>
          </View>
        )}

        {/* Tabs */}
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={s.tabScroll}>
          <View style={s.tabRow}>
            {LOG_TABS.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.key;
              const count = Object.values(logsByDate)
                .flat()
                .filter(l => l.log_type === tab.key).length;

              return (
                <Pressable
                  key={tab.key}
                  onPress={() => { setActiveTab(tab.key); setExpandedDate(null); }}
                  style={[s.tab, isActive && { backgroundColor: `${tab.color}20`, borderColor: `${tab.color}50` }]}
                >
                  <Icon size={16} strokeWidth={1.5} color={isActive ? tab.color : colors.text.muted} />
                  <Text style={[s.tabText, isActive && { color: tab.color }]}>{t(tab.labelKey)}</Text>
                  {count > 0 && (
                    <View style={[s.tabBadge, { backgroundColor: isActive ? tab.color : colors.text.muted }]}>
                      <Text style={s.tabBadgeText}>{count}</Text>
                    </View>
                  )}
                </Pressable>
              );
            })}
          </View>
        </ScrollView>

        {/* Content */}
        <ScrollView style={s.scrollView} contentContainerStyle={s.scrollContent}>
          {loading ? (
            <View style={s.loadingCenter}>
              <ActivityIndicator size="large" color={colors.text.primary} />
              <Text style={s.loadingText}>Loading logbooks...</Text>
            </View>
          ) : sortedDates.length === 0 ? (
            // HONEST EMPTY STATE: "No Submitted Logs" is a claim about the
            // RECORD, so it may only be made when the SERVER answered. A
            // failed read says so instead.
            fetchState === 'ok' ? (
              <GlassCard style={s.emptyCard}>
                <FileText size={40} strokeWidth={1} color={colors.text.muted} />
                <Text style={s.emptyTitle}>No Submitted Logs</Text>
                <Text style={s.emptyText}>
                  Submitted {tabLabel(activeTab)} entries will appear here.
                </Text>
              </GlassCard>
            ) : (
              <OfflineNotice mode={fetchState} cachedCount={0} />
            )
          ) : (
            <>
            {fetchState !== 'ok' && (
              <OfflineNotice mode={fetchState} cachedCount={visibleLogCount} />
            )}
            {sortedDates.map((date) => {
              const logs = filteredDates[date];
              const isExpanded = expandedDate === date;

              return (
                <View key={date}>
                  <Pressable
                    onPress={() => setExpandedDate(isExpanded ? null : date)}
                    style={s.dateHeader}
                  >
                    <Calendar size={16} strokeWidth={1.5} color={colors.text.muted} />
                    <Text style={s.dateText}>{formatDate(date)}</Text>
                    <View style={s.dateBadge}>
                      <CheckCircle size={12} strokeWidth={2} color="#4ade80" />
                      <Text style={s.dateBadgeText}>{logs.length}</Text>
                    </View>
                    <ChevronRight
                      size={16} strokeWidth={1.5} color={colors.text.muted}
                      style={isExpanded ? { transform: [{ rotate: '90deg' }] } : {}}
                    />
                  </Pressable>

                  {isExpanded && (
                    <>
                      {/* Combined PDF button for this date */}
                      <View style={s.pdfRow}>
                        <GlassButton
                          title="Download Full Day Report"
                          icon={<Download size={14} strokeWidth={1.5} color={colors.text.primary} />}
                          onPress={() => handleCombinedPdf(date)}
                          style={s.pdfBtn}
                        />
                      </View>

                      {logs.map((log, idx) => (
                        <GlassCard key={log.id || idx} style={s.logCard}>
                          {/* Document Header */}
                          <View style={s.docHeader}>
                            <View style={s.docHeaderLeft}>
                              <Text style={s.logType}>
                                {tabLabel(log.log_type)}
                              </Text>
                              <Text style={s.docDate}>{formatDate(log.date || date)}</Text>
                            </View>
                            <View style={s.docHeaderRight}>
                              <View style={[s.statusBadge, log.status === 'submitted' ? s.statusSubmitted : s.statusDraft]}>
                                <Text style={[s.statusText, log.status === 'submitted' ? s.statusTextSubmitted : s.statusTextDraft]}>
                                  {log.status === 'submitted' ? 'SUBMITTED' : 'DRAFT'}
                                </Text>
                              </View>
                              <Text style={s.logTime}>
                                {log.created_at ? new Date(log.created_at).toLocaleTimeString('en-US', {
                                  hour: 'numeric', minute: '2-digit', hour12: true,
                                }) : ''}
                              </Text>
                            </View>
                          </View>

                          {/* Full Document Content */}
                          {renderLogContent(log)}

                          {/* PDF Actions — tap = browser, long-press = share */}
                          {log.status === 'submitted' && (log.id || log._id) && (
                            <View style={s.pdfActions}>
                              <Pressable
                                style={s.pdfActionBtn}
                                onPress={() => handleViewLogPdf(log, date)}
                                onLongPress={() => handleShareLogPdf(log, date)}
                              >
                                <Download size={14} strokeWidth={1.5} color="#3b82f6" />
                                <Text style={s.pdfActionText}>PDF</Text>
                              </Pressable>
                              <Pressable
                                style={s.pdfActionBtn}
                                onPress={() => handleShareLogPdf(log, date)}
                              >
                                <Share2 size={14} strokeWidth={1.5} color="#3b82f6" />
                                <Text style={s.pdfActionText}>Share</Text>
                              </Pressable>
                            </View>
                          )}
                        </GlassCard>
                      ))}
                    </>
                  )}
                </View>
              );
            })}
            </>
          )}
        </ScrollView>

        {/* Hide the bottom nav while locked — its Dashboard / Check-Ins
            entries lead off the read-only tab (the route gate would
            bounce them straight back). */}
        {!isLocked && <SiteNav />}
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
  container: { flex: 1 },
  header: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.md,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  headerTitle: { fontSize: 22, fontWeight: '600', color: colors.text.primary },
  headerSub: { fontSize: 15, color: colors.text.muted },

  // Tabs
  tabScroll: { flexGrow: 0, marginBottom: spacing.sm },
  tabRow: { flexDirection: 'row', gap: spacing.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.xs },
  tab: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.xs,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.sm,
    minHeight: 48,
    borderRadius: borderRadius.full, borderWidth: 1, borderColor: colors.glass.border,
    backgroundColor: colors.glass.background,
  },
  tabText: { fontSize: 16, fontWeight: '500', color: colors.text.muted },
  tabBadge: {
    minWidth: 22, height: 22, borderRadius: 11, alignItems: 'center', justifyContent: 'center',
    paddingHorizontal: 6,
  },
  tabBadgeText: { fontSize: 14, fontWeight: '700', color: '#fff' },

  // Content
  scrollView: { flex: 1 },
  scrollContent: { padding: spacing.lg, paddingBottom: 120 },
  loadingCenter: { alignItems: 'center', paddingVertical: spacing.xxl, gap: spacing.md },
  loadingText: { fontSize: 16, color: colors.text.muted },

  // Empty
  emptyCard: { alignItems: 'center', padding: spacing.xl, gap: spacing.md },
  emptyTitle: { fontSize: 20, fontWeight: '500', color: colors.text.primary },
  emptyText: { fontSize: 16, color: colors.text.muted, textAlign: 'center' },

  // Date rows
  dateHeader: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
    paddingVertical: spacing.md, paddingHorizontal: spacing.sm,
    borderBottomWidth: 1, borderBottomColor: colors.glass.border,
  },
  dateText: { flex: 1, fontSize: 18, fontWeight: '600', color: colors.text.primary },
  dateBadge: {
    flexDirection: 'row', alignItems: 'center', gap: 3,
    backgroundColor: semantic.verifiedBg, paddingHorizontal: spacing.sm, paddingVertical: 2,
    borderRadius: borderRadius.full,
  },
  dateBadgeText: { fontSize: 14, fontWeight: '600', color: '#4ade80' },

  // Log card — full document style
  logCard: { marginTop: spacing.sm, marginBottom: spacing.md, padding: spacing.md },

  // Document header
  docHeader: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start',
    marginBottom: spacing.md, paddingBottom: spacing.sm,
    borderBottomWidth: 2, borderBottomColor: 'rgba(59,130,246,0.3)',
  },
  docHeaderLeft: { flex: 1 },
  docHeaderRight: { alignItems: 'flex-end', gap: 4 },
  logType: { fontSize: 20, fontWeight: '700', color: colors.text.primary },
  docDate: { fontSize: 15, color: colors.text.muted, marginTop: 2 },
  logTime: { fontSize: 14, color: colors.text.muted },

  // Status badge
  statusBadge: {
    paddingHorizontal: spacing.sm, paddingVertical: 2,
    borderRadius: borderRadius.full, borderWidth: 1,
  },
  statusSubmitted: { backgroundColor: semantic.verifiedBg, borderColor: semantic.verifiedBorder },
  statusDraft: { backgroundColor: semantic.attentionBg, borderColor: semantic.attentionBorder },
  statusText: { fontSize: 14, fontWeight: '700', letterSpacing: 0.5 },
  statusTextSubmitted: { color: semantic.verified },
  statusTextDraft: { color: semantic.attention },

  // Document content
  docContent: { gap: 2 },
  docInfoBox: {
    backgroundColor: withAlpha('#ffffff', 0.03), borderRadius: borderRadius.md,
    padding: spacing.sm, gap: 6, borderWidth: 1, borderColor: withAlpha('#ffffff', 0.06),
  },
  docInfoRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  docInfoText: { fontSize: 16, color: colors.text.secondary, flex: 1 },
  docParagraph: { fontSize: 16, color: colors.text.secondary, lineHeight: 24, paddingLeft: 2 },
  rosterLegend: { fontSize: 12, color: colors.text.muted, lineHeight: 17, paddingLeft: 2, marginTop: spacing.xs, fontStyle: 'italic' },

  // Photo row
  photoRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs, paddingVertical: spacing.xs, paddingLeft: spacing.sm },
  activityPhoto: { width: 80, height: 60, borderRadius: 6, borderWidth: 1, borderColor: withAlpha('#ffffff', 0.1) },

  // Signature section
  signatureSection: { marginTop: spacing.md },
  signatureDivider: { height: 1, backgroundColor: withAlpha('#ffffff', 0.08), marginBottom: spacing.sm },
  signedByName: { fontSize: 16, color: semantic.verified, fontWeight: '500', marginTop: spacing.xs },

  // Topic chips
  topicChips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  topicChip: {
    flexDirection: 'row', alignItems: 'center', gap: 4,
    backgroundColor: 'rgba(139,92,246,0.1)', borderWidth: 1, borderColor: 'rgba(139,92,246,0.2)',
    borderRadius: borderRadius.full, paddingHorizontal: spacing.sm, paddingVertical: 4,
  },
  topicChipText: { fontSize: 15, color: '#c4b5fd', fontWeight: '500' },

  // Worker signatures grid
  workerSigGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  workerSigCard: {
    width: '47%', backgroundColor: withAlpha('#ffffff', 0.03), borderRadius: borderRadius.md,
    padding: spacing.xs, borderWidth: 1, borderColor: withAlpha('#ffffff', 0.06), alignItems: 'center',
  },
  workerSigName: { fontSize: 14, fontWeight: '600', color: colors.text.muted, marginBottom: 4 },
  workerSigImage: { width: 120, height: 36, borderRadius: 4, backgroundColor: withAlpha('#ffffff', 0.05) },

  // Unsigned workers
  unsignedBlock: { flexDirection: 'row', flexWrap: 'wrap', gap: 4, marginTop: spacing.xs, paddingLeft: 2 },
  unsignedLabel: { fontSize: 14, fontWeight: '700', color: colors.text.muted },
  unsignedNames: { fontSize: 14, color: colors.text.muted },

  // PDF buttons
  pdfRow: { paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, marginTop: spacing.xs },
  pdfBtn: { backgroundColor: 'rgba(59,130,246,0.1)', borderColor: 'rgba(59,130,246,0.25)' },
  pdfActions: {
    flexDirection: 'row', gap: spacing.sm, marginTop: spacing.md, paddingTop: spacing.sm,
    borderTopWidth: 1, borderTopColor: withAlpha('#ffffff', 0.06),
  },
  // Was paddingVertical spacing.xs around a 14px icon: a 22-24px target, the
  // smallest in site mode, on a device used with work gloves.
  pdfActionBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.xs,
    minHeight: 48, minWidth: 96,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.sm,
    backgroundColor: 'rgba(59,130,246,0.08)', borderRadius: borderRadius.full,
    borderWidth: 1, borderColor: 'rgba(59,130,246,0.2)',
  },
  pdfActionText: { fontSize: 16, fontWeight: '600', color: '#3b82f6' },

  // Legacy
  logField: { fontSize: 16, color: colors.text.secondary, lineHeight: 24 },
  logFieldLabel: { fontWeight: '600', color: colors.text.primary },

  // Inspector Mode banner
  inspectorBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginHorizontal: spacing.lg,
    marginBottom: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.md,
    backgroundColor: withAlpha('#f59e0b', 0.12),
    borderWidth: 1,
    borderColor: withAlpha('#f59e0b', 0.35),
  },
  inspectorBannerText: {
    flex: 1,
    fontSize: 15,
    fontWeight: '700',
    color: '#f59e0b',
    letterSpacing: 0.3,
  },
  exitBtn: {
    minHeight: 40,
    minWidth: 72,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
    borderRadius: borderRadius.full,
    backgroundColor: withAlpha('#f59e0b', 0.18),
    borderWidth: 1,
    borderColor: withAlpha('#f59e0b', 0.4),
  },
  exitBtnText: { fontSize: 15, fontWeight: '700', color: '#f59e0b' },
});
}
