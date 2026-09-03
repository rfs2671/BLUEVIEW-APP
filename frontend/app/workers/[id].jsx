import apiClient, { workersAPI } from '../../src/utils/api';
import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  TextInput,
  Alert,
  Platform,
  Image,
  Modal,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  User,
  Building2,
  Award,
  Edit3,
  Save,
  Plus,
  Trash2,
  FileText,
  Calendar,
  Pen,
  ShieldCheck,
  AlertTriangle,
  CreditCard,
  ChevronDown,
  ChevronUp,
  Check,
  X,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import GlassInput from '../../src/components/GlassInput';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { useWorkers } from '../../src/hooks/useWorkers';
import OfflineIndicator from '../../src/components/OfflineIndicator';
import OfflineNotice from '../../src/components/OfflineNotice';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { semantic, chrome, withAlpha } from '../../src/styles/semanticColors';
import { useTheme } from '../../src/context/ThemeContext';
import AsyncStorage from '@react-native-async-storage/async-storage';
import HeaderBrand from '../../src/components/HeaderBrand';
import { expiryStatus, expirySuffix } from '../../src/utils/expiry';
import { certLabel, certExpiration } from '../../src/utils/oshaLogModel';
import { pairingLine, hasPairing } from '../../src/utils/workerPairingCopy';
import { settleFetch, failureDetail } from '../../src/utils/offlineState';

/**
 * OFFLINE SST/OSHA CARD.
 *
 * This screen was online-only: a dead zone produced "Could not load worker
 * details" plus an empty card slot that reads as "this worker has no SST card"
 * — the worst possible answer to hand a DOB inspector or a CP at the gate.
 *
 * The card image arrives base64-INLINE in the /osha-card response (not a file
 * URL), so caching it needs nothing but AsyncStorage — no FileSystem, no native
 * module, OTA-deliverable. Same write-through/read-back shape as projectCache.
 */
const WORKER_PREFIX = 'bv_worker:';
const WORKER_OSHA_PREFIX = 'bv_worker_osha:';

async function cacheWorkerDetail(workerId, data) {
  if (!workerId || !data) return;
  try {
    await AsyncStorage.setItem(`${WORKER_PREFIX}${workerId}`, JSON.stringify(data));
  } catch (_e) { /* non-fatal — the network read still succeeded */ }
}

async function readCachedWorkerDetail(workerId) {
  try {
    const raw = await AsyncStorage.getItem(`${WORKER_PREFIX}${workerId}`);
    return raw ? JSON.parse(raw) : null;
  } catch (_e) {
    return null;
  }
}

/** The base64 card image + parsed fields, keyed per worker. */
async function cacheWorkerOsha(workerId, data) {
  if (!workerId || !data) return;
  try {
    await AsyncStorage.setItem(`${WORKER_OSHA_PREFIX}${workerId}`, JSON.stringify(data));
  } catch (_e) { /* non-fatal */ }
}

async function readCachedWorkerOsha(workerId) {
  try {
    const raw = await AsyncStorage.getItem(`${WORKER_OSHA_PREFIX}${workerId}`);
    return raw ? JSON.parse(raw) : null;
  } catch (_e) {
    return null;
  }
}

export default function WorkerDetailScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  // THE PROJECT CONTEXT, forwarded by whoever navigated here.
  //
  // This route has no project segment, and WorkerResponse cannot fill trade or
  // company -- its docstring says why: "a worker with pairings on two projects
  // has two companies, and this endpoint has no project context to choose
  // between them." The caller in workers.jsx is holding a CHECK-IN row, which
  // carries the pairing the server already resolved through
  // _get_worker_project_trade, so it passes it through rather than the screen
  // guessing or the endpoint being widened.
  //
  // ABSENT IS THE NORMAL CASE. Every other entry point has no project, and the
  // copy handles that by stating the rule instead of asserting a deficiency.
  const {
    id: workerId,
    projectId: routeProjectId,
    projectName: routeProjectName,
    trade: routeTrade,
    company: routeCompany,
  } = useLocalSearchParams();
  const { isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [worker, setWorker] = useState(null);
  const { getWorkerById, updateWorker } = useWorkers();
  // What actually went wrong, for the banner. Null until something does.
  const [detailError, setDetailError] = useState(null);
  const [editMode, setEditMode] = useState(false);
  
  // Edit form fields
  const [name, setName] = useState('');
  const [trade, setTrade] = useState('');
  const [company, setCompany] = useState('');
  const [oshaNumber, setOshaNumber] = useState('');
  
  // Certifications
  const [certifications, setCertifications] = useState([]);
  const [showAddCert, setShowAddCert] = useState(false);
  const [newCertName, setNewCertName] = useState('');
  const [newCertExpiry, setNewCertExpiry] = useState('');
  
  // Signature — READ ONLY on this screen. A worker's signature is captured at
  // the gate, from his own device, when he registers (register_and_checkin
  // writes workers.signature). There is no write path here and there must not
  // be one: PUT /workers/{id} filters through ALLOWED_WORKER_FIELDS, which
  // does not contain `signature`, and an admin drawing a worker's mark on a
  // detail screen would be a forged attestation rather than a captured one.
  const [signature, setSignature] = useState(null);

  // OSHA & Safety Orientation (fetched from API)
  const [oshaCardImage, setOshaCardImage] = useState(null);
  const [oshaData, setOshaData] = useState(null);
  const [safetyOrientations, setSafetyOrientations] = useState([]);
  const [loadingOsha, setLoadingOsha] = useState(false);
  const [showOshaCard, setShowOshaCard] = useState(false);
  const [expandedOrientation, setExpandedOrientation] = useState(null);

  // 'ok' | 'offline' | 'error' per fetch, so a failed load is never rendered
  // as "no card on file" / "no orientations".
  const [detailState, setDetailState] = useState('ok');
  const [oshaState, setOshaState] = useState('ok');

  const isAdmin = user?.role === 'admin' || user?.role === 'owner';

  // Credential expiry tone. Both the certification list and the OSHA/SST card
  // route through this: fixing only one of them leaves the other silently
  // lapsed, which is the bug being fixed here. null status (missing or
  // unparseable date) deliberately falls through to the unchanged muted style
  // rather than asserting the credential is fine.
  const expiryTone = (dateStr) => {
    const status = expiryStatus(dateStr);
    if (status === 'expired') return { color: semantic.criticalText, fontWeight: '600' };
    if (status === 'soon') return { color: semantic.attention, fontWeight: '600' };
    return null;
  };
  const isSiteDevice = user?.role === 'site_device';
  const canViewOsha = isAdmin || isSiteDevice;

  // PR B: cert-level review flag surface. The check-in review screen resolves
  // the ENTRY decision (Admit / Send home) but never verifies the credential —
  // the SST cert stays flagged (needs_review / review_reason). This is where
  // that flag is rendered so "stays flagged for review" is not a dead end.
  // English-only: this screen has no language path. Codes mirror review.jsx.
  const CERT_REVIEW_REASON = {
    CLASS_UNVERIFIED: 'Card class could not be read — verify the card',
    EXPIRY_IMPLAUSIBLE: 'Expiry date is implausible — re-scan or verify',
    EXPIRY_UNPARSEABLE: 'Expiry date could not be read — verify the card',
    EXPIRY_CONFLICT: 'Two scans disagree on the expiry — verify the card',
    DUPLICATE_SST: 'Duplicate SST records — resolve to one',
    // AN OBSERVATION, NOT A JUDGEMENT, and the same words the register uses.
    // "Incorrect" and "invalid" say the CP got it wrong; the app cannot claim
    // what he meant. This states what was expected and leaves him to compare
    // it with the card.
    //
    // THIS ONE IS EVALUATED AT READ TIME, not stored. The server overlays it
    // onto the certification it returns, so it arrives through the same keys
    // as a stored flag and needs no new branch here.
    CARD_NUMBER_FORMAT: 'Card number does not match the expected format — check the card and re-enter',
  };
  /**
   * What this certification is called, on the screen the CP checks it on.
   *
   * RENDER, NEVER FILTER. A credential the app cannot describe is itself a
   * finding, and a row that vanishes tells the CP nothing. A blank row with a
   * delete button beside it is worse still -- he cannot tell what he would be
   * deleting, and this same certification is what satisfies the OSHA baseline
   * at the gate.
   *
   * The chain ends in a sentence rather than an empty string for that reason:
   * "no type recorded" is a true statement the CP can act on.
   */
  const certDisplayName = (cert) => (
    certLabel(cert)
    || (cert?.card_number ? `Card ${cert.card_number}` : '')
    || 'Certification (no type recorded)'
  );
  /**
   * PREFER THE FORWARDED PAIRING, and never fall back to the worker document.
   *
   * `trade` / `company` state is still read off the worker doc by applyWorker,
   * because a LEGACY row may carry them and hiding a stored value is a
   * different defect. But they are not used as a fallback here:
   * _get_worker_project_trade refuses the same fallback for the same reason --
   * "a value from another project is worse than no value, because it is
   * silently wrong instead of visibly absent."
   */
  const workerPairing = pairingLine({
    trade: routeTrade,
    company: routeCompany,
    projectName: routeProjectName,
  });

  const flaggedCerts = (certifications || []).filter(
    (c) => c && (c.needs_review || c.review_reason)
  );

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated && workerId) {
      fetchWorker().then(() => {
      if (canViewOsha) {
        fetchOshaData();
        }
      });
    }
  }, [isAuthenticated, workerId]);

  const applyWorker = (workerData) => {
    setWorker(workerData);
    setName(workerData.name || '');
    setTrade(workerData.trade || '');
    setCompany(workerData.company || '');
    setOshaNumber(workerData.osha_number || workerData.oshaNumber || '');
    setCertifications(workerData.certifications || []);
    setSignature(workerData.signature || null);
  };

  const fetchWorker = async () => {
    // getWorkerById() swallows its own error and returns null, so the
    // workersAPI call below is what actually surfaces the offline rejection.
    const r = await settleFetch(async () => {
      let workerData = await getWorkerById(workerId);
      if (!workerData || !workerData.signature) {
        workerData = await workersAPI.getById(workerId);
      }
      return workerData;
    });

    if (r.status === 'ok' && r.data) {
      applyWorker(r.data);
      setDetailState('ok');
      cacheWorkerDetail(workerId, r.data); // write-through
    } else {
      console.error('Failed to fetch worker:', r.error);
      // KEEP THE ERROR. It used to go to the console and nowhere else, so a
      // 500, a 403, a 404 and a client-side throw all rendered the same
      // sentence — and the 500 was a pydantic ValidationError the server had
      // been naming in `detail` the whole time.
      setDetailError(failureDetail(
        r.status === 'ok' ? 'error' : r.status, r.error, 'this worker',
      ));
      const cached = await readCachedWorkerDetail(workerId);
      if (cached) applyWorker(cached);
      setDetailState(r.status === 'ok' ? 'error' : r.status);
    }
    setLoading(false);
  };

  const applyOsha = (data) => {
    setOshaCardImage(data.osha_card_image || null);
    setOshaData(data.osha_data || null);
    setSafetyOrientations(data.safety_orientations || []);
    // Only overwrite a signature we already have when this payload carries one.
    if (data.signature) setSignature(data.signature);
    if (data.osha_number && !oshaNumber) {
      setOshaNumber(data.osha_number);
    }
  };

  const fetchOshaData = async () => {
    setLoadingOsha(true);
    // Use centralized API utility to handle tokens and headers automatically
    const r = await settleFetch(() => workersAPI.getOshaCard(workerId));

    if (r.status === 'ok' && r.data) {
      applyOsha(r.data);
      setSignature(r.data.signature || null);
      setOshaState('ok');
      // The card image is base64 inline in this payload — caching the payload
      // caches the card itself.
      cacheWorkerOsha(workerId, r.data);
    } else {
      console.error('Failed to fetch OSHA data:', r.error);
      const cached = await readCachedWorkerOsha(workerId);
      if (cached) applyOsha(cached);
      setOshaState(r.status === 'ok' ? 'error' : r.status);
    }
    setLoadingOsha(false);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      // NO trade, NO company. They belong to the {worker, project} pair and
      // live in worker_project_trades; a worker-level copy is what bled across
      // jobs. The server no longer accepts them either — ALLOWED_WORKER_FIELDS
      // dropped both — so sending them would be a silent no-op, which is the
      // worse failure: the admin would be told "Worker information updated".
      await updateWorker(workerId, {
        name,
        osha_number: oshaNumber,
        certifications,
      });
      setWorker({ ...worker, name, oshaNumber });
      setEditMode(false);
      toast.success('Saved', 'Worker information updated');
    } catch (error) {
      console.error('Failed to save:', error);
      toast.error('Error', 'Could not save changes');
    } finally {
      setSaving(false);
    }
  };

  const CERT_TYPES = [
    { value: 'OSHA_10', label: 'OSHA-10' },
    { value: 'OSHA_30', label: 'OSHA-30' },
    { value: 'SST_FULL', label: 'SST Full (62-hr)' },
    { value: 'SST_LIMITED', label: 'SST Limited (10-hr)' },
    { value: 'SST_SUPERVISOR', label: 'SST Supervisor' },
    { value: 'FDNY_COF', label: 'FDNY Certificate of Fitness' },
    { value: 'SCAFFOLD', label: 'Scaffold Safety' },
    { value: 'RIGGING', label: 'Rigging' },
    { value: 'WELDING', label: 'Welding' },
    { value: 'ASBESTOS', label: 'Asbestos Handler' },
    { value: 'LEAD', label: 'Lead Abatement' },
    { value: 'CONFINED_SPACE', label: 'Confined Space' },
    { value: 'OTHER', label: 'Other' },
  ];

  const [newCertType, setNewCertType] = useState('OSHA_10');

  const handleAddCertification = async () => {
    const certData = {
      type: newCertType,
      card_number: newCertName.trim() || null,
      expiration_date: newCertExpiry || null,
      issue_date: new Date().toISOString(),
      verified: false,
    };

    try {
      const workerId = worker._id || worker.id;
      await apiClient.post(`/api/workers/${workerId}/certifications`, certData);
      const updated = await getWorkerById(workerId);
      setCertifications(updated?.certifications || []);
      setNewCertName('');
      setNewCertExpiry('');
      setNewCertType('OSHA_10');
      setShowAddCert(false);
      toast.success('Added', 'Certification added and validated');
    } catch (error) {
      console.error('Failed to add cert:', error);
      // THE SERVER NAMES THE CONDITION, THE CLIENT OWNS THE WORDING. A code
      // shipped without copy shows the generic line below to a CP who then has
      // no idea what to change — the failure #285 shipped and #286 had to come
      // back for. This branch lands in the SAME change as the refusal.
      //
      // IT SAYS WHAT THE APP EXPECTED, NOT THAT HE IS WRONG. The rule rests on
      // two production samples, so the honest message shows him the shape and
      // lets him compare it to the card in his hand.
      const code = error?.response?.data?.detail?.code;
      if (code === 'CARD_NUMBER_FORMAT') {
        toast.error(
          'Check the card number',
          'An SST card number is 10 letters and numbers, like JH447TBBXG. '
          + 'This entry does not match that, so it has not been saved.',
        );
        return;
      }
      toast.error('Error', 'Could not save certification');
    }
  };

  /**
   * WIRED. It used to be local state only.
   *
   * It filtered the row out of `certifications`, toasted "Certification
   * removed", and never called DELETE /api/workers/{id}/certifications/{i}.
   * The record was untouched and came back on the next fetch -- unless the CP
   * then opened the edit form and saved, at which point the whole array PUTs
   * and the certification is genuinely gone. So the control was either a lie
   * or a delayed, unannounced deletion, depending on what he did next.
   *
   * A control that reports success for something that did not happen is worse
   * than no control, and this one sits beside a credential the GATE depends on:
   * validate_worker_certifications reads `type` for the OSHA baseline, which is
   * the one hard block on check-in.
   *
   * BY INDEX, because that is what the endpoint takes. The list rendered is
   * `certifications` in order, so the row's index IS the stored index -- no
   * filtering happens between the two, which is one more reason the render
   * path must never drop a row it cannot describe.
   */
  const handleDeleteCertification = (index) => {
    const confirmDelete = async () => {
      const workerIdForDelete = worker?._id || worker?.id || workerId;
      try {
        await apiClient.delete(
          `/api/workers/${workerIdForDelete}/certifications/${index}`,
        );
      } catch (err) {
        // NOTHING WAS REMOVED, and the list is not touched. Announcing a
        // failure and leaving the row is the honest pair; the previous code
        // announced success and left the record.
        console.error('Failed to delete certification:', err);
        toast.error(
          'Not deleted',
          'The certification is still on this worker. Check your connection and try again.',
        );
        return;
      }
      // Re-read rather than splicing locally: the server owns the array, and a
      // local filter is what made the old control look like it had worked.
      try {
        const updated = await getWorkerById(workerIdForDelete);
        setCertifications(updated?.certifications || []);
      } catch (_e) {
        setCertifications(certifications.filter((_, i) => i !== index));
      }
      toast.success('Deleted', 'Certification removed');
    };

    if (Platform.OS === 'web') {
      if (window.confirm('Delete this certification?')) {
        confirmDelete();
      }
    } else {
      Alert.alert('Delete Certification', 'Delete this certification?', [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete', style: 'destructive', onPress: confirmDelete },
      ]);
    }
  };

  // THERE IS NO handleUpdateSignature. What stood here set signature state to
  // the literal string 'signature_data' with a freshly minted signed_at, closed
  // the stub pad, and toasted "Signature saved" — with no API call, no draft
  // write and no storage of any kind. An admin was told a signature was saved
  // and shown one "on file", dated today, for a worker who had none.
  //
  // A stub must not manufacture evidence, and the missing piece here is not a
  // write to be filled in later: PUT /workers/{id} does not accept `signature`,
  // and a signature an admin draws is not the thing the record means. The
  // affordance is gone rather than disabled, so nobody mistakes it for a to-do.

  if (authLoading || loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container} edges={['top']}>
          <View style={s.loadingContainer}>
            <ActivityIndicator size="large" color={colors.text.primary} />
            <Text style={s.loadingText}>Loading worker...</Text>
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  // Load failed AND nothing cached for this worker — say that, rather than
  // rendering a blank profile that looks like a worker with no details.
  if (!worker) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container} edges={['top']}>
          <View style={s.header}>
            <View style={s.headerLeft}>
              <GlassButton
                variant="icon"
                icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
                onPress={() => router.back()}
              />
              <HeaderBrand />
            </View>
            <View style={s.headerRight}>
              <OfflineIndicator />
            </View>
          </View>
          <View style={s.scrollContent}>
            <OfflineNotice
              mode={detailState === 'error' ? 'error' : 'offline'}
              detail={
                detailState === 'error'
                  ? (detailError || 'Could not load this worker. Try again.')
                  : (detailError
                    ? `${detailError} This is NOT a statement that the worker has no SST card.`
                    : "This worker has not been opened on this device while online, so there is no saved copy. Reconnect to load their card. This is NOT a statement that the worker has no SST card.")
              }
            />
            <GlassButton
              title="Retry"
              onPress={() => {
                setLoading(true);
                fetchWorker().then(() => {
                  if (canViewOsha) fetchOshaData();
                });
              }}
              style={s.retryBtn}
            />
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        <View style={s.header}>
          <View style={s.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.back()}
            />
            <HeaderBrand />
          </View>
          <View style={s.headerRight}>
            <OfflineIndicator />
            {/* Editing is hidden on a cached/failed read: the record on screen
                may be stale and the write needs the network anyway. */}
            {isAdmin && !editMode && detailState === 'ok' && (
              <GlassButton
                variant="icon"
                icon={<Edit3 size={18} strokeWidth={1.5} color={colors.text.primary} />}
                onPress={() => setEditMode(true)}
              />
            )}
          </View>
        </View>

        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {detailState !== 'ok' && (
            <OfflineNotice
              mode={detailState}
              cachedCount={1}
              detail={
                detailState === 'error'
                  ? 'Could not refresh this worker. Showing the last saved copy from this device.'
                  : 'Offline — showing the copy saved on this device. Reconnect to refresh. Edits cannot be saved offline.'
              }
            />
          )}

          <GlassCard style={s.profileCard}>
            <View style={s.avatarContainer}>
              <View style={s.avatar}>
                <Text style={s.avatarText}>{name?.charAt(0) || 'W'}</Text>
              </View>
              {editMode && (
                <View style={s.editBadge}>
                  <Edit3 size={12} color="#fff" />
                </View>
              )}
            </View>

            {editMode ? (
              <View style={s.editForm}>
                <GlassInput
                  value={name}
                  onChangeText={setName}
                  placeholder="Full Name"
                  leftIcon={<User size={18} color={colors.text.subtle} />}
                />
                {/*
                  THE TRADE AND COMPANY INPUTS ARE GONE, and the payload with
                  them. They wrote a worker-level copy of a value that belongs
                  to the {worker, project} pair — the bleed worker_project_trades
                  exists to prevent — and they sat directly under a card reading
                  "No trade specified / No company", so the screen invited the
                  forbidden write at the moment an admin was most motivated to
                  make it.

                  REMOVED RATHER THAN DISABLED. Leaving a field the server now
                  ignores is worse than the write it replaced: the admin types a
                  company, taps Save, and is told "Worker information updated".
                */}
                <GlassInput
                  value={oshaNumber}
                  onChangeText={setOshaNumber}
                  placeholder="OSHA Number"
                  leftIcon={<FileText size={18} color={colors.text.subtle} />}
                  style={s.inputSpacing}
                />
                
                <View style={s.editActions}>
                  <GlassButton
                    title="Cancel"
                    onPress={() => {
                      setEditMode(false);
                      setName(worker?.name || '');
                      // No trade/company reset: there are no inputs that could
                      // have changed them. Resetting state the form cannot
                      // touch would imply the fields are still editable.
                      setOshaNumber(worker?.osha_number || worker?.oshaNumber || '');
                    }}
                    style={s.cancelBtn}
                  />
                  <GlassButton
                    title="Save Changes"
                    icon={<Save size={16} color={colors.text.primary} />}
                    onPress={handleSave}
                    loading={saving}
                  />
                </View>
              </View>
            ) : (
              <View style={s.profileInfo}>
                <Text style={s.workerName}>{name}</Text>
                {/*
                  ONE LINE, and it never says "No company".
                
                  These were two reads off the WORKERS document -- fields
                  nothing writes, because a trade belongs to the
                  {worker, project} pair. "No trade specified" reported a
                  designed absence as missing data, which is what sent an admin
                  to the edit form to write the worker-level copy the design
                  forbids.
                
                  The Building2 row goes with it: an icon for a company we are
                  not naming is decoration on an absence.
                */}
                <Text style={s.workerTrade}>{workerPairing}</Text>
                
                {oshaNumber ? (
                  <View style={s.infoRow}>
                    <FileText size={16} color={colors.text.muted} />
                    <Text style={s.infoText}>OSHA: {oshaNumber}</Text>
                  </View>
                ) : null}
              </View>
            )}
          </GlassCard>

          {canViewOsha && (
            <View style={s.section}>
              <View style={s.sectionHeader}>
                <View style={s.sectionTitleRow}>
                  <CreditCard size={20} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={s.sectionTitle}>OSHA / SST Card</Text>
                </View>
              </View>

              {loadingOsha ? (
                <GlassCard style={s.emptyCard}>
                  <ActivityIndicator size="small" color={colors.text.muted} />
                  <Text style={s.emptyText}>Loading OSHA data...</Text>
                </GlassCard>
              ) : oshaCardImage ? (
                <GlassCard style={s.oshaCard}>
                  <Pressable onPress={() => setShowOshaCard(true)}>
                    <Image
                      source={{ uri: oshaCardImage }}
                      style={s.oshaCardImage}
                      resizeMode="contain"
                    />
                    <Text style={s.oshaCardTapHint}>Tap to enlarge</Text>
                  </Pressable>

                  {oshaData && (
                    <View style={s.oshaFields}>
                      {oshaData.name && (
                        <View style={s.oshaFieldRow}>
                          <Text style={s.oshaFieldLabel}>Name</Text>
                          <Text style={s.oshaFieldValue}>{oshaData.name}</Text>
                        </View>
                      )}
                      {oshaData.osha_number && (
                        <View style={s.oshaFieldRow}>
                          <Text style={s.oshaFieldLabel}>OSHA #</Text>
                          <Text style={s.oshaFieldValue}>{oshaData.osha_number}</Text>
                        </View>
                      )}
                      {oshaData.sst_number && (
                        <View style={s.oshaFieldRow}>
                          <Text style={s.oshaFieldLabel}>SST #</Text>
                          <Text style={s.oshaFieldValue}>{oshaData.sst_number}</Text>
                        </View>
                      )}
                      {oshaData.trade && (
                        <View style={s.oshaFieldRow}>
                          <Text style={s.oshaFieldLabel}>Trade</Text>
                          <Text style={s.oshaFieldValue}>{oshaData.trade}</Text>
                        </View>
                      )}
                      {oshaData.expiration && (
                        <View style={s.oshaFieldRow}>
                          <Text style={s.oshaFieldLabel}>Expires</Text>
                          <Text style={[s.oshaFieldValue, expiryTone(oshaData.expiration)]}>
                            {oshaData.expiration}{expirySuffix(oshaData.expiration)}
                          </Text>
                        </View>
                      )}
                      {oshaData.training_provider && (
                        <View style={s.oshaFieldRow}>
                          <Text style={s.oshaFieldLabel}>Provider</Text>
                          <Text style={s.oshaFieldValue}>{oshaData.training_provider}</Text>
                        </View>
                      )}
                    </View>
                  )}
                </GlassCard>
              ) : oshaState !== 'ok' ? (
                // NEVER "No OSHA card on file" for a FAILED load — that asserts
                // to an inspector that the worker is uncertified.
                <OfflineNotice
                  mode={oshaState}
                  detail={
                    oshaState === 'error'
                      ? 'Could not load this card. This is not a statement that no card exists — try again.'
                      : "Card not saved on this device yet. Reconnect to load it. This is NOT a statement that the worker has no card."
                  }
                />
              ) : (
                <GlassCard style={s.emptyCard}>
                  <CreditCard size={32} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={s.emptyText}>No OSHA card on file</Text>
                  <Text style={s.emptySubtext}>Worker will upload during NFC check-in</Text>
                </GlassCard>
              )}

              {/* Card IS on screen but came from the cache — say so, so nobody
                  reads a stale expiry as freshly verified. */}
              {oshaState !== 'ok' && oshaCardImage && (
                <OfflineNotice
                  mode={oshaState}
                  cachedCount={1}
                  detail={
                    oshaState === 'error'
                      ? 'Could not refresh — this is the last saved copy of the card.'
                      : 'Offline — this is the copy of the card saved on this device. Reconnect to re-verify.'
                  }
                />
              )}

              {/* PR B: the SST credential is still flagged for review even after
                  a CP admits the check-in. Surfaced here beside the card. */}
              {flaggedCerts.length > 0 && (
                <GlassCard style={s.certReviewCard}>
                  <View style={s.certReviewHeader}>
                    <AlertTriangle size={14} strokeWidth={1.5} color={semantic.attention} />
                    <Text style={s.certReviewTitle}>Credential needs review</Text>
                  </View>
                  {flaggedCerts.map((c, i) => (
                    <Text key={i} style={s.certReviewText}>
                      • {CERT_REVIEW_REASON[c.review_reason] || 'Verify the card'}
                    </Text>
                  ))}
                </GlassCard>
              )}
            </View>
          )}

          {canViewOsha && (
            <View style={s.section}>
              <View style={s.sectionHeader}>
                <View style={s.sectionTitleRow}>
                  <ShieldCheck size={20} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={s.sectionTitle}>Safety Orientations</Text>
                </View>
              </View>

              {safetyOrientations.length > 0 ? (
                <View style={s.orientationList}>
                  {safetyOrientations.map((orientation, index) => (
                    <GlassCard key={index} style={s.orientationItem}>
                      <Pressable
                        style={s.orientationHeader}
                        onPress={() => setExpandedOrientation(expandedOrientation === index ? null : index)}
                      >
                        <View style={s.orientationInfo}>
                          <View style={s.orientationBadge}>
                            <ShieldCheck size={14} color={semantic.verified} />
                          </View>
                          <View style={{ flex: 1 }}>
                            <Text style={s.orientationProject}>
                              {orientation.project_name || 'Unknown Project'}
                            </Text>
                            <Text style={s.orientationDate}>
                              {orientation.completed_at
                                ? new Date(orientation.completed_at).toLocaleDateString()
                                : 'Date unknown'}
                            </Text>
                          </View>
                        </View>
                        {expandedOrientation === index ? (
                          <ChevronUp size={18} color={colors.text.muted} />
                        ) : (
                          <ChevronDown size={18} color={colors.text.muted} />
                        )}
                      </Pressable>

                      {expandedOrientation === index && orientation.checklist && (
                        <View style={s.checklistExpanded}>
                          {Object.entries(orientation.checklist).map(([item, val], i) => (
                            <View key={i} style={s.checklistItem}>
                              <View style={[
                                s.checkIcon,
                                val?.checked && s.checkIconChecked,
                              ]}>
                                {val?.checked && <Check size={12} color="#fff" />}
                              </View>
                              <Text style={s.checklistItemText}>{item}</Text>
                            </View>
                          ))}
                        </View>
                      )}
                    </GlassCard>
                  ))}
                </View>
              ) : oshaState !== 'ok' ? (
                // Same fetch as the card — a failure here is not "none exist".
                <OfflineNotice
                  mode={oshaState}
                  detail={
                    oshaState === 'error'
                      ? 'Could not load orientation records. This does not mean none exist.'
                      : 'Orientation records are not saved on this device. Reconnect to load them — this does not mean none exist.'
                  }
                />
              ) : (
                <GlassCard style={s.emptyCard}>
                  <ShieldCheck size={32} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={s.emptyText}>No safety orientations</Text>
                  <Text style={s.emptySubtext}>Completed during first NFC check-in at each site</Text>
                </GlassCard>
              )}
            </View>
          )}

          <View style={s.section}>
            <View style={s.sectionHeader}>
              <View style={s.sectionTitleRow}>
                <Award size={20} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={s.sectionTitle}>Certifications</Text>
              </View>
              {isAdmin && (
                <GlassButton
                  variant="icon"
                  icon={<Plus size={18} strokeWidth={1.5} color={colors.text.primary} />}
                  onPress={() => setShowAddCert(true)}
                />
              )}
            </View>

            {showAddCert && (
              <GlassCard style={s.addForm}>
                <GlassInput
                  value={newCertName}
                  onChangeText={setNewCertName}
                  placeholder="Certification name"
                />
                <GlassInput
                  value={newCertExpiry}
                  onChangeText={setNewCertExpiry}
                  placeholder="Expiry date (optional)"
                  leftIcon={<Calendar size={18} color={colors.text.subtle} />}
                  style={s.inputSpacing}
                />
                <View style={s.addFormButtons}>
                  <GlassButton
                    title="Cancel"
                    onPress={() => setShowAddCert(false)}
                  />
                  <GlassButton
                    title="Add"
                    onPress={handleAddCertification}
                  />
                </View>
              </GlassCard>
            )}

            {certifications.length > 0 ? (
              <View style={s.certList}>
                {certifications.map((cert, index) => (
                  <View key={index} style={s.certItem}>
                    <IconPod size={40}>
                      <Award size={18} strokeWidth={1.5} color={semantic.neutral} />
                    </IconPod>
                    <View style={s.certInfo}>
                      {/*
                        THE REAL KEYS. This read `cert.name` and `cert.expiry`,
                        and a stored certification carries NEITHER -- the model
                        is {type, card_number, expiration_date, ...} and pydantic
                        drops anything else, so even this screen's own add form
                        could not produce a cert it could render. Result: an
                        award icon, a blank line, and a delete button.

                        certLabel/certExpiration are the accessors oshaLogModel
                        already exports for exactly this bug. They handle the
                        legacy name/expiry fallbacks and map the stored enum to
                        a label a DOB inspector reads. NOT a sixth copy.
                      */}
                      <Text style={s.certName}>{certDisplayName(cert)}</Text>
                      {certExpiration(cert) ? (
                        <Text style={[s.certExpiry, expiryTone(certExpiration(cert))]}>
                          Expires: {certExpiration(cert)}{expirySuffix(certExpiration(cert))}
                        </Text>
                      ) : null}
                    </View>
                    {isAdmin && (
                      <Pressable onPress={() => handleDeleteCertification(index)} style={s.deleteBtn}>
                        <Trash2 size={16} strokeWidth={1.5} color={colors.status.error} />
                      </Pressable>
                    )}
                  </View>
                ))}
              </View>
            ) : (
              <GlassCard style={s.emptyCard}>
                <Award size={32} strokeWidth={1} color={colors.text.subtle} />
                <Text style={s.emptyText}>No certifications</Text>
              </GlassCard>
            )}
          </View>

          <View style={s.section}>
            <View style={s.sectionHeader}>
              <View style={s.sectionTitleRow}>
                <Pen size={20} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={s.sectionTitle}>Digital Signature</Text>
              </View>
            </View>

            <GlassCard style={s.signatureCard}>
              {signature ? (
                <>
<View style={s.signaturePreview}>
                    {(() => {
                      const sigUri = typeof signature === 'string'
                        ? signature
                        : signature?.data
                          ? `data:image/png;base64,${signature.data}`
                          : null;
                      return sigUri ? (
                        <Image source={{ uri: sigUri }} style={{ width: '100%', height: 150 }} resizeMode="contain" />
                      ) : null;
                    })()}
                    <Text style={s.signatureText}>✍️ Signature on file</Text>
                    {/* No "Updated: <date>" row. A stored signature is a bare
                        image carrying no timestamp of its own — server.py says
                        so on _worker_signature_signed_at — and neither
                        GET /workers/{id} nor /osha-card returns one. The date
                        that used to render here could only ever be the one the
                        removed stub minted a moment earlier. */}
                  </View>
                </>
              ) : (
                <>
                  <Text style={s.noSignatureText}>No signature on file</Text>
                  {/* Stated, not offered. A signature is captured at the gate
                      on the worker's own device when he registers; it cannot
                      be added from this screen, and an admin drawing it here
                      would be signing for another man. */}
                  <Text style={s.noSignatureHint}>
                    Captured at the jobsite gate when the worker registers.
                  </Text>
                </>
              )}
            </GlassCard>
          </View>
        </ScrollView>

        <Modal
          visible={showOshaCard}
          transparent={true}
          animationType="fade"
          onRequestClose={() => setShowOshaCard(false)}
        >
          <Pressable
            style={s.modalOverlay}
            onPress={() => setShowOshaCard(false)}
          >
            <View style={s.modalContent}>
              <Pressable style={s.modalClose} onPress={() => setShowOshaCard(false)}>
                <X size={24} color="#fff" />
              </Pressable>
              {oshaCardImage && (
                <Image
                  source={{ uri: oshaCardImage }}
                  style={s.modalImage}
                  resizeMode="contain"
                />
              )}
            </View>
          </Pressable>
        </Modal>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
  container: {
    flex: 1,
  },
  loadingContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.md,
  },
  loadingText: {
    color: colors.text.muted,
    fontSize: 14,
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
  headerRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
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
  profileCard: {
    alignItems: 'center',
    marginBottom: spacing.xl,
  },
  avatarContainer: {
    position: 'relative',
    marginBottom: spacing.lg,
  },
  avatar: {
    width: 100,
    height: 100,
    borderRadius: 50,
    backgroundColor: '#3b82f6',
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: {
    fontSize: 42,
    fontWeight: '300',
    color: '#fff',
  },
  editBadge: {
    position: 'absolute',
    bottom: 0,
    right: 0,
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: chrome.brand,
    alignItems: 'center',
    justifyContent: 'center',
  },
  profileInfo: {
    alignItems: 'center',
  },
  workerName: {
    fontSize: 28,
    fontWeight: '300',
    color: colors.text.primary,
    marginBottom: spacing.xs,
  },
  workerTrade: {
    fontSize: 16,
    color: colors.text.muted,
    marginBottom: spacing.md,
  },
  infoRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.xs,
  },
  infoText: {
    fontSize: 14,
    color: colors.text.secondary,
  },
  editForm: {
    width: '100%',
  },
  inputSpacing: {
    marginTop: spacing.sm,
  },
  editActions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: spacing.sm,
    marginTop: spacing.lg,
  },
  cancelBtn: {
    opacity: 0.7,
  },
  retryBtn: {
    marginTop: spacing.md,
    alignSelf: 'flex-start',
  },
  section: {
    marginBottom: spacing.xl,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.md,
  },
  sectionTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '500',
    color: colors.text.primary,
  },
  oshaCard: {
    gap: spacing.md,
  },
  oshaCardImage: {
    width: '100%',
    // Size the frame to the card's own proportions (~1.6:1, credit-card
    // ratio) instead of a fixed 200px box. With resizeMode="contain" that
    // fixed height letterboxed a full card down until the printed expiry
    // was too small to read; an aspect-ratio frame renders it legibly.
    aspectRatio: 1.6,
    borderRadius: borderRadius.md,
    backgroundColor: withAlpha('#ffffff', 0.03),
  },
  oshaCardTapHint: {
    fontSize: 11,
    color: colors.text.subtle,
    textAlign: 'center',
    marginTop: 4,
  },
  oshaFields: {
    borderTopWidth: 1,
    borderTopColor: withAlpha('#ffffff', 0.06),
    paddingTop: spacing.md,
    gap: spacing.sm,
  },
  oshaFieldRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  oshaFieldLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.text.muted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  oshaFieldValue: {
    fontSize: 14,
    color: colors.text.primary,
    fontWeight: '500',
  },
  orientationList: {
    gap: spacing.sm,
  },
  orientationItem: {
    padding: 0,
    overflow: 'hidden',
  },
  orientationHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: spacing.md,
  },
  orientationInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    flex: 1,
  },
  orientationBadge: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: semantic.verifiedBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  orientationProject: {
    fontSize: 15,
    fontWeight: '500',
    color: colors.text.primary,
  },
  orientationDate: {
    fontSize: 12,
    color: colors.text.muted,
    marginTop: 2,
  },
  checklistExpanded: {
    borderTopWidth: 1,
    borderTopColor: withAlpha('#ffffff', 0.06),
    padding: spacing.md,
    gap: 8,
  },
  checklistItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
  },
  checkIcon: {
    width: 20,
    height: 20,
    borderRadius: 4,
    borderWidth: 1.5,
    borderColor: withAlpha('#ffffff', 0.15),
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 1,
  },
  checkIconChecked: {
    backgroundColor: semantic.verified,
    borderColor: semantic.verified,
  },
  checklistItemText: {
    fontSize: 13,
    color: colors.text.secondary,
    flex: 1,
    lineHeight: 18,
  },
  emptyCard: {
    alignItems: 'center',
    paddingVertical: spacing.xl,
    gap: spacing.sm,
  },
  emptyText: {
    fontSize: 14,
    color: colors.text.muted,
  },
  emptySubtext: {
    fontSize: 12,
    color: colors.text.subtle,
  },
  addForm: {
    marginBottom: spacing.md,
  },
  addFormButtons: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  certList: {
    gap: spacing.sm,
  },
  certItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.md,
  },
  certInfo: {
    flex: 1,
  },
  certName: {
    fontSize: 15,
    fontWeight: '500',
    color: colors.text.primary,
  },
  certExpiry: {
    fontSize: 12,
    color: colors.text.muted,
  },
  certReviewCard: {
    marginTop: spacing.sm,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: semantic.attentionBorder,
    backgroundColor: semantic.attentionBg,
  },
  certReviewHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginBottom: spacing.xs,
  },
  certReviewTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: semantic.attention,
  },
  certReviewText: {
    fontSize: 13,
    color: colors.text.secondary,
  },
  deleteBtn: {
    padding: spacing.sm,
  },
  signatureCard: {
    alignItems: 'center',
    gap: spacing.md,
  },
  signaturePreview: {
    alignItems: 'center',
  },
  signatureText: {
    fontSize: 18,
    color: colors.text.primary,
    marginBottom: spacing.xs,
  },
  noSignatureText: {
    fontSize: 14,
    color: colors.text.muted,
  },
  noSignatureHint: {
    fontSize: 12,
    color: colors.text.subtle,
    textAlign: 'center',
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: withAlpha('#000000', 0.9),
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalContent: {
    width: '95%',
    height: '80%',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalClose: {
    position: 'absolute',
    top: 0,
    right: 0,
    zIndex: 10,
    padding: 12,
  },
  modalImage: {
    width: '100%',
    height: '100%',
  },
});
}
