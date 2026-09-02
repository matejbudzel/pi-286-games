export function installMenu({start, inputMode, textStatus, showGameList, showPreGame, showPadMap}) {
  const games = document.querySelector("#games");
  async function initialise() {
    try {
      const keyboard = inputMode.value !== "pad", dancePad = inputMode.value !== "keyboard";
      const response = await fetch(`/web/api/games?keyboard=${keyboard ? 1 : 0}&dance_pad=${dancePad ? 1 : 0}`);
      const payload = await response.json();
      games.replaceChildren(); showGameList();
      for (const game of payload.games) {
        const button = document.createElement("button"); button.textContent = game.name;
        button.onclick = () => { document.querySelector("#pre-game-title").textContent = game.name;
          document.querySelector("#pre-game-hint").textContent = game.pre_game.launch_hint;
          const instructions = document.querySelector("#pre-game-instructions");
          instructions.replaceChildren(...game.pre_game.instructions.map(line => { const p = document.createElement("p"); p.textContent = line; return p; }));
          showPadMap(game); showPreGame(); document.querySelector("#pre-game-start").onclick = () => start(game.id); };
        games.append(button);
      }
      textStatus("Vyber hru. Tento runtime je určený iba pre dôveryhodnú lokálnu sieť.");
    } catch (error) { textStatus(`Nedá sa načítať launcher: ${error.message}`); }
  }
  document.querySelector("#pre-game-back").onclick = showGameList;
  inputMode.onchange = initialise;
  initialise();
}
