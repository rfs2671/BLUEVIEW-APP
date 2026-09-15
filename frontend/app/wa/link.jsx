// ── /wa/link?t=… — THE IN-CHAT FRONT DOOR ───────────────────────────────────
//
// Reached by tapping a link the bot posted in a WhatsApp group, for the person
// who added it and is holding a phone rather than sitting at the admin screen.
//
// IT IS THE SAME SCREEN, DELIBERATELY. The admin list and this both render
// app/admin/whatsapp-groups.jsx and both call the same backend routes; the
// only difference is that `t` in the query narrows the list to one group.
// Two screens doing one job is two places for the tenancy rules to drift, and
// those rules are the difference between a group linked to the right job and
// one customer's site data landing in another customer's chat.
//
// THE TOKEN GRANTS NOTHING. This route requires a normal login like any other,
// and the backend re-runs every role and tenant check. The token says WHICH
// group to show — it is a name, not a key.
export { default } from '../admin/whatsapp-groups';
