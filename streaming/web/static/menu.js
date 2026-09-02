export function createMenu({start}) {
  const menu = document.querySelector("#menu"), games = document.querySelector("#games"), inputMode = document.querySelector("#input-mode");
  const preGame = document.querySelector("#pre-game"), options = document.querySelector("#menu-options"), status = document.querySelector("#status");
  function textStatus(value) { status.textContent = value; }
  function capabilities() { return {keyboard: inputMode.value !== "pad", dancePad: inputMode.value !== "keyboard"}; }
  function showList() { menu.hidden = false; preGame.hidden = true; games.hidden = false; options.hidden = false; }
  function showPreGame() { games.hidden = true; preGame.hidden = false; options.hidden = true; }
  function showGame() { menu.hidden = true; }
  function launchOptions() { return {transport: document.querySelector("#transport").value, videoScaling: document.querySelector("#scaling").value, capabilities: capabilities()}; }
  function showPadMap(game) {
    const labels = game.pre_game.pad_labels, keys = game.pre_game.pad_keys;
    const legend = document.querySelector("#pre-game-pad"); legend.replaceChildren(); legend.hidden = !capabilities().dancePad;
    for (const button of [6, 2, 7, 0, 8, 3, 4, 1, 5]) {
      const entry = document.createElement("span");
      entry.textContent = button === 8 ? "START" : document.querySelector(`[data-pad-button="${button}"]`).textContent;
      const detail = document.createElement("small"); detail.textContent = keys[button] ? labels[button] : "nepoužité";
      entry.append(detail); legend.append(entry);
    }
  }
  async function initialise() {
    try {
      const caps = capabilities(), response = await fetch(`/web/api/games?keyboard=${caps.keyboard ? 1 : 0}&dance_pad=${caps.dancePad ? 1 : 0}`);
      if (!response.ok) throw Error(await response.text());
      const payload = await response.json();
      games.replaceChildren(); showList();
      for (const game of payload.games) {
        const button = document.createElement("button"); button.textContent = game.name;
        button.onclick = () => {
          document.querySelector("#pre-game-title").textContent = game.name;
          document.querySelector("#pre-game-hint").textContent = game.pre_game.launch_hint;
          const instructions = document.querySelector("#pre-game-instructions");
          instructions.replaceChildren(...game.pre_game.instructions.map(line => { const paragraph = document.createElement("p"); paragraph.textContent = line; return paragraph; }));
          showPadMap(game); showPreGame();
          document.querySelector("#pre-game-start").onclick = () => start(game.id, launchOptions());
        };
        games.append(button);
      }
      textStatus("Vyber hru. Tento runtime je určený iba pre dôveryhodnú lokálnu sieť.");
    } catch (error) { textStatus(`Nedá sa načítať launcher: ${error.message}`); }
  }
  document.querySelector("#pre-game-back").onclick = showList;
  inputMode.onchange = initialise;
  initialise();
  return {textStatus, showGame, showList};
}
