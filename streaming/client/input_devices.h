#ifndef PI286_INPUT_DEVICES_H
#define PI286_INPUT_DEVICES_H
#include "presenter.h"
#define INPUT_KEYBOARDS 32
typedef struct { int fd; char path[256]; } InputKeyboard;
typedef struct {
    int pad_fd;
    InputKeyboard keyboards[INPUT_KEYBOARDS];
    long long next_scan;
} InputDevices;
void input_devices_init(InputDevices *devices);
void input_devices_close(InputDevices *devices);
int input_devices_poll(InputDevices *devices, HeldState *held, int *quit, long long now);
#endif
