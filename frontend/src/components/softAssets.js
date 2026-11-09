// The soft-silicone surfaces, pre-rendered by scripts/build-soft-assets.py.
// Each is a capsule in three pieces (left cap, one-column middle, right cap).
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
  key:   { body: 60, margin: 52, capW: 130, imgH: 164 },
  keyp:  { body: 60, margin: 52, capW: 130, imgH: 164 },
  field: { body: 56, margin: 6,  capW: 50,  imgH: 68 },
};
