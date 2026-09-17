import React, { useState, useEffect } from 'react';
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
import OfflineNotice from '../../src/components/OfflineNotice';
import { settleFetch, isOfflineError } from '../../src/utils/offlineState';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { adminUsersAPI, projectsAPI, versionAPI } from '../../src/utils/api';
import { isBehindMinimum } from '../../src/utils/clientVersion';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { semantic, withAlpha } from '../../src/styles/semanticColors';
import { retentionSentence, drainWarning, accessRemovedSentence } from '../../src/utils/retentionCopy';
import { useTheme } from '../../src/context/ThemeContext';
import HeaderBrand from '../../src/components/HeaderBrand';
import {
  ASSIGNABLE_ROLES, ROLE_SUPERINTENDENT, roleLabel, roleHasLicence,
  licenceSentence,
} from '../../src/utils/roleVocabulary';

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

  // Modal states
  const [showAddModal, setShowAddModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showAssignModal, setShowAssignModal] = useState(false);
  const [selectedUser, setSelectedUser] = useState(null);
  
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
        if (formDobExpiry.trim()) payload.dob_registration_expiry = formDobExpiry.trim();
      }
      const newUser = await adminUsersAPI.create(payload);
      
      setUsers([...users, newUser]);
      resetForm();
      setShowAddModal(false);
      toast.success('Added', 'User created successfully');
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
    
    try {
      const updatePayload = {
        name: formName,
        email: formEmail,
        role: formRole,
      };
      if (formPhone.trim()) updatePayload.phone = formPhone.trim();
      if (roleHasLicence(formRole)) {
        if (formDobNumber.trim()) updatePayload.dob_superintendent_number = formDobNumber.trim();
        if (formDobExpiry.trim()) updatePayload.dob_registration_expiry = formDobExpiry.trim();
      }
      await adminUsersAPI.update(selectedUser.id, updatePayload);

      const updated = users.map(u =>
        u.id === selectedUser.id
          ? { ...u, name: formName, email: formEmail, role: formRole, phone: formPhone.trim() || u.phone }
          : u
      );
      
      setUsers(updated);
      resetForm();
      setShowEditModal(false);
      toast.success('Updated', 'User updated successfully');
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
  const renderRolePicker = () => {
    const chosen = ASSIGNABLE_ROLES.find((r) => r.value === formRole);
    return (
      <View style={s.roleSelectorBlock}>
        <Text style={s.roleSelectorLabel}>Role:</Text>
        <View style={s.roleSelector}>
          {ASSIGNABLE_ROLES.map((role) => (
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
        <GlassInput
          value={formDobExpiry}
          onChangeText={setFormDobExpiry}
          placeholder="Registration expiry (YYYY-MM-DD)"
          autoCapitalize="none"
          style={s.inputSpacing}
        />
        {/* SAID OUT LOUD, because an admin who leaves it blank has not recorded
            "no expiry" — he has recorded nothing, and the row will read "No DOB
            registration recorded" rather than looking valid. */}
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
                      <GlassButton
                        title="Assign"
                        icon={<FolderOpen size={14} color={colors.text.primary} />}
                        onPress={() => openAssignModal(userItem)}
                        style={s.actionBtn}
                      />
                      {/* ONLY FOR THE ROLE THAT HOLDS A REGISTRATION. An
                          admin or a CP has no DOB licence, so there is nothing
                          for this button to write. */}
                      {roleHasLicence(userItem.role) ? (
                        <GlassButton
                          title="Registration"
                          icon={<HardHat size={14} color={colors.text.primary} />}
                          onPress={() => openCsModal(userItem)}
                          style={s.actionBtn}
                        />
                      ) : null}
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

          {/* Add User Modal */}
          {showAddModal && (
            <GlassCard variant="modal" style={s.modal}>
              <Text style={s.modalTitle}>Add New User</Text>
              <GlassInput
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
              <View style={s.modalActions}>
                <GlassButton
                  title="Cancel"
                  onPress={() => { setShowAddModal(false); resetForm(); }}
                />
                <GlassButton
                  title="Add User"
                  onPress={handleAddUser}
                />
              </View>
            </GlassCard>
          )}

          {/* Edit User Modal */}
          {showEditModal && (
            <GlassCard variant="modal" style={s.modal}>
              <Text style={s.modalTitle}>Edit User</Text>
              <GlassInput
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
              <View style={s.modalActions}>
                <GlassButton
                  title="Cancel"
                  onPress={() => { setShowEditModal(false); resetForm(); }}
                />
                <GlassButton
                  title="Save"
                  onPress={handleEditUser}
                />
              </View>
            </GlassCard>
          )}

          {/* ── CS REGISTRATION MODAL ─────────────────────────────────
              WHERE A SUPERINTENDENT IS REGISTERED NOW. It used to be its own
              admin tab, which asked for his name and DOB licence number again
              for every project — the same two facts retyped per jobsite, with
              nothing reconciling the copies. They are facts about a PERSON and
              they live on his record; this picks the jobsites. */}
          {showCsModal && (
            <GlassCard variant="modal" style={s.modal}>
              <Text style={s.modalTitle}>CS Registration</Text>
              <Text style={s.modalSubtitle}>
                {selectedUser?.name} — BC 3301.13.13 construction superintendent
              </Text>

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
                    <Text style={s.csEmpty}>
                      He is not assigned to any project yet. Assign him first —
                      a superintendent can only be registered on a job he is
                      assigned to.
                    </Text>
                  ) : (
                    (csState.selectable || []).map((prj) => {
                      const on = csSelected.includes(prj.project_id);
                      return (
                        <Pressable
                          key={prj.project_id}
                          onPress={() => toggleCsProject(prj.project_id)}
                          style={[s.projectItem, on && s.projectItemSelected]}
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
                      {' '}— not assigned to him, so this screen leaves those
                      registrations alone.
                    </Text>
                  )}

                  {/* THE DELETE SIDE, SAID OUT LOUD. A removed project is
                      soft-deleted and never hard-deleted: the row is the
                      provenance of every log filed under it. */}
                  <Text style={s.csHint}>
                    Unticking a project retires that registration. The record is
                    kept — logs already filed under it stay attributable.
                  </Text>
                </>
              )}

              <View style={s.modalActions}>
                <GlassButton
                  title="Cancel"
                  onPress={() => { setShowCsModal(false); setCsState(null); }}
                />
                <GlassButton
                  title={csSaving ? 'Saving…' : 'Save'}
                  onPress={handleSaveCsRegistrations}
                  disabled={csSaving || csLoading || !csState?.licence_number}
                />
              </View>
            </GlassCard>
          )}

          {/* Assign Projects Modal */}
          {showAssignModal && (
            <GlassCard variant="modal" style={s.modal}>
              <Text style={s.modalTitle}>Assign Projects</Text>
              <Text style={s.modalSubtitle}>Select projects for {selectedUser?.name}</Text>
              {projectsState !== 'ok' && (
                <OfflineNotice
                  mode={projectsState}
                  detail={projectsState === 'offline'
                    ? 'The project list could not be loaded, so it may be incomplete. Saving an assignment also needs a connection.'
                    : 'The project list could not be loaded, so it may be incomplete.'}
                />
              )}
              <View style={s.projectsList}>
                {projects.map((proj) => (
                  <Pressable
                    key={proj.id}
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
              <View style={s.modalActions}>
                <GlassButton
                  title="Cancel"
                  onPress={() => setShowAssignModal(false)}
                />
                <GlassButton
                  title="Save"
                  onPress={handleAssignProjects}
                />
              </View>
            </GlassCard>
          )}
        </ScrollView>
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
  modal: {
    marginTop: spacing.xl,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: spacing.lg,
  },
  modalSubtitle: {
    fontSize: 14,
    color: colors.text.muted,
    marginBottom: spacing.md,
  },
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
  modalActions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: spacing.sm,
    marginTop: spacing.lg,
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
