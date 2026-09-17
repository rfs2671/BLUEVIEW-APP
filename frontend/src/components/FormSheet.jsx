import React, { useEffect, useRef } from 'react';
import {
  Modal, View, Text, Pressable, ScrollView, KeyboardAvoidingView,
  Platform, StyleSheet,
} from 'react-native';
import { X } from 'lucide-react-native';
import { useTheme } from '../context/ThemeContext';
import { spacing, borderRadius } from '../styles/theme';
import { withAlpha } from '../styles/semanticColors';
import { ToastHost } from './Toast';

/**
 * A FORM PRESENTED OVER THE VIEWPORT, NOT APPENDED BELOW IT.
 *
 * ── THE BUG THIS EXISTS FOR ────────────────────────────────────────────────
 *
 * app/admin/users.jsx had four states called `showAddModal`, `showEditModal`,
 * `showAssignModal` and `showCsModal`, and NOT ONE React Native Modal in the
 * file — a grep for the opening tag returned zero. All four rendered as
 * plain `{cond && <GlassCard>}` blocks at the TAIL of the page's ScrollView,
 * after the user list. On a desktop the list is short and the block lands
 * near the fold, which is why it read as working. On a phone the list is a
 * screen-height of cards and the form opened somewhere below all of them: the
 * admin tapped Edit and nothing appeared to happen.
 *
 * The naming is the trap, and it is worth saying out loud because the next
 * person will read `showEditModal` and believe it: THOSE WERE NEVER MODALS.
 * A name is not a presentation. Nothing in the render tree made them one, and
 * nothing in the test suite could tell — the frontend suite reads source and
 * the mount smoke asks only "did it throw".
 *
 * ── WHY A SHARED COMPONENT AND NOT FOUR INLINE MODALS ──────────────────────
 *
 * The house pattern is inline: admin/safety-staff.jsx, admin/superintendent.jsx,
 * admin/site-devices.jsx and admin/checklists/index.jsx each open a
 * transparent slide-in Modal in place, repeating the overlay,
 * the card, the header and the action row. Copying that four more times would
 * have been the smaller diff and the wrong one, because two of the four things
 * these sheets must now do are BEHAVIOUR rather than markup:
 *
 *   FOCUS THE FIRST FIELD when it opens
 *   LOCK THE PAGE BEHIND IT so the backdrop does not scroll under the sheet
 *
 * Neither exists anywhere in the house pattern today. Written inline they are
 * four copies of an effect and a module-level counter, i.e. four places for
 * the next person to fix it in three of. So this is ONE component that keeps
 * the house pattern's markup and adds the two behaviours once.
 *
 * It is NOT a fifth dismissal convention. The three exits below are exactly
 * the set src/utils/modalHasAnExit.test.cjs already names as complete, in the
 * spelling src/components/ProjectRetentionCard.jsx already uses:
 *
 *   onRequestClose          Android's hardware back, and Escape on web
 *   a Pressable backdrop    tapping outside, with the card stopping the tap
 *                           so a press inside the form does not dismiss it
 *   an X IN THE HEADER      above the fold, whatever the form's length —
 *                           which is the one exit that does not rot as the
 *                           form grows, and the actual fix in that test
 *
 * ── THE SURFACE IS OPAQUE AND THEMED, DELIBERATELY ─────────────────────────
 *
 * The four screens above hardcode `backgroundColor: '#1a1a2e'` on the sheet —
 * a dark card that draws `colors.text.primary` on it, which in the LIGHT theme
 * is near-black text on a near-black card. `GlassCard variant="modal"` is the
 * other tempting reuse and is worse inside a real Modal: it drops the gradient
 * and leaves only a blur, and on native there is nothing behind a Modal to
 * blur (a Modal is a separate OS window), so the card renders as a 50%-opaque
 * wash over the dim backdrop. This takes ConfirmDialog.jsx's surface instead —
 * the shared dialog in this repo, already proven in both themes.
 *
 * ── AND THE TOAST HOST ─────────────────────────────────────────────────────
 *
 * Nothing in the app's view tree paints above a native Modal, toasts included;
 * src/utils/toastInsideModals.test.cjs is the whole argument. Every form moved
 * in here raises its refusals as toasts ("Please fill in all required fields",
 * "Could not create user", the one-job-rule warning), so without a second
 * mount point those sheets would refuse SILENTLY on a phone — a strictly worse
 * bug than the one being fixed. `<ToastHost />` renders null when no toast is
 * up, so a quiet sheet pays nothing for it.
 *
 * ── COMPONENT IDENTITY ─────────────────────────────────────────────────────
 *
 * This file, and everything that is used as a JSX element type inside it, is
 * declared at MODULE SCOPE. de2b330 (#388) is the reason: `Field`,
 * `CorrectionChoice` and `EntryList` were declared inside a screen's function
 * body, so each render produced a new function object, React compared element
 * types by reference, found them unequal and rebuilt the subtree — destroying
 * the TextInput on every keystroke, which is what "the keyboard closes after
 * every character" is. These sheets are full of text inputs. Nothing here may
 * be declared inside a render body; captures become props.
 *
 * Props:
 *   visible         — bool
 *   title           — header text
 *   subtitle        — optional line under the title
 *   onClose         — () => void, wired to all three exits
 *   initialFocusRef — optional ref focused when the sheet appears. Omit it and
 *                     the sheet card itself takes focus, which still moves the
 *                     caret and the screen reader off the page behind.
 *   footer          — the action row, pinned below the scrolling body
 *   children        — the form
 */

// ── PAGE SCROLL LOCK ───────────────────────────────────────────────────────
//
// WEB ONLY, and that is not laziness. On native a Modal is a separate OS
// window: the screen behind it is not in the same view hierarchy and cannot
// receive a scroll at all, so there is nothing to lock.
//
// ON WEB, MEASURED RATHER THAN ASSUMED (scripts/admin-users-sheets.cjs drives
// a wheel over the backdrop at 443px and reads the scroll positions):
//
//   THE APP'S OWN ScrollView IS ALREADY SAFE, and not because of anything
//   here. react-native-web portals the Modal onto document.body as a
//   `position: fixed` overlay (exports/Modal/ModalPortal.js and
//   ModalContent.js), so the overlay is not a descendant of that div and the
//   wheel never reaches it. Measured: scrollTop 600 before the sheet, 600
//   after 1500px of wheel over the backdrop.
//
//   THE DOCUMENT SCROLLER IS WHAT THESE TWO PIN, and on the Expo web shell
//   `body` already carries `overflow: hidden` while `documentElement` does
//   not — so on that shell this is observable on the root element and is a
//   no-op on the body. It is kept for the host where that is NOT true: this
//   bundle is also served behind other shells, and a component that relies on
//   the index.html of one of them has a dependency nobody wrote down.
//
// WHICH IS WHY THE PREVIOUS VALUE IS RESTORED rather than cleared: on that
// same shell "restore" means putting `hidden` BACK on the body, and a cleanup
// that reset it to '' would hand the page a scrollbar it never had.
//
// A COUNTER, NOT A BOOLEAN. Two sheets can be mounted at once — nothing in
// users.jsx closes the Assign sheet before opening the CS one — and with a
// boolean the first to close would unlock the page under the second. The
// counter is module scope because the lock is a property of the document, not
// of any one sheet.
let pageLockCount = 0;
let savedOverflow = null;

function lockPageScroll() {
  if (Platform.OS !== 'web' || typeof document === 'undefined' || !document.body) return;
  pageLockCount += 1;
  if (pageLockCount > 1) return;
  savedOverflow = {
    body: document.body.style.overflow,
    root: document.documentElement ? document.documentElement.style.overflow : '',
  };
  document.body.style.overflow = 'hidden';
  if (document.documentElement) document.documentElement.style.overflow = 'hidden';
}

function unlockPageScroll() {
  if (Platform.OS !== 'web' || typeof document === 'undefined' || !document.body) return;
  // NEVER DRIVEN NEGATIVE. An unlock without a matching lock (a remount, a
  // fast-refresh) would otherwise leave the count at -1 and the next lock
  // would be a no-op — the page would scroll under the sheet again, with
  // nothing to show for it.
  if (pageLockCount === 0) return;
  pageLockCount -= 1;
  if (pageLockCount > 0) return;
  document.body.style.overflow = savedOverflow ? savedOverflow.body : '';
  if (document.documentElement) {
    document.documentElement.style.overflow = savedOverflow ? savedOverflow.root : '';
  }
  savedOverflow = null;
}

// The sheet is presented before it can be focused, and the two platforms take
// different amounts of time to get there: on native the Modal is a window that
// does not exist yet on the render that sets `visible`, and the slide takes
// ~300ms; on web the portal node is in the document immediately and only the
// CSS slide is outstanding. Focusing during the transform makes Chrome scroll
// the sheet to the focused node mid-slide.
const FOCUS_DELAY_MS = Platform.OS === 'web' ? 80 : 300;

export default function FormSheet({
  visible,
  title,
  subtitle,
  onClose,
  initialFocusRef,
  footer,
  children,
}) {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const cardRef = useRef(null);

  useEffect(() => {
    if (!visible) return undefined;
    lockPageScroll();
    return unlockPageScroll;
  }, [visible]);

  useEffect(() => {
    if (!visible) return undefined;
    const t = setTimeout(() => {
      // The caller's field if it named one, otherwise the sheet itself. The
      // fallback is not decorative: a sheet with no text field (a project
      // picker) would otherwise leave focus on a button on the page BEHIND
      // it, so a keyboard or screen-reader user's next Tab walks the list
      // they cannot see instead of the dialog they just opened.
      const target = (initialFocusRef && initialFocusRef.current) || cardRef.current;
      if (target && typeof target.focus === 'function') target.focus();
    }, FOCUS_DELAY_MS);
    return () => clearTimeout(t);
  }, [visible, initialFocusRef]);

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={s.fill}
      >
        <Pressable style={s.backdrop} onPress={onClose}>
          {/* STOPS THE TAP AT THE CARD. Without this, every press inside the
              form reaches the backdrop and dismisses the sheet mid-edit. */}
          <Pressable
            ref={cardRef}
            style={s.card}
            onPress={(e) => e.stopPropagation()}
            // -1, NOT 0. react-native-web gives a Pressable tabIndex 0 by
            // default (exports/Pressable/index.js), which would put the card
            // itself in the tab order ahead of the first field. -1 keeps it
            // out of the order while still allowing the programmatic focus()
            // below — which is the whole difference between "tabbable" and
            // "focusable". No such prop on native, where there is no tab
            // order and the Modal window already holds the input focus.
            {...(Platform.OS === 'web' ? { tabIndex: -1 } : null)}
          >
            <View style={s.header}>
              <View style={s.headerText}>
                <Text style={s.title}>{title}</Text>
                {subtitle ? <Text style={s.subtitle}>{subtitle}</Text> : null}
              </View>
              {/* IN THE HEADER, not at the foot of the form. A Close below a
                  scrolling body is only reachable by scrolling to it, which is
                  the defect modalHasAnExit.test.cjs was written for. */}
              <Pressable
                onPress={onClose}
                accessibilityRole="button"
                accessibilityLabel="Close"
                style={s.headerClose}
              >
                <X size={20} strokeWidth={2} color={colors.text.secondary} />
              </Pressable>
            </View>

            <ScrollView
              style={s.body}
              contentContainerStyle={s.bodyContent}
              keyboardShouldPersistTaps="handled"
            >
              {children}
            </ScrollView>

            {footer ? <View style={s.footer}>{footer}</View> : null}

            {/* The second mount point, not a second treatment — see the header
                comment and src/utils/toastInsideModals.test.cjs. */}
            <ToastHost />
          </Pressable>
        </Pressable>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    fill: {
      flex: 1,
    },
    backdrop: {
      flex: 1,
      backgroundColor: withAlpha('#020617', 0.7),
      alignItems: 'center',
      justifyContent: 'center',
      padding: spacing.lg,
    },
    // maxHeight, not height: a two-field form is a short sheet rather than a
    // full-height one with a hole in it. The body scrolls when the form is
    // longer than the space, which is what keeps this usable at 443px with a
    // keyboard up.
    card: {
      width: '100%',
      maxWidth: 500,
      maxHeight: '85%',
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: isDark ? '#1e293b' : '#e2e8f0',
      backgroundColor: isDark ? '#0f172a' : '#ffffff',
      overflow: 'hidden',
      ...Platform.select({
        web: { boxShadow: '0 20px 40px rgba(0,0,0,0.45)' },
        default: {
          elevation: 12,
          shadowColor: '#000',
          shadowOpacity: 0.4,
          shadowRadius: 16,
          shadowOffset: { width: 0, height: 8 },
        },
      }),
    },
    header: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      justifyContent: 'space-between',
      gap: spacing.sm,
      padding: spacing.lg,
      borderBottomWidth: 1,
      borderBottomColor: colors.glass.border,
    },
    headerText: {
      flex: 1,
    },
    title: {
      fontSize: 20,
      fontWeight: '500',
      color: colors.text.primary,
    },
    subtitle: {
      fontSize: 14,
      color: colors.text.muted,
      marginTop: spacing.xs,
    },
    // 44 square at minimum, because this is the exit and it is being tapped
    // with a gloved thumb on a phone held at a jobsite.
    headerClose: {
      width: 44,
      height: 44,
      alignItems: 'center',
      justifyContent: 'center',
      marginTop: -spacing.sm,
      marginRight: -spacing.sm,
    },
    body: {
      flexShrink: 1,
    },
    bodyContent: {
      padding: spacing.lg,
    },
    footer: {
      flexDirection: 'row',
      justifyContent: 'flex-end',
      gap: spacing.sm,
      padding: spacing.lg,
      borderTopWidth: 1,
      borderTopColor: colors.glass.border,
    },
  });
}
