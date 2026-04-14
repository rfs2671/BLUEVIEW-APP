import { useEffect } from 'react';
import { useRouter } from 'expo-router';

// Insurance info moved to Settings → Profile.
// This page redirects to /settings for backward compatibility.
export default function AdminInsuranceRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace('/settings');
  }, []);
  return null;
}
