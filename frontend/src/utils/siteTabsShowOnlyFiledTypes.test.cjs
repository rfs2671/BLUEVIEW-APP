/**
 * THE TABLET SHOWS ONLY THE LOG BOOKS THIS PROJECT HAS FILED.
 *
 *   node frontend/src/utils/siteTabsShowOnlyFiledTypes.test.cjs
 *
 * `app/site/logbooks.jsx` drew every entry of LOG_TABS -- every type the
 * registry knows -- whether or not the project had ever filed one. Twelve
 * tabs on a project that files five, the rest dead ends reading "entries
 * will appear here." The badge already hid a zero count; the tab did not.
 * Operator: the tablet "should show only working ones."
 *
 * TWO THINGS ARE ASSERTED, AND THE SECOND IS THE ONE THAT BITES.
 *
 *  1. Only tabs with records are drawn.
 *  2. Every place that FILTERS by tab reads the tab actually in force, not
 *     the raw selection. `activeTab` defaults to daily_jobsite; on a project
 *     that never filed one, the tab is hidden and the screen falls back to
 *     the first type that has records. If any one filter still read
 *     `activeTab`, the list would show one type's dates and tapping a date
 *     would filter its detail by another -- a day that opens empty. The
 *     expanded-detail filter was exactly that, and was caught while writing
 *     this.
 *
 * LOG_TABS ITSELF STAYS COMPLETE. logbookViewRenderers.test.cjs asserts it
 * covers every registered type; this change filters what is DRAWN, never
 * what is known, so a type filed for the first time gets its tab on the next
 * sync.
 *
 * Source assertions are matched against comment-stripped code: this file and
 * that screen both quote the old line in prose, and a scan of the raw text
 * would pass on the comment that says it was fixed.
 */
const fs = require('fs');
const path = require('path');

const SRC = fs.readFileSync(
  path.join(__dirname, '..', '..', 'app', 'site', 'logbooks.jsx'), 'utf8');
const stripComments = (s) => s
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
  .replace(/(^|[^:])\/\/[^\n]*/g, '$1');
const CODE = stripComments(SRC);

let passed = 0; let failed = 0;
const ok = (cond, label) => {
  if (cond) { passed += 1; console.log('  PASS ', label); }
  else { failed += 1; console.log('  FAIL ', label); }
};

console.log('\n1. only tabs with records are drawn');
ok(/const visibleTabs\s*=\s*LOG_TABS\.filter\(\s*\(tab\)\s*=>\s*tabCount\(tab\.key\)\s*>\s*0\s*\)/.test(CODE),
  'visibleTabs is LOG_TABS filtered to types with at least one record');
ok(/\{visibleTabs\.map\(/.test(CODE),
  'the tab row draws visibleTabs');
ok(!/\{LOG_TABS\.map\(/.test(CODE),
  'and no longer draws the whole of LOG_TABS');

console.log('\n2. the count that hides a tab is the badge\'s count');
ok(/const tabCount\s*=\s*\(key\)\s*=>\s*dateIndex/.test(CODE),
  'tabCount reads the INDEX — the whole filed history, not a window');
ok(/const count\s*=\s*tabCount\(tab\.key\)/.test(CODE),
  'the badge uses the same tabCount, so a drawn tab never shows a zero');

console.log('\n3. every filter reads the tab in force');
ok(/const effectiveTab\s*=\s*visibleTabs\.some\(/.test(CODE),
  'effectiveTab falls back when the selected tab has no records');
ok(/l\.log_type === effectiveTab\)\s*,?\s*\}\)\)/.test(CODE)
  || /\.filter\(\(l\) => l\.log_type === effectiveTab\)/.test(CODE),
  'the date list filters by effectiveTab');
ok(/detail\.filter\(\(l\) => l\.log_type === effectiveTab\)/.test(CODE),
  'the EXPANDED DAY filters by effectiveTab — the one that would have opened empty');
ok(/const isActive\s*=\s*effectiveTab === tab\.key/.test(CODE),
  'the lit tab is the one in force, so the screen never filters to a tab it does not highlight');

// THE NEGATIVE THAT MATTERS. Any filter still reading the raw selection is
// the split-brain defect: list and detail disagreeing about which type they
// show. Only the state, the derivation and the setter may name activeTab.
const rawFilters = (CODE.match(/log_type === activeTab/g) || []).length;
ok(rawFilters === 0,
  `no filter compares log_type to the raw activeTab (found ${rawFilters})`);

console.log('\n4. LOG_TABS itself is untouched — the tab filter is still the only way in');
ok(/const LOG_TABS\s*=\s*\[/.test(CODE),
  'LOG_TABS is still declared as the complete list');

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
