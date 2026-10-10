/**
 * The message something came from: an attention item, a state change, an
 * Upcoming event or a search answer. What the screen says for it. Pure, so
 * it is tested under plain node (sourceMessage.test.cjs).
 *
 * A voice note's words are its transcript, as said (Spanish stays Spanish);
 * its quote is marked 🎤, and the sheet shows the language, how sure the
 * transcription was, the English, and a button to play the audio.
 * (GET /api/projects/{id}/whatsapp/messages/{row}/source)
 */

export const MIC = '🎤';

const LANGS = { en: 'English', es: 'Spanish', yi: 'Yiddish' };

export function langLabel(code) {
  if (!code) return '';
  return LANGS[code] || String(code).charAt(0).toUpperCase() + String(code).slice(1);
}

/** “words” — or 🎤 “words” for a voice note. */
export function quoteText(quote, voice) {
  if (!quote) return '';
  return voice ? `${MIC} “${quote}”` : `“${quote}”`;
}

/** "🎤 Spanish · 6s · 91% sure". */
export function voiceLine(v) {
  if (!v) return '';
  const parts = [`${MIC} ${langLabel(v.lang) || 'Voice note'}`];
  if (v.duration_sec) parts.push(`${Math.round(v.duration_sec)}s`);
  if (typeof v.confidence === 'number') parts.push(`${Math.round(v.confidence * 100)}% sure`);
  return parts.join(' · ');
}

/** Why a voice note's item waits for a look, or null. */
export function reviewNote(v, reason) {
  const why = reason || (v && v.review ? (v.lang === 'yi' ? 'yiddish_voice' : 'low_confidence_voice') : null);
  if (why === 'yiddish_voice') {
    return 'Flagged: a Yiddish voice note. Check the words before acting on it.';
  }
  if (why === 'low_confidence_voice') {
    return 'Flagged: the transcription may be wrong. Play it before acting on it.';
  }
  return null;
}

/** The English, only when it says something the words do not. */
export function englishLine(v, text) {
  if (!v || !v.english) return null;
  const a = String(v.english).trim().toLowerCase();
  const b = String(text || '').trim().toLowerCase();
  return a && a !== b ? `In English: “${v.english}”` : null;
}

/** "Carlos · Oct 14, 7:15 AM", New York time. */
export function headLine(src) {
  if (!src) return '';
  const parts = [];
  if (src.who) parts.push(src.who);
  if (src.at) {
    try {
      parts.push(new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/New_York', month: 'short', day: 'numeric',
        hour: 'numeric', minute: '2-digit',
      }).format(new Date(src.at)).replace(/\s/g, ' '));
    } catch (e) { /* no date */ }
  }
  return parts.join(' · ');
}
