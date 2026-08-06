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

const LOG_TABS = [
  { key: 'daily_jobsite', label: 'Daily Jobsite', icon: ClipboardList, color: '#3b82f6' },
  { key: 'toolbox_talk', label: 'Toolbox Talk', icon: BookOpen, color: '#8b5cf6' },
  { key: 'preshift_signin', label: 'Pre-Shift Sign-In', icon: Users, color: semantic.neutral },
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

export default function SiteLogbooksViewer() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading, siteMode, siteProject } = useAuth();
  const { isLocked, unlock } = useInspectorLock();
  const toast = useToast();

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
      <Icon size={16} strokeWidth={1.5} color={colors.text.muted} />
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
                  { text: `${act.crew_name || ''} ${act.company || 'Unknown'}`.trim(), flex: 1.5 },
                  { text: String(act.num_workers || 0), flex: 0.6 },
                  { text: act.work_description || 'N/A', flex: 2 },
                  { text: act.work_locations || 'N/A', flex: 1 },
                ]} />
                {(act.photos || []).length > 0 && (
                  <View style={s.photoRow}>
                    {act.photos.map((photo, pi) => {
                      const uri = photo.base64
                        ? (photo.base64.startsWith('data:') ? photo.base64 : `data:image/jpeg;base64,${photo.base64}`)
                        : photo.uri;
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
            <DocTableRow isHeader cells={[{ text: 'Name', flex: 1.5 }, { text: 'Company', flex: 1 }, { text: 'Signed', flex: 0.6 }]} />
            {attendees.map((a, i) => (
              <DocTableRow key={i} cells={[{ text: a.name || 'Unknown', flex: 1.5 }, { text: a.company || '', flex: 1 }, { text: a.signed ? '✓' : '—', flex: 0.6 }]} />
            ))}
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

  const renderLogContent = (log) => {
    if (log.log_type === 'daily_jobsite') return renderDailyJobsite(log);
    if (log.log_type === 'toolbox_talk') return renderToolboxTalk(log);
    if (log.log_type === 'preshift_signin') return renderPreshiftSignin(log);
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
                  <Text style={[s.tabText, isActive && { color: tab.color }]}>{tab.label}</Text>
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
                  Submitted {LOG_TABS.find(t => t.key === activeTab)?.label || ''} entries will appear here.
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
                                {LOG_TABS.find(t => t.key === log.log_type)?.label || log.log_type}
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
