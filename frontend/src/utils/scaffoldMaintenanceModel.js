/**
 * The Scaffold Maintenance Log — the NYC DOB sidewalk-shed daily inspection.
 *
 * WHY A MODULE. Same reason as dailyJobsiteModel.js and oshaLogModel.js: the
 * frontend suite has no renderer, so logic in a component can only be grepped
 * while logic in a module can be EXECUTED. Everything here decides what a DOB
 * inspector reads off a filed document.
 *
 * THE PAYLOAD SHAPE IS FROZEN — `{ general_info, answers }`, rendered by
 * backend/server.py:13321-13385 and again at :19050, and displayed by
 * app/site/logbooks.jsx. The nine general_info keys and the nineteen answer
 * keys below are that contract; scaffoldMaintenanceModel.test.cjs asserts them
 * against the renderer's own list rather than a copy.
 *
 * ── drawings_on_site: ONE KEY, AND IT IS A QUESTION ──────────────────────────
 *
 * It appears exactly ONCE in this file, as question 19, which is where the CP
 * answers it. It is NOT a general_info key and nothing seeds it.
 *
 * It used to be both: `general_info.drawings_on_site` was initialised to 'YES'
 * with no control anywhere on the screen that could change it — the app
 * asserting, on every scaffold log, that drawings were on site for inspection
 * when nobody had said so. Both PDF renderers already read only the answers one
 * and say so in as many words, so removing the seed changed no printed page: an
 * unanswered question renders "Not recorded", never a silent YES.
 */

// ── General information — 8 typed fields, prefilled from project memory ──────
//
// `kind` drives the control, not the storage: every value is stored and sent as
// a STRING regardless, because that is what the renderers print and what
// update_scaffold_info already holds.
export const GENERAL_INFO_FIELDS = Object.freeze([
  { key: 'scaffold_erector', labelKey: 'fErector', kind: 'text' },
  { key: 'renters_name', labelKey: 'fRenter', kind: 'text' },
  { key: 'permit_number', labelKey: 'fPermit', kind: 'text' },
  { key: 'installation_date', labelKey: 'fInstalled', kind: 'date' },
  { key: 'expiration_date', labelKey: 'fExpires', kind: 'date' },
  { key: 'phone', labelKey: 'fPhone', kind: 'phone' },
  { key: 'scaffold_height', labelKey: 'fHeight', kind: 'text' },
  { key: 'num_platforms', labelKey: 'fPlatforms', kind: 'number' },
]);

export const SHED_TYPES = Object.freeze(['Light', 'Med.', 'Heavy', 'Duty']);

/** The shed type a project starts on when memory holds none. */
export const DEFAULT_SHED_TYPE = 'Heavy';

// The nine keys that travel in general_info: the eight above plus shed_type.
export const GENERAL_INFO_KEYS = Object.freeze(
  [...GENERAL_INFO_FIELDS.map((f) => f.key), 'shed_type'],
);

// ── The 19 checks, in the order the CP walks them ────────────────────────────
// Label text is duplicated in backend/server.py:13329-13349 because that
// renderer prints filed documents with no access to this bundle. The test
// asserts the two lists agree, key for key and word for word.
export const MAINTENANCE_QUESTIONS = Object.freeze([
  { key: 'signs_on_parapets', label: 'Are the signs on the parapets?' },
  { key: 'base_plates_mudsills', label: 'Are the base plates and mudsills secured?' },
  { key: 'scaffold_pins_bolts', label: 'Are the scaffold pins and bolts installed?' },
  { key: 'legs_poles_plumb', label: 'Are the legs and poles plumb, braced and not displaced?' },
  { key: 'tie_ins_spaced', label: 'Are tie-ins correctly spaced, properly secured and the correct amount?' },
  { key: 'cross_braces', label: 'Are cross braces fully attached, not bent, and not missing?' },
  { key: 'pipe_clamps_tight', label: 'Are pipe clamps tight?' },
  { key: 'window_jacks_tight', label: 'Are window jacks tight?' },
  { key: 'planks_secured', label: 'Are all the planks secured?' },
  { key: 'decking_planks_condition', label: 'Are decking and planks in good condition?' },
  { key: 'deck_fully_planked', label: 'Is deck fully planked?' },
  { key: 'gaps_open_spaces', label: 'Are there gaps or open spaces on decking?' },
  { key: 'guardrails_toe_boards', label: 'Are the guardrails and toe boards secured at all places where required?' },
  { key: 'netting_extension', label: 'Is the netting extension of full length and height?' },
  { key: 'netting_secured', label: 'Is the netting secured?' },
  { key: 'parapet_height', label: 'Is the parapet the proper height and secured?' },
  { key: 'lights_working', label: 'Are the lights working?' },
  { key: 'deck_clean', label: 'Is the deck clean and free of debris?' },
  { key: 'drawings_on_site', label: 'Drawings on site for inspection?' },
]);

// YES / NO / N/A — strings, not booleans. An N/A the CP CHOSE is a real answer
// and is rendered as chosen; an unanswered question is neither.
export const ANSWER_OPTIONS = Object.freeze(['YES', 'NO', 'N/A']);

/**
 * A blank general_info.
 *
 * NOTHING IS SEEDED WITH AN ANSWER. shed_type carries a default because it is a
 * property of the shed that is always one of four, and the CP is looking at it;
 * an inspection QUESTION is different and gets no default at all.
 */
export const EMPTY_GENERAL_INFO = () => ({
  scaffold_erector: '',
  renters_name: '',
  permit_number: '',
  installation_date: '',
  expiration_date: '',
  phone: '',
  scaffold_height: '',
  num_platforms: '',
  shed_type: DEFAULT_SHED_TYPE,
});

/**
 * Project memory -> the form. Only the nine keys this screen owns, so a stray
 * field on the project document cannot ride into a signed log.
 */
export function prefillFromScaffoldInfo(info) {
  const src = (info && typeof info === 'object') ? info : {};
  const out = EMPTY_GENERAL_INFO();
  for (const key of GENERAL_INFO_KEYS) {
    if (key === 'shed_type') {
      out.shed_type = src.shed_type || DEFAULT_SHED_TYPE;
    } else {
      out[key] = src[key] || '';
    }
  }
  return out;
}

/**
 * The form -> project memory.
 *
 * update_scaffold_info writes EVERY key it is handed
 * (backend/server.py:16936 `"drawings_on_site": data.get("drawings_on_site")`),
 * so a key sent as undefined is stored as null — replacing whatever the project
 * already had with nothing. Dropping undefined keys leaves them untouched.
 */
export function scaffoldInfoForSave(generalInfo) {
  return Object.fromEntries(
    Object.entries(generalInfo || {}).filter(([, v]) => v !== undefined),
  );
}

/** How many of the 19 the CP has answered. */
export function answeredCount(answers) {
  const a = (answers && typeof answers === 'object') ? answers : {};
  return MAINTENANCE_QUESTIONS.filter(
    (q) => String(a[q.key] ?? '').trim() !== '',
  ).length;
}

/**
 * Which steps the CP has LEFT incomplete. Marks only; never gates.
 *
 * Step 1 the shed, step 2 the checks, step 3 the signature. Step 2 is
 * incomplete until ALL 19 are answered — this is a DOB inspection form and a
 * half-walked shed is the thing the pip exists to show.
 */
export function incompleteSteps({ generalInfo, answers, cpSignature }) {
  const out = [];
  const gi = (generalInfo && typeof generalInfo === 'object') ? generalInfo : {};
  const anyField = GENERAL_INFO_FIELDS.some(
    (f) => String(gi[f.key] ?? '').trim() !== '',
  );
  if (!anyField) out.push(1);
  if (answeredCount(answers) < MAINTENANCE_QUESTIONS.length) out.push(2);
  if (!String(cpSignature || '').trim()) out.push(3);
  return out;
}

/** The payload body. The ONE place the shape is decided. */
export function draftBody(generalInfo, answers) {
  return {
    general_info: generalInfo || {},
    answers: answers || {},
  };
}

export default {
  GENERAL_INFO_FIELDS,
  GENERAL_INFO_KEYS,
  SHED_TYPES,
  DEFAULT_SHED_TYPE,
  MAINTENANCE_QUESTIONS,
  ANSWER_OPTIONS,
  EMPTY_GENERAL_INFO,
  prefillFromScaffoldInfo,
  scaffoldInfoForSave,
  answeredCount,
  incompleteSteps,
  draftBody,
};
