/**
 * A toast the user cannot see is not feedback.
 *
 * A native Modal is a separate OS window — a Dialog on Android, a presented
 * view controller on iOS. `zIndex` and `elevation` are scoped to ONE view
 * hierarchy, and so is React tree position, so nothing in the app's tree can
 * paint above a Modal. The provider's stack carries `zIndex: 99999` and still
 * renders behind every sheet.
 *
 * Two non-fixes have been proposed for this, and both are the same mistake:
 *
 *   raise the zIndex           already 99999; it does not cross windows
 *   reorder ToastProvider      it is ALREADY the innermost provider in
 *                              _layout.jsx, and tree order does not cross
 *                              windows either
 *
 * And one real fix was tried and reverted — efea5c9, "toast blocking UI":
 * wrapping the provider's stack in its own Modal fixed the layering and broke
 * touch, because RN's Modal root intercepts every touch regardless of
 * pointerEvents on its children. For the four seconds a toast was up, nothing
 * was tappable.
 *
 * So the fix is a SECOND MOUNT POINT, not a different layer. Same provider,
 * same useToast(), same Toast component, same styles — only the window differs.
 *
 *   node frontend/src/utils/toastInsideModals.test.cjs
 */
const fs = require('fs');
const path = require('path');

const FRONTEND = path.join(__dirname, '..', '..');
const read = (p) => fs.readFileSync(path.join(FRONTEND, p), 'utf8');
const TOAST = read(path.join('src', 'components', 'Toast.js'));
const LAYOUT = read(path.join('app', '_layout.jsx'));
const SETTINGS = read(path.join('app', 'settings.jsx'));
const PROJECT = read(path.join('app', 'project', '[id].jsx'));

let passed = 0; let failed = 0;
function ok(cond, label) {
  if (cond) { passed += 1; console.log('  PASS ', label); }
  else { failed += 1; console.log('  FAIL ', label); }
}

console.log('\n-- one mechanism, not a second treatment --');
{
  ok(/export const ToastHost/.test(TOAST), 'ToastHost is exported from the toast module');
  // It must render the SAME component the provider does. A host that built its
  // own card would be the fifth error treatment this codebase does not need.
  const host = TOAST.slice(TOAST.indexOf('export const ToastHost'));
  ok(host.length > 100, 'ANCHOR: the host slice is non-empty');
  ok(/<Toast key=\{t\.id\}/.test(host), 'it renders the same Toast component');
  ok(/stack\.styles\.toastContainer/.test(host),
    'and the same styles object — not a copy that can drift');
  ok(/stack\.removeToast/.test(host), 'and dismissal goes back to the same list');
}

console.log('\n-- it reads the live stack, and cannot raise toasts --');
{
  // Two contexts on purpose: the API to RAISE a toast, and the list to RENDER
  // it. A screen reaching in to read the list would be able to mutate feedback
  // it does not own.
  ok(/const ToastStackContext = createContext/.test(TOAST),
    'the live list has its own context');
  ok(!/export const ToastStackContext/.test(TOAST),
    'which is NOT exported — screens raise toasts through useToast(), never by '
    + 'reaching into the stack');
  ok(/useContext\(ToastStackContext\)/.test(TOAST), 'and the host reads it');
}

console.log('\n-- an idle sheet is unaffected --');
{
  const host = TOAST.slice(TOAST.indexOf('export const ToastHost'));
  ok(/toasts\.length === 0\) return null/.test(host),
    'renders nothing when no toast is up, so mounting it costs a closed sheet '
    + 'nothing');
  ok(/pointerEvents="box-none"/.test(host),
    'and box-none, so it never eats a tap meant for the sheet beneath it');
}

console.log('\n-- mounted where an unseen error costs something --');
{
  // The deletion sheet: a failed request would otherwise show the user nothing
  // at all, on a screen about removing their account.
  ok(/import \{ useToast, ToastHost \}/.test(SETTINGS), 'settings imports it');
  const sheet = SETTINGS.slice(SETTINGS.indexOf('deletionConfirmOpen}'),
    SETTINGS.indexOf('Request deletion'));
  ok(sheet.length > 200, 'ANCHOR: the deletion sheet slice is non-empty');
  ok(/<ToastHost \/>/.test(sheet), 'and mounts it inside the deletion sheet');

  // Tag programming: every outcome is a toast, including the library's own
  // "unsupported tag api". An admin holding a phone to a tag sees nothing.
  ok(/import \{ useToast, ToastHost \}/.test(PROJECT), 'the project screen imports it');
  const nfc = PROJECT.slice(PROJECT.indexOf('visible={showAddNfcModal}'),
    PROJECT.indexOf('visible={showAddNfcModal}') + 1400);
  ok(nfc.length > 200, 'ANCHOR: the NFC sheet slice is non-empty');
  ok(/<ToastHost \/>/.test(nfc), 'and mounts it inside the NFC programming sheet');
}

console.log('\n-- the two non-fixes stay refused --');
{
  // If someone "fixes" this by bumping zIndex or moving the provider, the
  // symptom is unchanged and the commit says otherwise.
  ok(/zIndex: 99999/.test(TOAST),
    'ANCHOR: the provider stack still carries a high zIndex (which does not '
    + 'cross windows, and is not what fixed this)');
  const providerOrder = LAYOUT.indexOf('<ToastProvider>');
  const shell = LAYOUT.indexOf('<AppShell />');
  ok(providerOrder > -1 && shell > providerOrder,
    'ToastProvider is still the innermost provider — there is nothing to '
    + 'reorder it above, and reordering would not cross a window anyway');
  ok(!/<Modal[^>]*>\s*<View pointerEvents="box-none" style=\{styles\.toastContainer\}/.test(TOAST),
    'and the provider stack is NOT re-wrapped in a Modal — that was efea5c9, '
    + 'which fixed layering and made the screen untappable for four seconds');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASSED');
