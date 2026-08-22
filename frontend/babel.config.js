module.exports = function (api) {
  api.cache(true);
  return {
    presets: ['babel-preset-expo'],
    plugins: [
      // The two @babel/plugin-proposal-* entries that were here existed
      // only for WatermelonDB's `@field` decorators. That JS went in
      // e8bf396 and there is not one decorator left in app/ or src/.
      //
      // class-properties was worse than unused: it was NOT in
      // devDependencies at all, so it resolved transitively. That is a
      // live hazard today, not only a migration one — babel-preset-expo@54
      // stops resolving it and the build fails on a plugin nothing needs.
      'react-native-reanimated/plugin', // Keep this last
    ],
  };
};
