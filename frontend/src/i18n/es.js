// Spanish catalogue. Key-identical to ./en.js for every namespace it declares —
// the test asserts that, so a key added to one and forgotten in the other fails
// CI instead of silently falling back to English.
//
// It does NOT declare every namespace en.js does. A logbook is a legal record
// filed with the DOB and is written in English; Spanish belongs where a WORKER
// must understand what he is signing (the gate, and any worker signature or
// acknowledgment line inside a logbook). Namespaces that are entirely CP-facing
// are English-only and are listed in EN_ONLY_NAMESPACES in i18n.test.cjs, which
// asserts they are absent here rather than merely tolerating the gap.
//
// Every string here was moved verbatim out of the component that used to own
// it.

export default {
  // ── DELIBERATELY ABSENT, NOT MISSING ──────────────────────────────────────
  //   dailyJobsite, logbookView, review, finalize, reportPreview
  //
  // A logbook is a legal record filed with the DOB, so it is written in
  // English — a DOB inspector reads English. Spanish belongs where a WORKER has
  // to understand what he is signing: the gate, and any line a worker signs or
  // acknowledges inside a logbook.
  //
  // All five are CP-, inspector- or admin-facing: the daily jobsite editor, the
  // filed-log viewer, the flagged-worker review screen, the lock/refusal
  // prompts, and the admin report preview. No worker signs anything on any of
  // them — every SignaturePad under app/logbooks/ captures the COMPETENT
  // PERSON's signature, and a worker's signature is captured at the gate and
  // rendered here read-only.
  //
  // Safe by construction: translate() falls back to DEFAULT_LOCALE when the
  // active locale has no entry (src/i18n/index.js), so a Spanish-locale user
  // sees English rather than a blank or a raw key. i18n.test.cjs lists these in
  // EN_ONLY_NAMESPACES and asserts they are ABSENT here — a partial declaration
  // or a well-meant re-translation FAILS.

  // ── src/components/SignaturePad.js — 5 keys, was the local SIG_STRINGS ─────
  //
  // KEPT, AND NOT AN OVERSIGHT — do not strip this in a future audit.
  //
  // Strictly this is CP-facing today: SignaturePad renders only on CP screens,
  // so by the rule above it would go. It stays because it is the exact
  // component a WORKER would use if worker signing moves in-app, which is on
  // the roadmap. Deleting its Spanish would delete the mechanism the
  // worker-signature exception depends on, and it would have to be rebuilt.
  //
  // It is therefore held to the NORMAL strict parity rules — key-identical with
  // en, no blanks, no untranslated copies — not to the EN-only allowlist.
  signature: {
    verified: 'VERIFICADO',
    unaffirmed: 'SIN AFIRMAR',
    affirm: 'Afirmar para este documento',
    clearResign: 'Borrar y Firmar de nuevo',
    unaffirmedHint: 'Firma heredada — toque Afirmar para dar fe de este documento.',
  },


  // ── app/admin/whatsapp-groups.jsx — conectar un grupo a una obra ──────────
  waGroups: {
    title: 'Grupos en espera',
    subtitle: 'Grupos donde está el asistente pero que aún no están conectados a una obra. Elija el proyecto y confirme — nada se conecta solo.',
    unavailableTitle: 'Grupos no disponibles',
    unavailableOffline: 'La lista de espera no se pudo obtener sin conexión.',
    unavailableError: 'La lista de espera no se pudo leer del servidor.',
    emptyTitle: 'Nada en espera',
    emptyDesc: 'Agregue el número de Levelog a un grupo de WhatsApp y aparecerá aquí.',
    unnamed: 'Grupo sin nombre',
    choose: 'Elija un proyecto',
    matched: 'Coincidencia por el nombre del grupo — cámbielo si no es correcto',
    confirm: 'Confirmar',
    confirmAll: 'Confirmar coincidencias',
    hide: 'Ocultar',
    connectedTitle: 'Conectado',
    connectFailTitle: 'No se pudo conectar',
    connectFailBody: 'Inténtelo de nuevo',
    offlineTitle: 'Sin conexión',
    offlineConnect: 'Conectar un grupo requiere conexión. No se cambió nada.',
    partialTitle: 'Algunos no se conectaron',
    hideFailTitle: 'No se pudo ocultar',
    deniedTitle: 'Acceso denegado',
    deniedBody: 'Se requiere acceso de propietario, administrador o CP',
  },

  // ── Botón Descargar (Planos y archivos) y abrir en el navegador (web) ─────
  fileDownload: {
    downloading: 'Descargando',
    progress: '{pct}% de {total} MB',
    progressUnknown: '{done} MB hasta ahora',
    cancel: 'Cancelar',
    failTitle: 'La descarga falló',
    failBody: 'No se pudo descargar el archivo. Inténtelo de nuevo.',
    network: 'La conexión se cortó antes de terminar el archivo. Inténtelo de nuevo con mejor señal.',
    noAccess: 'No tiene acceso a este archivo.',
    notStored: 'Este archivo aún no está disponible para descargar. Puede que todavía se esté sincronizando.',
    cancelled: 'Descarga cancelada.',
    popupBlocked: 'Su navegador bloqueó la pestaña de descarga. Permita las ventanas emergentes para Levelog e inténtelo de nuevo.',
    shareUnavailable: 'Este dispositivo no tiene opción para compartir archivos.',
    offlineTitle: 'No disponible sin conexión',
    offlineBody: 'Este archivo no está guardado en este dispositivo. Vuelva a conectarse e inténtelo de nuevo.',
  },

  // ── La etiqueta de Cumplimiento (ver en.js: una etiqueta, un espacio) ─────
  // "Enable DOB Tracking" queda en inglés: es el nombre del interruptor tal como
  // aparece en pantalla, y ese interruptor no está traducido.
  compliance: {
    penaltyHearingPending: '(audiencia pendiente)',
    title: 'Cumplimiento',
    loadError: 'No se pudieron cargar los datos de cumplimiento',
    deleteConfirmWeb: '¿Eliminar "{name}"?\n\nEsto eliminará permanentemente el proyecto y todos sus datos de cumplimiento. Esta acción no se puede deshacer.',
    deleteConfirmNative: 'Esto eliminará permanentemente "{name}" y todos sus datos de cumplimiento. Esta acción no se puede deshacer.',
    notificationPrefsSubtitle: 'Ajuste qué señales de cumplimiento le llegan y cómo',
    helpCheckTracking: 'Abra la página de Cumplimiento del proyecto (ícono de engranaje). Confirme que "Enable DOB Tracking" esté activado. Si está desactivado, no se obtendrán datos del DOB para el proyecto.',
    helpEditBin: 'Si el BIN ya se resolvió automáticamente al edificio equivocado, abra la página de Cumplimiento (ícono de engranaje) y edite el campo BIN directamente.',
  },

  // ── app/project/[id]/dob-logs.jsx — embargo navideño del DOT ─────────────
  dotEmbargo: {
    banner: 'Embargo navideño del 15 de nov al 2 de ene: {n} permisos activos del DOT no tienen exención.',
    bannerOne: 'Embargo navideño del 15 de nov al 2 de ene: 1 permiso activo del DOT no tiene exención.',
    permits: 'Permisos: {list}',
    action: 'Solicite una exención o detenga el trabajo del 15 de nov al 2 de ene.',
    unverifiedTitle: 'Embargo navideño del 15 de nov al 2 de ene: revise estos permisos',
    unverified: 'Exención no verificada: {list}',
  },

  // ── app/project/[id]/dob-logs.jsx — la pestaña del DOT (DOT Fase 1 B) ────
  dotCompliance: {
    tabLabel: 'Permisos del DOT',
    showing: 'Mostrando: permisos del DOT',
    setupTitle: 'Configure la vinculación de permisos del DOT',
    setupIntro: 'La mayoría de los permisos del DOT se registran por cuadra, no por dirección. Confirme las cuadras frente a su obra y los nombres a los que se emiten sus permisos.',
    suggestedNote: 'Sugerido a partir de los permisos ya vinculados a su dirección.',
    fallbackNote: 'Aún no hay permisos vinculados. Estas son cuadras que el DOT ha registrado en {street}.',
    noSuggestions: 'Aún no hay nada que sugerir. Agregue su frente a mano.',
    permitteesLabel: 'Permisos a nombre de',
    frontagesLabel: 'Sus cuadras (frentes)',
    frontageText: '{on} de {from} a {to}',
    frontageOneCross: '{on} en {cross}',
    seenOn: '{n} permisos',
    seenOnOne: '1 permiso',
    suggestedBy: 'Sugerido por {name}',
    suggestedByUnknown: 'Sugerido por un superintendente',
    pendingSuggestion: 'Esperando la confirmación de un administrador o gerente de obra.',
    confirm: 'Confirmar',
    edit: 'Editar',
    cancel: 'Cancelar',
    remove: 'Quitar',
    addFrontage: 'Agregar frente',
    suggestFrontage: 'Sugerir un frente',
    addPermittee: 'Agregar nombre',
    onStreet: 'Calle',
    fromStreet: 'Desde la calle transversal',
    toStreet: 'Hasta la calle transversal',
    permitteeName: 'Nombre del titular como lo escribe el DOT',
    readOnly: 'Un administrador de la empresa o gerente de obra confirma esta configuración.',
    confirmedTitle: 'Configuración del DOT confirmada',
    confirmedSummary: '{frontages} cuadras, {permittees} nombres de titulares',
    nextCheck: 'Los permisos de estas cuadras aparecerán tras la próxima revisión del DOT (cada 2 horas).',
    suggestionSent: 'Sugerencia enviada. Un administrador o gerente de obra la confirmará.',
    needsTitle: 'Requiere confirmación',
    needsPrompt: 'Permiso de {permittee} en su cuadra. ¿Es suyo?',
    unknownPermittee: 'otra empresa',
    accept: 'Sí, es nuestro',
    reject: 'No es nuestro',
    needsOlder: 'No se muestran {n} permisos anteriores de otros en su cuadra.',
    permitsTitle: 'Permisos',
    groupActive: 'Activos',
    groupExpiring: 'Vencen en 14 días o menos',
    groupExpired: 'Vencidos',
    renewedBy: 'Renovado por {permit}',
    waiverMissing: 'Sin exención del embargo navideño',
    waiverUnverified: 'Exención no verificada',
    workDates: 'Trabajo {start} – {end}',
    daysLeft: 'Quedan {n} días',
    dayLeft: 'Queda 1 día',
    endsToday: 'Termina hoy',
    permittee: 'Titular: {name}',
    noPermits: 'Aún no hay permisos del DOT en este proyecto.',
    loadFailed: 'No se pudieron cargar los permisos del DOT. Esto no es un historial limpio.',
    saveFailed: 'No se guardó. Inténtelo de nuevo.',
    frontageInvalid: 'Un frente necesita una calle y al menos una calle transversal.',
  },
};
