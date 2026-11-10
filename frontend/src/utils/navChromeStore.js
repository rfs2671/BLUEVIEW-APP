// Tiny external store: is the bottom nav on screen right now?
//
// FloatingNav is mounted by each screen separately, while the corner settings
// button lives once at the app root. This is how the root knows whether to show
// the button (it shows only where the nav does) and how other header pieces
// (the offline pill) know to leave room for it.
import { useSyncExternalStore } from 'react';

let count = 0;
const listeners = new Set();

const emit = () => listeners.forEach((l) => l());

export function registerNavChrome() {
  count += 1;
  emit();
  return () => {
    count = Math.max(0, count - 1);
    emit();
  };
}

const subscribe = (l) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

export function useNavChromeVisible() {
  return useSyncExternalStore(subscribe, () => count > 0, () => false);
}

// Width the corner button takes, so neighbours can clear it.
export const CORNER_BUTTON_SPACE = 56; // the 44dp corner gear plus a 12dp gap
