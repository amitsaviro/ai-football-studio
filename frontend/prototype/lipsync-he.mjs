/**
 * Hebrew lip-sync module for TalkingHead: Hebrew text -> Oculus visemes.
 *
 * Same interface as TalkingHead's built-in modules (lipsync-fi.mjs etc.):
 * preProcessText(s) and wordsToVisemes(word) -> { words, visemes, times, durations },
 * where times/durations are in relative units that TalkingHead stretches over the word's
 * real duration (from the TTS word-boundary timestamps).
 *
 * Hebrew is written without vowels, but mouth shapes are driven mostly by consonants
 * (lips closing on מ/ב/פ, teeth on ש/ס/צ...). Vowels are approximated: ו and י act as
 * vowels between consonants, and an open "a" is inserted between consecutive consonants.
 */

// Consonants -> Oculus viseme
const CONSONANTS = {
  'ב': 'PP', 'מ': 'PP', 'ם': 'PP', 'פ': 'PP',
  'ף': 'FF',
  'ד': 'DD', 'ת': 'DD', 'ט': 'DD',
  'נ': 'nn', 'ן': 'nn', 'ל': 'nn',
  'ס': 'SS', 'צ': 'SS', 'ץ': 'SS', 'ז': 'SS',
  'ש': 'CH',
  'ג': 'kk', 'ק': 'kk', 'כ': 'kk', 'ך': 'kk', 'ח': 'kk',
  'ר': 'RR',
};

// Relative durations (1 = average), in the spirit of the built-in modules
const DURATIONS = {
  aa: 0.95, E: 0.9, I: 0.92, O: 0.96, U: 0.95,
  PP: 1.08, SS: 1.23, CH: 1.2, DD: 1.05, FF: 1.0, kk: 1.21, nn: 0.88, RR: 0.88,
};

const DIGITS = ['אפס', 'אחת', 'שתיים', 'שלוש', 'ארבע', 'חמש', 'שש', 'שבע', 'שמונה', 'תשע'];

class LipsyncHe {

  preProcessText(s) {
    return s
      .replace(/[֑-ׇ]/g, '')                               // niqqud / cantillation marks
      .replace(/\d/g, d => ' ' + DIGITS[+d] + ' ')                   // digits -> Hebrew words
      .replace(/[^א-ת\s]/g, ' ')                            // keep Hebrew letters only
      .replace(/\s+/g, ' ')
      .trim();
  }

  /** Turn one (pre-processed) word into a viseme sequence. */
  wordsToVisemes(word) {
    const out = { words: word, visemes: [], times: [], durations: [] };
    const chars = [...word].filter(c => c !== ' ');
    let t = 0;
    const push = (viseme, weight = 1) => {
      const last = out.visemes.length - 1;
      if (last >= 0 && out.visemes[last] === viseme) {               // merge repeats
        out.durations[last] += 0.6 * DURATIONS[viseme] * weight;
        t += 0.6 * DURATIONS[viseme] * weight;
        return;
      }
      const d = DURATIONS[viseme] * weight;
      out.visemes.push(viseme); out.times.push(t); out.durations.push(d);
      t += d;
    };

    for (let i = 0; i < chars.length; i++) {
      const c = chars[i], next = chars[i + 1];
      const first = i === 0, last = i === chars.length - 1;

      if (c === 'ו') { first ? push('FF') : push(next && next !== 'ו' && i > 0 ? 'O' : 'U'); continue; }
      if (c === 'י') { push(first ? 'I' : 'I', first ? 0.7 : 1); continue; }
      if (c === 'א' || c === 'ע') { push('aa'); continue; }
      if (c === 'ה') { push(last ? 'aa' : 'E', last ? 0.8 : 0.6); continue; }

      const v = CONSONANTS[c];
      if (!v) continue;
      push(v);
      // No written vowel follows: assume an open vowel between two consonants.
      if (next && CONSONANTS[next]) push(i === 0 ? 'E' : 'aa', 0.8);
    }
    return out;
  }
}

export { LipsyncHe };
