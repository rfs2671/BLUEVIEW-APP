// Integrations → WhatsApp → Company settings (Admins): company-wide
// switches, e.g. "Default: chase on Sundays".
import React from 'react';
import WhatsAppScreen from '../../src/components/WhatsAppScreen';
import CompanyWhatsAppPanel from '../../src/components/whatsapp/CompanyWhatsAppPanel';

export default function WhatsAppCompanyScreen() {
  return (
    <WhatsAppScreen title="Company settings">
      <CompanyWhatsAppPanel />
    </WhatsAppScreen>
  );
}
