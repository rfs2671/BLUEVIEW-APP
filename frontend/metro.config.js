const { getDefaultConfig } = require('expo/metro-config');
const config = getDefaultConfig(__dirname);

// The pdf.js dist files ship as `.txt` (assets/pdfjs/*.txt) so Metro copies
// them as ASSETS instead of trying to bundle them as source — `.js` would be
// treated as a module. They are renamed back to `.js` when staged on disk at
// runtime by src/utils/pdfjsViewer.js. `.html` is already an asset extension
// by default; `.txt` is not.
if (!config.resolver.assetExts.includes('txt')) {
  config.resolver.assetExts.push('txt');
}

config.resolver.resolveRequest = (context, moduleName, platform) => {
  // The WatermelonDB web exclusion that lived here is gone with the
  // package: it kept Watermelon's native shim out of the WEB bundle, and
  // with no dependency the branch can never be true.
  return context.resolveRequest(context, moduleName, platform);
};

module.exports = config;
