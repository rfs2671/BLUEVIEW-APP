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
    title: 'Cumplimiento',
    loadError: 'No se pudieron cargar los datos de cumplimiento',
    deleteConfirmWeb: '¿Eliminar "{name}"?\n\nEsto eliminará permanentemente el proyecto y todos sus datos de cumplimiento. Esta acción no se puede deshacer.',
    deleteConfirmNative: 'Esto eliminará permanentemente "{name}" y todos sus datos de cumplimiento. Esta acción no se puede deshacer.',
    notificationPrefsSubtitle: 'Ajuste qué señales de cumplimiento le llegan y cómo',
    helpCheckTracking: 'Abra la página de Cumplimiento del proyecto (ícono de engranaje). Confirme que "Enable DOB Tracking" esté activado. Si está desactivado, no se obtendrán datos del DOB para el proyecto.',
    helpEditBin: 'Si el BIN ya se resolvió automáticamente al edificio equivocado, abra la página de Cumplimiento (ícono de engranaje) y edite el campo BIN directamente.',
    showDobText: 'Mostrar texto del DOB',
    hideDobText: 'Ocultar texto del DOB',
    plainLineAi: 'Resumen escrito por IA a partir del texto del DOB',
    hearingAt: 'Audiencia el {date} a las {time}',
    hearingOn: 'Audiencia el {date}',
    penalty: 'Multa',
    penaltySetAtHearing: 'La multa se fija en la audiencia',
    balanceDue: 'Saldo pendiente {amount}',
    binOne: 'BIN del edificio: {bin}',
    binMany: 'BIN de los edificios: {list}',
    renewalOne: '1 permiso necesita renovación',
    renewalMany: '{n} permisos necesitan renovación',
  },

  // ── app/project/[id]/dob-logs.jsx — embargo navideño del DOT ─────────────
  dotEmbargo: {
    banner: 'Embargo navideño del 15 de nov al 2 de ene: {n} permisos activos del DOT no tienen exención.',
    bannerOne: 'Embargo navideño del 15 de nov al 2 de ene: 1 permiso activo del DOT no tiene exención.',
    permits: 'Permisos: {list}',
    action: 'Solicite una exención o detenga el trabajo del 15 de nov al 2 de ene.',
    coverageNote: 'Revisa los permisos vinculados a su dirección. Los permisos registrados por tramo de calle llegarán con la próxima actualización.',
    unverifiedTitle: 'Embargo navideño del 15 de nov al 2 de ene: revise estos permisos',
    unverified: 'Exención no verificada: {list}',
  },
};
