/* Serializes session creation so double taps cannot launch two DOSBox sessions. */
export function createSession({begin, end}) {
  let starting = false;
  return {
    async start(gameId) {
      if (starting) return;
      starting = true;
      try { await begin(gameId); }
      finally { starting = false; }
    },
    stop() { return end(); },
  };
}
