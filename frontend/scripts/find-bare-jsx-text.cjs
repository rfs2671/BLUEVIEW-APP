#!/usr/bin/env node
/**
 * Find text rendered outside a <Text>, which React 19 THROWS on.
 *
 *   "Text strings must be rendered within a <Text> component."
 *
 * React 18 logged this as a warning and carried on, so these have been sitting
 * in the tree for as long as they have existed. React 19 makes them a crash, so
 * the SDK 54 upgrade did not introduce them — it stopped hiding them.
 *
 * That is why this sweeps the whole app rather than the one screen that
 * crashed: the operator has not walked every screen on this build, and a
 * warning nobody read is not evidence of absence.
 *
 * REAL PARSING, not a regex. A regex over JSX cannot tell a string inside a
 * prop from a string in a child position, and would drown the real findings in
 * false positives.
 *
 *   node frontend/scripts/find-bare-jsx-text.cjs
 *
 * Exit 1 if anything is found, so it can gate CI later.
 */
const fs = require('fs');
const path = require('path');
const parser = require('@babel/parser');

const ROOT = path.join(__dirname, '..');

/**
 * Components that legitimately accept a raw string child.
 *
 * The local ones were each VERIFIED to wrap children in a <Text> rather than
 * assumed - a wrapper that does not would hide a real crash behind an
 * allowlist entry, which is worse than the noise it removes.
 *
 *   HelpParagraph, HelpKbd   src/components/HelpPageShell.jsx, both render <Text>
 *   title                    app/+html.jsx, a DOM head tag, not React Native
 */
const TEXT_LIKE = new Set([
  'Text', 'RNText', 'Animated.Text', 'AppText', 'ThemedText',
  'HelpParagraph', 'HelpKbd',
  'title',
  // react-native-svg
  'TSpan', 'TextPath',
]);

/** These take children that are not rendered as UI, so text inside is fine. */
const NON_RENDERING = new Set(['Fragment', 'React.Fragment']);

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules' || e.name === 'dist' || e.name === '.expo') continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (/\.(jsx|js)$/.test(e.name) && !/\.test\.cjs$/.test(e.name)) out.push(p);
  }
  return out;
}

/** The name of a JSX element, however it is written. */
function nameOf(node) {
  const n = node && node.name;
  if (!n) return '';
  if (n.type === 'JSXIdentifier') return n.name;
  if (n.type === 'JSXMemberExpression') {
    return `${nameOf({ name: n.object })}.${n.property.name}`;
  }
  return '';
}

/**
 * Can this expression evaluate to a bare string or number at render time?
 * Conservative on purpose: only the shapes that actually produce text.
 */
function yieldsText(node) {
  if (!node) return false;
  switch (node.type) {
    case 'StringLiteral':
      return node.value.trim().length > 0;
    case 'NumericLiteral':
      return true;
    case 'TemplateLiteral':
      return true;
    case 'LogicalExpression':
      // {cond && 'text'} — only the right side renders.
      return node.operator !== '??' && yieldsText(node.right);
    case 'ConditionalExpression':
      return yieldsText(node.consequent) || yieldsText(node.alternate);
    default:
      return false;
  }
}

const findings = [];

for (const file of walk(path.join(ROOT, 'app')).concat(walk(path.join(ROOT, 'src')))) {
  let ast;
  const src = fs.readFileSync(file, 'utf8');
  try {
    ast = parser.parse(src, {
      sourceType: 'module',
      plugins: ['jsx', 'classProperties', 'objectRestSpread', 'optionalChaining',
        'nullishCoalescingOperator', 'dynamicImport'],
      errorRecovery: true,
    });
  } catch (e) {
    console.error(`  ! could not parse ${path.relative(ROOT, file)}: ${e.message}`);
    continue;
  }

  const visit = (node, parentEl) => {
    if (!node || typeof node !== 'object') return;
    if (Array.isArray(node)) { node.forEach((n) => visit(n, parentEl)); return; }

    if (node.type === 'JSXElement' || node.type === 'JSXFragment') {
      const el = node.type === 'JSXElement'
        ? nameOf(node.openingElement) : 'Fragment';
      const safe = TEXT_LIKE.has(el) || NON_RENDERING.has(el);

      for (const child of node.children || []) {
        if (child.type === 'JSXText') {
          // Whitespace between elements is stripped by the compiler.
          if (child.value.trim().length > 0 && !safe) {
            findings.push({
              file, line: child.loc.start.line, parent: el,
              kind: 'bare text', snippet: child.value.trim().slice(0, 60),
            });
          }
        } else if (child.type === 'JSXExpressionContainer') {
          if (!safe && yieldsText(child.expression)) {
            findings.push({
              file, line: child.loc.start.line, parent: el,
              kind: 'expression yielding text',
              snippet: src.slice(child.start, Math.min(child.end, child.start + 70))
                .replace(/\s+/g, ' '),
            });
          }
        }
      }
      // Props are not child positions; only recurse into children and prop VALUES
      // that themselves contain JSX.
      visit(node.children, el);
      if (node.openingElement) visit(node.openingElement.attributes, parentEl);
      return;
    }

    for (const key of Object.keys(node)) {
      if (key === 'loc' || key === 'start' || key === 'end') continue;
      visit(node[key], parentEl);
    }
  };

  visit(ast.program.body, null);
}

if (findings.length === 0) {
  console.log('\nNo bare text outside <Text>. React 19 has nothing to throw on.\n');
  process.exit(0);
}

console.log(`\n${findings.length} place(s) render text outside a <Text>:\n`);
const byFile = {};
for (const f of findings) (byFile[f.file] ||= []).push(f);
for (const [file, list] of Object.entries(byFile)) {
  console.log(`  ${path.relative(ROOT, file)}`);
  for (const f of list) {
    console.log(`    :${f.line}  in <${f.parent}>  ${f.kind}`);
    console.log(`             ${f.snippet}`);
  }
}
console.log('');
process.exit(1);
