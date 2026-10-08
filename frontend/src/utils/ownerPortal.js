/**
 * OWNER PORTAL (platform operator only): what the portal's nav, company users
 * screen and Deleted items tab SAY, from what the server returned. Pure and
 * tested (ownerPortal.test.cjs); the screens only fetch and draw.
 *
 * The server is the boundary: every /api/owner route answers 404 to anyone
 * who is not the operator. Nothing here decides access.
 */

// The portal's own nav. It replaces the app's sidebar and tab bar on every
// /owner screen; "Back to app" (OwnerNav) returns to the normal app.
export const OWNER_NAV = [
  { key: 'companies', label: 'Companies', path: '/owner' },
  { key: 'deleted', label: 'Deleted items', path: '/owner/deleted' },
  { key: 'pending', label: 'Pending deletion', path: '/owner/pending-deletion' },
];

export function ownerNavActive(pathname) {
  const p = String(pathname || '');
  if (p.startsWith('/owner/deleted')) return 'deleted';
  if (p.startsWith('/owner/pending-deletion')) return 'pending';
  if (p === '/owner' || p.startsWith('/owner/company')) return 'companies';
  return null;
}

export const ROLE_LABEL = {
  admin: 'Admin',
  pm: 'Project manager',
  superintendent: 'Superintendent',
  cp: 'Competent person',
  worker: 'Worker',
  demo: 'Demo',
  owner: 'Owner (retired)',
};

export function roleLabel(role) {
  const r = String(role || '').trim().toLowerCase();
  return ROLE_LABEL[r] || (r ? r : 'No role');
}

const isAdmin = (u) => String(u?.role || '').trim().toLowerCase() === 'admin';

/**
 * What the operator may do to one user on the company screen. The server
 * refuses the same things (409 LAST_ADMIN); this only keeps the screen from
 * offering a button the server will refuse.
 */
export function userActions(user, users) {
  const list = Array.isArray(users) ? users : [];
  const admins = list.filter(isAdmin);
  const onlyAdmin = isAdmin(user) && admins.length <= 1;
  return {
    canRemove: !onlyAdmin,
    // Changing an only admin's role to anything but admin would leave none.
    canChangeRole: !onlyAdmin,
    lockedReason: onlyAdmin ? "Only admin — make someone else an admin first" : null,
  };
}

/** The add-admin form: what to send, or why not yet. */
export function addAdminRequest({ email, name, password }) {
  const e = String(email || '').trim();
  if (!e || !e.includes('@')) return { error: 'Enter an email address.' };
  const body = { email: e };
  const n = String(name || '').trim();
  if (n) body.name = n;
  if (password) body.password = password;
  return { body };
}

export const KIND_LABEL = { company: 'Company', project: 'Project', user: 'User' };

export const DELETED_FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'company', label: 'Companies' },
  { key: 'project', label: 'Projects' },
  { key: 'user', label: 'Users' },
];

export function filterDeleted(items, kind) {
  const list = Array.isArray(items) ? items : [];
  return kind && kind !== 'all' ? list.filter((r) => r.kind === kind) : list;
}

function fmtWhen(at) {
  if (!at) return 'unknown date';
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return String(at);
  return d.toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
}

/**
 * One Deleted items row, as text: type, name/address, company, deleted by,
 * deleted at. A project an admin MARKED (not yet deleted) says so.
 */
export function deletedRowView(row) {
  const r = row || {};
  const kind = KIND_LABEL[r.kind] || r.kind || '';
  const badge = r.kind === 'project' && r.state === 'marked'
    ? 'Marked for deletion' : 'Deleted';
  const hard = r.hard_delete || {};
  return {
    key: `${r.kind}:${r.id}`,
    kind,
    badge,
    name: r.name || r.id || '',
    company: r.kind === 'company' ? null : (r.company_name || 'No company'),
    by: r.deleted_by_name || r.deleted_by || 'Unknown',
    at: fmtWhen(r.deleted_at),
    role: r.kind === 'user' && r.role ? roleLabel(r.role) : null,
    hardDeleteEnabled: hard.enabled === true,
    hardDeleteReason: hard.enabled === true ? null
      : (hard.reason || 'Pending delete-service fix'),
  };
}

const COLLECTION_LABEL = {
  dob_logs: 'DOB records',
  checkins: 'Check-ins',
  logbooks: 'Logbooks',
  logbook_entries: 'Logbook entries',
  nfc_tags: 'NFC tags',
  project_files: 'Files',
  daily_logs: 'Daily logs',
  daily_log_photos: 'Daily log photos',
  checklists: 'Checklists',
  projects: 'Projects',
  live_projects: 'Live projects',
  users: 'Users',
  workers: 'Workers',
};

/** The preview modal: counts per collection, R2 files, and what blocks it. */
export function previewView(p) {
  const out = p || {};
  const counts = Object.entries(out.counts || {})
    .filter(([, n]) => typeof n === 'number' && n !== 0)
    .map(([k, n]) => ({ key: k, label: COLLECTION_LABEL[k] || k,
                        value: n < 0 ? 'unknown' : String(n) }))
    .sort((a, b) => a.label.localeCompare(b.label));
  const r2 = out.r2_files || {};
  const r2Lines = [];
  if (typeof r2.project_files === 'number') {
    r2Lines.push(`${r2.project_files} stored file${r2.project_files === 1 ? '' : 's'}`);
  }
  if (typeof r2.indexed_pages === 'number' && r2.indexed_pages > 0) {
    r2Lines.push(`${r2.indexed_pages} indexed page${r2.indexed_pages === 1 ? '' : 's'}`);
  }
  return {
    title: out.name || '',
    counts,
    empty: counts.length === 0,
    r2: r2Lines,
    blocking: (out.blocking || []).map((b) => b.reason || b.kind),
    note: 'Preview only. Nothing was deleted.',
  };
}

/** What a restore brought back, as one sentence. */
export function restoreSummary(res) {
  const c = (res && res.children) || {};
  const parts = [];
  const add = (n, one, many) => { if (n) parts.push(`${n} ${n === 1 ? one : many}`); };
  add(c.users, 'user', 'users');
  add(c.projects, 'project', 'projects');
  add(c.companies, 'company', 'companies');
  add(c.nfc_tags, 'NFC tag', 'NFC tags');
  return parts.length ? `Also restored: ${parts.join(', ')}.` : 'Restored.';
}

/** A refusal from the server, in the words it sent. */
export function serverMessage(error, fallback) {
  const d = error?.response?.data?.detail;
  if (d && typeof d === 'object' && d.message) return d.message;
  if (typeof d === 'string' && d) return d;
  return fallback || 'Something went wrong. Try again.';
}
