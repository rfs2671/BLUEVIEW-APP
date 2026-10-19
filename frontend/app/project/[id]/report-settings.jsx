import { useEffect } from 'react';
import { useRouter, useLocalSearchParams } from 'expo-router';

// Report Settings is part of Project → Reports now: the daily report's send
// time and the addresses it is emailed to sit with the rest of the job's
// report schedule. This route redirects there for old links and app builds.
export default function ReportSettingsRedirect() {
  const router = useRouter();
  const { id } = useLocalSearchParams();
  useEffect(() => {
    if (id) router.replace(`/projects/${id}/reports`);
  }, [id]);
  return null;
}
