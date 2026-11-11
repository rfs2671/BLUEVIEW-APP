// Tiny external store: is a full-screen document (the PDF reader) open right now?
//
// On desktop the sidebar rail sits above the page and used to cover the left edge of the document. While a document is
// open the rail hides all the way and only pops out when the cursor reaches the left edge of the screen.
import { useSyncExternalStore } from 'react';

let count = 0;
const listeners = new Set();
const emit = () => listeners.forEach((l) => l());

export function registerReader() {
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

export function useReaderOpen() {
  return useSyncExternalStore(subscribe, () => count > 0, () => false);
}
