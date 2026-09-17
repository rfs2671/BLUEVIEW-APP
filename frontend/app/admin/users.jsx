import React, { useState, useEffect, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  RefreshControl,
  Alert,
  Platform,
  Image,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  Users,
  Plus,
  Edit3,
  Trash2,
  Mail,
  Shield,
  ShieldAlert,
  FolderOpen,
  CheckCircle,
  HardHat,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import GlassInput from '../../src/components/GlassInput';
import FloatingNav from '../../src/components/FloatingNav';
import FormSheet from '../../src/components/FormSheet';
import OfflineNotice from '../../src/components/OfflineNotice';
import { settleFetch, isOfflineError } from '../../src/utils/offlineState';
import { useToast } from '../../src/components/Toast';
import { useAuth, isPlatformOperator } from '../../src/context/AuthContext';
import { adminUsersAPI, projectsAPI, versionAPI } from '../../src/utils/api';
import { isBehindMinimum } from '../../src/utils/clientVersion';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { semantic, withAlpha } from '../../src/styles/semanticColors';
import { retentionSentence, drainWarning, accessRemovedSentence } from '../../src/utils/retentionCopy';
import { useTheme } from '../../src/context/ThemeContext';
import HeaderBrand from '../../src/components/HeaderBrand';
import {
  ROLE_SUPERINTENDENT, roleLabel, roleHasLicence,
  licenceSentence, rolesAssignableBy,
} from '../../src/utils/roleVocabulary';
import DateInput from '../../src/components/DateInput';
import { dateEntryError, toStoredDate } from '../../src/utils/dateEntry';

export default function AdminUsersScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();

  // The floor this deploy supports, so a row can say whether an install is
  // below it. Null until it answers, and null means say nothing.
  const [clientFloor, setClientFloor] = useState(null);
  useEffect(() => {
    versionAPI.get()
      .then((v) => setClientFloor(v?.client_minimum_supported || null))
      .catch(() => { /* unknown is not behind */ });
  }, []);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [users, setUsers] = useState([]);
  const [projects, setProjects] = useState([]);

  // OFFLINE vs EMPTY — 'ok' | 'offline' | 'error'. The old `.catch(() => [])`
  // turned an unreachable server into a confident "No users found".
  const [fetchState, setFetchState] = useState('ok');
  const [projectsState, setProjectsState] = useState('ok');

  // ── THE FOUR SHEETS ────────────────────────────────────────────────────
  //
  // THESE NAMES USED TO BE A LIE, and it is worth recording because the next
  // person will read `showEditModal` and believe it. Until this change the
  // file opened no React Native Modal at all — a grep for the opening tag
  // returned zero, and it is spelled that way here on purpose, because
  // src/utils/modalHasAnExit.test.cjs counts opening tags in SOURCE TEXT and
  // would have counted this sentence as a fifth modal with no exit — and
  // all four of these flags gated a plain `{cond && <GlassCard>}` block
  // appended to the TAIL of the page's ScrollView, below the user list.
  //
  // On a laptop with three users that lands near the fold, which is why it
  // read as working for a year. On a phone the list is a screen-height of
  // cards and the form opened somewhere beneath all of them: the admin tapped
  // Edit, Registration or Assign and nothing appeared to happen. They are
  // FormSheets now — presented over the viewport, see
  // src/components/FormSheet.jsx.
  const [showAddModal, setShowAddModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showAssignModal, setShowAssignModal] = useState(false);
  const [selectedUser, setSelectedUser] = useState(null);

  // The field each sheet puts the caret in when it opens. A ref rather than
  // `autoFocus` because the sheet is a Modal: the input does not exist on the
  // render that sets `visible`, so the focus has to happen after the
  // presentation — FormSheet owns that timing for all of them.
  const addNameRef = useRef(null);
  const editNameRef = useRef(null);
  const firstProjectRef = useRef(null);

  // Form fields
  const [formName, setFormName] = useState('');
  const [formEmail, setFormEmail] = useState('');
  const [formPhone, setFormPhone] = useState('');
  const [formRole, setFormRole] = useState('cp');
  const [formPassword, setFormPassword] = useState('');
  const [assignedProjects, setAssignedProjects] = useState([]);
  // THE SUPERINTENDENT'S DOB REGISTRATION, on his own account rather than
  // retyped into every project's CS registration. Shown only while the picker
  // says `superintendent`; the server drops these fields for every other role
  // and $unsets them on a demotion, so a value typed and then switched away
  // from is never stored.
  const [formDobNumber, setFormDobNumber] = useState('');
  const [formDobExpiry, setFormDobExpiry] = useState('');
  // ── THE CS REGISTRATION, MOVED OFF ITS OWN TAB ──────────────────────────
  //
  // `csState` is null until the server answers. IT IS NEVER SEEDED FROM
  // `assigned_projects` OR FROM ANYTHING ELSE THE CLIENT ALREADY HAS: the
  // multi-select's initial value decides what the save DE-SELECTS, and a
  // de-selection soft-deletes the row that governs who may file BC 3301.13.13
  // on that project. A guess here is a guess about a statutory record.
  const [showCsModal, setShowCsModal] = useState(false);
  const [csState, setCsState] = useState(null);
  const [csLoading, setCsLoading] = useState(false);
  const [csSelected, setCsSelected] = useState([]);
  const [csSaving, setCsSaving] = useState(false);

  const isAdmin = user?.role === 'admin';

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchData();
    }
  }, [isAuthenticated]);

  const fetchData = async () => {
    // Fetch real data from API. settleFetch replaces `.catch(() => [])` so an
    // unreachable server is reported, not rendered as "no users".
    const [usersRes, projectsRes] = await Promise.all([
      settleFetch(() => adminUsersAPI.getAll()),
      settleFetch(() => projectsAPI.getAll()),
    ]);

    setFetchState(usersRes.status);
    if (usersRes.status === 'ok') {
      // ── EVERY ACCOUNT THIS SCREEN CAN CREATE, IT MUST ALSO SHOW ────────
      //
      // THIS READ `.filter(u => u.role !== 'admin')`, under a comment saying
      // "Only show CPs and workers". That was survivable while the picker
      // offered cp and worker. It is not now that "Admin" is one of the four
      // roles the picker offers: an admin created here VANISHED the moment the
      // list refreshed, and could then be neither edited, assigned a project,
      // nor deleted from any screen in the app.
      //
      // The self-edit guard is separate and stays -- `isSelf` disables Edit on
      // the caller's own row, which is the protection this filter was
      // accidentally providing for exactly one account.
      const filteredUsers = Array.isArray(usersRes.data) ? usersRes.data : [];
      setUsers(filteredUsers);
    } else {
      console.error('Failed to fetch users:', usersRes.error);
    }

    setProjectsState(projectsRes.status);
    if (projectsRes.status === 'ok') {
      setProjects(Array.isArray(projectsRes.data) ? projectsRes.data.map(p => ({
        id: p.id || p._id,
        name: p.name,
      })) : []);
    } else {
      console.error('Failed to fetch projects:', projectsRes.error);
    }

    if (usersRes.status === 'error' || projectsRes.status === 'error') {
      toast.error('Error', 'Could not load users');
    }

    setLoading(false);
    setRefreshing(false);
  };

  const onRefresh = () => {
    setRefreshing(true);
    fetchData();
  };

  const handleAddUser = async () => {
    if (!formName.trim() || !formEmail.trim() || !formPassword.trim()) {
      toast.error('Error', 'Please fill in all required fields');
      return;
    }
    // A DATE THE SERVER CANNOT READ IS NOT SENT. Stored, it reads back as
    // nothing and the row reports a missing registration NUMBER. The check is
    // the shared one every date field uses — src/utils/dateEntry.js.
    if (roleHasLicence(formRole) && dateEntryError(formDobExpiry)) {
      toast.error('Check the expiry', dateEntryError(formDobExpiry));
      return;
    }

    try {
      const payload = {
        name: formName,
        email: formEmail,
        role: formRole,
        password: formPassword,
      };
      if (formPhone.trim()) payload.phone = formPhone.trim();
      // ONLY FOR THE ROLE THAT HOLDS ONE. The server drops them for every
      // other role anyway; not sending them keeps the request honest about
      // what was asked for.
      if (roleHasLicence(formRole)) {
        if (formDobNumber.trim()) payload.dob_superintendent_number = formDobNumber.trim();
        // ISO, ALWAYS. The field shows MM/DD/YYYY; what is stored is what the
        // server's reader parses. A loaded '07/212029' becomes 2029-07-21 here
        // and only here — when Save is pressed.
        if (toStoredDate(formDobExpiry)) payload.dob_registration_expiry = toStoredDate(formDobExpiry);
      }
      await adminUsersAPI.create(payload);

      resetForm();
      setShowAddModal(false);
      toast.success('Added', 'User created successfully');
      // THE LIST IS RE-READ RATHER THAN APPENDED TO, for the reason the edit
      // path gives: `licence` is derived by the server and a row built from
      // the create response would carry a badge nobody computed. It is also
      // the only thing that shows a new superintendent in the right ORDER —
      // the list is sorted by name on the server, and an append puts him last.
      fetchData();
    } catch (error) {
      console.error('Failed to create user:', error);
      // Nothing is queued offline — be explicit that the user was NOT created.
      if (isOfflineError(error)) {
        toast.error('Offline', 'Creating a user needs a connection. Nothing was saved.');
      } else {
        toast.error('Error', error.response?.data?.detail || 'Could not create user');
      }
    }
  };

  const handleEditUser = async () => {
    if (!selectedUser) return;
    
    // PREVENT EDITING SELF
    if (selectedUser.id === user?.id || selectedUser.id === user?._id) {
      toast.error('Error', 'You cannot edit your own account');
      return;
    }
    // The same refusal as the Add path, for the same reason. This is the route
    // '07/212029' actually came through — and the route it now leaves by: the
    // form reads it as 07/21/2029, and Save sends 2029-07-21.
    if (roleHasLicence(formRole) && dateEntryError(formDobExpiry)) {
      toast.error('Check the expiry', dateEntryError(formDobExpiry));
      return;
    }

    try {
      const updatePayload = {
        name: formName,
        email: formEmail,
        role: formRole,
      };
      if (formPhone.trim()) updatePayload.phone = formPhone.trim();
      if (roleHasLicence(formRole)) {
        if (formDobNumber.trim()) updatePayload.dob_superintendent_number = formDobNumber.trim();
        if (toStoredDate(formDobExpiry)) updatePayload.dob_registration_expiry = toStoredDate(formDobExpiry);
      }
      await adminUsersAPI.update(selectedUser.id, updatePayload);

      resetForm();
      setShowEditModal(false);
      toast.success('Updated', 'User updated successfully');
      // ── THE CARD REFETCHES, IT DOES NOT PATCH ITSELF ───────────────────
      //
      // THIS PATCHED FOUR FIELDS IN LOCAL STATE and left every DERIVED field
      // stale — including `licence`, which is the block the DOB warning is
      // drawn from and which only the server computes. So saving a
      // registration number fixed the account and NOT the badge: the warning
      // stayed on screen until the admin pulled to refresh, which from the
      // device is indistinguishable from the save not having landed.
      //
      // IT COSTS NO NEW ENDPOINT. `USER_LIST_FIELDS` already projects the
      // number, the expiry and the card URL, and the badge is derived per row
      // inside GET /admin/users — so the list call the screen already makes
      // carries everything the badge reads.
      fetchData();
    } catch (error) {
      console.error('Failed to update user:', error);
      if (isOfflineError(error)) {
        toast.error('Offline', 'Saving needs a connection. Your changes were not saved.');
      } else {
        toast.error('Error', error.response?.data?.detail || 'Could not update user');
      }
    }
  };

  /**
   * THE SAME FACTS THE USER WAS SHOWN, FROM THE OTHER SIDE.
   *
   * An admin pressing this is ending somebody's access, and the two things he
   * must know first are what survives and what does not:
   *
   *   SURVIVES — every filed logbook, signature and check-in, with the man's
   *   name still on them. `users` is in the server's SOFT_DELETE_NEVER_PURGE
   *   set and deletion is a soft delete that stamps `deleted_user:<id>`, so a
   *   3301-02 signed by a departed CP still names its signer AND records that
   *   the account is gone. Nothing about the attestation changes.
   *
   *   DOES NOT — unsynced work on that person's handset. Once his token stops
   *   authenticating, the reconnect drain takes a 401, which the client reads
   *   as a server refusal; the drafts stay on the phone, bannered as
   *   "refused", and never land. This is the only sentence here that can save
   *   a signed compliance record, so it goes in front of the admin BEFORE the
   *   destructive action, not in a doc.
   */
  const deleteUserBody = (name) => {
    // THE SAME SENTENCE THE ACCOUNT HOLDER SAW, in the third person. NOT a
    // parallel wording — retentionCopy.js is the single definition, and two
    // wordings of one guarantee is how they drift apart.
    const who = name || 'This user';
    const NL = String.fromCharCode(10);
    return [
      accessRemovedSentence(who),
      retentionSentence(who),
      'Check first: ' + drainWarning(who),
    ].join(NL + NL);
  };

  const handleDeleteUser = (userId, userName) => {
    // PREVENT DELETING SELF
    if (userId === user?.id || userId === user?._id) {
      toast.error('Error', 'You cannot delete your own account');
      return;
    }
    
    const confirmDelete = async () => {
      try {
        await adminUsersAPI.delete(userId);
        setUsers(users.filter(u => u.id !== userId));
        toast.success('Deleted', 'User removed');
      } catch (error) {
        console.error('Failed to delete user:', error);
        if (isOfflineError(error)) {
          toast.error('Offline', 'Deleting needs a connection. The user was not deleted.');
        } else {
          toast.error('Error', error.response?.data?.detail || 'Could not delete user');
        }
      }
    };

    const body = deleteUserBody(userName);
    if (Platform.OS === 'web') {
      if (window.confirm(body)) {
        confirmDelete();
      }
    } else {
      Alert.alert('Delete account', body, [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete account', style: 'destructive', onPress: confirmDelete },
      ]);
    }
  };

  const handleAssignProjects = async () => {
    if (!selectedUser) return;
    
    try {
      await adminUsersAPI.assignProjects(selectedUser.id, assignedProjects);
      
      const updated = users.map(u => 
        u.id === selectedUser.id 
          ? { ...u, assigned_projects: assignedProjects }
          : u
      );
      
      setUsers(updated);
      setShowAssignModal(false);
      toast.success('Updated', 'Projects assigned');
    } catch (error) {
      console.error('Failed to assign projects:', error);
      if (isOfflineError(error)) {
        toast.error('Offline', 'Assigning projects needs a connection. Nothing was saved.');
      } else {
        toast.error('Error', 'Could not assign projects');
      }
    }
  };

  const toggleProjectAssignment = (projectId) => {
    setAssignedProjects(prev => 
      prev.includes(projectId)
        ? prev.filter(id => id !== projectId)
        : [...prev, projectId]
    );
  };

  const openEditModal = (userItem) => {
    // PREVENT EDITING SELF
    if (userItem.id === user?.id || userItem.id === user?._id) {
      toast.error('Error', 'You cannot edit your own account');
      return;
    }
    
    setSelectedUser(userItem);
    setFormName(userItem.name);
    setFormEmail(userItem.email);
    setFormPhone(userItem.phone || '');
    setFormRole(userItem.role);
    setFormDobNumber(userItem.dob_superintendent_number || '');
    setFormDobExpiry(userItem.dob_registration_expiry || '');
    setShowEditModal(true);
  };

  // Read what he is registered on TODAY, then show the picker. The modal
  // opens on a spinner rather than on an empty selection, because an empty
  // selection that the admin then saves is the delete-everything case.
  const openCsModal = async (userItem) => {
    setSelectedUser(userItem);
    setShowCsModal(true);
    setCsLoading(true);
    setCsState(null);
    setCsSelected([]);
    try {
      const data = await adminUsersAPI.getCsRegistrations(userItem.id);
      setCsState(data);
      setCsSelected(data.registered_project_ids || []);
    } catch (error) {
      console.error('Failed to load CS registrations:', error);
      toast.error(
        isOfflineError(error) ? 'Offline' : 'Error',
        'Could not read the current registrations. Nothing was changed.',
      );
      setShowCsModal(false);
    } finally {
      setCsLoading(false);
    }
  };

  const toggleCsProject = (projectId) => {
    setCsSelected((prev) => (prev.includes(projectId)
      ? prev.filter((id) => id !== projectId)
      : [...prev, projectId]));
  };

  const handleSaveCsRegistrations = async () => {
    if (!selectedUser || !csState) return;
    setCsSaving(true);
    try {
      const result = await adminUsersAPI.setCsRegistrations(selectedUser.id, csSelected);
      // THE ONE-JOB WARNING IS SHOWN, NOT SWALLOWED. The server does not refuse
      // a second active job — NYC DOB limits a CS to one, and the system's job
      // is to make the breach visible to the office rather than to block a
      // registration an admin may be making because the other job has ended.
      const warnings = result.conflict_warnings || [];
      if (warnings.length) {
        toast.error('One-job rule', warnings[0]);
      } else {
        toast.success('Saved', 'Registrations updated');
      }
      setShowCsModal(false);
      setCsState(null);
      fetchData();
    } catch (error) {
      console.error('Failed to save CS registrations:', error);
      toast.error(
        isOfflineError(error) ? 'Offline' : 'Error',
        error.response?.data?.detail
          || 'Could not save the registrations. Nothing was changed.',
      );
    } finally {
      setCsSaving(false);
    }
  };

  const openAssignModal = (userItem) => {
    setSelectedUser(userItem);
    setAssignedProjects(userItem.assigned_projects || []);
    setShowAssignModal(true);
  };

  const resetForm = () => {
    setFormName('');
    setFormEmail('');
    setFormPhone('');
    setFormRole('cp');
    setFormPassword('');
    setFormDobNumber('');
    setFormDobExpiry('');
    setSelectedUser(null);
  };

  // ONE PICKER, RENDERED TWICE. The Add and Edit modals each carried their own
  // hand-written pair of role buttons — the same roles, the same labels, two
  // copies. That is why "Worker" had to be deleted in two places and why
  // nothing could enumerate what the screen offers. The list is
  // src/utils/roleVocabulary.js now, and roleVocabulary.test.cjs holds it in
  // step with the server's allow-list.
  //
  // ── AND WHAT IT OFFERS DEPENDS ON WHO IS LOOKING ──────────────────────────
  //
  // A company admin manages PM, Superintendent and CP; admin accounts are the
  // platform operator's, created in the owner panel. Leaving "Admin" on his
  // picker would let him create an account that vanishes from this very list
  // on the next refresh — the #576 defect ("created users don't vanish")
  // arriving from the server end instead of the client one.
  //
  // THE SERVER REFUSES IT ANYWAY (`assert_role_assignable_by`, 403). This is
  // the courtesy half: a button that produces a refusal is a worse screen than
  // no button.
  const rolePickerOptions = rolesAssignableBy(isPlatformOperator(user));

  const renderRolePicker = () => {
    const chosen = rolePickerOptions.find((r) => r.value === formRole);
    return (
      <View style={s.roleSelectorBlock}>
        <Text style={s.roleSelectorLabel}>Role:</Text>
        <View style={s.roleSelector}>
          {rolePickerOptions.map((role) => (
            <Pressable
              key={role.value}
              onPress={() => setFormRole(role.value)}
              style={[s.roleOption, formRole === role.value && s.roleOptionActive]}
            >
              <Text style={[s.roleOptionText, formRole === role.value && s.roleOptionTextActive]}>
                {role.label}
              </Text>
            </Pressable>
          ))}
        </View>
        {/* WHAT THE ROLE ACTUALLY DOES, under the buttons. "PM" and "CP" are
            three-letter words, and an admin picking between four of them from
            the words alone is guessing at a permission grant. */}
        {chosen ? <Text style={s.roleBlurb}>{chosen.blurb}</Text> : null}
      </View>
    );
  };

  // ── THE EXPIRY, CHECKED WHILE HE TYPES IT ────────────────────────────────
  //
  // '07/212029' — '07/21/2029' with a slash missing — was typed into this
  // field, posted as free text, and SAVED. The server reads ISO, so it read
  // back as nothing at all, and the row then said "No DOB registration
  // recorded" about an account whose registration NUMBER was right there.
  //
  // From the device, a save that stores something unreadable is
  // indistinguishable from a save that failed. The operator typed it twice.
  //
  // THE FIELD IS THE SHARED DateInput NOW. He types digits on a number pad,
  // the slashes arrive by themselves, and an impossible date is named under
  // the field as he types it — the message comes from the component, which
  // asks the same src/utils/dateEntry.js the Save handlers above ask. There
  // is no second validator on this screen: PR #584's typed-ISO check would
  // have refused every value this field can produce.
  //
  // A STORED VALUE IS SHOWN READ, NOT WRITTEN. Opening Michael's account
  // shows 07/21/2029 with a note naming the stored '07/212029'. formDobExpiry
  // still holds '07/212029' until Save converts it, so opening and closing
  // the sheet writes nothing.

  // The licence block, shown only for the one role that holds a licence.
  const renderLicenceFields = () => {
    if (!roleHasLicence(formRole)) return null;
    return (
      <>
        <GlassInput
          value={formDobNumber}
          onChangeText={setFormDobNumber}
          placeholder="DOB registration number"
          autoCapitalize="characters"
          style={s.inputSpacing}
        />
        <DateInput
          as={GlassInput}
          value={formDobExpiry}
          onChange={setFormDobExpiry}
          placeholder="Registration expiry (MM/DD/YYYY)"
          accessibilityLabel="DOB registration expiry, month day year"
          palette={{ error: colors.status.error, hint: colors.text.muted }}
          style={s.inputSpacing}
        />
        {/* SAID OUT LOUD, because an admin who leaves it blank has not recorded
            "no expiry" — he has recorded nothing, and the row will read "DOB
            registration expiry not recorded" rather than looking valid. */}
        <Text style={s.licenceHint}>
          Warns {'≥'}30 days before expiry. Left blank, this account shows as
          unchecked rather than as valid.
        </Text>
      </>
    );
  };

  const formatPhoneDisplay = (phone) => {
    if (!phone) return '';
    const digits = phone.replace(/\D/g, '');
    if (digits.length === 11 && digits[0] === '1') {
      return `+1 (${digits.slice(1, 4)}) ${digits.slice(4, 7)}-${digits.slice(7)}`;
    }
    if (digits.length === 10) {
      return `+1 (${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
    }
    return phone;
  };

  const getRoleBadgeStyle = (role) => {
    switch (role) {
      case 'admin': return { bg: semantic.neutralBg, color: semantic.neutralStrong };
      case 'cp': return { bg: 'rgba(59, 130, 246, 0.2)', color: '#60a5fa' };
      // The two roles this screen can now create. Distinct colours, because a
      // list where three of four roles share one grey badge is a list where the
      // badge answers nothing.
      case ROLE_SUPERINTENDENT: return { bg: 'rgba(168, 85, 247, 0.2)', color: '#c084fc' };
      case 'pm': return { bg: 'rgba(245, 158, 11, 0.2)', color: '#fbbf24' };
      default: return { bg: withAlpha('#9ca3af', 0.2), color: '#9ca3af' };
    }
  };

  if (!isAdmin) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container} edges={['top']}>
          <View style={s.accessDenied}>
            <ShieldAlert size={56} strokeWidth={1} color={colors.status.error} />
            <Text style={s.accessDeniedTitle}>Admin Access Required</Text>
            <Text style={s.accessDeniedDesc}>
              Only administrators can access user management.
            </Text>
            <GlassButton
              title="Return to Dashboard"
              onPress={() => router.push('/')}
              style={s.returnBtn}
            />
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

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
          <View style={s.headerRight}>
            <GlassButton
              variant="icon"
              icon={<Plus size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => setShowAddModal(true)}
            />
          </View>
        </View>

        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.text.primary} />
          }
        >
          {/* Title */}
          <View style={s.titleSection}>
            <Text style={s.titleLabel}>ADMIN</Text>
            <View style={s.titleRow}>
              <Text style={s.titleText}>User Management</Text>
              <View style={s.countBadge}>
                <Text style={s.countText}>{users.length}</Text>
              </View>
            </View>
          </View>

          {loading ? (
            <View style={s.loadingContainer}>
              <ActivityIndicator size="large" color={colors.text.primary} />
            </View>
          ) : (
            <View style={s.usersList}>
              {users.map((userItem) => {
                const roleStyle = getRoleBadgeStyle(userItem.role);
                const isSelf = userItem.id === user?.id || userItem.id === user?._id;
                
                return (
                  <GlassCard key={userItem.id} style={s.userCard}>
                    <View style={s.userHeader}>
                      <View style={s.userAvatar}>
                        <Text style={s.userInitial}>{userItem.name?.charAt(0) || 'U'}</Text>
                      </View>
                      <View style={s.userInfo}>
                        <Text style={s.userName}>{userItem.name}</Text>
                        <Text style={s.userEmail}>{userItem.email}</Text>
                        {userItem.phone ? <Text style={s.userEmail}>{formatPhoneDisplay(userItem.phone)}</Text> : null}
                        {/* WHOSE PHONE IS STRANDED. A device below the
                            runtimeVersion floor receives no OTA at all and is
                            told nothing, so on 2026-08-28 a stale install
                            looked exactly like a server fault for a day. The
                            person who can act on it is an admin, not the CP
                            holding the phone, so the actionable version lives
                            here — on the row they already read — and the CP
                            gets only a non-blocking marker.
                            Silent when the version is current or unknown: an
                            install we cannot judge must not be accused. */}
                        {isBehindMinimum(userItem.client_version, clientFloor) ? (
                          <Text style={s.staleAppBadge}>
                            App v{userItem.client_version} — out of date, receives no updates
                          </Text>
                        ) : null}
                        {/* THE 30-DAY DOB REGISTRATION WARNING, ON THE ROW THE
                            ADMIN ALREADY READS. The verdict comes from the
                            server (`licence.state`) and is not recomputed here:
                            a second date calculation is a second answer to "has
                            it expired", and the two disagree on the day it
                            matters. Silent for a licence with months left, and
                            LOUD for one nobody has recorded — an unchecked
                            registration must not render like a valid one. */}
                        {(() => {
                          const note = licenceSentence(userItem.licence);
                          return note ? (
                            <Text style={note.tone === 'error' ? s.licenceExpired : s.licenceWarning}>
                              {note.text}
                            </Text>
                          ) : null;
                        })()}
                        {/* The request, where the admin already looks. It is a
                            field on the user's own row rather than a queue on
                            a screen nobody opens — an unread queue is the
                            "contact support" stall in another costume. */}
                        {userItem.deletion_requested_at ? (
                          <Text style={s.delRequestBadge}>
                            Requested deletion{' '}
                            {new Date(userItem.deletion_requested_at).toLocaleDateString(undefined, {
                              day: 'numeric', month: 'short',
                            })}
                          </Text>
                        ) : null}
                      </View>
                      <View style={[s.roleBadge, { backgroundColor: roleStyle.bg }]}>
                        <Text style={[s.roleText, { color: roleStyle.color }]}>
                          {roleLabel(userItem.role)}
                        </Text>
                      </View>
                    </View>

                    {userItem.assigned_projects?.length > 0 && (
                      <View style={s.projectsRow}>
                        <FolderOpen size={14} color={colors.text.muted} />
                        <Text style={s.projectsText}>
                          {userItem.assigned_projects.length} project(s) assigned
                        </Text>
                      </View>
                    )}

                    <View style={s.userActions}>
                      {/* ── ONE BUTTON OR THE OTHER, NEVER BOTH ───────────
                          A SUPERINTENDENT'S PROJECTS ARE HIS REGISTRATIONS.
                          Registering him on a job writes the cs_registrations
                          row AND assigns the project; unregistering retires
                          the row AND removes the assignment. Assign would be a
                          second writer of one side of that — a project on his
                          list with no registration behind it, which he can
                          open and cannot file on, because the BC 3301.13.13
                          gate keys on the REGISTRATION and never on the
                          assignment.

                          THE SERVER REFUSES IT TOO (POST /assign-projects and
                          PUT /admin/users both 422 for this role). Removing
                          the button is the courtesy; the refusal is the rule.

                          CP AND PM KEEP ASSIGN. They hold no registration, so
                          for them the assignment list IS the grant and this is
                          the only place it is written. */}
                      {roleHasLicence(userItem.role) ? (
                        <GlassButton
                          title="Registration"
                          icon={<HardHat size={14} color={colors.text.primary} />}
                          onPress={() => openCsModal(userItem)}
                          style={s.actionBtn}
                        />
                      ) : (
                        <GlassButton
                          title="Assign"
                          icon={<FolderOpen size={14} color={colors.text.primary} />}
                          onPress={() => openAssignModal(userItem)}
                          style={s.actionBtn}
                        />
                      )}
                      <GlassButton
                        title="Edit"
                        icon={<Edit3 size={14} color={colors.text.primary} />}
                        onPress={() => openEditModal(userItem)}
                        style={s.actionBtn}
                        disabled={isSelf}
                      />
                      <Pressable 
                        onPress={() => handleDeleteUser(userItem.id, userItem.name)}
                        style={[s.deleteBtn, isSelf && s.deleteBtnDisabled]}
                        disabled={isSelf}
                      >
                        <Trash2 size={16} color={isSelf ? colors.text.subtle : colors.status.error} />
                      </Pressable>
                    </View>
                  </GlassCard>
                );
              })}

              {users.length === 0 && fetchState !== 'ok' && (
                <OfflineNotice
                  mode={fetchState}
                  detail={fetchState === 'offline'
                    ? 'The user list could not be loaded because the server is unreachable. This does not mean there are no users.'
                    : undefined}
                />
              )}

              {users.length === 0 && fetchState === 'ok' && (
                <GlassCard style={s.emptyCard}>
                  <Users size={48} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={s.emptyText}>No users found</Text>
                  <GlassButton
                    title="Add User"
                    icon={<Plus size={16} color={colors.text.primary} />}
                    onPress={() => setShowAddModal(true)}
                  />
                </GlassCard>
              )}
            </View>
          )}
        </ScrollView>

        {/* ── THE FOUR SHEETS, AND WHY THEY SIT OUT HERE ────────────────────
            Siblings of the ScrollView, not children of it. That is not
            tidiness. Every one of these used to be the LAST CHILD of the
            scrolling list above, which is precisely what put them below the
            fold: a form whose mount point scrolls is a form the reader has to
            go and find. admin/safety-staff.jsx, admin/superintendent.jsx,
            admin/site-devices.jsx and admin/checklists/index.jsx all open
            theirs here too, after </ScrollView>.

            The role picker and the licence block below are CALLED as plain
            functions returning elements — deliberately, and the two call
            sites are counted by roleVocabulary.test.cjs, which is why this
            paragraph does not spell either name out. They are NOT components
            used as element types. That distinction is de2b330
            (#388): a component declared in a render body is a new function
            object every render, React compares element types by reference,
            and the whole subtree — TextInputs included — is destroyed and
            rebuilt on every keystroke. Calling a function that returns
            elements has no element type of its own and cannot do that. If
            either of these ever becomes a component, it moves to module
            scope and its captures become props. */}

        {/* Add User */}
        <FormSheet
          visible={showAddModal}
          title="Add New User"
          onClose={() => { setShowAddModal(false); resetForm(); }}
          initialFocusRef={addNameRef}
          footer={(
            <>
              <GlassButton
                title="Cancel"
                onPress={() => { setShowAddModal(false); resetForm(); }}
              />
              <GlassButton
                title="Add User"
                onPress={handleAddUser}
              />
            </>
          )}
        >
          <GlassInput
            ref={addNameRef}
            value={formName}
            onChangeText={setFormName}
            placeholder="Full Name"
          />
          <GlassInput
            value={formEmail}
            onChangeText={setFormEmail}
            placeholder="Email"
            keyboardType="email-address"
            leftIcon={<Mail size={18} color={colors.text.subtle} />}
            style={s.inputSpacing}
          />
          <GlassInput
            value={formPhone}
            onChangeText={setFormPhone}
            placeholder="Phone Number (optional)"
            keyboardType="phone-pad"
            style={s.inputSpacing}
          />
          <GlassInput
            value={formPassword}
            onChangeText={setFormPassword}
            placeholder="Password"
            secureTextEntry
            style={s.inputSpacing}
          />
          {renderRolePicker()}
          {renderLicenceFields()}
        </FormSheet>

        {/* Edit User */}
        <FormSheet
          visible={showEditModal}
          title="Edit User"
          onClose={() => { setShowEditModal(false); resetForm(); }}
          initialFocusRef={editNameRef}
          footer={(
            <>
              <GlassButton
                title="Cancel"
                onPress={() => { setShowEditModal(false); resetForm(); }}
              />
              <GlassButton
                title="Save"
                onPress={handleEditUser}
              />
            </>
          )}
        >
          <GlassInput
            ref={editNameRef}
            value={formName}
            onChangeText={setFormName}
            placeholder="Full Name"
          />
          <GlassInput
            value={formEmail}
            onChangeText={setFormEmail}
            placeholder="Email"
            keyboardType="email-address"
            style={s.inputSpacing}
          />
          <GlassInput
            value={formPhone}
            onChangeText={setFormPhone}
            placeholder="Phone Number (optional)"
            keyboardType="phone-pad"
            style={s.inputSpacing}
          />
          {renderRolePicker()}
          {renderLicenceFields()}
        </FormSheet>

        {/* ── CS REGISTRATION ───────────────────────────────────────
            WHERE A SUPERINTENDENT IS REGISTERED NOW. It used to be its own
            admin tab, which asked for his name and DOB licence number again
            for every project — the same two facts retyped per jobsite, with
            nothing reconciling the copies. They are facts about a PERSON and
            they live on his record; this picks the jobsites.

            NO initialFocusRef. This sheet deliberately opens on a spinner —
            the selection may not be seeded from anything the client already
            has — so at focus time there is no field to focus and the sheet
            itself takes it. */}
        <FormSheet
          visible={showCsModal}
          title="CS Registration"
          subtitle={`${selectedUser?.name || ''} — BC 3301.13.13 construction superintendent`}
          onClose={() => { setShowCsModal(false); setCsState(null); }}
          footer={(
            <>
              <GlassButton
                title="Cancel"
                onPress={() => { setShowCsModal(false); setCsState(null); }}
              />
              <GlassButton
                title={csSaving ? 'Saving…' : 'Save'}
                onPress={handleSaveCsRegistrations}
                disabled={csSaving || csLoading || !csState?.licence_number}
              />
            </>
          )}
        >
          {csLoading || !csState ? (
            <ActivityIndicator size="large" color={colors.text.primary} />
          ) : (
            <>
              {/* THE LICENCE THAT WILL BE WRITTEN, SHOWN BEFORE IT IS.
                  The server refuses without one, because
                  `license_number_normalized` is what the one-job conflict
                  query joins on — a registration with no number is
                  invisible to the check that exists to catch double-
                  jobbing. Saying so here beats a 422 the admin has to
                  decode. */}
              {csState.licence_number ? (
                <Text style={s.csLicence}>
                  DOB registration {csState.licence_number}
                </Text>
              ) : (
                <Text style={s.csBlocked}>
                  No DOB registration number on this account. Add it under
                  Edit before registering him on a project — the one-job
                  rule is checked on the licence number.
                </Text>
              )}

              <Text style={s.csSectionLabel}>REGISTERED ON</Text>
              {(csState.selectable || []).length === 0 ? (
                /* THE SENTENCE HAD TO CHANGE WITH THE RULING. It read
                   "Assign him first" — advice for a button that is no longer
                   on his card, pointing at a prerequisite that no longer
                   exists. The picker now offers the company's projects, so an
                   empty list means the COMPANY has none. */
                <Text style={s.csEmpty}>
                  This company has no projects yet. Create one first —
                  registering him on a job is also what assigns it to him.
                </Text>
              ) : (
                (csState.selectable || []).map((prj) => {
                  const on = csSelected.includes(prj.project_id);
                  return (
                    <Pressable
                      key={prj.project_id}
                      onPress={() => toggleCsProject(prj.project_id)}
                      style={[s.projectItem, s.projectItemSpacing, on && s.projectItemSelected]}
                    >
                      <Text style={s.projectItemName}>
                        {prj.name || prj.project_id}
                      </Text>
                      {on ? <CheckCircle size={18} color={semantic.verified} /> : null}
                    </Pressable>
                  );
                })
              )}

              {/* ROWS THIS SCREEN CANNOT TOUCH, NAMED RATHER THAN HIDDEN.
                  A registration on a project he is not assigned to cannot
                  appear in the list above, and the server deliberately
                  leaves it alone on save. Without this line the list would
                  silently omit a live registration and read as the whole
                  truth. */}
              {(csState.registered_elsewhere || []).length > 0 && (
                <Text style={s.csElsewhere}>
                  Also registered on{' '}
                  {(csState.registered_elsewhere || [])
                    .map((r) => r.name || r.project_id).join(', ')}
                  {' '}— outside this company's projects, so this screen
                  leaves those registrations alone.
                </Text>
              )}

              {/* BOTH SIDES OF THE ACT, SAID OUT LOUD. Ticking a project
                  registers him AND assigns it; unticking retires the
                  registration AND removes the assignment. The row itself is
                  soft-deleted and never hard-deleted — it is the provenance of
                  every log filed under it. */}
              <Text style={s.csHint}>
                Ticking a project registers him on it and assigns it to him.
                Unticking retires that registration and removes the
                assignment. The record is kept — logs already filed under it
                stay attributable.
              </Text>
            </>
          )}
        </FormSheet>

        {/* Assign Projects */}
        <FormSheet
          visible={showAssignModal}
          title="Assign Projects"
          subtitle={`Select projects for ${selectedUser?.name || ''}`}
          onClose={() => setShowAssignModal(false)}
          // THE FIRST ROW IS THE FIRST FIELD ON THIS ONE. There is no text
          // input here, so "focus the first field" means the first project
          // in the picker; with no projects to show the ref is null and
          // FormSheet falls back to the sheet itself.
          initialFocusRef={firstProjectRef}
          footer={(
            <>
              <GlassButton
                title="Cancel"
                onPress={() => setShowAssignModal(false)}
              />
              <GlassButton
                title="Save"
                onPress={handleAssignProjects}
              />
            </>
          )}
        >
          {projectsState !== 'ok' && (
            <OfflineNotice
              mode={projectsState}
              detail={projectsState === 'offline'
                ? 'The project list could not be loaded, so it may be incomplete. Saving an assignment also needs a connection.'
                : 'The project list could not be loaded, so it may be incomplete.'}
            />
          )}
          <View style={s.projectsList}>
            {projects.map((proj, i) => (
              <Pressable
                key={proj.id}
                ref={i === 0 ? firstProjectRef : null}
                onPress={() => toggleProjectAssignment(proj.id)}
                style={[
                  s.projectItem,
                  assignedProjects.includes(proj.id) && s.projectItemSelected,
                ]}
              >
                <Text style={s.projectItemName}>{proj.name}</Text>
                {assignedProjects.includes(proj.id) && (
                  <CheckCircle size={18} color={semantic.verified} />
                )}
              </Pressable>
            ))}
          </View>
        </FormSheet>

        <FloatingNav />
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
  container: {
    flex: 1,
  },
  accessDenied: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.xl,
    gap: spacing.md,
  },
  accessDeniedTitle: {
    fontSize: 22,
    fontWeight: '500',
    color: colors.text.primary,
    marginTop: spacing.md,
  },
  accessDeniedDesc: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
  },
  returnBtn: {
    marginTop: spacing.lg,
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
  titleSection: {
    marginBottom: spacing.xl,
  },
  titleLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.sm,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  titleText: {
    fontSize: 32,
    fontWeight: '200',
    color: colors.text.primary,
  },
  countBadge: {
    backgroundColor: colors.glass.background,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  countText: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text.primary,
  },
  loadingContainer: {
    paddingVertical: spacing.xxl,
    alignItems: 'center',
  },
  usersList: {
    gap: spacing.md,
  },
  userCard: {
    marginBottom: 0,
  },
  userHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginBottom: spacing.md,
  },
  userAvatar: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: '#3b82f6',
    alignItems: 'center',
    justifyContent: 'center',
  },
  userInitial: {
    fontSize: 20,
    fontWeight: '500',
    color: '#fff',
  },
  userInfo: {
    flex: 1,
  },
  userName: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
  },
  userEmail: {
    fontSize: 13,
    color: colors.text.muted,
  },
  // semantic.attention, not destructive: a stale install is a thing to fix,
  // not a thing that has gone wrong with this person's account.
  staleAppBadge: {
    fontSize: 12,
    fontWeight: '600',
    color: semantic.attention,
    marginTop: 2,
  },
  // The deletion request. semantic.attention rather than a destructive red:
  // the REQUEST is not the destructive act, the admin pressing delete is.
  delRequestBadge: {
    fontSize: 12,
    fontWeight: '600',
    color: semantic.attention,
    marginTop: 2,
  },
  // TWO TONES, because "expires in 12 days" and "EXPIRED" are not the same
  // fact. An expired DOB registration makes every log signed after it an
  // attestation by an unregistered person; that is an error state, not a
  // reminder.
  licenceWarning: {
    fontSize: 12,
    fontWeight: '600',
    color: semantic.attention,
    marginTop: 2,
  },
  licenceExpired: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.status.error,
    marginTop: 2,
  },
  csLicence: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.text.secondary,
    marginTop: spacing.sm,
  },
  csBlocked: {
    fontSize: 13,
    lineHeight: 18,
    fontWeight: '600',
    color: semantic.attention,
    marginTop: spacing.sm,
  },
  csSectionLabel: {
    fontSize: 11,
    letterSpacing: 1,
    color: colors.text.muted,
    marginTop: spacing.lg,
    marginBottom: spacing.sm,
  },
  csEmpty: {
    fontSize: 13,
    lineHeight: 18,
    color: colors.text.muted,
  },
  csElsewhere: {
    fontSize: 12,
    lineHeight: 17,
    color: semantic.attention,
    marginTop: spacing.md,
  },
  csHint: {
    fontSize: 12,
    lineHeight: 17,
    color: colors.text.muted,
    marginTop: spacing.md,
  },
  roleBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.sm,
  },
  roleText: {
    fontSize: 10,
    fontWeight: '600',
  },
  projectsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginBottom: spacing.md,
  },
  projectsText: {
    fontSize: 12,
    color: colors.text.muted,
  },
  userActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.glass.border,
    paddingTop: spacing.md,
  },
  actionBtn: {
    flex: 1,
  },
  deleteBtn: {
    padding: spacing.md,
    borderRadius: borderRadius.md,
    backgroundColor: colors.glass.background,
  },
  deleteBtnDisabled: {
    opacity: 0.3,
  },
  emptyCard: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
    gap: spacing.md,
  },
  emptyText: {
    fontSize: 16,
    color: colors.text.muted,
  },
  // `modal`, `modalTitle`, `modalSubtitle` and `modalActions` are GONE, not
  // left behind. `modal` was `marginTop: spacing.xl` — the entire presentation
  // those four forms had, which is to say a gap above a block in a list. The
  // title, the subtitle and the action row now belong to FormSheet, and a dead
  // style named `modal` sitting in this file is the next person's evidence
  // that something here is a modal.
  inputSpacing: {
    marginTop: spacing.sm,
  },
  roleSelectorBlock: {
    marginTop: spacing.md,
  },
  // WRAPS. Two roles fitted on one line; four do not, and on a phone the
  // fourth silently left the screen rather than moving to a second row.
  roleSelector: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: spacing.sm,
    marginTop: spacing.xs,
  },
  roleBlurb: {
    fontSize: 12,
    lineHeight: 17,
    color: colors.text.muted,
    marginTop: spacing.sm,
  },
  licenceHint: {
    fontSize: 12,
    lineHeight: 17,
    color: colors.text.muted,
    marginTop: spacing.xs,
  },
  roleSelectorLabel: {
    fontSize: 14,
    color: colors.text.muted,
  },
  roleOption: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.md,
    backgroundColor: colors.glass.background,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  roleOptionActive: {
    backgroundColor: 'rgba(59, 130, 246, 0.2)',
    borderColor: '#3b82f6',
  },
  roleOptionText: {
    fontSize: 13,
    color: colors.text.muted,
  },
  roleOptionTextActive: {
    color: '#60a5fa',
    fontWeight: '500',
  },
  projectsList: {
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  projectItem: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: spacing.md,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  // The CS picker's rows are not inside a gapped wrapper the way the Assign
  // picker's are — they sit between the section label and the elsewhere note —
  // so they carry their own separation rather than touching edge to edge.
  projectItemSpacing: {
    marginTop: spacing.sm,
  },
  projectItemSelected: {
    backgroundColor: semantic.verifiedBg,
    borderColor: semantic.verifiedBorder,
  },
  projectItemName: {
    fontSize: 14,
    color: colors.text.primary,
  },
});
}
