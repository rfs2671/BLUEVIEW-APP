import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  Modal,
  KeyboardAvoidingView,
  Platform,
  Alert,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  LogOut,
  Building2,
  Plus,
  Edit3,
  Trash2,
  Users,
  AlertTriangle,
  X,
  Eye,
  ShieldAlert,
  CheckCircle,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import GlassInput from '../../src/components/GlassInput';
import GCAutocomplete from '../../src/components/GCAutocomplete';
import { GlassSkeleton } from '../../src/components/GlassSkeleton';
import FloatingNav from '../../src/components/FloatingNav';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import apiClient from '../../src/utils/api';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

// Owner password
const OWNER_PASSWORD = 'Asdddfgh1$';

// Owner API functions
const ownerAPI = {
  getCompanies: async () => {
    const response = await apiClient.get('/api/owner/companies');
    return response.data;
  },
  createCompany: async (companyData) => {
    const response = await apiClient.post('/api/owner/companies', companyData);
    return response.data;
  },
  getAdmins: async () => {
    const response = await apiClient.get('/api/owner/admins');
    return response.data;
  },
  createAdmin: async (adminData) => {
    const response = await apiClient.post('/api/owner/admins', adminData);
    return response.data;
  },
  deleteAdmin: async (adminId) => {
    const response = await apiClient.delete(`/api/owner/admins/${adminId}`);
    return response.data;
  },
  migrateData: async (assignments) => {
    const response = await apiClient.post('/api/admin/migrate-company-data', {
      assignments: assignments,
    });
    return response.data;
  },
};

export default function OwnerPortalScreen() {
  const router = useRouter();
  const { user, logout, isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  // Auth state
  const [ownerAuthenticated, setOwnerAuthenticated] = useState(false);
  const [password, setPassword] = useState('');

  // Data state
  const [loading, setLoading] = useState(false);
  const [companies, setCompanies] = useState([]);
  const [admins, setAdmins] = useState([]);
  const [unmigratedAdmins, setUnmigratedAdmins] = useState([]);

  // Modal states
  const [showCreateCompanyModal, setShowCreateCompanyModal] = useState(false);
  const [showCreateAdminModal, setShowCreateAdminModal] = useState(false);
  const [showCompanyAdminsModal, setShowCompanyAdminsModal] = useState(false);
  const [showMigrationModal, setShowMigrationModal] = useState(false);
  const [showDeleteCompanyModal, setShowDeleteCompanyModal] = useState(false);
  const [showDeleteAdminModal, setShowDeleteAdminModal] = useState(false);

  // Selected data
  const [selectedCompany, setSelectedCompany] = useState(null);
  const [selectedAdmin, setSelectedAdmin] = useState(null);
  const [companyAdmins, setCompanyAdmins] = useState([]);

  // Form fields
  const [formCompanyName, setFormCompanyName] = useState('');
  const [gcSelection, setGcSelection] = useState(null); // { license_number, business_name, ... } or null
  const [formAdminName, setFormAdminName] = useState('');
  const [formAdminEmail, setFormAdminEmail] = useState('');
  const [formAdminPassword, setFormAdminPassword] = useState('');
  const [formAdminCompanyId, setFormAdminCompanyId] = useState('');

  // Migration state
  const [migrationAssignments, setMigrationAssignments] = useState({});

  // Redirect if not logged in
  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (ownerAuthenticated && isAuthenticated) {
      fetchData();
    }
  }, [ownerAuthenticated, isAuthenticated]);

  const handleOwnerLogin = () => {
    if (password === OWNER_PASSWORD) {
      setOwnerAuthenticated(true);
      setPassword('');
      toast.success('Welcome', 'Owner portal access granted');
    } else {
      toast.error('Access Denied', 'Invalid owner password');
    }
  };

  const handleLogout = async () => {
    setOwnerAuthenticated(false);
    setPassword('');
    await logout();
    router.replace('/login');
  };

  const fetchData = async () => {
    setLoading(true);
    try {
      const [companiesData, adminsData] = await Promise.all([
        ownerAPI.getCompanies(),
        ownerAPI.getAdmins(),
      ]);

      setCompanies(Array.isArray(companiesData) ? companiesData : []);
      setAdmins(Array.isArray(adminsData) ? adminsData : []);

      // Find admins without company_id
      const unmigrated = adminsData.filter(a => !a.company_id);
      setUnmigratedAdmins(unmigrated);
    } catch (error) {
      console.error('Failed to fetch data:', error);
      toast.error('Error', 'Could not load data');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateCompany = async () => {
    if (!formCompanyName.trim()) {
      toast.error('Error', 'Company name is required');
      return;
    }

    try {
      const payload = { name: formCompanyName };
      if (gcSelection) {
        payload.gc_license_number = gcSelection.license_number;
        payload.gc_business_name = gcSelection.business_name;
        payload.gc_licensee_name = gcSelection.licensee_name;
        payload.gc_license_status = gcSelection.license_status;
        payload.gc_license_expiration = gcSelection.license_expiration;
        payload.gc_resolved = true;
      }
      const newCompany = await ownerAPI.createCompany(payload);
      setCompanies([...companies, newCompany]);
      setFormCompanyName('');
      setGcSelection(null);
      setShowCreateCompanyModal(false);
      toast.success('Created', gcSelection ? 'Company created with GC license linked' : 'Company created successfully');
    } catch (error) {
      console.error('Failed to create company:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not create company');
    }
  };

  const handleCreateAdmin = async () => {
    if (!formAdminName.trim() || !formAdminEmail.trim() || !formAdminPassword.trim() || !formAdminCompanyId) {
      toast.error('Error', 'All fields are required');
      return;
    }

    try {
      const selectedCompany = companies.find(c => c.id === formAdminCompanyId);
      const newAdmin = await ownerAPI.createAdmin({
        name: formAdminName,
        email: formAdminEmail,
        password: formAdminPassword,
        company_name: selectedCompany.name,
      });

      setAdmins([...admins, newAdmin]);
      resetAdminForm();
      setShowCreateAdminModal(false);
      toast.success('Created', 'Admin account created successfully');
    } catch (error) {
      console.error('Failed to create admin:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not create admin');
    }
  };

  const handleViewCompanyAdmins = (company) => {
    const companyAdminsList = admins.filter(a => a.company_id === company.id);
    setSelectedCompany(company);
    setCompanyAdmins(companyAdminsList);
    setShowCompanyAdminsModal(true);
  };

  const handleDeleteCompany = (company) => {
    const companyAdminsList = admins.filter(a => a.company_id === company.id);
    
    if (companyAdminsList.length > 0) {
      toast.error('Cannot Delete', `Company has ${companyAdminsList.length} admin(s). Remove admins first.`);
      return;
    }

    setSelectedCompany(company);
    setShowDeleteCompanyModal(true);
  };

  const confirmDeleteCompany = async () => {
  try {
    await apiClient.delete(`/api/owner/companies/${selectedCompany.id}`);
    setCompanies(companies.filter(c => c.id !== selectedCompany.id));
    toast.success('Deleted', 'Company deleted successfully');
  } catch (error) {
    console.error('Failed to delete company:', error);
    toast.error('Error', error.response?.data?.detail || 'Could not delete company');
  } finally {
    setShowDeleteCompanyModal(false);
    setSelectedCompany(null);
  }
};

  const handleDeleteAdmin = (admin) => {
    setSelectedAdmin(admin);
    setShowDeleteAdminModal(true);
  };

  const confirmDeleteAdmin = async () => {
    try {
      await ownerAPI.deleteAdmin(selectedAdmin.id);
      setAdmins(admins.filter(a => a.id !== selectedAdmin.id));
      toast.success('Deleted', 'Admin account deleted');
      setShowDeleteAdminModal(false);
      setSelectedAdmin(null);
    } catch (error) {
      console.error('Failed to delete admin:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not delete admin');
    }
  };

  const handleOpenMigration = () => {
    // Initialize migration assignments
    const initial = {};
    unmigratedAdmins.forEach(admin => {
      initial[admin.id] = '';
    });
    setMigrationAssignments(initial);
    setShowMigrationModal(true);
  };

  const handleMigrate = async () => {
    // Check all admins have company assigned
    const allAssigned = Object.values(migrationAssignments).every(id => id !== '');
    if (!allAssigned) {
      toast.error('Error', 'Please assign all admins to companies');
      return;
    }

    try {
      const assignments = Object.entries(migrationAssignments).map(([adminId, companyId]) => {
        const admin = unmigratedAdmins.find(a => a.id === adminId);
        return {
          admin_email: admin.email,
          company_id: companyId,
        };
      });

      const result = await ownerAPI.migrateData(assignments);
      
      toast.success('Success', 'Data migration completed');
      setShowMigrationModal(false);
      fetchData(); // Refresh data
    } catch (error) {
      console.error('Migration failed:', error);
      toast.error('Error', error.response?.data?.detail || 'Migration failed');
    }
  };

  const resetAdminForm = () => {
    setFormAdminName('');
    setFormAdminEmail('');
    setFormAdminPassword('');
    setFormAdminCompanyId('');
  };

  // If not authenticated with owner password
  if (!ownerAuthenticated) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container} edges={['top']}>
          <View style={styles.header}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/')}
            />
            <Text style={styles.logoText}>OWNER PORTAL</Text>
            <View style={{ width: 48 }} />
          </View>

          <View style={styles.centerContent}>
            <GlassCard style={styles.loginCard}>
              <IconPod size={64}>
                <ShieldAlert size={28} strokeWidth={1.5} color="#f59e0b" />
              </IconPod>
              <Text style={styles.loginTitle}>Owner Access</Text>
              <Text style={styles.loginSubtitle}>Enter owner password to continue</Text>

              <View style={styles.loginForm}>
                <GlassInput
                  value={password}
                  onChangeText={setPassword}
                  placeholder="Owner password"
                  secureTextEntry
                  onSubmitEditing={handleOwnerLogin}
                  autoFocus
                />
                <GlassButton
                  title="Access Portal"
                  onPress={handleOwnerLogin}
                  style={styles.loginButton}
                />
              </View>
            </GlassCard>
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container} edges={['top']}>
        {/* Header */}
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/')}
            />
            <Text style={styles.logoText}>OWNER PORTAL</Text>
          </View>
          <GlassButton
            variant="icon"
            icon={<LogOut size={20} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={handleLogout}
          />
        </View>

        <ScrollView
          style={styles.scrollView}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {/* Migration Banner */}
          {unmigratedAdmins.length > 0 && (
            <Pressable onPress={handleOpenMigration} style={styles.migrationBanner}>
              <AlertTriangle size={20} strokeWidth={1.5} color="#f59e0b" />
              <View style={styles.migrationText}>
                <Text style={styles.migrationTitle}>
                  ⚠️ You have {unmigratedAdmins.length} admin(s) without companies
                </Text>
                <Text style={styles.migrationSubtitle}>Tap to assign companies and migrate data</Text>
              </View>
            </Pressable>
          )}

          {/* Companies Section */}
          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <Text style={styles.sectionTitle}>Companies</Text>
              <GlassButton
                title="Create Company"
                icon={<Plus size={16} strokeWidth={1.5} color={colors.text.primary} />}
                onPress={() => setShowCreateCompanyModal(true)}
              />
            </View>

            {loading ? (
              <View style={styles.loadingContainer}>
                <GlassSkeleton width="100%" height={80} borderRadiusValue={borderRadius.xl} />
              </View>
            ) : companies.length > 0 ? (
              <View style={styles.companiesList}>
                {companies.map((company) => {
                  const companyAdminCount = admins.filter(a => a.company_id === company.id).length;
                  const hasGc = !!company.gc_license_number;
                  const gcStatus = (company.gc_license_status || '').toUpperCase();
                  const gcActive = gcStatus === 'ACTIVE';
                  const insRecords = company.gc_insurance_records || [];
                  const getInsColor = (expStr) => {
                    if (!expStr) return '#6b7280';
                    const d = new Date(expStr);
                    if (isNaN(d.getTime())) return '#6b7280';
                    const daysLeft = Math.ceil((d - new Date()) / (1000 * 60 * 60 * 24));
                    if (daysLeft < 0) return '#ef4444';
                    if (daysLeft <= 60) return '#f59e0b';
                    return '#22c55e';
                  };
                  const insGL = insRecords.find(r => r.insurance_type === 'general_liability');
                  const insWC = insRecords.find(r => r.insurance_type === 'workers_comp');
                  const insDB = insRecords.find(r => r.insurance_type === 'disability');
                  const fmtShort = (s) => {
                    if (!s) return '--';
                    const d = new Date(s);
                    if (isNaN(d.getTime())) return s.length > 10 ? s.slice(0, 10) : s;
                    return `${d.getMonth()+1}/${d.getDate()}/${String(d.getFullYear()).slice(2)}`;
                  };

                  return (
                    <GlassCard key={company.id} style={styles.companyCard}>
                      <View style={styles.companyHeader}>
                        <IconPod size={44}>
                          <Building2 size={18} strokeWidth={1.5} color={colors.text.secondary} />
                        </IconPod>
                        <View style={styles.companyInfo}>
                          <Text style={styles.companyName}>{company.name}</Text>
                          <Text style={styles.companyMeta}>
                            {companyAdminCount} admin{companyAdminCount !== 1 ? 's' : ''}
                          </Text>
                        </View>
                        <View style={styles.companyActions}>
                          <Pressable
                            onPress={() => handleViewCompanyAdmins(company)}
                            style={styles.actionBtn}
                          >
                            <Eye size={18} strokeWidth={1.5} color={colors.text.primary} />
                          </Pressable>
                          <Pressable
                            onPress={() => handleDeleteCompany(company)}
                            style={styles.actionBtn}
                          >
                            <Trash2 size={18} strokeWidth={1.5} color="#ef4444" />
                          </Pressable>
                        </View>
                      </View>

                      {/* GC License & Insurance info */}
                      {hasGc ? (
                        <View style={styles.gcInfoBlock}>
                          <View style={styles.gcLicenseRow}>
                            <Text style={[styles.gcLicenseText, { color: gcActive ? '#22c55e' : '#ef4444' }]}>
                              GC-{company.gc_license_number} · {gcStatus || 'Unknown'}
                            </Text>
                          </View>
                          {insRecords.length > 0 ? (
                            <View style={styles.gcInsuranceRow}>
                              <Text style={[styles.gcInsLabel, { color: getInsColor(insGL?.expiration_date) }]}>
                                GL: {fmtShort(insGL?.expiration_date)}
                              </Text>
                              <Text style={styles.gcInsSep}>|</Text>
                              <Text style={[styles.gcInsLabel, { color: getInsColor(insWC?.expiration_date) }]}>
                                WC: {fmtShort(insWC?.expiration_date)}
                              </Text>
                              <Text style={styles.gcInsSep}>|</Text>
                              <Text style={[styles.gcInsLabel, { color: getInsColor(insDB?.expiration_date) }]}>
                                DB: {fmtShort(insDB?.expiration_date)}
                              </Text>
                            </View>
                          ) : (
                            <Text style={styles.gcNoInsurance}>No insurance on file</Text>
                          )}
                        </View>
                      ) : company.gc_resolved === false && company.name ? (
                        <View style={styles.gcUnverifiedBlock}>
                          <AlertTriangle size={12} color="#f59e0b" />
                          <Text style={styles.gcUnverifiedText}>Unverified — not matched to DOB</Text>
                        </View>
                      ) : null}
                    </GlassCard>
                  );
                })}
              </View>
            ) : (
              <GlassCard style={styles.emptyCard}>
                <Building2 size={40} strokeWidth={1} color={colors.text.subtle} />
                <Text style={styles.emptyText}>No companies yet</Text>
                <Text style={styles.emptySubtext}>Create your first company to get started</Text>
              </GlassCard>
            )}
          </View>

          {/* Create Admin Section */}
          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <Text style={styles.sectionTitle}>Admin Accounts</Text>
              <GlassButton
                title="Create Admin"
                icon={<Plus size={16} strokeWidth={1.5} color={colors.text.primary} />}
                onPress={() => setShowCreateAdminModal(true)}
                disabled={companies.length === 0}
              />
            </View>

            {companies.length === 0 && (
              <View style={styles.infoBox}>
                <AlertTriangle size={16} strokeWidth={1.5} color="#f59e0b" />
                <Text style={styles.infoText}>Create a company first before adding admins</Text>
              </View>
            )}
          </View>
        </ScrollView>

        <FloatingNav />

        {/* Create Company Modal */}
        <Modal
          visible={showCreateCompanyModal}
          transparent
          animationType="slide"
          onRequestClose={() => setShowCreateCompanyModal(false)}
        >
          <KeyboardAvoidingView
            behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
            style={styles.modalOverlay}
          >
            <Pressable style={styles.modalBackdrop} onPress={() => setShowCreateCompanyModal(false)} />
            <View style={styles.modalContent}>
              <GlassCard variant="modal" style={styles.modalCard}>
                <View style={styles.modalHeader}>
                  <Text style={styles.modalTitle}>Create Company</Text>
                  <Pressable onPress={() => setShowCreateCompanyModal(false)}>
                    <X size={24} color={colors.text.primary} />
                  </Pressable>
                </View>

                <View style={styles.modalForm}>
                  <View style={[styles.inputGroup, { zIndex: 100 }]}>
                    <Text style={styles.inputLabel}>COMPANY NAME (GC LICENSE LOOKUP)</Text>
                    <GCAutocomplete
                      value={formCompanyName}
                      onChangeText={(text) => {
                        setFormCompanyName(text);
                        // If user edits after selecting, clear the selection
                        if (gcSelection && text !== gcSelection.business_name) {
                          setGcSelection(null);
                        }
                      }}
                      onSelect={(gc) => {
                        setGcSelection(gc);
                        setFormCompanyName(gc.business_name || '');
                      }}
                      placeholder="Search by GC company name..."
                    />
                    {gcSelection ? (
                      <View style={styles.gcLinkedBadge}>
                        <CheckCircle size={14} color="#22c55e" />
                        <Text style={styles.gcLinkedText}>
                          GC-{gcSelection.license_number} · {gcSelection.license_status || 'Active'}
                        </Text>
                      </View>
                    ) : formCompanyName.length > 0 ? (
                      <Text style={styles.gcUnlinkedText}>
                        No GC license selected — company will be created without DOB link
                      </Text>
                    ) : null}
                  </View>

                  <GlassButton
                    title="Create Company"
                    onPress={handleCreateCompany}
                    style={styles.submitButton}
                  />
                </View>
              </GlassCard>
            </View>
          </KeyboardAvoidingView>
        </Modal>

        {/* Create Admin Modal */}
        <Modal
          visible={showCreateAdminModal}
          transparent
          animationType="slide"
          onRequestClose={() => {
            setShowCreateAdminModal(false);
            resetAdminForm();
          }}
        >
          <KeyboardAvoidingView
            behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
            style={styles.modalOverlay}
          >
            <Pressable
              style={styles.modalBackdrop}
              onPress={() => {
                setShowCreateAdminModal(false);
                resetAdminForm();
              }}
            />
            <View style={styles.modalContent}>
              <GlassCard variant="modal" style={styles.modalCard}>
                <View style={styles.modalHeader}>
                  <Text style={styles.modalTitle}>Create Admin Account</Text>
                  <Pressable
                    onPress={() => {
                      setShowCreateAdminModal(false);
                      resetAdminForm();
                    }}
                  >
                    <X size={24} color={colors.text.primary} />
                  </Pressable>
                </View>

                <View style={styles.modalForm}>
                  <View style={styles.inputGroup}>
                    <Text style={styles.inputLabel}>COMPANY</Text>
                    <Pressable
                      onPress={() => {}} // Will be dropdown
                      style={styles.selectInput}
                    >
                      <Text style={styles.selectText}>
                        {formAdminCompanyId
                          ? companies.find(c => c.id === formAdminCompanyId)?.name
                          : 'Select company'}
                      </Text>
                    </Pressable>
                    <ScrollView style={styles.dropdown} nestedScrollEnabled>
                      {companies.map(company => (
                        <Pressable
                          key={company.id}
                          onPress={() => setFormAdminCompanyId(company.id)}
                          style={[
                            styles.dropdownItem,
                            formAdminCompanyId === company.id && styles.dropdownItemSelected,
                          ]}
                        >
                          <Text style={styles.dropdownText}>{company.name}</Text>
                        </Pressable>
                      ))}
                    </ScrollView>
                  </View>

                  <View style={styles.inputGroup}>
                    <Text style={styles.inputLabel}>ADMIN NAME</Text>
                    <GlassInput
                      value={formAdminName}
                      onChangeText={setFormAdminName}
                      placeholder="Full name"
                    />
                  </View>

                  <View style={styles.inputGroup}>
                    <Text style={styles.inputLabel}>EMAIL</Text>
                    <GlassInput
                      value={formAdminEmail}
                      onChangeText={setFormAdminEmail}
                      placeholder="admin@company.com"
                      keyboardType="email-address"
                      autoCapitalize="none"
                    />
                  </View>

                  <View style={styles.inputGroup}>
                    <Text style={styles.inputLabel}>PASSWORD</Text>
                    <GlassInput
                      value={formAdminPassword}
                      onChangeText={setFormAdminPassword}
                      placeholder="Create password"
                      secureTextEntry
                    />
                  </View>

                  <GlassButton
                    title="Create Admin"
                    onPress={handleCreateAdmin}
                    style={styles.submitButton}
                  />
                </View>
              </GlassCard>
            </View>
          </KeyboardAvoidingView>
        </Modal>

        {/* View Company Admins Modal */}
        <Modal
          visible={showCompanyAdminsModal}
          transparent
          animationType="slide"
          onRequestClose={() => setShowCompanyAdminsModal(false)}
        >
          <View style={styles.modalOverlay}>
            <Pressable style={styles.modalBackdrop} onPress={() => setShowCompanyAdminsModal(false)} />
            <View style={styles.modalContent}>
              <GlassCard variant="modal" style={styles.modalCard}>
                <View style={styles.modalHeader}>
                  <Text style={styles.modalTitle}>
                    {selectedCompany?.name} - Admins
                  </Text>
                  <Pressable onPress={() => setShowCompanyAdminsModal(false)}>
                    <X size={24} color={colors.text.primary} />
                  </Pressable>
                </View>

                <ScrollView style={styles.adminsList}>
                  {companyAdmins.length > 0 ? (
                    companyAdmins.map((admin) => (
                      <View key={admin.id} style={styles.adminItem}>
                        <View style={styles.adminInfo}>
                          <Text style={styles.adminName}>{admin.name}</Text>
                          <Text style={styles.adminEmail}>{admin.email}</Text>
                        </View>
                        <Pressable
                          onPress={() => {
                            setShowCompanyAdminsModal(false);
                            handleDeleteAdmin(admin);
                          }}
                          style={styles.deleteAdminBtn}
                        >
                          <Trash2 size={18} strokeWidth={1.5} color="#ef4444" />
                        </Pressable>
                      </View>
                    ))
                  ) : (
                    <Text style={styles.emptyText}>No admins in this company</Text>
                  )}
                </ScrollView>
              </GlassCard>
            </View>
          </View>
        </Modal>

        {/* Migration Modal */}
        <Modal
          visible={showMigrationModal}
          transparent
          animationType="slide"
          onRequestClose={() => setShowMigrationModal(false)}
        >
          <View style={styles.modalOverlay}>
            <Pressable style={styles.modalBackdrop} onPress={() => setShowMigrationModal(false)} />
            <View style={styles.modalContent}>
              <GlassCard variant="modal" style={styles.modalCard}>
                <View style={styles.modalHeader}>
                  <Text style={styles.modalTitle}>Migrate Admin Data</Text>
                  <Pressable onPress={() => setShowMigrationModal(false)}>
                    <X size={24} color={colors.text.primary} />
                  </Pressable>
                </View>

                <Text style={styles.migrationInstructions}>
                  Assign each admin to a company. Their projects, workers, and data will be moved to that company.
                </Text>

                <ScrollView style={styles.migrationList}>
                  {unmigratedAdmins.map((admin) => (
                    <View key={admin.id} style={styles.migrationItem}>
                      <View style={styles.migrationAdminInfo}>
                        <Text style={styles.migrationAdminName}>{admin.name}</Text>
                        <Text style={styles.migrationAdminEmail}>{admin.email}</Text>
                      </View>
                      <ScrollView style={styles.migrationDropdown} nestedScrollEnabled>
                        <Text style={styles.dropdownLabel}>Assign to:</Text>
                        {companies.map(company => (
                          <Pressable
                            key={company.id}
                            onPress={() =>
                              setMigrationAssignments({
                                ...migrationAssignments,
                                [admin.id]: company.id,
                              })
                            }
                            style={[
                              styles.dropdownItem,
                              migrationAssignments[admin.id] === company.id && styles.dropdownItemSelected,
                            ]}
                          >
                            <Text style={styles.dropdownText}>{company.name}</Text>
                            {migrationAssignments[admin.id] === company.id && (
                              <CheckCircle size={16} strokeWidth={1.5} color="#4ade80" />
                            )}
                          </Pressable>
                        ))}
                      </ScrollView>
                    </View>
                  ))}
                </ScrollView>

                <GlassButton
                  title="Migrate Data"
                  onPress={handleMigrate}
                  style={styles.submitButton}
                />
              </GlassCard>
            </View>
          </View>
        </Modal>

        {/* Delete Company Confirmation */}
        <Modal
          visible={showDeleteCompanyModal}
          transparent
          animationType="fade"
          onRequestClose={() => setShowDeleteCompanyModal(false)}
        >
          <View style={styles.modalOverlay}>
            <Pressable style={styles.modalBackdrop} onPress={() => setShowDeleteCompanyModal(false)} />
            <View style={styles.modalContent}>
              <GlassCard variant="modal" style={styles.confirmCard}>
                <IconPod size={64}>
                  <AlertTriangle size={28} strokeWidth={1.5} color="#ef4444" />
                </IconPod>
                <Text style={styles.confirmTitle}>Delete Company?</Text>
                <Text style={styles.confirmText}>
                  Are you sure you want to delete "{selectedCompany?.name}"?
                </Text>
                <View style={styles.confirmActions}>
                  <GlassButton
                    title="Cancel"
                    onPress={() => setShowDeleteCompanyModal(false)}
                    variant="secondary"
                  />
                  <GlassButton
                    title="Delete"
                    onPress={confirmDeleteCompany}
                    style={styles.deleteButton}
                  />
                </View>
              </GlassCard>
            </View>
          </View>
        </Modal>

        {/* Delete Admin Confirmation */}
        <Modal
          visible={showDeleteAdminModal}
          transparent
          animationType="fade"
          onRequestClose={() => setShowDeleteAdminModal(false)}
        >
          <View style={styles.modalOverlay}>
            <Pressable style={styles.modalBackdrop} onPress={() => setShowDeleteAdminModal(false)} />
            <View style={styles.modalContent}>
              <GlassCard variant="modal" style={styles.confirmCard}>
                <IconPod size={64}>
                  <AlertTriangle size={28} strokeWidth={1.5} color="#ef4444" />
                </IconPod>
                <Text style={styles.confirmTitle}>Delete Admin?</Text>
                <Text style={styles.confirmText}>
                  Are you sure you want to delete admin "{selectedAdmin?.name}"?
                </Text>
                <Text style={styles.confirmWarning}>
                  ⚠️ This will only delete the admin account. Their created projects and data will remain.
                </Text>
                <View style={styles.confirmActions}>
                  <GlassButton
                    title="Cancel"
                    onPress={() => setShowDeleteAdminModal(false)}
                    variant="secondary"
                  />
                  <GlassButton
                    title="Delete"
                    onPress={confirmDeleteAdmin}
                    style={styles.deleteButton}
                  />
                </View>
              </GlassCard>
            </View>
          </View>
        </Modal>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

const styles = StyleSheet.create({
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
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  logoText: {
    ...typography.label,
    fontSize: 11,
    letterSpacing: 2,
    color: colors.text.muted,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: spacing.lg,
  },
  centerContent: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: spacing.lg,
  },
  loginCard: {
    width: '100%',
    maxWidth: 400,
    alignItems: 'center',
    padding: spacing.xxl,
  },
  loginTitle: {
    fontSize: 24,
    fontWeight: '300',
    color: colors.text.primary,
    marginTop: spacing.lg,
  },
  loginSubtitle: {
    fontSize: 14,
    color: colors.text.muted,
    marginTop: spacing.xs,
    marginBottom: spacing.xl,
  },
  loginForm: {
    width: '100%',
    gap: spacing.md,
  },
  loginButton: {
    marginTop: spacing.sm,
  },
  migrationBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    backgroundColor: 'rgba(245, 158, 11, 0.1)',
    borderWidth: 1,
    borderColor: 'rgba(245, 158, 11, 0.3)',
    borderRadius: borderRadius.xl,
    padding: spacing.lg,
    marginBottom: spacing.lg,
  },
  migrationText: {
    flex: 1,
  },
  migrationTitle: {
    fontSize: 14,
    fontWeight: '500',
    color: '#f59e0b',
  },
  migrationSubtitle: {
    fontSize: 12,
    color: colors.text.muted,
    marginTop: spacing.xs,
  },
  section: {
    marginBottom: spacing.xl,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.lg,
  },
  sectionTitle: {
    fontSize: 20,
    fontWeight: '400',
    color: colors.text.primary,
  },
  loadingContainer: {
    paddingVertical: spacing.lg,
  },
  companiesList: {
    gap: spacing.md,
  },
  companyCard: {
    marginBottom: 0,
  },
  companyHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  companyInfo: {
    flex: 1,
  },
  companyName: {
    fontSize: 18,
    fontWeight: '500',
    color: colors.text.primary,
  },
  companyMeta: {
    fontSize: 13,
    color: colors.text.muted,
    marginTop: spacing.xs,
  },
  companyActions: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  actionBtn: {
    padding: spacing.sm,
  },
  // GC info on company cards
  gcInfoBlock: {
    marginTop: spacing.sm,
    paddingTop: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255,255,255,0.06)',
  },
  gcLicenseRow: {
    marginBottom: 4,
  },
  gcLicenseText: {
    fontSize: 12,
    fontWeight: '600',
  },
  gcInsuranceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  gcInsLabel: {
    fontSize: 11,
    fontWeight: '500',
  },
  gcInsSep: {
    fontSize: 11,
    color: 'rgba(255,255,255,0.2)',
  },
  gcNoInsurance: {
    fontSize: 11,
    color: colors.text.subtle,
    fontStyle: 'italic',
  },
  gcUnverifiedBlock: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginTop: spacing.sm,
    paddingTop: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255,255,255,0.06)',
  },
  gcUnverifiedText: {
    fontSize: 11,
    color: '#f59e0b',
  },
  // GC in create company modal
  gcLinkedBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginTop: 8,
  },
  gcLinkedText: {
    fontSize: 12,
    color: '#22c55e',
    fontWeight: '500',
  },
  gcUnlinkedText: {
    fontSize: 11,
    color: colors.text.subtle,
    marginTop: 6,
  },
  emptyCard: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
    gap: spacing.md,
  },
  emptyText: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.muted,
  },
  emptySubtext: {
    fontSize: 13,
    color: colors.text.subtle,
  },
  infoBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: 'rgba(245, 158, 11, 0.1)',
    borderWidth: 1,
    borderColor: 'rgba(245, 158, 11, 0.3)',
    borderRadius: borderRadius.lg,
    padding: spacing.md,
  },
  infoText: {
    flex: 1,
    fontSize: 13,
    color: colors.text.secondary,
  },
  modalOverlay: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalBackdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
  },
  modalContent: {
    width: '90%',
    maxWidth: 500,
    maxHeight: '80%',
  },
  modalCard: {
    padding: spacing.xl,
  },
  modalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.lg,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: '500',
    color: colors.text.primary,
  },
  modalForm: {
    gap: spacing.md,
  },
  inputGroup: {
    gap: spacing.xs,
  },
  inputLabel: {
    ...typography.label,
    fontSize: 11,
    color: colors.text.muted,
  },
  selectInput: {
    backgroundColor: colors.glass.background,
    borderWidth: 1,
    borderColor: colors.glass.border,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
  },
  selectText: {
    fontSize: 15,
    color: colors.text.primary,
  },
  dropdown: {
    maxHeight: 150,
    marginTop: spacing.xs,
  },
  dropdownItem: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: spacing.md,
    backgroundColor: colors.glass.background,
    borderWidth: 1,
    borderColor: colors.glass.border,
    borderRadius: borderRadius.md,
    marginBottom: spacing.xs,
  },
  dropdownItemSelected: {
    borderColor: '#4ade80',
    backgroundColor: 'rgba(74, 222, 128, 0.1)',
  },
  dropdownText: {
    fontSize: 14,
    color: colors.text.primary,
  },
  dropdownLabel: {
    ...typography.label,
    fontSize: 10,
    color: colors.text.muted,
    marginBottom: spacing.xs,
  },
  submitButton: {
    marginTop: spacing.md,
  },
  adminsList: {
    maxHeight: 400,
  },
  adminItem: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: spacing.md,
    backgroundColor: colors.glass.background,
    borderWidth: 1,
    borderColor: colors.glass.border,
    borderRadius: borderRadius.lg,
    marginBottom: spacing.sm,
  },
  adminInfo: {
    flex: 1,
  },
  adminName: {
    fontSize: 15,
    fontWeight: '500',
    color: colors.text.primary,
  },
  adminEmail: {
    fontSize: 13,
    color: colors.text.muted,
    marginTop: spacing.xs,
  },
  deleteAdminBtn: {
    padding: spacing.sm,
  },
  migrationInstructions: {
    fontSize: 14,
    color: colors.text.secondary,
    marginBottom: spacing.lg,
  },
  migrationList: {
    maxHeight: 400,
    marginBottom: spacing.lg,
  },
  migrationItem: {
    padding: spacing.md,
    backgroundColor: colors.glass.background,
    borderWidth: 1,
    borderColor: colors.glass.border,
    borderRadius: borderRadius.lg,
    marginBottom: spacing.md,
  },
  migrationAdminInfo: {
    marginBottom: spacing.md,
  },
  migrationAdminName: {
    fontSize: 15,
    fontWeight: '500',
    color: colors.text.primary,
  },
  migrationAdminEmail: {
    fontSize: 13,
    color: colors.text.muted,
    marginTop: spacing.xs,
  },
  migrationDropdown: {
    maxHeight: 120,
  },
  confirmCard: {
    alignItems: 'center',
    padding: spacing.xxl,
  },
  confirmTitle: {
    fontSize: 20,
    fontWeight: '500',
    color: colors.text.primary,
    marginTop: spacing.lg,
  },
  confirmText: {
    fontSize: 14,
    color: colors.text.secondary,
    textAlign: 'center',
    marginTop: spacing.sm,
  },
  confirmWarning: {
    fontSize: 12,
    color: '#f59e0b',
    textAlign: 'center',
    marginTop: spacing.md,
  },
  confirmActions: {
    flexDirection: 'row',
    gap: spacing.md,
    marginTop: spacing.xl,
    width: '100%',
  },
  deleteButton: {
    backgroundColor: 'rgba(239, 68, 68, 0.2)',
    borderColor: '#ef4444',
  },
});
