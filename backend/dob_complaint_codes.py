"""
DOB Complaint Disposition & Category Codes
═══════════════════════════════════════════
Complete lookup tables from NYC Open Data + DOB official PDF.
Used by _determine_severity, _generate_next_action, and _extract_complaint_fields
to provide intelligent complaint classification in Levelog.

Sources:
  - Disposition codes: https://data.cityofnewyork.us/id/6v9u-ndjg
  - Category codes:    https://www.nyc.gov/assets/buildings/pdf/complaint_category.pdf
"""

# ══════════════════════════════════════════════════════════════════════════════
# DISPOSITION CODES — What happened after the inspector visited
# ══════════════════════════════════════════════════════════════════════════════
# Risk levels:
#   CRITICAL  = Stop work / vacate / criminal — immediate PM alert + push notification
#   HIGH      = Violation served / unsafe condition — same-day PM alert
#   MEDIUM    = Assigned for follow-up / partial action — daily digest
#   LOW       = Referred to other agency / informational — silent log
#   PENDING   = Inspector couldn't access / needs return — track & remind
#   RESOLVED  = No violation / closed / completed — no action needed

DOB_DISPOSITION_CODES = {
    # ── CRITICAL: Stop Work / Vacate / Criminal ──
    "A3": {"label": "Full Stop Work Order Served", "risk": "CRITICAL", "action": "STOP ALL WORK. Contact attorney and DOB immediately."},
    "H5": {"label": "Stop All Work / No TCAO Issued", "risk": "CRITICAL", "action": "STOP ALL WORK. Contact attorney and DOB immediately."},
    "A1": {"label": "Buildings Violation(s) Served", "risk": "CRITICAL", "action": "Review violation details. Schedule correction with DOB."},
    "A2": {"label": "Criminal Court Summons Served", "risk": "CRITICAL", "action": "URGENT: Criminal summons issued. Contact attorney immediately."},
    "A4": {"label": "Buildings Violation(s) & Criminal Court Summons Served", "risk": "CRITICAL", "action": "URGENT: Violation + criminal summons. Contact attorney immediately."},
    "A5": {"label": "Buildings Violation(s) & Criminal Court Summons Served", "risk": "CRITICAL", "action": "URGENT: Violation + criminal summons. Contact attorney immediately."},
    "A9": {"label": "ECB & Buildings Violations Served", "risk": "CRITICAL", "action": "Multiple violations served. Contact expediter for correction plan."},
    "H3": {"label": "Building Violation Issued for Failure to Obey SWO", "risk": "CRITICAL", "action": "CRITICAL: Violated stop work order. Contact attorney — criminal liability."},
    "H4": {"label": "Criminal Court Summons Served Due to Failure to Obey SWO", "risk": "CRITICAL", "action": "CRITICAL: Criminal summons for SWO violation. Contact attorney immediately."},
    "V3": {"label": "Stop Work Order Violation Served for Non-Compliant After Hours Work", "risk": "CRITICAL", "action": "SWO for after-hours violation. Stop all work. Contact DOB."},
    "W1": {"label": "Violation Served for Disobeying Vacate Order", "risk": "CRITICAL", "action": "CRITICAL: Vacate order disobeyed. Contact attorney immediately."},
    "Y1": {"label": "Full Vacate Order Issued", "risk": "CRITICAL", "action": "BUILDING VACATED. No entry permitted. Contact DOB and attorney."},
    "Y3": {"label": "Partial Vacate Order Issued", "risk": "CRITICAL", "action": "Partial vacate in effect. Evacuate affected areas. Contact DOB."},
    "RH": {"label": "Emergency Declaration Issued", "risk": "CRITICAL", "action": "Emergency declaration active. Follow DOB emergency protocols."},
    "RI": {"label": "Immediate Emergency Declaration Issued", "risk": "CRITICAL", "action": "IMMEDIATE emergency. Follow DOB emergency protocols now."},
    "RK": {"label": "Unsafe Building — Violation Issued", "risk": "CRITICAL", "action": "Building deemed unsafe. Violation issued. Contact structural engineer."},
    "RA": {"label": "Commissioner's Order Issued to Owner", "risk": "CRITICAL", "action": "Commissioner's order received. Comply within stated deadline."},
    "P3": {"label": "Closure/Padlock Order Issued", "risk": "CRITICAL", "action": "PADLOCK ORDER: Building closed by DOB. Contact attorney."},
    "ND": {"label": "Notice of Deficiency Issued", "risk": "CRITICAL", "action": "Notice of deficiency. Correct cited conditions within deadline."},
    "K4": {"label": "Cranes & Derricks — Stop Work Order — No Associated Address", "risk": "CRITICAL", "action": "Crane SWO issued. Stop all crane operations immediately."},
    "K6": {"label": "Letter of Deficiency Issued with Partial SWO", "risk": "CRITICAL", "action": "Deficiency + partial SWO. Stop affected work. Correct deficiency."},

    # ── HIGH: Violation / ECB Served / Unsafe Conditions ──
    "A6": {"label": "Vacant/Open/Unguarded Structure — Violation(s) Issued", "risk": "HIGH", "action": "Secure the property immediately. Violation issued for open structure."},
    "A7": {"label": "Complaint Accepted by Padlock Unit", "risk": "HIGH", "action": "Padlock unit reviewing. Potential closure risk. Contact attorney."},
    "A8": {"label": "ECB Violation Served", "risk": "HIGH", "action": "ECB violation served. Respond before hearing date to avoid penalties."},
    "B1": {"label": "Buildings Violation(s) Prepared — Attempt to Serve Will Be Made", "risk": "HIGH", "action": "Violation incoming. Inspector will attempt service. Prepare response."},
    "B2": {"label": "ECB Violation(s) Prepared — Attempt to Serve Will Be Made", "risk": "HIGH", "action": "ECB violation incoming. Prepare for service and hearing."},
    "L1": {"label": "Partial Stop Work Order", "risk": "HIGH", "action": "PARTIAL SWO: Stop affected work type. Other work may continue."},
    "R5": {"label": "Inspection — Class 1 ECB(s) Written / Order to Correct", "risk": "HIGH", "action": "ECB violation written with order to correct. Schedule fix."},
    "K5": {"label": "Letter of Deficiency Issued", "risk": "HIGH", "action": "Deficiency letter received. Correct within stated deadline."},
    "Q1": {"label": "Compromised Structure: Owner Prof Report Required", "risk": "HIGH", "action": "Structural report required. Hire PE/RA to assess and submit report."},
    "RU": {"label": "LL11 Unsafe — Initiated", "risk": "HIGH", "action": "Facade declared unsafe under Local Law 11. Immediate remediation required."},
    "RM": {"label": "Structural Monitoring: Owner Professional Report Required", "risk": "HIGH", "action": "Submit structural monitoring report. Hire PE for assessment."},
    "RN": {"label": "Structural Monitoring: Owner Professional Report Deadline Passed", "risk": "HIGH", "action": "OVERDUE: Structural report deadline passed. Submit immediately."},
    "WC": {"label": "Weather: NOD Issued / Unsafe / Red Tag / Eng Evaluation Required", "risk": "HIGH", "action": "Red tag — no occupancy. Engineering evaluation required."},
    "RE": {"label": "Commissioner's Order — Weekly Monitoring", "risk": "HIGH", "action": "Weekly monitoring required per Commissioner's order."},
    "S3": {"label": "Stalled: Excavation — Unsafe", "risk": "HIGH", "action": "Unsafe excavation at stalled site. Secure and remediate."},
    "S6": {"label": "Stalled: Superstructure — Unsafe", "risk": "HIGH", "action": "Unsafe superstructure at stalled site. Secure and remediate."},

    # ── MEDIUM: Assigned / Under Investigation / Partial Actions ──
    "D1": {"label": "Complaint Assigned to Construction Unit", "risk": "MEDIUM", "action": "Inspector assigned. Ensure site compliance before inspection."},
    "D2": {"label": "Complaint Assigned to Plumbing Unit", "risk": "MEDIUM", "action": "Plumbing inspector assigned. Verify plumbing permits and compliance."},
    "D3": {"label": "Complaint Assigned to Elevator Unit", "risk": "MEDIUM", "action": "Elevator inspector assigned. Verify elevator permits and safety."},
    "D4": {"label": "Complaint Assigned to BEST Squad", "risk": "MEDIUM", "action": "BEST squad assigned. Enforcement team inspection incoming."},
    "D5": {"label": "Complaint Assigned to Emergency Response Team", "risk": "MEDIUM", "action": "Emergency response assigned. High-priority inspection incoming."},
    "D6": {"label": "Complaint Assigned to Boiler Unit", "risk": "MEDIUM", "action": "Boiler inspector assigned. Verify boiler permits and compliance."},
    "D7": {"label": "Complaint Assigned to Cranes and Derricks Unit", "risk": "MEDIUM", "action": "Crane inspector assigned. Verify crane permits and safety certs."},
    "D8": {"label": "Complaint Assigned to Executive Inspections", "risk": "MEDIUM", "action": "Executive inspection assigned. Senior inspector visit expected."},
    "D9": {"label": "Complaint Assigned to Electrical Unit", "risk": "MEDIUM", "action": "Electrical inspector assigned. Verify electrical permits and work."},
    "EA": {"label": "Complaint Assigned to Interior Demolition Unit", "risk": "MEDIUM", "action": "Interior demo unit assigned. Verify demo permits and safety."},
    "EB": {"label": "Complaint Assigned to Facade Inspection Safety Program", "risk": "MEDIUM", "action": "Facade inspection assigned. Verify FISP compliance."},
    "EC": {"label": "Complaint Assigned to Structurally Compromised Buildings Unit", "risk": "MEDIUM", "action": "Structural unit assigned. Prepare engineering documentation."},
    "ED": {"label": "Complaint Assigned to Retaining Walls Unit", "risk": "MEDIUM", "action": "Retaining wall inspection assigned. Verify wall stability."},
    "E1": {"label": "Complaint Assigned to Building Marshal's Office", "risk": "MEDIUM", "action": "Building Marshal assigned. Enforcement action likely."},
    "E2": {"label": "Complaint Assigned to Legal Affairs/Padlock Unit", "risk": "MEDIUM", "action": "Legal/Padlock unit assigned. Potential closure risk."},
    "E3": {"label": "Complaint Assigned to Boro Office for Final Inspection", "risk": "MEDIUM", "action": "Final inspection scheduled at borough office."},
    "E4": {"label": "Complaint Assigned to LL58/87 Unit (Handicap Access)", "risk": "MEDIUM", "action": "Handicap access inspection assigned. Verify ADA compliance."},
    "E5": {"label": "Complaint Assigned to Center for Re-Evaluation", "risk": "MEDIUM", "action": "Under re-evaluation. Previous determination being reviewed."},
    "E6": {"label": "Complaint Assigned to Special Operations Unit", "risk": "MEDIUM", "action": "Special operations assigned. Non-routine inspection expected."},
    "E7": {"label": "Complaint Assigned to Scaffold Safety Team", "risk": "MEDIUM", "action": "Scaffold safety inspection. Verify scaffold permits and safety."},
    "E8": {"label": "Complaint Assigned to Excavation Inspection & Audits Team", "risk": "MEDIUM", "action": "Excavation audit assigned. Verify excavation permits and shoring."},
    "E9": {"label": "Complaint Assigned to Stalled Sites Unit", "risk": "MEDIUM", "action": "Stalled sites unit reviewing. Ensure site is secured."},
    "EE": {"label": "Complaint Reassigned for Review", "risk": "MEDIUM", "action": "Complaint reassigned. Follow up with DOB for status."},
    "EZ": {"label": "Complaint Assigned to Dept of Investigation", "risk": "MEDIUM", "action": "DOI investigation. Cooperate fully with investigators."},
    "F4": {"label": "Complaint Referred for Review", "risk": "MEDIUM", "action": "Under DOB review. Monitor for follow-up actions."},
    "I3": {"label": "Compliance Inspection Performed", "risk": "MEDIUM", "action": "Compliance inspection done. Check for any resulting violations."},
    "J1": {"label": "Follow-Up Inspection to Be Scheduled Upon Further Research", "risk": "MEDIUM", "action": "Follow-up inspection pending. Maintain compliance."},
    "J3": {"label": "Reviewed — Inspection to Be Scheduled", "risk": "MEDIUM", "action": "Inspection being scheduled. Ensure site is ready."},
    "J4": {"label": "Follow-Up Inspection Scheduled for Hazardous Condition", "risk": "MEDIUM", "action": "Hazardous condition follow-up scheduled. Correct condition ASAP."},
    "L3": {"label": "Stop Work Order Partially Rescinded", "risk": "MEDIUM", "action": "Partial SWO lifted. Some work may resume. Verify scope with DOB."},
    "P2": {"label": "Follow Up Inspection Required Pending Adoption", "risk": "MEDIUM", "action": "Pending adoption follow-up. Monitor status."},
    "P6": {"label": "Initial Notification Accepted", "risk": "MEDIUM", "action": "Notification accepted by DOB. Processing underway."},
    "R4": {"label": "Inspection — Engineering Assessment Required", "risk": "MEDIUM", "action": "Engineering assessment needed. Hire PE for evaluation."},
    "RB": {"label": "Commissioner's Order — Owner Remediation Plans Accepted", "risk": "MEDIUM", "action": "Remediation plan accepted. Execute per approved timeline."},
    "RW": {"label": "Immediate/Emergency Dec — Previously Issued/Underway", "risk": "MEDIUM", "action": "Emergency declaration already in progress. Monitor status."},
    "RX": {"label": "Unsafe Building — Precept Previously Issued/Underway", "risk": "MEDIUM", "action": "Unsafe building precept active. Follow existing remediation plan."},
    "RZ": {"label": "Vacate — Previously Issued/Underway", "risk": "MEDIUM", "action": "Vacate order already in effect. Follow existing protocols."},
    "RY": {"label": "Facade Report — Previously Issued/Underway", "risk": "MEDIUM", "action": "Facade report already required. Submit per deadline."},
    "S2": {"label": "Stalled: Excavation Deteriorating — No Immediate Threat", "risk": "MEDIUM", "action": "Excavation deteriorating. Plan remediation before it becomes unsafe."},
    "S5": {"label": "Stalled: Superstructure Deteriorating — No Immediate Threat", "risk": "MEDIUM", "action": "Superstructure deteriorating. Plan remediation."},
    "S8": {"label": "Stalled: Construction in Progress", "risk": "MEDIUM", "action": "Stalled site with active construction. Verify permits current."},
    "S9": {"label": "Stalled: Emergency Declaration Filed", "risk": "MEDIUM", "action": "Emergency declaration filed for stalled site. Monitor status."},
    "WD": {"label": "Weather: NOD Issued / Restricted / Yellow Tag / Eng Evaluation Reqd", "risk": "MEDIUM", "action": "Yellow tag — restricted occupancy. Engineering evaluation needed."},
    "WE": {"label": "Weather: NOD Issued / Downgraded to Yellow / Eng Evaluation Required", "risk": "MEDIUM", "action": "Downgraded to yellow. Engineering evaluation still required."},
    "WH": {"label": "Weather: Green Tag Rescinded / Structurally Sound / Utilities Unresolved", "risk": "MEDIUM", "action": "Structure sound but utility issues remain. Resolve utilities."},
    "WJ": {"label": "Weather: Enforcement Order to Be Issued / See Referenced Complaint", "risk": "MEDIUM", "action": "Weather-related enforcement pending. Check referenced complaint."},
    "K2": {"label": "Address Invalid — Pending Buildings Verification", "risk": "MEDIUM", "action": "Address verification pending. May need re-inspection."},
    "K7": {"label": "Notification of Correction Received", "risk": "MEDIUM", "action": "Correction notification received by DOB. Verify acceptance."},
    "K8": {"label": "Correction Verified by DOB", "risk": "MEDIUM", "action": "DOB verified correction. Confirm violation closure."},

    # ── MARCH Program ──
    "MA": {"label": "MARCH: No Enforcement Action Taken", "risk": "LOW", "action": "MARCH inspection — no action taken. Log and close."},
    "MB": {"label": "MARCH: Failure to Maintain Bldg / ECB NOV Issued", "risk": "HIGH", "action": "MARCH violation for failure to maintain. Respond to ECB."},
    "MC": {"label": "MARCH: Contrary to Approved Plans / ECB NOV Issued", "risk": "HIGH", "action": "MARCH violation — work contrary to plans. Correct and respond."},
    "MD": {"label": "MARCH: Exit Passage Obstructed / ECB NOV Issued", "risk": "HIGH", "action": "MARCH egress violation. Clear exit passages immediately."},
    "ME": {"label": "MARCH: Exit Passage Obstructed / ECB NOV & Full Vacate Issued", "risk": "CRITICAL", "action": "MARCH full vacate for blocked egress. Building evacuated."},
    "MF": {"label": "MARCH: Exit Passage Obstructed / ECB NOV & Partial Vacate Issued", "risk": "CRITICAL", "action": "MARCH partial vacate for blocked egress. Evacuate affected areas."},
    "MG": {"label": "MARCH: Occupancy Contrary to C of O / ECB NOV Issued", "risk": "HIGH", "action": "MARCH C of O violation. Correct occupancy use."},
    "MH": {"label": "MARCH: No PA Permit / ECB NOV & Full Vacate Issued", "risk": "CRITICAL", "action": "MARCH full vacate — no PA permit. Building evacuated."},
    "MI": {"label": "MARCH: No PA Permit / ECB NOV & Partial Vacate Issued", "risk": "CRITICAL", "action": "MARCH partial vacate — no PA permit. Evacuate affected areas."},
    "MJ": {"label": "MARCH: Work Without Permit / ECB NOV Issued", "risk": "HIGH", "action": "MARCH violation — work without permit. Stop work and file permits."},
    "MK": {"label": "MARCH: No PA Permit / ECB NOV Issued", "risk": "HIGH", "action": "MARCH violation — no PA permit. File permit immediately."},

    # ── LOW: Referred to Other Agencies ──
    "F1": {"label": "Complaint Referred to DEP", "risk": "LOW", "action": "Referred to Dept of Environmental Protection. Not a DOB matter."},
    "F2": {"label": "Complaint Referred to NYS DHCR", "risk": "LOW", "action": "Referred to NYS Housing & Community Renewal. Not a DOB matter."},
    "F3": {"label": "Complaint Referred to Dept of Health", "risk": "LOW", "action": "Referred to Health Dept. Not a DOB matter."},
    "F5": {"label": "Complaint Referred to Dept of Sanitation", "risk": "LOW", "action": "Referred to Sanitation. Not a DOB matter."},
    "F6": {"label": "Complaint Referred to DOT", "risk": "LOW", "action": "Referred to Dept of Transportation. Not a DOB matter."},
    "F7": {"label": "Complaint Referred to NYS Office of Real Properties", "risk": "LOW", "action": "Referred to NYS Real Properties. Not a DOB matter."},
    "F8": {"label": "Complaint Referred to HPD", "risk": "LOW", "action": "Referred to Housing Preservation & Development."},
    "F9": {"label": "Complaint Referred to HUD (Federal)", "risk": "LOW", "action": "Referred to Federal HUD. Not a DOB matter."},
    "G1": {"label": "Complaint Referred to Inspector General's Office", "risk": "LOW", "action": "Referred to IG. Internal investigation."},
    "G2": {"label": "Complaint Referred to Dept of Parks and Recreation", "risk": "LOW", "action": "Referred to Parks. Not a DOB matter."},
    "G3": {"label": "Complaint Referred to TLC", "risk": "LOW", "action": "Referred to Taxi & Limousine Commission. Not a DOB matter."},
    "G4": {"label": "Complaint Referred to Dept of Consumer Affairs", "risk": "LOW", "action": "Referred to Consumer Affairs. Not a DOB matter."},
    "G5": {"label": "Complaint Referred to NYPD", "risk": "LOW", "action": "Referred to NYPD. Law enforcement matter."},
    "G6": {"label": "Complaint Referred to FDNY", "risk": "LOW", "action": "Referred to Fire Dept. Fire safety matter."},
    "G7": {"label": "Complaint Referred to Mayor's Office of Special Enforcement", "risk": "LOW", "action": "Referred to Mayor's enforcement office."},
    "G8": {"label": "Complaint Referred to NYCHA", "risk": "LOW", "action": "Referred to NYC Housing Authority."},
    "G9": {"label": "Complaint Referred to Dept Citywide Administrative Services", "risk": "LOW", "action": "Referred to DCAS. Not a DOB matter."},

    # ── PENDING: No Access / Needs Return Visit ──
    "C1": {"label": "Inspector Unable to Gain Access — 1st Attempt", "risk": "PENDING", "action": "Inspector could not access. Expect return visit. Ensure access."},
    "C2": {"label": "Inspector Unable to Gain Access — 2nd Attempt", "risk": "PENDING", "action": "2nd failed access attempt. Provide access or face violation."},
    "C3": {"label": "Access Denied — 1st Attempt", "risk": "PENDING", "action": "Access denied to inspector. Provide access on return visit."},
    "C4": {"label": "Access Denied — 2nd Attempt", "risk": "PENDING", "action": "2nd access denial. Violation likely if access denied again."},
    "C5": {"label": "AW: No Access — 1st Attempt", "risk": "PENDING", "action": "After-hours: no access. Expect return visit."},
    "C6": {"label": "AW: Access Denied — 1st Attempt", "risk": "PENDING", "action": "After-hours: access denied. Provide access on return."},
    "C7": {"label": "AW: No Access — 2nd Attempt", "risk": "PENDING", "action": "After-hours: 2nd no-access. Ensure someone is on site."},
    "C8": {"label": "AW: Access Denied — 2nd Attempt", "risk": "PENDING", "action": "After-hours: 2nd access denial. Violation risk increasing."},

    # ── RESOLVED: No Violation / Closed / Completed ──
    "I1": {"label": "Complaint Unsubstantiated Based on Department Records", "risk": "RESOLVED", "action": "Complaint unsubstantiated. No action needed."},
    "I2": {"label": "No Violation Warranted for Complaint at Time of Inspection", "risk": "RESOLVED", "action": "Inspector found no violation. Complaint cleared."},
    "J2": {"label": "Complaint Resolved by Periodic Inspection", "risk": "RESOLVED", "action": "Resolved during routine inspection. No further action."},
    "K1": {"label": "Insufficient Information / Unable to Locate Address", "risk": "RESOLVED", "action": "Complaint closed — address not found. No action needed."},
    "L2": {"label": "Stop Work Order Fully Rescinded", "risk": "RESOLVED", "action": "SWO fully lifted. All work may resume."},
    "P1": {"label": "Job Vested", "risk": "RESOLVED", "action": "Job vested. No action needed."},
    "P4": {"label": "Closure/Padlock Order Rescinded", "risk": "RESOLVED", "action": "Padlock order removed. Building may reopen."},
    "Q4": {"label": "Compromised Structure: Condition Remedied", "risk": "RESOLVED", "action": "Structural issue resolved. No further action."},
    "R1": {"label": "Inspection — No Immediate Action / No Follow-Up Required", "risk": "RESOLVED", "action": "Inspection complete. No issues found."},
    "R3": {"label": "Inspection — No Immediate Action / Monthly Inspection", "risk": "RESOLVED", "action": "No immediate issue. Monthly monitoring continues."},
    "R6": {"label": "Engineering — No Immediate Action / No Follow-Up Required", "risk": "RESOLVED", "action": "Engineering review clear. No action needed."},
    "R7": {"label": "Engineering — No Immediate Action / Weekly Assessment", "risk": "RESOLVED", "action": "No immediate issue. Weekly engineering monitoring continues."},
    "R8": {"label": "Engineering — No Immediate Action / Monthly Assessment", "risk": "RESOLVED", "action": "No immediate issue. Monthly engineering monitoring continues."},
    "R9": {"label": "Building at Risk Program — No Immediate Danger", "risk": "RESOLVED", "action": "No immediate danger. Monitoring program active."},
    "RG": {"label": "Commissioner's Order — Owner Remediation Completed", "risk": "RESOLVED", "action": "Remediation completed. Commissioner's order satisfied."},
    "RJ": {"label": "Immediate/Emergency Declaration — Action Completed", "risk": "RESOLVED", "action": "Emergency resolved. Declaration closed."},
    "RL": {"label": "Unsafe Building — Action Completed", "risk": "RESOLVED", "action": "Unsafe condition resolved. Building cleared."},
    "RT": {"label": "Compromised Structure: Action Completed", "risk": "RESOLVED", "action": "Structural issue remediated. Complaint closed."},
    "RV": {"label": "LL11 Unsafe — Action Completed", "risk": "RESOLVED", "action": "Facade issue resolved under Local Law 11."},
    "S0": {"label": "Stalled: All Work Completed", "risk": "RESOLVED", "action": "Stalled site resolved. All work completed."},
    "S1": {"label": "Stalled: Excavation — No Immediate Threat", "risk": "RESOLVED", "action": "Stalled excavation stable. No immediate action needed."},
    "S4": {"label": "Stalled: Superstructure — No Immediate Threat", "risk": "RESOLVED", "action": "Stalled superstructure stable. No immediate action needed."},
    "S7": {"label": "Stalled: No Immediate Threat — Graded & Fenced", "risk": "RESOLVED", "action": "Stalled site secured. No immediate action."},
    "WA": {"label": "Weather Related: No Action Necessary", "risk": "RESOLVED", "action": "Weather inspection — no action needed."},
    "WB": {"label": "Weather Related: No Access", "risk": "RESOLVED", "action": "Weather inspection — could not access. No action."},
    "WF": {"label": "Weather: No Further Action / Downgraded to Green", "risk": "RESOLVED", "action": "Downgraded to green. No restrictions."},
    "WG": {"label": "Weather: Green Tag Rescinded / No Occupancy Restrictions", "risk": "RESOLVED", "action": "All clear. No occupancy restrictions."},
    "WI": {"label": "Weather: No Action Warranted by DOB / Refer to Other Agency", "risk": "RESOLVED", "action": "Not a DOB matter. Referred elsewhere."},
    "XX": {"label": "Administrative Closure", "risk": "RESOLVED", "action": "Administratively closed. No action needed."},
    "Y2": {"label": "Vacate Order Fully Rescinded", "risk": "RESOLVED", "action": "Vacate order lifted. Full occupancy restored."},
    "Y4": {"label": "Vacate Order Partially Rescinded", "risk": "RESOLVED", "action": "Partial vacate lifted. Some areas may reoccupy."},

    # ── Miscellaneous ──
    "AB": {"label": "ECB Violation Previously Issued", "risk": "RESOLVED", "action": "Duplicate of prior ECB violation; no new action required."},
    "H1": {"label": "Please See Complaint Number", "risk": "MEDIUM", "action": "Cross-referenced complaint. Check linked complaint number."},
    "H2": {"label": "Previously Inspected Complaint — Pre-BIS Complaint Number", "risk": "RESOLVED", "action": "Historical complaint. Already inspected."},
    "K3": {"label": "Cranes & Derricks — No Address — See Comments", "risk": "MEDIUM", "action": "Crane complaint without address. Check comments for details."},
    "M1": {"label": "Bicycle Access Plan: Elevator Use Acceptable", "risk": "RESOLVED", "action": "Bicycle access approved. No action."},
    "M3": {"label": "Bicycle Access Plan: Alternate Use Parking Requirement Met", "risk": "RESOLVED", "action": "Bicycle access requirement met. No action."},
    "M4": {"label": "Bicycle Access Plan: Alternate Use Parking Requirement Not Met", "risk": "LOW", "action": "Bicycle parking requirement not met. Update plan."},
    "P5": {"label": "Potential Ordinary Plumbing Work", "risk": "LOW", "action": "Plumbing work identified. Verify permits if needed."},
}


# ══════════════════════════════════════════════════════════════════════════════
# COMPLAINT CATEGORY CODES — What the complaint is about
# ══════════════════════════════════════════════════════════════════════════════
# Risk levels assigned based on life-safety impact for construction sites.

DOB_CATEGORY_CODES = {
    # ── CRITICAL: Immediate life safety ──
    "01": {"desc": "Accident — Construction/Plumbing", "risk": "CRITICAL"},
    "02": {"desc": "Accident — To Public", "risk": "CRITICAL"},
    "10": {"desc": "Debris/Building — Falling or In Danger of Falling", "risk": "CRITICAL"},
    "14": {"desc": "Excavation — Undermining Adjacent Building", "risk": "CRITICAL"},
    "16": {"desc": "Inadequate Support/Shoring", "risk": "CRITICAL"},
    "28": {"desc": "Building — In Danger of Collapse", "risk": "CRITICAL"},
    "30": {"desc": "Building Shaking/Vibrating/Structural Stability Affected", "risk": "CRITICAL"},
    "40": {"desc": "Falling — Part of Building", "risk": "CRITICAL"},
    "41": {"desc": "Falling — Part of Building in Danger of", "risk": "CRITICAL"},
    "43": {"desc": "Structural Stability Affected", "risk": "CRITICAL"},
    "62": {"desc": "Elevator: Danger Condition/Shaft Open/Unguarded", "risk": "CRITICAL"},
    "64": {"desc": "Elevator Shaft: Open and Unguarded", "risk": "CRITICAL"},
    "67": {"desc": "Crane: No Permit/License/Cert/Unsafe/Illegal", "risk": "CRITICAL"},
    "68": {"desc": "Crane/Scaffold: Unsafe/Illegal Operations", "risk": "CRITICAL"},
    "69": {"desc": "Crane/Scaffold: Unsafe Installation/Equipment", "risk": "CRITICAL"},
    "81": {"desc": "Elevator: Accident", "risk": "CRITICAL"},
    "82": {"desc": "Boiler: Accident/Explosion", "risk": "CRITICAL"},
    "89": {"desc": "Accident — Cranes/Derricks/Suspension", "risk": "CRITICAL"},
    "91": {"desc": "Site Conditions Endangering Workers", "risk": "CRITICAL"},
    "1C": {"desc": "Damage Assessment Request or Report (Disaster)", "risk": "CRITICAL"},
    "1E": {"desc": "Suspended (Hanging) Scaffolds — No Permit/License/Dangerous/Accident", "risk": "CRITICAL"},
    "2B": {"desc": "Failure to Comply with Vacate Order", "risk": "CRITICAL"},
    "2K": {"desc": "Structurally Compromised Building (LL33/08)", "risk": "CRITICAL"},
    "5C": {"desc": "Structural Stability Impacted — New Building Under Construction", "risk": "CRITICAL"},
    "5E": {"desc": "Amusement Ride Accident/Incident", "risk": "CRITICAL"},

    # ── HIGH: Permit violations / Unsafe conditions / Active enforcement ──
    "03": {"desc": "Adjacent Buildings — Not Protected", "risk": "HIGH"},
    "05": {"desc": "Permit — None (Building/PA/Demo etc.)", "risk": "HIGH"},
    "09": {"desc": "Debris — Excessive", "risk": "HIGH"},
    "11": {"desc": "Demolition — No Permit", "risk": "HIGH"},
    "12": {"desc": "Demolition — Unsafe/Illegal/Mechanical Demo", "risk": "HIGH"},
    "17": {"desc": "Material/Personnel Hoist — No Permit", "risk": "HIGH"},
    "18": {"desc": "Material Storage — Unsafe", "risk": "HIGH"},
    "19": {"desc": "Mechanical Demolition — Illegal", "risk": "HIGH"},
    "21": {"desc": "Safety Net/Guard Rail — Damaged/Inadequate/None (over 6-stories/75ft)", "risk": "HIGH"},
    "22": {"desc": "Safety Netting — None", "risk": "HIGH"},
    "23": {"desc": "Sidewalk Shed/Supported Scaffold/Inadequate/Defect/None/No Permit/No Cert", "risk": "HIGH"},
    "24": {"desc": "Sidewalk Shed — None", "risk": "HIGH"},
    "29": {"desc": "Building — Vacant, Open and Unguarded", "risk": "HIGH"},
    "31": {"desc": "Certificate of Occupancy — None/Illegal/Contrary to CO", "risk": "HIGH"},
    "37": {"desc": "Egress: Locked/Blocked/Improper/No Secondary Means", "risk": "HIGH"},
    "38": {"desc": "Egress: Exit Door Not Proper", "risk": "HIGH"},
    "39": {"desc": "Egress: No Secondary Means", "risk": "HIGH"},
    "45": {"desc": "Illegal Conversion", "risk": "HIGH"},
    "46": {"desc": "PA Permit — None", "risk": "HIGH"},
    "54": {"desc": "Wall/Retaining Wall — Bulging/Cracked", "risk": "HIGH"},
    "56": {"desc": "Boiler: Fumes/Smoke/Carbon Monoxide", "risk": "HIGH"},
    "59": {"desc": "Electrical Wiring: Defective/Exposed — In Progress", "risk": "HIGH"},
    "65": {"desc": "Gas Hook-Up/Piping — Illegal or Defective", "risk": "HIGH"},
    "83": {"desc": "Construction: Contrary/Beyond Approved Plans/Permits", "risk": "HIGH"},
    "84": {"desc": "Facade: Defective/Cracking", "risk": "HIGH"},
    "86": {"desc": "Work Contrary to Stop Work Order", "risk": "HIGH"},
    "88": {"desc": "Safety Net/Guard Rail — Damaged/Inadequate/None (6-stories/75ft or Less)", "risk": "HIGH"},
    "1A": {"desc": "Illegal Conversion Commercial Building/Space to Dwelling Units", "risk": "HIGH"},
    "1F": {"desc": "Failure to Comply with Annual Crane Inspection", "risk": "HIGH"},
    "2A": {"desc": "Posted Notice or Order Removed/Tampered With", "risk": "HIGH"},
    "2F": {"desc": "Building Under Structural Monitoring", "risk": "HIGH"},
    "2L": {"desc": "Facade (LL11/98) — Unsafe Notification", "risk": "HIGH"},
    "3A": {"desc": "Unlicensed/Illegal/Improper Electrical Work in Progress", "risk": "HIGH"},
    "4H": {"desc": "V.E.S.T. Program (DOB & NYPD)", "risk": "HIGH"},
    "5B": {"desc": "Non-Compliance with Lightweight Materials", "risk": "HIGH"},
    "5D": {"desc": "Non-Compliance with TPPN 1/00 — Vertical Enlargements", "risk": "HIGH"},
    "5G": {"desc": "Unlicensed/Illegal/Improper Work In-Progress", "risk": "HIGH"},
    "6V": {"desc": "Tenant Safety Inspection", "risk": "HIGH"},
    "6W": {"desc": "Tenant Safety — Failure to Post/Distribute", "risk": "HIGH"},
    "7J": {"desc": "Work Without a Permit — Occupied Multiple Dwelling", "risk": "HIGH"},
    "7L": {"desc": "DOHMH Referral — Tenant Protection Non-Compliance", "risk": "HIGH"},

    # ── MEDIUM: Moderate enforcement / compliance issues ──
    "04": {"desc": "After Hours Work — Illegal", "risk": "MEDIUM"},
    "06": {"desc": "Construction — Change Grade/Change Watercourse", "risk": "MEDIUM"},
    "07": {"desc": "Construction — Change Watercourse", "risk": "MEDIUM"},
    "08": {"desc": "Contractor's Sign — None", "risk": "MEDIUM"},
    "15": {"desc": "Fence — None/Inadequate/Illegal", "risk": "MEDIUM"},
    "20": {"desc": "Landmark Building — Illegal Work", "risk": "MEDIUM"},
    "25": {"desc": "Warning Signs/Lights — None", "risk": "MEDIUM"},
    "26": {"desc": "Watchman — None", "risk": "MEDIUM"},
    "32": {"desc": "C of O — Not Being Complied With", "risk": "MEDIUM"},
    "33": {"desc": "Commercial Use — Illegal", "risk": "MEDIUM"},
    "42": {"desc": "Fence — Illegal", "risk": "MEDIUM"},
    "44": {"desc": "Fireplace/Wood Stove — Illegal", "risk": "MEDIUM"},
    "47": {"desc": "PA Permit — Not Being Complied With", "risk": "MEDIUM"},
    "48": {"desc": "Residential Use — Illegal", "risk": "MEDIUM"},
    "50": {"desc": "Sign Falling: Danger/Sign Erection or Display In-Progress (Illegal)", "risk": "MEDIUM"},
    "51": {"desc": "Illegal Social Club", "risk": "MEDIUM"},
    "52": {"desc": "Sprinkler System — Inadequate", "risk": "MEDIUM"},
    "53": {"desc": "Vent/Exhaust — Illegal/Improper", "risk": "MEDIUM"},
    "55": {"desc": "Zoning: Non-Conforming", "risk": "MEDIUM"},
    "57": {"desc": "Boiler: Illegal", "risk": "MEDIUM"},
    "58": {"desc": "Boiler: Defective/Inoperative/No Permit", "risk": "MEDIUM"},
    "60": {"desc": "Electrical Work: Improper", "risk": "MEDIUM"},
    "61": {"desc": "Electrical Work: Unlicensed, In-Progress", "risk": "MEDIUM"},
    "63": {"desc": "Elevator: Defective/Inoperative", "risk": "MEDIUM"},
    "66": {"desc": "Plumbing Work — Illegal/No Permit (also Sprinkler/Standpipe)", "risk": "MEDIUM"},
    "70": {"desc": "Suspension Scaffold Hanging — No Work In-Progress", "risk": "MEDIUM"},
    "71": {"desc": "SRO: Illegal Work/No Permit/Change in Occupancy Use", "risk": "MEDIUM"},
    "72": {"desc": "SRO: Change in Occupancy/Use", "risk": "MEDIUM"},
    "73": {"desc": "Failure to Maintain", "risk": "MEDIUM"},
    "74": {"desc": "Illegal Commercial/Manufacturing Use in Residential Zone", "risk": "MEDIUM"},
    "76": {"desc": "Unlicensed/Illegal/Improper Plumbing Work In-Progress", "risk": "MEDIUM"},
    "77": {"desc": "Contrary to LL58/87 (Handicap Access)", "risk": "MEDIUM"},
    "80": {"desc": "Elevator Not Inspected/Illegal/No Permit", "risk": "MEDIUM"},
    "85": {"desc": "Failure to Retain Water/Improper Drainage (LL103/89)", "risk": "MEDIUM"},
    "90": {"desc": "Unlicensed/Illegal Activity", "risk": "MEDIUM"},
    "92": {"desc": "Illegal Conversion of Manufacturing/Industrial Space", "risk": "MEDIUM"},
    "93": {"desc": "Request for Retaining Wall Safety Inspection", "risk": "MEDIUM"},
    "94": {"desc": "Plumbing: Defective/Leaking/Not Maintained", "risk": "MEDIUM"},
    "96": {"desc": "Unlicensed Boiler, Electrical, Plumbing or Sign Work Completed", "risk": "MEDIUM"},
    "1G": {"desc": "Stalled Construction Site", "risk": "MEDIUM"},
    "1H": {"desc": "Emergency Asbestos Response Inspection", "risk": "MEDIUM"},
    "1J": {"desc": "Jewelry/Dentistry Torch: Gas Piping Removed w/o Permit", "risk": "MEDIUM"},
    "1K": {"desc": "Bowstring Truss Tracking Complaint", "risk": "MEDIUM"},
    "1L": {"desc": "Gas Utility Referral", "risk": "MEDIUM"},
    "2C": {"desc": "Smoking Ban — Smoking on Construction Site", "risk": "MEDIUM"},
    "2D": {"desc": "Smoking Signs — No Smoking Signs Not Observed on Construction Site", "risk": "MEDIUM"},
    "2G": {"desc": "Advertising Sign/Billboard/Posters/Flexible Fabric — Illegal", "risk": "MEDIUM"},
    "2H": {"desc": "Second Avenue Subway Construction", "risk": "MEDIUM"},
    "2M": {"desc": "Monopole Tracking Complaint", "risk": "MEDIUM"},
    "2N": {"desc": "COVID-19 Executive Order", "risk": "MEDIUM"},
    "4A": {"desc": "Illegal Hotel Rooms in Residential Buildings", "risk": "MEDIUM"},
    "4B": {"desc": "SEP — Professional Certification Compliance Audit", "risk": "MEDIUM"},
    "4G": {"desc": "Illegal Conversion No Access Follow-Up", "risk": "MEDIUM"},
    "4J": {"desc": "M.A.R.C.H. Program (Interagency)", "risk": "MEDIUM"},
    "4X": {"desc": "After Hours Work — With an AHV Permit", "risk": "MEDIUM"},
    "5A": {"desc": "Request for Joint FDNY/DOB Inspection", "risk": "MEDIUM"},
    "5F": {"desc": "Compliance Inspection", "risk": "MEDIUM"},
    "5H": {"desc": "Illegal Activity", "risk": "MEDIUM"},
    "5J": {"desc": "Multi Agency Joint Inspection", "risk": "MEDIUM"},
    "6A": {"desc": "Vesting Inspection", "risk": "MEDIUM"},
    "6X": {"desc": "Work Without Permits Watch List Compliance", "risk": "MEDIUM"},
    "6Y": {"desc": "Local Law Audits", "risk": "MEDIUM"},
    "6Z": {"desc": "Training Compliance", "risk": "MEDIUM"},
    "7A": {"desc": "Integrity Complaint Referral", "risk": "MEDIUM"},
    "7B": {"desc": "Illegal Commercial or Manufacturing Use in a C1 or C2 Zone", "risk": "MEDIUM"},
    "7K": {"desc": "Local Law 188/17 Compliance Inspections — Active Jobs", "risk": "MEDIUM"},
    "8A": {"desc": "Construction Safety Compliance (CSC) Action", "risk": "MEDIUM"},

    # ── LOW: Minor / administrative / tracking ──
    "27": {"desc": "Auto Repair — Illegal", "risk": "LOW"},
    "34": {"desc": "Compactor Room/Refuse Chute — Illegal", "risk": "LOW"},
    "35": {"desc": "Curb Cut/Driveway/Carport — Illegal", "risk": "LOW"},
    "36": {"desc": "Driveway/Carport — Illegal", "risk": "LOW"},
    "49": {"desc": "Storefront or Business Sign/Awning/Marquee/Canopy — Illegal", "risk": "LOW"},
    "75": {"desc": "Adult Establishment", "risk": "LOW"},
    "78": {"desc": "Privately Owned Public Space/Non-Compliance", "risk": "LOW"},
    "79": {"desc": "Lights from Parking Lot Shining on Building", "risk": "LOW"},
    "87": {"desc": "Request for Deck Safety Inspection", "risk": "LOW"},
    "95": {"desc": "Bronx 2nd Offense Pilot Project", "risk": "LOW"},
    "97": {"desc": "Other Agency Jurisdiction", "risk": "LOW"},
    "98": {"desc": "Refer to Operations for Determination", "risk": "LOW"},
    "99": {"desc": "Other", "risk": "LOW"},
    "1B": {"desc": "Illegal Tree Removal/Topo Change in SNAD", "risk": "LOW"},
    "1D": {"desc": "Con Edison Referral", "risk": "LOW"},
    "1U": {"desc": "Special Operations Compliance Inspection", "risk": "LOW"},
    "1V": {"desc": "Electrical Enforcement Work Order (DOB)", "risk": "LOW"},
    "1W": {"desc": "Plumbing Enforcement Work Order (DOB)", "risk": "LOW"},
    "1X": {"desc": "Construction Enforcement Work Order (DOB)", "risk": "LOW"},
    "1Y": {"desc": "Enforcement Work Order (DOB)", "risk": "LOW"},
    "1Z": {"desc": "Enforcement Work Order (DOB)", "risk": "LOW"},
    "2E": {"desc": "Tracking Complaint for Full Demolition Notification", "risk": "LOW"},
    "2J": {"desc": "SANDY: Building Destroyed", "risk": "LOW"},
    "2P": {"desc": "Facades Unit Compliance Inspection", "risk": "LOW"},
    "3B": {"desc": "Routine Inspection", "risk": "LOW"},
    "3C": {"desc": "Plan Compliance Inspection", "risk": "LOW"},
    "3D": {"desc": "Bicycle Access Waiver Request — Elevator Safety", "risk": "LOW"},
    "3E": {"desc": "Bicycle Access Waiver Request — Alternate Parking", "risk": "LOW"},
    "3G": {"desc": "Restroom Non-Compliance with Local Law 79/16", "risk": "LOW"},
    "3H": {"desc": "DCP/BSA Compliance Inspection", "risk": "LOW"},
    "4E": {"desc": "Stalled Sites Tracking Complaint", "risk": "LOW"},
    "4K": {"desc": "CSC: DM Tracking Complaint", "risk": "LOW"},
    "4L": {"desc": "CSC: High-Rise Tracking Complaint", "risk": "LOW"},
    "4M": {"desc": "CSC: Low-Rise Tracking Complaint", "risk": "LOW"},
    "4N": {"desc": "Retaining Wall Tracking Complaint", "risk": "LOW"},
    "4P": {"desc": "Legal/Padlock Tracking Complaint", "risk": "LOW"},
    "4S": {"desc": "Sustainability Enforcement Work Order", "risk": "LOW"},
    "4W": {"desc": "Woodside Settlement Project", "risk": "LOW"},
    "6B": {"desc": "Semi-Annual Homeless Shelter Inspection: Plumbing", "risk": "LOW"},
    "6C": {"desc": "Semi-Annual Homeless Shelter Inspection: Construction", "risk": "LOW"},
    "6D": {"desc": "Semi-Annual Homeless Shelter Inspection: Electrical", "risk": "LOW"},
    "6M": {"desc": "Elevator: Multiple Devices on Property", "risk": "LOW"},
    "6S": {"desc": "Elevator: Single Device on Property/No Alternate Service", "risk": "LOW"},
    "7F": {"desc": "CSE: Tracking Compliance", "risk": "LOW"},
    "7G": {"desc": "CSE: Sweep", "risk": "LOW"},
    "7N": {"desc": "Privately Owned Public Space/Compliance Inspection", "risk": "LOW"},
    "13": {"desc": "Elevator In (FDNY) Readiness — None", "risk": "LOW"},
}


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS — Use these in server.py
# ══════════════════════════════════════════════════════════════════════════════

# Risk level hierarchy for severity comparison
_RISK_PRIORITY = {"CRITICAL": 5, "HIGH": 4, "MEDIUM": 3, "PENDING": 2, "LOW": 1, "RESOLVED": 0}


def classify_complaint(rec: dict) -> dict:
    """
    Classify a complaint record using disposition and category codes.

    Returns dict with:
      - risk_level: CRITICAL / HIGH / MEDIUM / LOW / PENDING / RESOLVED
      - disposition_label: Human-readable disposition description
      - category_label: Human-readable category description
      - action: Recommended next action
      - severity: 'Action' or 'Good' (for Levelog severity field)
    """
    disp_code = str(rec.get("disposition_code") or rec.get("status") or "").strip().upper()
    cat_code = str(rec.get("complaint_category") or "").strip()

    disp_info = DOB_DISPOSITION_CODES.get(disp_code, {})
    cat_info = DOB_CATEGORY_CODES.get(cat_code, {})

    disp_risk = disp_info.get("risk", "MEDIUM")
    cat_risk = cat_info.get("risk", "MEDIUM")

    # Use the higher risk of disposition vs category
    if _RISK_PRIORITY.get(cat_risk, 0) > _RISK_PRIORITY.get(disp_risk, 0):
        final_risk = cat_risk
    else:
        final_risk = disp_risk

    # Map to Levelog severity
    if final_risk in ("CRITICAL", "HIGH", "PENDING"):
        severity = "Action"
    else:
        severity = "Good"

    # Build action text
    action = disp_info.get("action", "")
    if not action:
        if final_risk == "CRITICAL":
            action = "CRITICAL complaint filed. Ensure full site compliance immediately."
        elif final_risk == "HIGH":
            action = "High-priority complaint. Inspector visit expected. Verify compliance."
        elif final_risk == "PENDING":
            action = "Inspector needs access. Ensure site is accessible for next visit."
        elif final_risk == "RESOLVED":
            action = "Complaint resolved. No action needed."
        else:
            action = "Complaint under review. Monitor for updates."

    return {
        "risk_level": final_risk,
        "disposition_label": disp_info.get("label", f"Code {disp_code}"),
        "category_label": cat_info.get("desc", f"Category {cat_code}"),
        "action": action,
        "severity": severity,
    }


def get_disposition_label(code: str) -> str:
    """Get human-readable label for a disposition code."""
    info = DOB_DISPOSITION_CODES.get(str(code).strip().upper(), {})
    return info.get("label", f"Disposition {code}")


def get_category_label(code: str) -> str:
    """Get human-readable description for a category code."""
    info = DOB_CATEGORY_CODES.get(str(code).strip(), {})
    return info.get("desc", f"Category {code}")


def get_complaint_risk(code: str, code_type: str = "disposition") -> str:
    """Get risk level for a disposition or category code."""
    if code_type == "disposition":
        info = DOB_DISPOSITION_CODES.get(str(code).strip().upper(), {})
    else:
        info = DOB_CATEGORY_CODES.get(str(code).strip(), {})
    return info.get("risk", "MEDIUM")
