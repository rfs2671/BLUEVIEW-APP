"""Who may use the Levelog Assistant in a direct message, and which tools.

Pure: no database, no network. server.py asks it on every tool call the DM
brain makes (_dm_brain_exec_one) and on every change the change flow is about
to make (_dm_action_do); the model is shown only the tools a role may call,
but HIDING A TOOL IS NOT THE GATE. The server refuses per call, here.

── THE RULING (owner, 2026-11-09) ───────────────────────────────────────────

Superintendents and CPs use the assistant ON THEIR ASSIGNED JOBS ONLY. Their
jobs are their user record's `assigned_projects`, each re-proven to be their
company's (server.py _dm_assistant_projects); a role alone never opens a job.

They may: report inspections, send evidence (sign-offs, photos), ask about
progress (work_status, find / send photos) and read the schedule
(schedule_lookahead, viewing a PROPOSED sequence).

Reserved to a PM or an admin: approving a PROPOSED sequence (the official
schedule approval), every tool that changes project data (propose_change,
answer_pending_change, set_sub_trade, undo_last_change), company reports
(send_report), and the proactive side of the assistant (the morning brief,
its settings, reminders): a field role is never messaged first.

What is NOT reserved and NOT in the ruling's list is read-only and job-scoped
the same way (who is on site, the daily log, drawings), EXCEPT what reads
company-wide or enforcement records (DOB / DOT, permits, the subs roster,
group-chat history and voice notes, follow-ups): those stay with PM / admin
until someone rules otherwise. Every tool the brain has is in exactly one of
the two sets below; tests/test_dm_roles.py holds that against server.py.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

#: Roles answered on their assigned jobs only, with the field tool set.
FIELD_ROLES = frozenset({"superintendent", "cp"})
#: Roles answered with every tool (a PM on assigned jobs, an admin on all).
MANAGER_ROLES = frozenset({"admin", "pm"})

#: Tools a superintendent / CP may call, on their assigned jobs.
FIELD_TOOLS = frozenset({
    # progress
    "work_status", "find_photos", "send_photos", "daily_log", "open_items", "punch_status",
    "headcount", "who_on_site", "site_headcount", "sub_attendance", "material_status",
    "project_info", "upcoming_events",
    "project_status",
    # inspections and evidence (the floor of a photo they were just sent)
    "report_inspection", "confirm_photo_place",
    # the schedule (proposed_sequence: viewing only, approve is refused below)
    "schedule_lookahead", "proposed_sequence",
    # drawings
    "search_plans", "sheet_info", "send_sheet", "send_plan_file", "check_drawing_set",
    # drops nothing but their own open question
    "cancel_pending_change",
})

#: Tools reserved to a PM or an admin, and what each one is, for the refusal.
MANAGER_TOOLS: Dict[str, str] = {
    "propose_change": "changing job data (jobs, subs, people, settings)",
    "answer_pending_change": "changing job data",
    "set_sub_trade": "changing the subs list",
    "undo_last_change": "undoing a change",
    "send_report": "company reports",
    "remind_me": "reminders",
    "resend_my_brief": "the morning brief",
    "brief_status": "the morning brief",
    "my_settings": "assistant settings",
    "list_subs": "the subs list",
    "find_sub": "the subs list",
    "dob_status": "DOB records",
    "dot_status": "DOT records",
    "active_permits": "permits",
    "search_project_history": "group-chat history",
    "recent_voice_notes": "voice notes",
    "follow_ups": "follow-ups",
}

#: What a field role may do, said in every refusal.
FIELD_CAN = ("report an inspection, send a sign-off or photos, ask about progress and photos, "
             "and read the schedule, on their assigned jobs")


def norm(role: Any) -> str:
    return str(role or "").strip().lower()


def is_field(role: Any) -> bool:
    return norm(role) in FIELD_ROLES


def role_label(role: Any) -> str:
    """The role as the assistant names it to the model."""
    return {"admin": "admin", "pm": "project manager", "superintendent": "superintendent",
            "cp": "CP (competent person)"}.get(norm(role), norm(role) or "user")


def refusal(role: Any, what: str) -> str:
    """The tool result for a refused call: what was refused, why, and that
    nothing changed. The model is told to say so plainly."""
    return (f"REFUSED for their role ({role_label(role)}): {what} is for a PM or an admin. "
            f"Nothing was changed or sent. Tell them plainly that a PM or admin has to do this; "
            f"their role may {FIELD_CAN}.")


def tool_refusal(role: Any, name: str, args: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """None when this role may make this call; else the refusal text.

    Admin and PM: every tool (their own job scope is applied by the tools).
    Superintendent and CP: FIELD_TOOLS only, and proposed_sequence without
    `approve`. Any other role, and any tool in neither set: refused (a tool
    added later is closed to field roles until it is put in a set)."""
    r = norm(role)
    if r in MANAGER_ROLES:
        return None
    if r not in FIELD_ROLES:
        return refusal(role, "the assistant")
    if name == "proposed_sequence" and (args or {}).get("approve"):
        return refusal(role, "approving a sequence")
    if name in FIELD_TOOLS:
        return None
    return refusal(role, MANAGER_TOOLS.get(name, "that"))


def change_refusal(role: Any) -> Optional[str]:
    """None when this role may make a change through the change flow."""
    return None if norm(role) in MANAGER_ROLES else refusal(role, "changing job data")


def may_approve_sequence(role: Any) -> bool:
    return norm(role) in MANAGER_ROLES


#: The system prompt's note for a field role.
FIELD_PROMPT = (
    "ROLE LIMITS: this person is a {label}. Only the jobs listed are theirs (their assigned jobs). They may "
    + FIELD_CAN + ". They may NOT change job data, approve a sequence, get company reports, or read DOB / DOT, "
    "permits, the subs list, chat history or voice notes: those are for a PM or an admin. If they ask for one, "
    "say plainly that a PM or admin has to do it. Your tools are the ones they may use."
)

#: When the brain cannot answer a field role (no key, or switched off for
#: their company): the old pipeline is an admin / PM path, so it never
#: answers them.
FIELD_UNAVAILABLE_TEXT = "Levelog Assistant can't answer here right now. Please try again later."

#: A photo from a field role that is not a sign-off: walkthroughs (punch
#: lists sent to subs) are a PM / admin flow.
FIELD_PHOTO_TEXT = ("Got the photo. I keep photos here only as inspection sign-offs: send it again with the "
                    "inspection and floor in the caption, e.g. \"plumbing rough sign-off floor 3\".")
