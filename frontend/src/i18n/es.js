// Spanish catalogue. Same namespaces and same key names as ./en.js — the test
// asserts the two catalogues are key-identical, so a key added to one and
// forgotten in the other fails CI instead of silently falling back to English.
//
// Every string here was moved verbatim out of the component that used to own
// it.

export default {
  // ── app/logbooks/review.jsx — 47 keys, was the local TRANSLATIONS map ──────
  review: {
    title: 'Revisión de Registros',
    subtitle: 'Trabajadores que requieren una decisión',
    selectProject: 'Seleccione un proyecto',
    noProjects: 'Aún no tiene proyectos asignados.',
    empty: 'Nada que revisar',
    emptyHint: 'No hay registros marcados en este proyecto.',
    loadError: 'No se pudieron cargar los registros marcados',
    offlineLoad: 'No se cargó — este dispositivo no puede comunicarse con el servidor. Esto NO confirma que no haya nada que revisar.',
    errorLoad: 'No se pudieron leer los registros marcados. Deslice para actualizar o inténtelo de nuevo.',
    offlineProjects: 'No se pudo cargar su lista de proyectos, por lo que no hay nada que seleccionar. Reconéctese y deslice para actualizar.',
    errorProjects: 'No se pudo leer su lista de proyectos. Deslice para actualizar o inténtelo de nuevo.',
    offlineWrite: 'Sin conexión — no se registró nada',
    offlineWriteHint: 'La decisión NO se guardó. Reconéctese e inténtelo de nuevo.',
    expiredSst: 'SST vencida',
    expiredOn: 'venció',
    needsTrade: 'Sin oficio asignado',
    needsTradeHint: 'Este proyecto no tenía oficios configurados cuando se registró.',
    approve: 'Aprobar',
    sendHome: 'Enviar a casa',
    approved: 'Aprobado',
    sentHome: 'Enviado a casa',
    by: 'por',
    reviewFailed: 'No se pudo registrar la decisión',
    approvedToast: 'Trabajador aprobado para permanecer en el sitio',
    sentHomeToast: 'Decisión de enviar a casa registrada',
    viewCard: 'Toque la tarjeta para ampliar',
    noCard: 'No hay imagen de la tarjeta',
    checkedInAt: 'Registrado',
    refresh: 'Actualizar',
    close: 'Cerrar',
    assignTrade: 'Asignar oficio',
    chooseTrade: 'Elija un oficio y empresa',
    assign: 'Asignar',
    cancel: 'Cancelar',
    assigned: 'Oficio asignado',
    assignedToast: 'Oficio asignado a este registro',
    assignFailed: 'No se pudo asignar el oficio',
    noRoster: 'Este proyecto aún no tiene oficios configurados — un administrador debe agregarlos primero.',
    // Códigos de motivo de revisión (el backend guarda el CÓDIGO; el texto va aquí).
    unknownSst: 'SST sin verificar',
    admit: 'Admitir',
    admittedUnverified: 'Admitido — credencial aún sin verificar',
    unknownAdmitHint: 'Admitir registra solo la entrada — no verifica la tarjeta. La credencial permanece marcada para revisión.',
    reason_CLASS_UNVERIFIED: 'No se pudo leer la clase de la tarjeta — verifique la tarjeta',
    reason_EXPIRY_IMPLAUSIBLE: 'La fecha de vencimiento no es plausible — reescanee o verifique',
    reason_EXPIRY_UNPARSEABLE: 'No se pudo leer la fecha de vencimiento — verifique la tarjeta',
    reason_EXPIRY_CONFLICT: 'Dos escaneos no coinciden en el vencimiento — verifique la tarjeta',
    reason_DUPLICATE_SST: 'Registros SST duplicados — consolide en uno',
  },

  // ── src/components/SignaturePad.js — 5 keys, was the local SIG_STRINGS ─────
  signature: {
    verified: 'VERIFICADO',
    unaffirmed: 'SIN AFIRMAR',
    affirm: 'Afirmar para este documento',
    clearResign: 'Borrar y Firmar de nuevo',
    unaffirmedHint: 'Firma heredada — toque Afirmar para dar fe de este documento.',
  },
};
