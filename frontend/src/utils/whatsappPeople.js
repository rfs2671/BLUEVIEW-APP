/**
 * Project → WhatsApp → People: what the screen says for the server's answers.
 * Pure, tested under plain node (whatsappPeople.test.cjs).
 *
 * Group senders mostly arrive with a WhatsApp privacy id that matches no phone
 * on file. An admin or PM says who each one is — a name and their company on
 * the job — once per company; every group of the company uses it, and the
 * Attention list names them from then on. Nothing is sent to anyone.
 * (GET/PUT/DELETE /api/projects/{id}/whatsapp/people[/{key}])
 */

export const PEOPLE_TITLE = 'People';
export const PEOPLE_NOTE =
  'People writing in your groups whom Levelog can’t match to anyone on file. '
  + 'Say who they are once and every group of your company uses it. '
  + 'Nobody is messaged.';

export const GC_TEAM = 'GC team';

export function emptyText(state) {
  return state === 'none' ? 'Everyone writing in your groups is matched to a person.' : '';
}

/** "Not assigned" or "Carlos Baez · Bright Electric". */
export function assignmentLine(row) {
  const a = row && row.assigned;
  if (!a) return 'Not assigned';
  return a.sub_company ? `${a.person_name} · ${a.sub_company}` : a.person_name;
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

function shortDate(iso, now = new Date()) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const opts = { month: 'short', day: 'numeric' };
  if (d.getFullYear() !== now.getFullYear()) opts.year = 'numeric';
  return d.toLocaleDateString('en-US', opts);
}

/** "Main St Project · 12 messages · last Oct 8". */
export function detailLine(row, now) {
  if (!row) return '';
  const parts = [];
  const groups = row.groups || [];
  if (groups.length === 1) parts.push(groups[0]);
  else if (groups.length > 1) parts.push(plural(groups.length, 'group', 'groups'));
  parts.push(plural(row.message_count || 0, 'message', 'messages'));
  const last = shortDate(row.last_message_at, now);
  if (last) parts.push(`last ${last}`);
  return parts.join(' · ');
}

/** The form: what to send, or why not yet. */
export function assignRequest({ name, company }, companies) {
  const n = String(name || '').trim().replace(/\s+/g, ' ');
  if (!n) return { error: 'Enter the person’s name.' };
  if (n.length > 80) return { error: 'Keep the name under 80 characters.' };
  const list = companies || [];
  if (!company || !list.includes(company)) return { error: 'Pick their company.' };
  return { body: { personName: n, subCompany: company } };
}

/** What the toast says after a save. */
export function savedText(res) {
  const n = (res && res.open_items_updated) || 0;
  if (!n) return 'Saved for every group of your company.';
  return `Saved. ${plural(n, 'open item now names', 'open items now name')} them.`;
}

/** Who may see the People card: an admin or a PM (the server's rule). */
export function canManagePeople(user) {
  if (user && user.is_platform_operator === true) return true;
  const role = String((user && user.role) || '').trim().toLowerCase();
  return role === 'admin' || role === 'pm';
}

function looksLikeId(s) {
  return /@/.test(s) || /\d{7,}/.test(s.replace(/[\s\-().+]/g, ''));
}

/** Never let a raw WhatsApp id reach the screen, whatever the server sends.
 *  ("Unnamed sender …0101", the last 4 of a phone, is allowed.) */
export function safeLabel(label) {
  const s = String(label || '').trim();
  if (!s || looksLikeId(s)) return 'Unnamed sender';
  return s;
}

/** The name to pre-fill the form with: the WhatsApp name, or nothing when
 *  that name is really a number or an id. */
export function safeName(name) {
  const s = String(name || '').trim();
  return s && !looksLikeId(s) ? s : '';
}
