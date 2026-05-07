/**
 * Phase E1 — single-flag boolean read hook.
 *
 * Usage:
 *
 *   import { useFeatureFlag } from '../src/hooks/useFeatureFlag';
 *
 *   function Dashboard() {
 *     const showV2Hero = useFeatureFlag('v2_dashboard_redesign');
 *     return showV2Hero ? <V2Hero /> : <V1Hero />;
 *   }
 *
 * Returns false BEFORE the per-session flag map has loaded —
 * this is the "fail closed during loading" invariant. v1 users
 * never see a flash of v2 UI while the flags GET is in flight.
 *
 * The provider (FeatureFlagsProvider in
 * src/context/FeatureFlagsContext.js) must be mounted above any
 * component that calls this hook. _layout.jsx wires it.
 */

import { useFeatureFlagsContext } from '../context/FeatureFlagsContext';

export function useFeatureFlag(flag) {
  const { flags, loaded } = useFeatureFlagsContext();
  if (!loaded) return false;       // fail closed during loading
  return Boolean(flags && flags[flag]);
}

export default useFeatureFlag;
