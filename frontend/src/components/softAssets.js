// The soft-silicone surfaces, pre-rendered by scripts/build-soft-assets.py.
// Each is a capsule in three pieces (left cap, one-column middle, right cap), at @1x/@2x/@3x.
// Static require paths so the bundler can find every file.
export const SOFT = {
  light: {
    key:   { L: require('../../assets/soft/key_light_L.png'),   M: require('../../assets/soft/key_light_M.png'),   R: require('../../assets/soft/key_light_R.png') },
    keyp:  { L: require('../../assets/soft/keyp_light_L.png'),  M: require('../../assets/soft/keyp_light_M.png'),  R: require('../../assets/soft/keyp_light_R.png') },
    field: { L: require('../../assets/soft/field_light_L.png'), M: require('../../assets/soft/field_light_M.png'), R: require('../../assets/soft/field_light_R.png') },
  },
  dark: {
    key:   { L: require('../../assets/soft/key_dark_L.png'),    M: require('../../assets/soft/key_dark_M.png'),    R: require('../../assets/soft/key_dark_R.png') },
    keyp:  { L: require('../../assets/soft/keyp_dark_L.png'),   M: require('../../assets/soft/keyp_dark_M.png'),   R: require('../../assets/soft/keyp_dark_R.png') },
    field: { L: require('../../assets/soft/field_dark_L.png'),  M: require('../../assets/soft/field_dark_M.png'),  R: require('../../assets/soft/field_dark_R.png') },
  },
};

// Sizes in dp, matching the generator: the body (what you see as the control),
// the room the image keeps around it for its shadow, and the width of each end piece.
export const SOFT_DIMS = {
  key:   { body: 60, margin: 52, capW: 138, imgH: 164 },
  keyp:  { body: 60, margin: 52, capW: 138, imgH: 164 },
  field: { body: 60, margin: 28, capW: 102, imgH: 116 },
};

// The logo, raised from the surface and lit like the keys: same 2103x1080 canvas as the
// plain logo, so the entrance animation lands on it exactly.
export const SOFT_LOGO = {
  light: require('../../assets/soft/logo_light.png'),
  dark: require('../../assets/soft/logo_dark.png'),
};

// Stretchable panels, cut in nine pieces (see build-soft-assets.py): `card` rises, `well` is pressed in.
export const SOFT_PANEL = {
  light: {
    card: { tl: require('../../assets/soft/card_light_tl.png'), tc: require('../../assets/soft/card_light_tc.png'), tr: require('../../assets/soft/card_light_tr.png'), ml: require('../../assets/soft/card_light_ml.png'), mc: require('../../assets/soft/card_light_mc.png'), mr: require('../../assets/soft/card_light_mr.png'), bl: require('../../assets/soft/card_light_bl.png'), bc: require('../../assets/soft/card_light_bc.png'), br: require('../../assets/soft/card_light_br.png') },
    cardp: { tl: require('../../assets/soft/cardp_light_tl.png'), tc: require('../../assets/soft/cardp_light_tc.png'), tr: require('../../assets/soft/cardp_light_tr.png'), ml: require('../../assets/soft/cardp_light_ml.png'), mc: require('../../assets/soft/cardp_light_mc.png'), mr: require('../../assets/soft/cardp_light_mr.png'), bl: require('../../assets/soft/cardp_light_bl.png'), bc: require('../../assets/soft/cardp_light_bc.png'), br: require('../../assets/soft/cardp_light_br.png') },
    slim: { tl: require('../../assets/soft/slim_light_tl.png'), tc: require('../../assets/soft/slim_light_tc.png'), tr: require('../../assets/soft/slim_light_tr.png'), ml: require('../../assets/soft/slim_light_ml.png'), mc: require('../../assets/soft/slim_light_mc.png'), mr: require('../../assets/soft/slim_light_mr.png'), bl: require('../../assets/soft/slim_light_bl.png'), bc: require('../../assets/soft/slim_light_bc.png'), br: require('../../assets/soft/slim_light_br.png') },
    slimp: { tl: require('../../assets/soft/slimp_light_tl.png'), tc: require('../../assets/soft/slimp_light_tc.png'), tr: require('../../assets/soft/slimp_light_tr.png'), ml: require('../../assets/soft/slimp_light_ml.png'), mc: require('../../assets/soft/slimp_light_mc.png'), mr: require('../../assets/soft/slimp_light_mr.png'), bl: require('../../assets/soft/slimp_light_bl.png'), bc: require('../../assets/soft/slimp_light_bc.png'), br: require('../../assets/soft/slimp_light_br.png') },
    slimw: { tl: require('../../assets/soft/slimw_light_tl.png'), tc: require('../../assets/soft/slimw_light_tc.png'), tr: require('../../assets/soft/slimw_light_tr.png'), ml: require('../../assets/soft/slimw_light_ml.png'), mc: require('../../assets/soft/slimw_light_mc.png'), mr: require('../../assets/soft/slimw_light_mr.png'), bl: require('../../assets/soft/slimw_light_bl.png'), bc: require('../../assets/soft/slimw_light_bc.png'), br: require('../../assets/soft/slimw_light_br.png') },
    well: { tl: require('../../assets/soft/well_light_tl.png'), tc: require('../../assets/soft/well_light_tc.png'), tr: require('../../assets/soft/well_light_tr.png'), ml: require('../../assets/soft/well_light_ml.png'), mc: require('../../assets/soft/well_light_mc.png'), mr: require('../../assets/soft/well_light_mr.png'), bl: require('../../assets/soft/well_light_bl.png'), bc: require('../../assets/soft/well_light_bc.png'), br: require('../../assets/soft/well_light_br.png') },
  },
  dark: {
    card: { tl: require('../../assets/soft/card_dark_tl.png'), tc: require('../../assets/soft/card_dark_tc.png'), tr: require('../../assets/soft/card_dark_tr.png'), ml: require('../../assets/soft/card_dark_ml.png'), mc: require('../../assets/soft/card_dark_mc.png'), mr: require('../../assets/soft/card_dark_mr.png'), bl: require('../../assets/soft/card_dark_bl.png'), bc: require('../../assets/soft/card_dark_bc.png'), br: require('../../assets/soft/card_dark_br.png') },
    cardp: { tl: require('../../assets/soft/cardp_dark_tl.png'), tc: require('../../assets/soft/cardp_dark_tc.png'), tr: require('../../assets/soft/cardp_dark_tr.png'), ml: require('../../assets/soft/cardp_dark_ml.png'), mc: require('../../assets/soft/cardp_dark_mc.png'), mr: require('../../assets/soft/cardp_dark_mr.png'), bl: require('../../assets/soft/cardp_dark_bl.png'), bc: require('../../assets/soft/cardp_dark_bc.png'), br: require('../../assets/soft/cardp_dark_br.png') },
    slim: { tl: require('../../assets/soft/slim_dark_tl.png'), tc: require('../../assets/soft/slim_dark_tc.png'), tr: require('../../assets/soft/slim_dark_tr.png'), ml: require('../../assets/soft/slim_dark_ml.png'), mc: require('../../assets/soft/slim_dark_mc.png'), mr: require('../../assets/soft/slim_dark_mr.png'), bl: require('../../assets/soft/slim_dark_bl.png'), bc: require('../../assets/soft/slim_dark_bc.png'), br: require('../../assets/soft/slim_dark_br.png') },
    slimp: { tl: require('../../assets/soft/slimp_dark_tl.png'), tc: require('../../assets/soft/slimp_dark_tc.png'), tr: require('../../assets/soft/slimp_dark_tr.png'), ml: require('../../assets/soft/slimp_dark_ml.png'), mc: require('../../assets/soft/slimp_dark_mc.png'), mr: require('../../assets/soft/slimp_dark_mr.png'), bl: require('../../assets/soft/slimp_dark_bl.png'), bc: require('../../assets/soft/slimp_dark_bc.png'), br: require('../../assets/soft/slimp_dark_br.png') },
    slimw: { tl: require('../../assets/soft/slimw_dark_tl.png'), tc: require('../../assets/soft/slimw_dark_tc.png'), tr: require('../../assets/soft/slimw_dark_tr.png'), ml: require('../../assets/soft/slimw_dark_ml.png'), mc: require('../../assets/soft/slimw_dark_mc.png'), mr: require('../../assets/soft/slimw_dark_mr.png'), bl: require('../../assets/soft/slimw_dark_bl.png'), bc: require('../../assets/soft/slimw_dark_bc.png'), br: require('../../assets/soft/slimw_dark_br.png') },
    well: { tl: require('../../assets/soft/well_dark_tl.png'), tc: require('../../assets/soft/well_dark_tc.png'), tr: require('../../assets/soft/well_dark_tr.png'), ml: require('../../assets/soft/well_dark_ml.png'), mc: require('../../assets/soft/well_dark_mc.png'), mr: require('../../assets/soft/well_dark_mr.png'), bl: require('../../assets/soft/well_dark_bl.png'), bc: require('../../assets/soft/well_dark_bc.png'), br: require('../../assets/soft/well_dark_br.png') },
  },
};
export const SOFT_PANEL_DIMS = {
  card: { margin: 32, corner: 72, radius: 20, min: 80 },
  cardp: { margin: 32, corner: 72, radius: 20, min: 80 },
  well: { margin: 28, corner: 76, radius: 26, min: 96 },
  slim: { margin: 32, corner: 60, radius: 18, min: 56 },
  slimp: { margin: 32, corner: 60, radius: 18, min: 56 },
  slimw: { margin: 28, corner: 56, radius: 18, min: 56 },
};

// A small raised pill, fixed height 44: left cap, one-column middle, right cap.
export const SOFT_PILL = {
  light: { L: require('../../assets/soft/pill_light_L.png'), M: require('../../assets/soft/pill_light_M.png'), R: require('../../assets/soft/pill_light_R.png') },
  lightp: { L: require('../../assets/soft/pillp_light_L.png'), M: require('../../assets/soft/pillp_light_M.png'), R: require('../../assets/soft/pillp_light_R.png') },
  dark: { L: require('../../assets/soft/pill_dark_L.png'), M: require('../../assets/soft/pill_dark_M.png'), R: require('../../assets/soft/pill_dark_R.png') },
  darkp: { L: require('../../assets/soft/pillp_dark_L.png'), M: require('../../assets/soft/pillp_dark_M.png'), R: require('../../assets/soft/pillp_dark_R.png') },
};
export const SOFT_PILL_DIMS = { body: 44, margin: 32, capW: 76, imgH: 108 };

// The whole picture of each surface, for iPhone: one image stretched with fixed corners (cap insets).
// Pieces drawn separately faded at their joins there; a single image has no joins.
export const SOFT_FULL = {
  light: { key: require('../../assets/soft/key_light_full.png'), keyp: require('../../assets/soft/keyp_light_full.png'), field: require('../../assets/soft/field_light_full.png'), pill: require('../../assets/soft/pill_light_full.png'), pillp: require('../../assets/soft/pillp_light_full.png'), card: require('../../assets/soft/card_light_full.png'), cardp: require('../../assets/soft/cardp_light_full.png'), well: require('../../assets/soft/well_light_full.png'), slim: require('../../assets/soft/slim_light_full.png'), slimp: require('../../assets/soft/slimp_light_full.png'), slimw: require('../../assets/soft/slimw_light_full.png') },
  dark: { key: require('../../assets/soft/key_dark_full.png'), keyp: require('../../assets/soft/keyp_dark_full.png'), field: require('../../assets/soft/field_dark_full.png'), pill: require('../../assets/soft/pill_dark_full.png'), pillp: require('../../assets/soft/pillp_dark_full.png'), card: require('../../assets/soft/card_dark_full.png'), cardp: require('../../assets/soft/cardp_dark_full.png'), well: require('../../assets/soft/well_dark_full.png'), slim: require('../../assets/soft/slim_dark_full.png'), slimp: require('../../assets/soft/slimp_dark_full.png'), slimw: require('../../assets/soft/slimw_dark_full.png') },
};

// The round 44dp button, one fixed-size picture each: raised and pressed.
export const SOFT_PEBBLE = {
  light: { up: require('../../assets/soft/pebble_light.png'), down: require('../../assets/soft/pebblep_light.png') },
  dark: { up: require('../../assets/soft/pebble_dark.png'), down: require('../../assets/soft/pebblep_dark.png') },
};
export const SOFT_PEBBLE_DIMS = { body: 44, margin: 32, img: 108 };
