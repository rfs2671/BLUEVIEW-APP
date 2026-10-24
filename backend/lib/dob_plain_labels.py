"""The plain one-liner a Compliance card leads with, from the record's DOB code.
Pure: no DB, no HTTP, no model.

WHY. A DOB card used to lead with `ai_summary`, which is DOB's own wording
("ATOI OBSERVED ACTIVE DEMOLITION IN PROGRESS. GENERAL CONTRACTOR FAILURE TO
PROVIDE ...") or a code ("DOB code: 2P7"). A superintendent reading it on a
phone should get one plain line of at most MAX_WORDS words, in English or
Spanish, and the DOB text behind a toggle.

DETERMINISTIC FIRST. A record whose code is in the tables below gets the
table's line. Every label was written from the official description of the
code, never from the record and never from memory of what a code "usually"
means; a code that is not in the tables gets NO label from here (the caller
falls through to the stored model line, lib/dob_plain_lines, or the generic
line below). A row of the table must say no more than its source says.

SOURCES
  * DOB complaint category codes (dataset eabe-havv `complaint_category`):
    NYC DOB, "Complaint Category" code list,
    https://www.nyc.gov/assets/buildings/pdf/complaint_category.pdf
    -- the same source dob_complaint_codes.DOB_CATEGORY_CODES transcribes;
    every code below is in that map, and its official wording is what
    `dob_text` shows under "Show DOB text".
  * ECB infraction codes (dataset 6bgk-3dad `infraction_code1`): the official
    charge descriptions in NYC OATH "Hearings Division Case Status"
    (https://data.cityofnewyork.us/d/jz4z-kudi), columns `charge_1_code` /
    `charge_1_code_description`, rows with issuing_agency "DEPT. OF
    BUILDINGS". OATH writes a DOB code with a leading "B" that 6bgk-3dad
    leaves off -- read 2026-10-24 on the three 588 Thomas S Boyland summonses:
    6bgk 282 = OATH B282, 1P3 = B1P3, 2P7 = B2P7. `ecb_code()` strips it.

BROAD CODES. OATH describes several DOB codes only as "MISCELLANEOUS
VIOLATIONS" (B106, B206, B306, B179, B279, B1P7, B2P7) and DOB's complaint
category 99 is "Other". Their table rows are marked `broad`: true, but no help
on a card when the record also carries DOB's own free text. A broad row is
used only when no better line exists -- after the model's line was refused
(lib/dob_plain_lines) or when the record has no free text at all.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

__all__ = [
    "MAX_WORDS", "COMPLAINT_CATEGORY_LABELS", "ECB_INFRACTION_LABELS",
    "word_count", "ecb_code", "is_ecb", "code_label", "generic_label",
    "dob_text", "free_text",
]

MAX_WORDS = 12

ECB_DATASET = "6bgk-3dad"


def _l(en: str, es: str, broad: bool = False) -> Dict[str, Any]:
    row: Dict[str, Any] = {"en": en, "es": es}
    if broad:
        row["broad"] = True
    return row


# ── DOB complaint categories (complaint_category.pdf) ───────────────────────
COMPLAINT_CATEGORY_LABELS: Dict[str, Dict[str, Any]] = {
    "01": _l("Accident at a construction or plumbing job",
             "Accidente en una obra de construcción o plomería"),
    "02": _l("Accident that hurt the public",
             "Accidente que afectó al público"),
    "03": _l("Neighboring buildings not protected from the work",
             "Edificios vecinos sin protección contra la obra"),
    "04": _l("Work done after legal hours",
             "Trabajo fuera del horario permitido"),
    "05": _l("Work without a permit", "Trabajo sin permiso"),
    "06": _l("Construction changing the grade or a watercourse",
             "Obra que cambia el nivel del terreno o un cauce"),
    "07": _l("Construction changing a watercourse",
             "Obra que cambia un cauce de agua"),
    "08": _l("No contractor's sign posted", "No hay letrero del contratista"),
    "09": _l("Too much debris", "Exceso de escombros"),
    "10": _l("Debris or part of the building falling or about to fall",
             "Escombros o partes del edificio cayendo o por caer"),
    "11": _l("Demolition without a permit", "Demolición sin permiso"),
    "12": _l("Unsafe or illegal demolition", "Demolición insegura o ilegal"),
    "13": _l("Elevator not ready for fire department use",
             "Ascensor no preparado para uso de los bomberos"),
    "14": _l("Excavation undermining a neighboring building",
             "Excavación que socava un edificio vecino"),
    "15": _l("Fence missing, inadequate or illegal",
             "Cerca inexistente, inadecuada o ilegal"),
    "16": _l("Inadequate support or shoring",
             "Soporte o apuntalamiento inadecuado"),
    "17": _l("Material or personnel hoist without a permit",
             "Montacargas o elevador de personal sin permiso"),
    "18": _l("Materials stored unsafely",
             "Materiales almacenados de forma insegura"),
    "19": _l("Illegal mechanical demolition", "Demolición mecánica ilegal"),
    "20": _l("Illegal work on a landmark building",
             "Trabajo ilegal en un edificio histórico"),
    "21": _l("Safety netting or guardrails damaged, inadequate or missing",
             "Redes de seguridad o barandas dañadas, inadecuadas o ausentes"),
    "22": _l("No safety netting", "No hay redes de seguridad"),
    "23": _l("Sidewalk shed or scaffold defective, missing or unpermitted",
             "Cobertizo de acera o andamio defectuoso, ausente o sin permiso"),
    "24": _l("No sidewalk shed", "No hay cobertizo de acera"),
    "25": _l("Warning signs or lights missing",
             "Faltan letreros o luces de advertencia"),
    "26": _l("No watchman", "No hay vigilante"),
    "28": _l("Building in danger of collapse",
             "Edificio en peligro de derrumbe"),
    "29": _l("Vacant building open and unguarded",
             "Edificio vacío abierto y sin vigilancia"),
    "30": _l("Building shaking or vibrating; stability affected",
             "Edificio temblando o vibrando; estabilidad afectada"),
    "31": _l("No certificate of occupancy, or use contrary to it",
             "Sin certificado de ocupación, o uso contrario a este"),
    "32": _l("Certificate of occupancy not being followed",
             "No se cumple el certificado de ocupación"),
    "37": _l("Exit locked, blocked or improper",
             "Salida cerrada con llave, bloqueada o inadecuada"),
    "38": _l("Exit door not proper", "Puerta de salida inadecuada"),
    "39": _l("No secondary way out", "No hay salida secundaria"),
    "40": _l("Part of the building fell", "Se cayó una parte del edificio"),
    "41": _l("Part of the building in danger of falling",
             "Parte del edificio en peligro de caer"),
    "43": _l("Structural stability affected",
             "Estabilidad estructural afectada"),
    "45": _l("Illegal conversion", "Conversión ilegal"),
    "46": _l("No place of assembly permit",
             "No hay permiso de lugar de reunión pública"),
    "47": _l("Place of assembly permit not being followed",
             "No se cumple el permiso de lugar de reunión pública"),
    "52": _l("Sprinkler system inadequate", "Sistema de rociadores inadecuado"),
    "53": _l("Vent or exhaust illegal or improper",
             "Ventilación o extracción ilegal o inadecuada"),
    "54": _l("Wall or retaining wall bulging or cracked",
             "Muro o muro de contención abombado o agrietado"),
    "56": _l("Boiler fumes, smoke or carbon monoxide",
             "Gases, humo o monóxido de carbono de la caldera"),
    "57": _l("Illegal boiler", "Caldera ilegal"),
    "58": _l("Boiler defective, not working or without a permit",
             "Caldera defectuosa, sin funcionar o sin permiso"),
    "59": _l("Defective or exposed electrical wiring",
             "Cableado eléctrico defectuoso o expuesto"),
    "60": _l("Improper electrical work", "Trabajo eléctrico inadecuado"),
    "61": _l("Unlicensed electrical work in progress",
             "Trabajo eléctrico sin licencia en curso"),
    "62": _l("Dangerous elevator, or open unguarded shaft",
             "Ascensor peligroso, o hueco abierto sin protección"),
    "63": _l("Elevator defective or not working",
             "Ascensor defectuoso o fuera de servicio"),
    "64": _l("Elevator shaft open and unguarded",
             "Hueco del ascensor abierto y sin protección"),
    "65": _l("Gas hookup or piping illegal or defective",
             "Conexión o tubería de gas ilegal o defectuosa"),
    "66": _l("Plumbing work illegal or without a permit",
             "Trabajo de plomería ilegal o sin permiso"),
    "67": _l("Crane unsafe, illegal, or without permit, license or certificate",
             "Grúa insegura, ilegal, o sin permiso, licencia o certificado"),
    "68": _l("Unsafe or illegal crane or scaffold operation",
             "Operación insegura o ilegal de grúa o andamio"),
    "69": _l("Unsafe crane or scaffold installation or equipment",
             "Instalación o equipo inseguro de grúa o andamio"),
    "70": _l("Suspension scaffold hanging with no work underway",
             "Andamio colgante instalado sin trabajo en curso"),
    "73": _l("Failure to maintain the building",
             "Falta de mantenimiento del edificio"),
    "76": _l("Unlicensed, illegal or improper plumbing work in progress",
             "Trabajo de plomería sin licencia, ilegal o inadecuado en curso"),
    "77": _l("Accessibility requirements not met",
             "No se cumplen los requisitos de accesibilidad"),
    "80": _l("Elevator not inspected, illegal or without a permit",
             "Ascensor sin inspección, ilegal o sin permiso"),
    "81": _l("Elevator accident", "Accidente de ascensor"),
    "82": _l("Boiler accident or explosion",
             "Accidente o explosión de caldera"),
    "83": _l("Construction contrary to or beyond approved plans or permits",
             "Obra contraria a los planos o permisos aprobados, o más allá"),
    "84": _l("Facade defective or cracking",
             "Fachada defectuosa o agrietada"),
    "85": _l("Improper drainage or failure to retain water",
             "Drenaje inadecuado o falta de retención de agua"),
    "86": _l("Work continuing despite a stop work order",
             "Trabajo que continúa pese a una orden de suspensión"),
    "88": _l("Safety netting or guardrails damaged, inadequate or missing",
             "Redes de seguridad o barandas dañadas, inadecuadas o ausentes"),
    "89": _l("Accident with a crane, derrick or suspended scaffold",
             "Accidente con grúa, torre de izaje o andamio colgante"),
    "90": _l("Unlicensed or illegal activity", "Actividad ilegal o sin licencia"),
    "91": _l("Site conditions endangering workers",
             "Condiciones de la obra que ponen en peligro a los trabajadores"),
    "93": _l("Request for a retaining wall safety inspection",
             "Solicitud de inspección de seguridad de un muro de contención"),
    "94": _l("Plumbing defective, leaking or not maintained",
             "Plomería defectuosa, con fugas o sin mantenimiento"),
    "96": _l("Unlicensed boiler, electrical, plumbing or sign work completed",
             "Trabajo de caldera, electricidad, plomería o letrero hecho sin licencia"),
    "97": _l("Another agency's jurisdiction",
             "Bajo la jurisdicción de otra agencia"),
    "98": _l("Referred to DOB operations for a decision",
             "Remitida a operaciones del DOB para una decisión"),
    "99": _l("Other DOB complaint", "Otra queja al DOB", broad=True),
    "1E": _l("Suspended scaffold dangerous, unpermitted, unlicensed or in an accident",
             "Andamio colgante peligroso, sin permiso, sin licencia o accidentado"),
    "1F": _l("Annual crane inspection not done",
             "No se hizo la inspección anual de la grúa"),
    "1G": _l("Stalled construction site", "Obra de construcción paralizada"),
    "2A": _l("Posted notice or order removed or tampered with",
             "Aviso u orden publicada retirada o alterada"),
    "2B": _l("Vacate order not followed", "No se cumple la orden de desalojo"),
    "2C": _l("Smoking on the construction site", "Fumar en la obra"),
    "2D": _l("No-smoking signs not seen on the construction site",
             "No se ven letreros de no fumar en la obra"),
    "2F": _l("Building under structural monitoring",
             "Edificio bajo monitoreo estructural"),
    "2K": _l("Structurally compromised building",
             "Edificio estructuralmente comprometido"),
    "2L": _l("Facade reported unsafe", "Fachada reportada como insegura"),
    "3A": _l("Unlicensed, illegal or improper electrical work in progress",
             "Trabajo eléctrico sin licencia, ilegal o inadecuado en curso"),
    "3B": _l("Routine inspection", "Inspección de rutina"),
    "3C": _l("Plan compliance inspection",
             "Inspección de cumplimiento de planos"),
    "4B": _l("Professional certification compliance audit",
             "Auditoría de cumplimiento de certificación profesional"),
    "4K": _l("Construction safety tracking complaint",
             "Queja de seguimiento de seguridad en la construcción"),
    "4L": _l("Construction safety tracking complaint, high-rise",
             "Queja de seguimiento de seguridad en obra de gran altura"),
    "4M": _l("Construction safety tracking complaint, low-rise",
             "Queja de seguimiento de seguridad en obra de poca altura"),
    "4X": _l("After-hours work with an after-hours permit",
             "Trabajo fuera de horario con permiso para ese horario"),
    "5A": _l("Request for a joint FDNY and DOB inspection",
             "Solicitud de inspección conjunta del FDNY y el DOB"),
    "5B": _l("Lightweight materials rules not followed",
             "No se cumplen las normas de materiales livianos"),
    "5C": _l("Structural stability affected at a new building under construction",
             "Estabilidad estructural afectada en un edificio nuevo en obra"),
    "5F": _l("Compliance inspection", "Inspección de cumplimiento"),
    "5G": _l("Unlicensed, illegal or improper work in progress",
             "Trabajo sin licencia, ilegal o inadecuado en curso"),
    "5J": _l("Multi-agency joint inspection",
             "Inspección conjunta de varias agencias"),
    "6X": _l("Work-without-permits watch list check",
             "Control de la lista de vigilancia de trabajo sin permiso"),
    "6Y": _l("Local law audit", "Auditoría de leyes locales"),
    "6Z": _l("Training compliance check",
             "Control de cumplimiento de capacitación"),
    "7J": _l("Work without a permit in an occupied multiple dwelling",
             "Trabajo sin permiso en un edificio residencial ocupado"),
    "7K": _l("Local law compliance inspection on an active job",
             "Inspección de cumplimiento de ley local en una obra activa"),
    "8A": _l("Construction safety compliance action",
             "Acción de cumplimiento de seguridad en la construcción"),
}


# ── ECB infraction codes (OATH charge descriptions, "B" prefix removed) ─────
_MISC = _l("Miscellaneous building code violation",
           "Infracción variada del código de construcción", broad=True)

ECB_INFRACTION_LABELS: Dict[str, Dict[str, Any]] = {
    # WORK WITHOUT A PERMIT
    "101": _l("Work without a permit", "Trabajo sin permiso"),
    "201": _l("Work without a permit", "Trabajo sin permiso"),
    "301": _l("Work without a permit", "Trabajo sin permiso"),
    # FAILURE TO MAINTAIN BUILDING IN CODE-COMPLIANT MANNER
    "102": _l("Building not maintained to code",
              "Edificio sin mantenimiento conforme al código"),
    "202": _l("Building not maintained to code",
              "Edificio sin mantenimiento conforme al código"),
    "302": _l("Building not maintained to code",
              "Edificio sin mantenimiento conforme al código"),
    # OCCUPANCY CONTRARY TO THAT ALLOWED BY C OF O OR BUILDING DEPT RECORDS
    "103": _l("Occupancy contrary to the certificate of occupancy",
              "Ocupación contraria al certificado de ocupación"),
    "203": _l("Occupancy contrary to the certificate of occupancy",
              "Ocupación contraria al certificado de ocupación"),
    "303": _l("Occupancy contrary to the certificate of occupancy",
              "Ocupación contraria al certificado de ocupación"),
    # FAILURE TO MAINTAIN BUILDING WALL S OR APPURTENANCES
    "104": _l("Building walls or attachments not maintained",
              "Muros o elementos adosados del edificio sin mantenimiento"),
    "204": _l("Building walls or attachments not maintained",
              "Muros o elementos adosados del edificio sin mantenimiento"),
    # BUILDING OR OPEN LOT OCCUPIED WITHOUT A VALID CERTIFICATE OF OCCUPANCY
    "107": _l("Occupied without a valid certificate of occupancy",
              "Ocupado sin un certificado de ocupación válido"),
    # ALT CHANGED BLDG OCCUPIED W O VALID C OF O
    "108": _l("Altered building occupied without a valid certificate of occupancy",
              "Edificio alterado ocupado sin certificado de ocupación válido"),
    "208": _l("Altered building occupied without a valid certificate of occupancy",
              "Edificio alterado ocupado sin certificado de ocupación válido"),
    # FAIL TO SAFEGUARD PUBLIC AND PROPERTY
    "109": _l("Failed to safeguard the public and property",
              "No se protegió al público ni a la propiedad"),
    "209": _l("Failed to safeguard the public and property",
              "No se protegió al público ni a la propiedad"),
    # FAILURE TO NOTIFY THE DEPT PRIOR TO THE COMMENCEMENT OF EARTHWORK
    "111": _l("DOB not notified before earthwork started",
              "No se avisó al DOB antes de iniciar el movimiento de tierra"),
    # UNLAWFULLY CONTINUED WORK WHILE ON NOTICE OF A STOP WORK ORDER
    "112": _l("Work continued under a stop work order",
              "Se siguió trabajando bajo una orden de suspensión"),
    # FAILURE TO INSTITUTE MAINTAIN SAFETY EQUIPMENT - NO GUARD RAILS
    "115": _l("Required safety equipment missing: no guardrails",
              "Falta equipo de seguridad requerido: sin barandas"),
    # FAILURE TO PROVIDE REQUIRED NOTIFICATION PRIOR TO DEMOLITION
    "116": _l("Required notice not given before demolition",
              "No se dio el aviso requerido antes de la demolición"),
    # FAILURE TO INSTITUTE MAINTAIN SAFETY EQUIPMENT MEASURES - NO HANDRAILS
    "120": _l("Required safety equipment missing: no handrails",
              "Falta equipo de seguridad requerido: sin pasamanos"),
    # DEMOLITION WORK WITHOUT REQUIRED DEMOLITION PERMIT
    "121": _l("Demolition without the required demolition permit",
              "Demolición sin el permiso de demolición requerido"),
    # FAILURE TO PROVIDE UNOBSTRUCTED EXIT PASSAGEWAY
    "127": _l("Exit passageway not kept clear",
              "Pasillo de salida no despejado"),
    # FAILURE PROVIDE SIDEWALK SHED WHERE REQUIRED
    "131": _l("No sidewalk shed where one is required",
              "No hay cobertizo de acera donde se requiere"),
    # FAIL MAINTAIN BLDG COMPLIANT MANNER: NO FIRE STOPPING
    "139": _l("No fire stopping", "Sin sellado cortafuego"),
    "239": _l("No fire stopping", "Sin sellado cortafuego"),
    # FAILURE TO MAINTAIN ELEVATOR OR CONVEYING SYSTEM
    "151": _l("Elevator or conveying system not maintained",
              "Ascensor o sistema de transporte sin mantenimiento"),
    "251": _l("Elevator or conveying system not maintained",
              "Ascensor o sistema de transporte sin mantenimiento"),
    # FAILURE TO MAINTAIN ADEQUATE HOUSEKEEPING PER SECTION REQUIREMENTS
    "181": _l("Inadequate housekeeping on site",
              "Limpieza y orden inadecuados en la obra"),
    "212": _l("Inadequate housekeeping on site",
              "Limpieza y orden inadecuados en la obra"),
    # WORK DOES NOT CONFORM TO APPROVED CONSTRUCTION DOCUMENTS AMENDMENTS
    "182": _l("Work does not match the approved plans",
              "El trabajo no coincide con los planos aprobados"),
    "282": _l("Work does not match the approved plans",
              "El trabajo no coincide con los planos aprobados"),
    # UNSAFE STORAGE OF COMBUSTIBLE MATERIAL AND EQUIPMENT
    "183": _l("Combustible material or equipment stored unsafely",
              "Material o equipo combustible almacenado de forma insegura"),
    # UNLAWFUL ACTS. FAILURE TO COMPLY WITH AN ORDER OF THE COMMISSIONER
    "187": _l("Commissioner's order not followed",
              "No se cumplió una orden del comisionado"),
    # FAIL TO MAINTAIN REQUIRED NUMBER OF MEANS OF EGRESS FOR EVERY FLOOR
    "189": _l("Required exits not kept on every floor",
              "No se mantienen las salidas requeridas en cada piso"),
    # FAIL TO NOTIFY DOB OF ACCIDENT INCIDENT DAMAGE TO ADJOINING PROPERTY
    "192": _l("DOB not told of an accident or damage next door",
              "No se avisó al DOB de un accidente o daño al vecino"),
    # ILLEGAL USE IN RESIDENTIAL DISTRICT
    "205": _l("Illegal use in a residential district",
              "Uso ilegal en una zona residencial"),
    "385": _l("Illegal use in a residential district",
              "Uso ilegal en una zona residencial"),
    # TEMPORARY CONSTRUCTION EQUIPMENT INSTALLATION ON SITE EXPIRED PERMIT
    "207": _l("Temporary construction equipment on site with an expired permit",
              "Equipo temporal de obra con permiso vencido"),
    # FAIL TO PROVIDE APPROVED OR ACCEPTED CONSTRUCTION DOCS AT JOB SITE
    "210": _l("Approved construction documents not at the job site",
              "Documentos de obra aprobados ausentes en la obra"),
    # JOB SITE FENCE NOT CONSTRUCTED OR MAINTAINED PURSUANT TO SECTION
    "211": _l("Job site fence not built or kept to code",
              "Cerca de la obra no construida o mantenida según el código"),
    # SIGN PANEL NOT PROVIDED OR NOT IN COMPLIANCE WITH SECTION
    "217": _l("Site sign panel missing or not to code",
              "Panel de letrero de obra ausente o no conforme"),
    # FAILURE TO POST OR PROPERLY POST PERMIT FOR WORK AT PREMISES
    "220": _l("Permit not posted, or not posted properly",
              "Permiso no exhibido, o mal exhibido"),
    # PEDESTRIAN PROTECTION DOES NOT MEET CODE SPECIFICATIONS
    "223": _l("Pedestrian protection does not meet code",
              "La protección peatonal no cumple el código"),
    # FAIL TO FILE AMENDMENT ACCEPTABLE REPORT TO CORRECT UNSAFE CONDITIONS
    "227": _l("Report to correct unsafe conditions not filed",
              "No se presentó el informe para corregir condiciones inseguras"),
    # FAILURE TO SUBMIT REQUIRED REPORT OF CRITICAL EXAMINATION (exterior wall)
    "230": _l("Required exterior wall examination report not submitted",
              "No se presentó el informe requerido de examen de fachada"),
    # FAIL TO MAINTAIN BLDG IN CODE-COMPLIANT MANNER: ILLUMINATION FOR EXITS
    "232": _l("Exit lighting not maintained",
              "Iluminación de salidas sin mantenimiento"),
    # FAIL MAINTAIN BLDG IN COMPLIANT MANNER: LACK EMERGENCY LIGHT FOR EXITS
    "238": _l("No emergency lighting for exits",
              "Sin iluminación de emergencia para las salidas"),
    # ILLEGAL USE IN A COMMERCIAL DISTRICT
    "247": _l("Illegal use in a commercial district",
              "Uso ilegal en una zona comercial"),
    # EXIT DOOR NOT SELF-CLOSING
    "252": _l("Exit door not self-closing", "La puerta de salida no cierra sola"),
    # FAIL MAINTAIN BLDG IN COMPLIANT MANNER: SERVICE EQUIPMENT - BOILER
    "254": _l("Boiler not maintained to code",
              "Caldera sin mantenimiento conforme al código"),
    "354": _l("Boiler not maintained to code",
              "Caldera sin mantenimiento conforme al código"),
    # FAIL TO NOTIFY DOB PRIOR TO INSTALLATION REMOVAL OF SUSPENDED SCAFFOLD
    "261": _l("DOB not told before a suspended scaffold went up or down",
              "Sin aviso al DOB antes de instalar o retirar un andamio colgante"),
    # FAIL TO COMPLY W COMMISSIONER ORDER TO FILE CERT OF CORRECTION W DOB
    "263": _l("Certificate of correction not filed as ordered",
              "No se presentó el certificado de corrección ordenado"),
    # FAILURE TO FILE COMPLETE BOILER INSPECTION REPORT
    "265": _l("Complete boiler inspection report not filed",
              "No se presentó el informe completo de inspección de caldera"),
    # VIOLATION OF PARKING REGULATIONS IN A RESIDENTIAL DISTRICT
    "283": _l("Parking rules broken in a residential district",
              "Infracción de reglas de estacionamiento en zona residencial"),
    "383": _l("Parking rules broken in a residential district",
              "Infracción de reglas de estacionamiento en zona residencial"),
    # FENCE EXCEEDS PERMITTED HEIGHT
    "307": _l("Fence taller than allowed", "Cerca más alta de lo permitido"),
    # ELECTRICAL WORK WITHOUT A PERMIT
    "1C9": _l("Electrical work without a permit", "Trabajo eléctrico sin permiso"),
    "2C4": _l("Electrical work without a permit", "Trabajo eléctrico sin permiso"),
    "309": _l("Electrical work without a permit", "Trabajo eléctrico sin permiso"),
    # UNAPPROVED UNSAFE UNSUITABLE ELECTRICAL EQUIPMENT OR WIRING IN USE
    "1D2": _l("Unapproved or unsafe electrical equipment or wiring in use",
              "Equipo o cableado eléctrico no aprobado o inseguro en uso"),
    "2C9": _l("Unapproved or unsafe electrical equipment or wiring in use",
              "Equipo o cableado eléctrico no aprobado o inseguro en uso"),
    # FAIL TO TAKE REQUIRED MEASURES TO SECURE PUBLIC SAFETY - UNSAFE FACADE
    "1E4": _l("Unsafe facade: required public safety measures not taken",
              "Fachada insegura: no se tomaron las medidas de seguridad requeridas"),
    # FAILURE TO COMPLY WITH MANUFACTURER SPECIFICATIONS
    "1F1": _l("Manufacturer specifications not followed",
              "No se siguieron las especificaciones del fabricante"),
    "2F6": _l("Manufacturer specifications not followed",
              "No se siguieron las especificaciones del fabricante"),
    # FAILURE TO MAINTAIN DISPLAY ON SITE DOCUMENTS REQUIRED BY BC CHAPTER 33
    "1F2": _l("Required site documents not kept on display",
              "Documentos requeridos no exhibidos en la obra"),
    "2F7": _l("Required site documents not kept on display",
              "Documentos requeridos no exhibidos en la obra"),
    # TAMPERED WITH, REMOVED OR DEFACED A WRITTEN POSTED STOP WORK ORDER
    "1F8": _l("Posted stop work order tampered with or removed",
              "Orden de suspensión publicada alterada o retirada"),
    # FAILURE TO OBEY A VACATE ORDER FROM THE COMMISSIONER
    "1F9": _l("Commissioner's vacate order not obeyed",
              "No se obedeció la orden de desalojo del comisionado"),
    # REMOVED OR DEFACED A WRITTEN POSTED VACATE ORDER
    "1G1": _l("Posted vacate order removed or defaced",
              "Orden de desalojo publicada retirada o dañada"),
    # FAILURE TO DESIGNATE AND OR HAVE CONSTRUCTION SUPERINTENDENT PRESENT
    "1G6": _l("No construction superintendent designated or present",
              "Sin superintendente de obra designado o presente"),
    # CONSTRUCTION SUPERINTENDENT FAILED TO PERFORM DUTIES PER CODE
    "2G5": _l("Construction superintendent did not perform required duties",
              "El superintendente de obra no cumplió sus funciones"),
    # FAILED TO TIMELY NOTIFY DEPT. OF AN INCIDENT-FATALITY INJURY
    "1M7": _l("DOB not notified in time of an injury or death",
              "No se avisó a tiempo al DOB de una lesión o muerte"),
    # FAILED TO PROTECT ADJ. PROPERTY
    "1P3": _l("Failed to protect the neighboring property",
              "No se protegió la propiedad vecina"),
    "2P3": _l("Failed to protect the neighboring property",
              "No se protegió la propiedad vecina"),
    # TEMP CONSTRUCTION EQUIP INSTALLATION ON SITE EXPIRED PERMIT SHED
    "2P8": _l("Sidewalk shed on site with an expired permit",
              "Cobertizo de acera con permiso vencido"),
    # PERMIT HOLDER FAIL TO PROVIDE ACCESS AND OR EXPOSE WORK ON ACTIVE SITE
    "2A7": _l("Permit holder did not give access to the work",
              "El titular del permiso no dio acceso al trabajo"),
    # FAIL TO CONDUCT FILE A FINAL INSPECTION OF PERMITTED WORK W THE DEPT.
    "2G1": _l("Final inspection of permitted work not done or filed",
              "No se hizo o presentó la inspección final del trabajo"),
    # FAIL TO OBTAIN TEMP CONST PERMIT PRIOR TO INSTALL USE TEMP CONST. EQUIP
    "2L1": _l("Temporary construction equipment used without a permit",
              "Equipo temporal de obra usado sin permiso"),
    # MISCELLANEOUS VIOLATIONS -- broad, see the module docstring.
    "106": _MISC, "206": _MISC, "306": _MISC, "179": _MISC, "279": _MISC,
    "1P7": _MISC, "2P7": _MISC,
}


def word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", str(text or "").strip()) if w])


def ecb_code(raw: Any) -> str:
    """6bgk-3dad `infraction_code1` / OATH `charge_1_code` -> the table key:
    upper-cased, spaces removed, OATH's leading "B" dropped ('B282' -> '282')."""
    s = re.sub(r"\s+", "", str(raw or "")).upper()
    if len(s) == 4 and s.startswith("B"):
        s = s[1:]
    return s


def is_ecb(row: Dict[str, Any]) -> bool:
    """An ECB/OATH summons row (dataset 6bgk-3dad). A stop-work wording in the
    description can make its violation_subtype SWO, so the subtype alone is
    not the test."""
    return (str(row.get("dataset") or "") == ECB_DATASET
            or bool(row.get("ecb_status"))
            or str(row.get("violation_subtype") or "") == "ECB")


def _is_311(row: Dict[str, Any]) -> bool:
    return (str(row.get("source") or "") == "311"
            or str(row.get("complaint_source") or "").startswith("311")
            or str(row.get("raw_dob_id") or "").startswith("311:"))


def code_label(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The table row for this record's code, or None. Never invents one."""
    rtype = str(row.get("record_type") or "")
    if rtype == "complaint" and not _is_311(row):
        code = str(row.get("complaint_type") or row.get("complaint_category") or "").strip().upper()
        return COMPLAINT_CATEGORY_LABELS.get(code)
    if rtype in ("violation", "swo") and is_ecb(row):
        return ECB_INFRACTION_LABELS.get(ecb_code(row.get("infraction_code")))
    return None


# The generic line when nothing better exists. Neutral: it names the kind of
# record and points at the text, and says nothing about what happened.
_GENERIC = {
    "complaint": _l("DOB complaint — see DOB text", "Queja del DOB — vea el texto del DOB"),
    "complaint_311": _l("311 complaint — see complaint text",
                        "Queja al 311 — vea el texto de la queja"),
    "ecb": _l("ECB violation — see DOB text", "Infracción de la ECB — vea el texto del DOB"),
    "violation": _l("DOB violation — see DOB text", "Infracción del DOB — vea el texto del DOB"),
    "swo": _l("DOB stop work order — see DOB text",
              "Orden de suspensión del DOB — vea el texto del DOB"),
}


def generic_label(row: Dict[str, Any]) -> Dict[str, str]:
    rtype = str(row.get("record_type") or "")
    if rtype == "complaint":
        key = "complaint_311" if _is_311(row) else "complaint"
    elif rtype == "swo":
        key = "swo"
    elif is_ecb(row):
        key = "ecb"
    else:
        key = "violation"
    return {"en": _GENERIC[key]["en"], "es": _GENERIC[key]["es"]}


def _squash(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def dob_text(row: Dict[str, Any]) -> str:
    """The record's full text as DOB (or 311) wrote it: what "Show DOB text"
    reveals, and the ONLY text the model is given and checked against."""
    rtype = str(row.get("record_type") or "")
    if rtype == "complaint":
        if _is_311(row):
            parts = [_squash(row.get("complaint_type")), _squash(row.get("description")),
                     _squash(row.get("resolution_description"))]
            return ". ".join(p for p in parts if p)
        try:
            from dob_complaint_codes import DOB_CATEGORY_CODES, DOB_DISPOSITION_CODES
        except Exception:                                  # pragma: no cover
            DOB_CATEGORY_CODES, DOB_DISPOSITION_CODES = {}, {}
        out = []
        cat = str(row.get("complaint_type") or "").strip()
        if cat:
            desc = (DOB_CATEGORY_CODES.get(cat) or {}).get("desc")
            out.append(f"Category {cat}: {desc}" if desc else f"Category {cat}")
        disp = str(row.get("disposition_code") or "").strip().upper()
        if disp:
            label = (DOB_DISPOSITION_CODES.get(disp) or {}).get("label")
            out.append(f"Disposition {disp}: {label}" if label else f"Disposition {disp}")
        return ". ".join(out)
    if rtype in ("violation", "swo"):
        parts = [_squash(row.get("description"))]
        law = _squash(row.get("section_law_description"))
        if law and law not in parts[0]:
            parts.append(law)
        return " — ".join(p for p in parts if p)
    return _squash(row.get("description"))


def free_text(row: Dict[str, Any]) -> str:
    """DOB's own words, when the record has some worth summarising: a violation
    / SWO description, or a 311 complaint's descriptor. '' for a DOB complaint
    (eabe-havv carries codes only) and for a bare code."""
    rtype = str(row.get("record_type") or "")
    if rtype == "complaint" and not _is_311(row):
        return ""
    text = dob_text(row)
    if len(re.findall(r"[A-Za-z]{3,}", text)) < 3:
        return ""
    return text
