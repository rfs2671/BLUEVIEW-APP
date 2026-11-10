import { useWindowDimensions } from 'react-native';
import { useNavChromeVisible, CORNER_BUTTON_SPACE } from '../utils/navChromeStore';
import { useIsDesktop } from '../hooks/useIsDesktop';

/**
 * Style for the right-hand group of a screen's header: moves it left of the always-there settings gear in the top
 * corner (CornerSettings) so the two never sit on top of each other. OfflineIndicator does the same for itself; a
 * screen with its own header button (compliance settings, add user) uses this.
 *
 *   <View style={[s.headerRight, useCornerInset()]}>
 */
export function useCornerInset() {
  const navChrome = useNavChromeVisible();
  const isDesktop = useIsDesktop();
  return navChrome && !isDesktop ? { marginRight: CORNER_BUTTON_SPACE } : null;
}

export default useCornerInset;

/**
 * Style for HeaderBrand on a screen that has its OWN right-hand header button next to the corner gear: the company name
 * gets only the room left after the back button, that button and the gear (24 padding each side, 44 back, 16 gap,
 * 16 gap, 44 button, 56 corner gear and gap), and shrinks or ends in an ellipsis rather than running under them.
 */
export function useBrandRoom() {
  const navChrome = useNavChromeVisible();
  const isDesktop = useIsDesktop();
  const { width } = useWindowDimensions();
  if (!navChrome || isDesktop) return null;
  return { maxWidth: Math.max(96, width - (24 + 44 + 16 + 16 + 44 + 56 + 24)) };
}
