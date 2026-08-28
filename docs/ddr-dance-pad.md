# DDR dance pad

The appliance supports exactly one USB pad: `WiseGroup.,Ltd X-PAD, Extreme
Dance Pad`. It is a second input path, not a replacement for the keyboard.
Keyboard and pad controls work at the same time, and the launcher can be used
with only the pad attached.

The launcher reads Linux's lightweight joystick interface (`/dev/input/js*`);
it does not use pygame and does not translate joystick input through a separate
daemon. The device exposes two axes, ten buttons and no hats. Its axes are
deliberately ignored: every useful physical panel is a direct button.

```text
button 6       button 2       button 7
UP-LEFT        UP             UP-RIGHT

button 0       idle           button 3
LEFT           centre         RIGHT

button 4       button 1       button 5
DOWN-LEFT      DOWN           DOWN-RIGHT

SELECT = button 9             START = button 8
```

The centre is intentionally not a button: standing there is the pad's idle
position.

## Launcher and panic controls

In the menu, button 2 moves up, button 1 moves down, button 0 and button 3
are available as left/right, button 8 confirms, and button 9 goes back.
Selecting a title first opens its full-screen pad layout. Press keyboard Space
or button 8 to launch, or Escape/button 9 to return to the menu.

Button 9 is permanently reserved as SELECT. While DOSBox is running the
launcher monitors it and terminates that DOSBox child, returning to the menu.
It is never written into a DOSBox mapper file, so no game action can consume
it. F1 is always available as the keyboard panic control too; it needs no host
configuration.

## Per-game configuration

Each game has `ddr.conf` beside `game.conf` and `mapper.txt`. It maps the fixed
physical button to one of the keyboard entries already present in that game's
DOSBox mapper, and gives its Slovak on-pad description:

```ini
button0_key=LEFT
button0_label=Doľava
button2_key=UP
button2_label=Skok
button8_key=SPACE
button8_label=Streľba
```

Use `-` for an unused button. Include all buttons 0 through 8 so the pre-game
screen faithfully shows the physical 3×3 layout. Valid key values are `UP`,
`DOWN`, `LEFT`, `RIGHT`, `SPACE`, `ENTER`, `ESC`, `LSHIFT`, and `LCTRL`.
Button 9 must not appear in this file.

For each launch the launcher copies the game's normal `mapper.txt` to a fresh
temporary `/tmp/pi-286-games-dosbox-mapper.txt`, appends the configured
`stick_0 button N` bindings, and points the generated DOSBox configuration at
that copy. This preserves normal keyboard bindings and prevents mappings from
one game leaking to another.

## Testing the pad on DietPi

The appliance user must be in the `input` group (the installer already does
this). After changing groups, reboot or log in again. Confirm the device exists
with:

```sh
ls -l /dev/input/js* /dev/input/event*
```

For an interactive raw button check, install the optional diagnostic utility:

```sh
sudo apt install joystick
jstest /dev/input/js0
```

Pressing a panel should change its matching button number from `0` to `1`.
Do not test directions through axes; they are intentionally unused here.
