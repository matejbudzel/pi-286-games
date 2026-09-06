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
        struct input_event events[64];
        if (devices->keyboards[i].fd < 0) continue;
        count = read(devices->keyboards[i].fd, events, sizeof(events));
        if (count > 0) {
            for (j = 0; j < count / (ssize_t)sizeof(events[0]); j++) {
                if (events[j].type == EV_SYN && events[j].code == SYN_DROPPED) release_keyboard(held);
                if (events[j].type == EV_KEY && events[j].code == KEY_F1 && events[j].value == 1) *quit = 1;
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
