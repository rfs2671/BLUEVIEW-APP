// PR #15D.1 — display-layer helpers for the Compliance Risk panel.
//
// Centralises the three text-prettification concerns that
// CompliancePanel + RiskScoreDrawer previously duplicated:
//
//   • titleCase()         — generic underscore/whitespace → Title Case
//   • boroughLabel()      — borough humanisation ('BROOKLYN' → 'Brooklyn')
//   • projectTypeLabel()  — DOB project-type enum → GC-readable label
//                           (e.g. 'major_alt_with_enlargement' →
//                            'major alteration')
//   • parseBaselineLabel() — robust parser for the backend's
//                            anchored_baseline.label string
//                            (e.g. 'BROOKLYN new_building macro baseline')
//
// Why one file: pre-PR #15D.1, `_titleCase` was inline-duplicated in
// CompliancePanel.jsx:92-100 AND RiskScoreDrawer.jsx:112-120. Consolidating
// here removes the duplication and gives projectTypeLabel a single home.

// ── Project-type enum → GC-readable label (lock C5) ──────────────
// The 5 production dob_project_type values currently emitted by the
// backend's classification pipeline. Unknown values fall through to
// titleCase() so the UI never renders a raw underscore string.
export const PROJECT_TYPE_LABELS = {
  major_alt_with_enlargement: 'major alteration',
  minor_alt:                  'minor alteration',
  new_building:               'new building',
  full_demo:                  'full demolition',
  partial_demo:               'partial demolition',
};

/**
 * Generic Title-Case helper for prose interpolation. Same idiom as the
 * inline _titleCase that previously lived in CompliancePanel +
 * RiskScoreDrawer:
 *   'BROOKLYN'                    → 'Brooklyn'
 *   'STATEN ISLAND'               → 'Staten Island'
 *   'major_alt_with_enlargement'  → 'Major Alt With Enlargement'
 *   '' / null / undefined         → ''
 */
export function titleCase(s) {
  if (s === null || s === undefined) return '';
  return String(s)
    .toLowerCase()
    .split(/[\s_]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

/**
 * Borough display name. Backend stores PLUTO borough values in ALL
 * CAPS ('BROOKLYN', 'STATEN ISLAND'). Title-cases them for prose.
 * Returns '' for null/undefined so interpolation stays safe.
 */
export function boroughLabel(raw) {
  if (!raw) return '';
  return titleCase(raw);
}

/**
 * DOB project-type display label. Map lookup against
 * PROJECT_TYPE_LABELS; unknown values fall through to titleCase()
 * per D2 (resilient against future backend enums). Returns 'similar'
 * for null/empty so the cohort prose still reads cleanly.
 */
export function projectTypeLabel(raw) {
  if (!raw) return 'similar';
  if (Object.prototype.hasOwnProperty.call(PROJECT_TYPE_LABELS, raw)) {
    return PROJECT_TYPE_LABELS[raw];
  }
  return titleCase(raw);
}

/**
 * Parse the backend's anchored_baseline.label string into its borough
 * + project-type components.
 *
 * Backend format (locked by tests at backend/lib/statistical_engine/
 * live_mutation.py:519-527):
 *   f'{borough} {project_type} macro baseline'
 *
 * The borough may be multi-word ('STATEN ISLAND'); project_type is
 * always a single underscore-joined token. So we strip the locked
 * ' macro baseline' suffix and treat the LAST token as project_type
 * and everything before it as borough.
 *
 * Returns { borough, projectType } — both strings, or both null if
 * the label can't be parsed (missing/empty/wrong shape).
 *
 * Examples:
 *   'BROOKLYN new_building macro baseline'        → { borough: 'BROOKLYN',     projectType: 'new_building' }
 *   'STATEN ISLAND full_demo macro baseline'      → { borough: 'STATEN ISLAND', projectType: 'full_demo'    }
 *   ''                                             → { borough: null,           projectType: null            }
 *   null                                           → { borough: null,           projectType: null            }
 */
export function parseBaselineLabel(label) {
  if (!label || typeof label !== 'string') {
    return { borough: null, projectType: null };
  }
  // Strip the locked ' macro baseline' suffix. Case-insensitive +
  // whitespace-tolerant so a future backend tweak that capitalises
  // the suffix doesn't break the parser.
  const stripped = label.replace(/\s+macro\s+baseline\s*$/i, '').trim();
  if (!stripped) return { borough: null, projectType: null };
  const parts = stripped.split(/\s+/);
  if (parts.length < 2) return { borough: null, projectType: null };
  // Last token = project_type (always single-token: underscore-joined
  // in the backend enum). Everything else = borough (may be
  // multi-token, e.g. 'STATEN ISLAND').
  const projectType = parts[parts.length - 1];
  const borough = parts.slice(0, -1).join(' ');
  return { borough, projectType };
}

export default {
  PROJECT_TYPE_LABELS,
  titleCase,
  boroughLabel,
  projectTypeLabel,
  parseBaselineLabel,
};
