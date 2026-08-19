/**
 * IS THIS PROJECT'S §3310 CLASSIFICATION ACTUALLY DECIDED?
 *
 * The client mirror of server.py's classification_assessed. A project_class
 * outside the valid set — missing, null, empty, junk — means nobody has
 * assessed it, NOT that it is regular.
 *
 * WHY THIS EXISTS. Screens branched on `project_class === 'major_a'` and on
 * `(p.project_class || 'regular')`, both of which read an ABSENCE as an answer.
 * A project nobody classified was reported as needing no Site Safety
 * Coordinator and no Site Safety Manager — the app asserting something it
 * cannot verify, on a staffing requirement.
 *
 * One predicate so the screens cannot each invent their own.
 */
export const VALID_PROJECT_CLASSES = Object.freeze(['regular', 'major_a', 'major_b']);

export const classificationAssessed = (p) =>
  VALID_PROJECT_CLASSES.includes(String((p || {}).project_class || ''));

/** True only when the class is KNOWN to be major. Unassessed is not major. */
export const isMajorClass = (p) => {
  const c = String((p || {}).project_class || '');
  return c === 'major_a' || c === 'major_b';
};

export default { VALID_PROJECT_CLASSES, classificationAssessed, isMajorClass };
