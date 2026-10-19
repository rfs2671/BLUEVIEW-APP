import { useEffect } from 'react';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { useAuth } from '../../../src/context/AuthContext';

// Report Settings is part of Project → Reports now: the daily report's send
// time and the addresses it is emailed to sit with the rest of the job's
// report schedule. This route redirects there for old links and app builds —
// after the sign-in check the old screen made: a signed-out reader goes to
// /login, as before, not to a Reports screen whose calls would all fail.
export default function ReportSettingsRedirect() {
  const router = useRouter();
  const { id } = useLocalSearchParams();
  const { isAuthenticated, isLoading } = useAuth();
  useEffect(() => {
    if (isLoading) return;
    if (!isAuthenticated) { router.replace('/login'); return; }
    if (id) router.replace(`/projects/${id}/reports`);
  }, [id, isAuthenticated, isLoading]);
  return null;
}
