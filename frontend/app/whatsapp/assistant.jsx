// Integrations → WhatsApp → Personal assistant: this person's own Levelog
// Assistant — on/off, morning brief time, weekends.
import React from 'react';
import WhatsAppScreen from '../../src/components/WhatsAppScreen';
import WhatsAppAssistantPanel from '../../src/components/WhatsAppAssistantPanel';

export default function WhatsAppAssistantScreen() {
  return (
    <WhatsAppScreen title="Personal assistant">
      <WhatsAppAssistantPanel />
    </WhatsAppScreen>
  );
}
