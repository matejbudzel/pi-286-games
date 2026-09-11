#include <assert.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>
#include <zlib.h>
#include "input_devices.c"
int main(void) {
    InputDevices devices; HeldState held = {0}; int quit = 0, fds[2], is_2x, capture, sequence, audio_length, next_audio, video_length; unsigned int revision;
    unsigned char *raw, *compressed, *packet, frame[FRAME], frame2[FRAME2]; const unsigned char *audio; uLongf compressed_length;
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
    raw = malloc(FRAME2); compressed = malloc(compressBound(FRAME2)); packet = malloc(POLL_HEADER + VIDEO_HEADER + compressBound(FRAME2));
    assert(raw && compressed && packet);
    memset(raw, 0x5a, FRAME2); compressed_length = compressBound(FRAME2);
    assert(compress2(compressed, &compressed_length, raw, FRAME2, 1) == Z_OK);
    memcpy(packet, "P2P1", 4); packet[4] = packet[5] = 0; packet[6] = (unsigned char)((VIDEO_HEADER + compressed_length) >> 8); packet[7] = (unsigned char)(VIDEO_HEADER + compressed_length);
    memset(packet + 8, 0, 8); memcpy(packet + POLL_HEADER, "P2V1\004\0\0\0", 8); memset(packet + POLL_HEADER + 8, 0, 8); memcpy(packet + POLL_HEADER + VIDEO_HEADER, compressed, compressed_length);
    assert(apply_poll_packet(frame, frame2, &is_2x, packet, POLL_HEADER + VIDEO_HEADER + compressed_length, &capture, &sequence, &audio, &audio_length, &next_audio));
    assert(is_2x && !memcmp(frame2, raw, FRAME2));
    video_length = VIDEO_HEADER + 2 + TILE2 * TILE2 * 2;
    memcpy(packet, "P2P1", 4); packet[4] = packet[5] = 0; packet[6] = (unsigned char)(video_length >> 8); packet[7] = (unsigned char)video_length;
    memset(packet + 8, 0, 8); memcpy(packet + POLL_HEADER, "P2V1\005\0\0\1", 8); memset(packet + POLL_HEADER + 8, 0, 8);
    packet[POLL_HEADER + VIDEO_HEADER] = packet[POLL_HEADER + VIDEO_HEADER + 1] = 1;
    memset(packet + POLL_HEADER + VIDEO_HEADER + 2, 0x3c, TILE2 * TILE2 * 2); memset(frame2, 0, FRAME2);
    assert(apply_poll_packet(frame, frame2, &is_2x, packet, POLL_HEADER + video_length, &capture, &sequence, &audio, &audio_length, &next_audio));
    assert(is_2x && frame2[(TILE2 * W2 + TILE2) * 2] == 0x3c);
    free(packet); free(compressed); free(raw);
    input_devices_close(&devices);
    return 0;
}
