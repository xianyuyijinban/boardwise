// Paste into EasyEDA Pro's script console (same place as probe1/probe2).
//
// Answers one question: does this editor realm have a usable random source?
// The connector needs 32 random bytes to invent its own pairing token; on
// 2026-09-13 a real editor reported `token: NONE — this editor cannot generate
// one`, i.e. bare `crypto` did not resolve there. This probe says what it
// actually sees, so the fix is based on measurement rather than assumption.

function probe(fn) {
  try {
    return { ok: true, value: fn() };
  } catch (e) {
    return { ok: false, error: String(e) + ' (' + (e && e.name) + ')' };
  }
}

const hex = (bytes) => Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');

return {
  cryptoType: probe(() => typeof crypto),
  cryptoGetRandomValuesType: probe(() => typeof crypto.getRandomValues),
  globalCryptoType: probe(() => typeof globalThis.crypto),
  cryptoIsGlobalCrypto: probe(() => crypto === globalThis.crypto),
  getRandomValuesWorks: probe(() => {
    const bytes = new Uint8Array(4);
    crypto.getRandomValues(bytes);
    return hex(bytes);
  }),
  mathRandomType: probe(() => typeof Math.random),
  // In case the editor keeps a random helper under its own API.
  edaSysMathKeys: probe(() => Object.keys(eda.sys_Math || {})),
  edaTopLevelKeysSample: probe(() => Object.keys(eda).slice(0, 24)),
};
