import React, { useCallback, useRef, useState } from 'react';
import ConfirmDialog from '../components/ConfirmDialog';
import { useAuth } from '../context/AuthContext';
import { useT } from '../i18n';

/**
 * LOG OUT WITHOUT SILENTLY LOSING WORK, AND WITHOUT HANDING IT ON.
 *
 * Every explicit "Log out" goes through here. It first lets the queued writes
 * go under this account (AuthContext.prepareLogout: a bounded drain, skipped
 * offline), then:
 *
 *   nothing left   logs out.
 *   something left asks — "N changes haven't been sent and will be deleted if
 *                  you log out" — Log out anyway / Cancel. Cancel keeps the
 *                  session and every queued write; Log out anyway deletes them.
 *
 * Deleting is the only other choice there is. Left on the device they would
 * replay after the next sign-in, under whoever that is.
 *
 * Returns { requestLogout, logoutDialog, loggingOut }. Render `logoutDialog`
 * once anywhere in the screen. `onLoggedOut` runs after the session is gone
 * (e.g. router.replace('/login')).
 */
export function useLogoutConfirm({ onLoggedOut } = {}) {
  const { prepareLogout, logout } = useAuth();
  const t = useT('logout');
  const [unsent, setUnsent] = useState(0);
  const [loggingOut, setLoggingOut] = useState(false);
  const busy = useRef(false);

  const finish = useCallback(async () => {
    setUnsent(0);
    // Already drained in prepareLogout; whatever is left is cleared, not sent.
    await logout({ drain: false });
    if (typeof onLoggedOut === 'function') onLoggedOut();
  }, [logout, onLoggedOut]);

  const requestLogout = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    setLoggingOut(true);
    try {
      const left = await prepareLogout();
      const n = (left && left.total) || 0;
      if (n > 0) {
        setUnsent(n);
        return;
      }
      await finish();
    } finally {
      busy.current = false;
      setLoggingOut(false);
    }
  }, [prepareLogout, finish]);

  const message = unsent === 1
    ? t('unsentBodyOne')
    : t('unsentBody').replace('{n}', String(unsent));

  const logoutDialog = (
    <ConfirmDialog
      visible={unsent > 0}
      destructive
      title={t('unsentTitle')}
      message={message}
      confirmLabel={t('logOutAnyway')}
      cancelLabel={t('cancel')}
      onConfirm={finish}
      onCancel={() => setUnsent(0)}
    />
  );

  return { requestLogout, logoutDialog, loggingOut };
}

export default useLogoutConfirm;
