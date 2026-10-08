"""Reactions instead of filler replies.

When Levelog Assistant acts on a message and has nothing useful to add, it
reacts to that exact message instead of sending "Got it" / "Done". A fixed
map, never random:

    DONE     👍  instruction understood and done (generic)
    COMPLETE ✅  item marked complete / task done / checklist item closed
    SAVED    📌  saved for later: logged, reminder set, added to a list
    WORKING  👀  working on it — a reply is still coming (long task)
    THANKS   🙏  someone thanks the bot
    PRAISE   ❤️  someone praises the bot (at most once per person per day)

Rules (enforced by the callers in server.py):
  * A question gets a text answer; 👀 first only if it takes over 5 seconds.
  * A failure or missing information gets a short text reply, no reaction.
  * Never a reaction AND filler text for the same action: if the reaction
    cannot be sent, the old text goes instead.
  * One reaction per message, and only on messages addressed to the bot.
  * START / STOP and the 1 / 2 GC-group reply keep their text confirmations.
"""

from __future__ import annotations

import re
from typing import Optional

DONE = "👍"
COMPLETE = "✅"
SAVED = "📌"
WORKING = "👀"
THANKS = "🙏"
PRAISE = "❤️"

REACTIONS = {"done": DONE, "complete": COMPLETE, "saved": SAVED,
             "working": WORKING, "thanks": THANKS, "praise": PRAISE}

# Seconds an answer may take before 👀 goes on the question.
WORKING_AFTER_SECONDS = 5.0

# Words that may sit around a thank-you or a compliment without making it a
# request: the bot's name, fillers, punctuation.
_NOISE = r"(?:@?levelog|assistant|bot|so|very|much|a\s+lot|lots|again|man|guys|team|!|\.|,|\s|🙏|👍|❤️|😊|🙂)*"
_THANKS_RE = re.compile(
    r"^" + _NOISE + r"(?:thanks|thank\s+you|thankyou|thx|ty|tysm|cheers|gracias|muchas\s+gracias)" + _NOISE + r"$",
    re.IGNORECASE)
_PRAISE_RE = re.compile(
    r"^" + _NOISE + r"(?:good\s+job|great\s+job|nice\s+job|well\s+done|nice\s+work|great\s+work|"
    r"good\s+bot|you(?:'re|\s+are)\s+(?:the\s+best|awesome|great)|love\s+(?:it|this|you)|"
    r"awesome|amazing|perfect|excellent|brilliant|great|nice)" + _NOISE + r"$",
    re.IGNORECASE)


def social_reaction(body: Optional[str]) -> Optional[str]:
    """'thanks' or 'praise' when the WHOLE message is only that; else None.
    Anything with a question or a request in it is not."""
    text = str(body or "").strip()
    if not text or "?" in text or len(text) > 60:
        return None
    if _THANKS_RE.match(text):
        return "thanks"
    if _PRAISE_RE.match(text):
        return "praise"
    return None
