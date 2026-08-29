/**
 * ONE FACT, THREE FIELD NAMES — the frontend half.
 *
 * `server.py:_worker_company` already collapses this on the backend, and the
 * comment above it records what the spread cost: four spellings for "which sub
 * does this man work for" across `checkins`, `trade_assignments`,
 * `worker_project_trades` and `worker_enrollments`, and four separate
 * production defects on one project.
 *
 * THE SCREEN HAD ITS OWN VERSION OF THE SAME BUG, and it was worse than a
 * miscount. workers.jsx counted distinct companies as:
 *
 *     new Set(todayCheckIns.map((c) => c.workerCompany)).size
 *
 * `/api/checkins` returns snake_case -- the check-in field whitelist is
 * `worker_company`, `project_name`, `project_id` -- and `workerCompany` is
 * produced NOWHERE as a check-in row field. So every row mapped to `undefined`
 * and the counter read
 *
 *     new Set([undefined, undefined, ...]).size === 1
 *
 * "Companies 1" was not a count of one company. It was a count of one
 * `undefined`, and it read 1 for any non-empty roster no matter how many
 * companies were on site. Four lines below it, the row renderer read the same
 * field correctly through a full or-chain -- so the rows showed the right
 * company names while the counter above them said 1. A screen that contradicts
 * itself is the shape this repo keeps getting bitten by.
 *
 * SEMANTICS MATCH THE BACKEND HELPER EXACTLY: first TRUTHY candidate wins, and
 * only the winner is stripped. A whitespace-only value is truthy, wins, and
 * strips to "" -- same as `(a || b || '').trim()` at every original call site.
 */

/** The first candidate that carries a value, stripped. '' when none do. */
function firstOf(...candidates) {
  for (const v of candidates) {
    if (v) return String(v).trim();
  }
  return '';
}

/** Which company a check-in row names. '' when it names none. */
export function checkinCompany(c) {
  return firstOf(c?.worker_company, c?.workerCompany, c?.company);
}

/** Which project a check-in row names. '' when it names none. */
export function checkinProject(c) {
  return firstOf(c?.project_name, c?.projectName, c?.project_id, c?.projectId);
}

/** Which worker a check-in row names. '' when it names none. */
export function checkinWorker(c) {
  return firstOf(c?.worker_name, c?.workerName, c?.name);
}

/**
 * The counting key for a name.
 *
 * CASE AND WHITESPACE ARE NOT IDENTITY. `_norm_key`'s comment on the backend
 * records that a trailing or doubled space made a lowercased (name, company)
 * pair miss and printed THE SAME MAN TWICE on a production pre-shift sheet.
 * "Arkon Builders" and "arkon  builders " are one company, and a headcount
 * that says otherwise is wrong in the direction that looks plausible.
 *
 * This is still a string-keyed identity, which is still the underlying problem
 * -- two genuinely different companies sharing a name collapse to one. Keying
 * on a company id is the real fix and is not this pass's decision.
 */
export function nameKey(s) {
  return String(s || '').trim().toLowerCase().replace(/\s+/g, ' ');
}

/**
 * How many distinct companies are named across these check-ins.
 *
 * A ROW THAT NAMES NO COMPANY IS NOT A COMPANY. It is dropped rather than
 * counted as one, because counting blanks is exactly the defect this replaces:
 * an unnamed company is a gap in the record, and inventing a unit for it makes
 * the gap look like a fact.
 */
export function distinctCompanies(rows) {
  const seen = new Set();
  for (const r of rows || []) {
    const k = nameKey(checkinCompany(r));
    if (k) seen.add(k);
  }
  return seen.size;
}

/** How many distinct projects are named across these check-ins. */
export function distinctProjects(rows) {
  const seen = new Set();
  for (const r of rows || []) {
    const k = nameKey(checkinProject(r));
    if (k) seen.add(k);
  }
  return seen.size;
}

export default {
  checkinCompany,
  checkinProject,
  checkinWorker,
  nameKey,
  distinctCompanies,
  distinctProjects,
};
