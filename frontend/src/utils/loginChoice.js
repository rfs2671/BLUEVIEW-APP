// ── ONE EMAIL, SEVERAL COMPANIES: WHAT THE LOGIN ANSWERED ───────────────────
//
// An email may hold one account per company (Roy, 2026-11-06). When the
// password opens more than one of them, POST /api/auth/login answers with a
// company picker instead of a session:
//
//   { choose_company: true,
//     accounts: [{ company_name, role, choice_token }, ...] }
//
// and NO token. The person picks a company and the app exchanges that
// account's `choice_token` at POST /api/auth/login/choose for the session.
// A choice lives five minutes and is not itself a session.
//
// Pure, so the login screen's branching is testable without React
// (loginCompanyPicker.test.cjs).

/** A session, a choice of companies, or nothing usable. */
export function readLoginAnswer(data) {
  const d = data || {};
  if (d.choose_company === true && Array.isArray(d.accounts)) {
    const accounts = d.accounts
      .filter((a) => a && typeof a.choice_token === 'string' && a.choice_token)
      .map((a) => ({
        companyName: (typeof a.company_name === 'string' && a.company_name.trim())
          ? a.company_name.trim() : null,
        role: typeof a.role === 'string' ? a.role : null,
        choiceToken: a.choice_token,
      }));
    if (accounts.length > 0) return { kind: 'choose', accounts };
    return { kind: 'none' };
  }
  if (typeof d.token === 'string' && d.token) return { kind: 'token', token: d.token };
  return { kind: 'none' };
}

/** The name a picker row shows. A signup with no company yet says so. */
export function companyLabel(account, t) {
  return (account && account.companyName) ? account.companyName : t('noCompany');
}

const ROLE_KEYS = {
  admin: 'role_admin',
  pm: 'role_pm',
  cp: 'role_cp',
  superintendent: 'role_superintendent',
  demo: 'role_demo',
};

/** The role line under a company name, or '' for a role with no copy. */
export function roleLabel(role, t) {
  const key = ROLE_KEYS[String(role || '').trim().toLowerCase()];
  return key ? t(key) : '';
}
