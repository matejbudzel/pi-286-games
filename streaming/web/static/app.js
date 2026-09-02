import {keyName} from "/input.js";
import {createMenu} from "/menu.js";
import {createSession} from "/stream-session.js";
import {createVirtualControls} from "/virtual-controls.js";

let session;
const controls = createVirtualControls({
  keyName,
  active: () => Boolean(session?.active()),
  stop: () => session.stop(),
  toggleHud: () => session.toggleHud(),
  changed: () => session?.sendControl(),
});
const menu = createMenu({start: (gameId, options) => session.start(gameId, options)});
session = createSession({
  input: controls,
  textStatus: menu.textStatus,
  showGame: options => { controls.show(options.capabilities); menu.showGame(); },
  showList: menu.showList,
});
