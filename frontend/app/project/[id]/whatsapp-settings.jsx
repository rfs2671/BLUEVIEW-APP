/**
 * The Levelog Assistant settings now live on the project's WhatsApp tab
 * (app/projects/[id]/whatsapp-groups.jsx). This route is kept so links and
 * bookmarks to it still land in the right place.
 */

import React from 'react';
import { Redirect, useLocalSearchParams } from 'expo-router';

export default function WhatsAppSettingsRedirect() {
  const { id } = useLocalSearchParams();
  return <Redirect href={`/projects/${id}/whatsapp-groups`} />;
}
