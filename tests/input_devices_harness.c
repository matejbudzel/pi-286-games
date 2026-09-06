#include <assert.h>
#include <limits.h>
#include "input_devices.c"
int main(void) {
    InputDevices devices; HeldState held = {0}; int quit = 0, fds[2]; unsigned int revision;
    struct js_event event = {0};
    input_devices_init(&devices); devices.next_scan = LLONG_MAX;
    event.type = JS_EVENT_BUTTON | JS_EVENT_INIT; event.number = 9; event.value = 1;
    pad_event(&held, &quit, &event); assert(!quit);
    event.type = JS_EVENT_AXIS; event.number = 2;
    pad_event(&held, &quit, &event); assert(!held.pad[2]);
    event.type = JS_EVENT_BUTTON;
    pad_event(&held, &quit, &event); assert(held.pad[2]);
    held_update(&held, "LEFT", 1); revision = held.revision;
    assert(pipe(fds) == 0); devices.pad_fd = fds[0]; close(fds[1]);
    assert(input_devices_poll(&devices, &held, &quit, 0));
    assert(devices.pad_fd == -1 && !held.pad[2] && held.count == 1 && held.revision > revision);
    /* A replacement descriptor receives ordinary button events. */
    assert(pipe(fds) == 0); devices.pad_fd = fds[0];
    assert(write(fds[1], &event, sizeof(event)) == sizeof(event));
    assert(input_devices_poll(&devices, &held, &quit, 0)); assert(held.pad[2]);
    close(fds[1]); close(devices.pad_fd); devices.pad_fd = -1;
    assert(pipe(fds) == 0); devices.keyboards[0].fd = fds[0]; close(fds[1]);
    assert(input_devices_poll(&devices, &held, &quit, 0));
    assert(held.count == 0 && held.pad[2] && devices.keyboards[0].fd == -1);
    event.number = 9; pad_event(&held, &quit, &event); assert(quit);
    input_devices_close(&devices);
    return 0;
}
