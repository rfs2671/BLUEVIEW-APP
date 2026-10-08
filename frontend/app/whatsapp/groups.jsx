// Integrations → WhatsApp → Project groups. Every group the Levelog number is
// in; a row opens that project's WhatsApp tab. Admins (and CPs) also link
// groups; a PM reads their own projects' groups only.
import React from 'react';
import { useAuth, isCompanyAdmin } from '../../src/context/AuthContext';
import WhatsAppScreen from '../../src/components/WhatsAppScreen';
import WhatsAppGroupsPanel from '../../src/components/WhatsAppGroupsPanel';

export default function WhatsAppGroupsScreen() {
  const { user } = useAuth();
  const role = String(user?.role || '').trim().toLowerCase();
  const canLink = isCompanyAdmin(user) || ['owner', 'admin', 'cp'].includes(role);
  return (
    <WhatsAppScreen title="Project groups">
      <WhatsAppGroupsPanel canLink={canLink} />
    </WhatsAppScreen>
  );
}
