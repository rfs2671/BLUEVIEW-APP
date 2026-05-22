// PR #52 — shared text-overflow + flex helpers.
//
// Operator feedback: "UI on mobile looks horrible. text cut off out of
// place and messy" and project names "breaking into multiple uneven
// rows cutting mid word". These helpers give every Text node a
// consistent, predictable overflow behavior so long content truncates
// with an ellipsis instead of wrapping mid-word or overflowing its
// container.
//
// Two kinds of export:
//   • PROPS spreads (numberOfLines / ellipsizeMode) — spread onto a
//     <Text {...textOverflowDefaults}> element.
//   • STYLE fragment (textBlockDefaults) — included in a Text's style
//     array so it shrinks inside a flex row instead of pushing siblings
//     off-screen.

// Single-line truncating text (badges, labels, inline values, chips).
export const textOverflowDefaults = {
  numberOfLines: 1,
  ellipsizeMode: 'tail',
};

// Multi-line truncating text (titles, addresses). Caps at `n` lines and
// ellipsizes the overflow — prevents mid-word breaks across many rows.
export function clampLines(n = 2) {
  return { numberOfLines: n, ellipsizeMode: 'tail' };
}

// Style fragment for text inside a flex row. flexShrink lets the text
// shrink; minWidth:0 lets it shrink below its intrinsic content width so
// the ellipsis can actually engage (RN/flexbox gotcha).
export const textBlockDefaults = {
  flexShrink: 1,
  minWidth: 0,
};

export default {
  textOverflowDefaults,
  clampLines,
  textBlockDefaults,
};
