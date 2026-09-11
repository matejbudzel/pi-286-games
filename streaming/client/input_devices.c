/* Linux input lifetime for the fixed Pi console; no grabs or SDL joystick list. */
#include "input_devices.h"
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <linux/input.h>
#include <linux/joystick.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

void input_devices_init(InputDevices *devices) {
    int i;
    memset(devices, 0, sizeof(*devices));
    devices->pad_fd = -1;
    for (i = 0; i < INPUT_KEYBOARDS; i++) devices->keyboards[i].fd = -1;
}

void input_devices_close(InputDevices *devices) {
    int i;
    if (devices->pad_fd >= 0) close(devices->pad_fd);
    for (i = 0; i < INPUT_KEYBOARDS; i++)
        if (devices->keyboards[i].fd >= 0) close(devices->keyboards[i].fd);
    input_devices_init(devices);
}

static void scan_devices(InputDevices *devices) {
    glob_t paths = {0}; size_t n; int fd, i, slot;
    if (devices->pad_fd < 0 && glob("/dev/input/js*", 0, NULL, &paths) == 0) {
        for (n = 0; n < paths.gl_pathc; n++) {
            char name[128] = {0}; unsigned char axes = 0, buttons = 0;
            fd = open(paths.gl_pathv[n], O_RDONLY | O_NONBLOCK | O_CLOEXEC);
            if (fd < 0) continue;
            ioctl(fd, JSIOCGAXES, &axes); ioctl(fd, JSIOCGBUTTONS, &buttons);
            /* Match the launcher's recognition of kernels that rename the X-PAD. */
            if (ioctl(fd, JSIOCGNAME(sizeof(name)), name) >= 0 &&
                (!strcmp(name, "WiseGroup.,Ltd X-PAD, Extreme Dance Pad") || (axes == 2 && buttons == 10))) {
                devices->pad_fd = fd;
                fprintf(stderr, "presenter: dance pad connected\n");
                break;
            }
            close(fd);
        }
    }
    globfree(&paths); memset(&paths, 0, sizeof(paths));
    if (glob("/dev/input/event*", 0, NULL, &paths) == 0) {
        for (n = 0; n < paths.gl_pathc; n++) {
            unsigned char bits[8] = {0}; int found = 0;
            slot = -1;
            for (i = 0; i < INPUT_KEYBOARDS; i++) {
                if (devices->keyboards[i].fd < 0) slot = i;
                else if (!strcmp(devices->keyboards[i].path, paths.gl_pathv[n])) found = 1;
            }
            if (found || slot < 0) continue;
            fd = open(paths.gl_pathv[n], O_RDONLY | O_NONBLOCK | O_CLOEXEC);
            if (fd < 0) continue;
            if (ioctl(fd, EVIOCGBIT(EV_KEY, sizeof(bits)), bits) >= 0 &&
                (bits[KEY_F1 / 8] & (1 << (KEY_F1 % 8)))) {
                devices->keyboards[slot].fd = fd;
                snprintf(devices->keyboards[slot].path, sizeof(devices->keyboards[slot].path), "%s", paths.gl_pathv[n]);
                fprintf(stderr, "presenter: keyboard connected\n");
            } else close(fd);
        }
    }
    globfree(&paths);
}

static void release_keyboard(HeldState *held) {
    /* SDL's console keyboard survives USB removal, but the missing key-up does not. */
    if (held->count) { held->count = 0; held->revision++; }
}

/* Keep the raw console keyboard path aligned with the server's closed DOS key
 * protocol.  F1 is intentionally absent: it is the local launcher return. */
static const char *linux_dos_key(unsigned short code) {
    switch (code) {
    case KEY_ESC: return "ESC"; case KEY_1: return "1"; case KEY_2: return "2"; case KEY_3: return "3"; case KEY_4: return "4";
    case KEY_5: return "5"; case KEY_6: return "6"; case KEY_7: return "7"; case KEY_8: return "8"; case KEY_9: return "9"; case KEY_0: return "0";
    case KEY_MINUS: return "MINUS"; case KEY_EQUAL: return "EQUALS"; case KEY_BACKSPACE: return "BACKSPACE"; case KEY_TAB: return "TAB";
    case KEY_Q: return "Q"; case KEY_W: return "W"; case KEY_E: return "E"; case KEY_R: return "R"; case KEY_T: return "T"; case KEY_Y: return "Y";
    case KEY_U: return "U"; case KEY_I: return "I"; case KEY_O: return "O"; case KEY_P: return "P"; case KEY_LEFTBRACE: return "LEFTBRACKET";
    case KEY_RIGHTBRACE: return "RIGHTBRACKET"; case KEY_ENTER: return "ENTER"; case KEY_LEFTCTRL: case KEY_RIGHTCTRL: return "CTRL";
    case KEY_A: return "A"; case KEY_S: return "S"; case KEY_D: return "D"; case KEY_F: return "F"; case KEY_G: return "G"; case KEY_H: return "H";
    case KEY_J: return "J"; case KEY_K: return "K"; case KEY_L: return "L"; case KEY_SEMICOLON: return "SEMICOLON"; case KEY_APOSTROPHE: return "QUOTE";
    case KEY_GRAVE: return "BACKQUOTE"; case KEY_LEFTSHIFT: case KEY_RIGHTSHIFT: return "SHIFT"; case KEY_BACKSLASH: return "BACKSLASH";
    case KEY_Z: return "Z"; case KEY_X: return "X"; case KEY_C: return "C"; case KEY_V: return "V"; case KEY_B: return "B"; case KEY_N: return "N";
    case KEY_M: return "M"; case KEY_COMMA: return "COMMA"; case KEY_DOT: return "PERIOD"; case KEY_SLASH: return "SLASH";
    case KEY_LEFTALT: case KEY_RIGHTALT: return "ALT"; case KEY_SPACE: return "SPACE"; case KEY_CAPSLOCK: return "CAPSLOCK";
    case KEY_F2: return "F2"; case KEY_F3: return "F3"; case KEY_F4: return "F4"; case KEY_F5: return "F5"; case KEY_F6: return "F6";
    case KEY_F7: return "F7"; case KEY_F8: return "F8"; case KEY_F9: return "F9"; case KEY_F10: return "F10"; case KEY_F11: return "F11"; case KEY_F12: return "F12";
    case KEY_NUMLOCK: return "NUMLOCK"; case KEY_SCROLLLOCK: return "SCROLLLOCK"; case KEY_KP7: return "KP7"; case KEY_KP8: return "KP8";
    case KEY_KP9: return "KP9"; case KEY_KPMINUS: return "KP_MINUS"; case KEY_KP4: return "KP4"; case KEY_KP5: return "KP5";
    case KEY_KP6: return "KP6"; case KEY_KPPLUS: return "KP_PLUS"; case KEY_KP1: return "KP1"; case KEY_KP2: return "KP2";
    case KEY_KP3: return "KP3"; case KEY_KP0: return "KP0"; case KEY_KPDOT: return "KP_PERIOD"; case KEY_KPENTER: return "KP_ENTER";
    case KEY_KPSLASH: return "KP_DIVIDE"; case KEY_KPASTERISK: return "KP_MULTIPLY"; case KEY_KPEQUAL: return "KP_EQUALS";
    case KEY_HOME: return "HOME"; case KEY_UP: return "UP"; case KEY_PAGEUP: return "PAGEUP"; case KEY_LEFT: return "LEFT";
    case KEY_RIGHT: return "RIGHT"; case KEY_END: return "END"; case KEY_DOWN: return "DOWN"; case KEY_PAGEDOWN: return "PAGEDOWN";
    case KEY_INSERT: return "INSERT"; case KEY_DELETE: return "DELETE"; case KEY_PAUSE: return "PAUSE";
    case KEY_SYSRQ: case KEY_PRINT: return "PRINT"; case KEY_LEFTMETA: case KEY_RIGHTMETA: return "META";
    default: return NULL;
    }
}

static void pad_event(HeldState *held, int *quit, const struct js_event *event) {
    /* Ignore axes and initial state, especially a held START/SELECT on reconnect. */
    if (event->type != JS_EVENT_BUTTON) return;
    if (event->number == 9 && event->value) { *quit = 1; return; }
    if (event->number < 9) pad_update(held, event->number, event->value != 0);
}

int input_devices_poll(InputDevices *devices, HeldState *held, int *quit, long long now) {
    unsigned int before = held->revision; int i, j; ssize_t count;
    if (devices->pad_fd >= 0) {
        struct js_event events[64];
        count = read(devices->pad_fd, events, sizeof(events));
        if (count > 0) {
            for (j = 0; j < count / (ssize_t)sizeof(events[0]); j++) pad_event(held, quit, &events[j]);
        } else if (count == 0 || (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)) {
            close(devices->pad_fd); devices->pad_fd = -1;
            for (j = 0; j < 9; j++) pad_update(held, j, 0);
            fprintf(stderr, "presenter: dance pad disconnected; released buttons\n");
        }
    }
    for (i = 0; i < INPUT_KEYBOARDS; i++) {
        struct input_event events[64]; const char *key;
        if (devices->keyboards[i].fd < 0) continue;
        count = read(devices->keyboards[i].fd, events, sizeof(events));
        if (count > 0) {
            for (j = 0; j < count / (ssize_t)sizeof(events[0]); j++) {
                if (events[j].type == EV_SYN && events[j].code == SYN_DROPPED) release_keyboard(held);
                if (events[j].type != EV_KEY) continue;
                if (events[j].code == KEY_F1) { if (events[j].value == 1) *quit = 1; continue; }
                key = linux_dos_key(events[j].code);
                if (key && events[j].value != 2) fprintf(stderr, "presenter: raw key %s %s\n", key, events[j].value ? "down" : "up");
                if (key && events[j].value != 2) held_update(held, key, events[j].value != 0);
            }
        } else if (count == 0 || (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)) {
            close(devices->keyboards[i].fd); devices->keyboards[i].fd = -1;
            release_keyboard(held);
            fprintf(stderr, "presenter: keyboard disconnected; released keys\n");
        }
    }
    if (now >= devices->next_scan) { scan_devices(devices); devices->next_scan = now + 2000; }
    return *quit || held->revision != before;
}
