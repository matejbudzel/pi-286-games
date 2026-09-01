#include "presenter.h"
#include <stdio.h>
#include <string.h>

static unsigned int read_be16(const unsigned char *value) { return ((unsigned int)value[0] << 8) | value[1]; }
static unsigned int read_be32(const unsigned char *value) { return ((unsigned int)value[0] << 24) | ((unsigned int)value[1] << 16) | ((unsigned int)value[2] << 8) | value[3]; }

static int apply_video_packet(unsigned char *frame, const unsigned char *packet, size_t length) {
    unsigned int kind, count, tile, tile_x, tile_y; size_t offset, row;
    if (length < VIDEO_HEADER || memcmp(packet, "P2V1", 4)) return 0;
    kind = packet[4]; count = read_be16(packet + 6);
    if (kind == 1) { if (count || length != VIDEO_HEADER + FRAME) return 0; memcpy(frame, packet + VIDEO_HEADER, FRAME); return 1; }
    if (kind != 2 || count > (W / TILE) * (H / TILE) || length != VIDEO_HEADER + count * (2 + TILE * TILE * 2)) return 0;
    offset = VIDEO_HEADER;
    for (tile = 0; tile < count; tile++) {
        tile_x = packet[offset++]; tile_y = packet[offset++]; if (tile_x >= W / TILE || tile_y >= H / TILE) return 0;
        for (row = 0; row < TILE; row++) { memcpy(frame + ((tile_y * TILE + row) * W + tile_x * TILE) * 2, packet + offset, TILE * 2); offset += TILE * 2; }
    }
    return 2;
}

int apply_poll_packet(unsigned char *frame, const unsigned char *packet, size_t length, int *video_capture, int *video_seq, const unsigned char **audio, int *audio_length, int *next_audio) {
    unsigned int video_length, pcm_length;
    if (length < POLL_HEADER || memcmp(packet, "P2P1", 4)) return 0;
    video_length = read_be32(packet + 4); pcm_length = read_be32(packet + 8);
    if (video_length > VIDEO_PACKET_MAX || pcm_length > 65536 || length != POLL_HEADER + video_length + pcm_length || !apply_video_packet(frame, packet + POLL_HEADER, video_length)) return 0;
    *video_capture = (int)read_be32(packet + POLL_HEADER + 12); *video_seq = (int)read_be32(packet + POLL_HEADER + 8);
    *audio = packet + POLL_HEADER + video_length; *audio_length = (int)pcm_length; *next_audio = (int)read_be32(packet + 12); return 1;
}

void held_update(HeldState *held, const char *key, int pressed) {
    int index; for (index = 0; index < held->count; index++) if (!strcmp(held->keys[index], key)) break;
    if (pressed && index == held->count && held->count < 64) { snprintf(held->keys[held->count++], sizeof(held->keys[0]), "%s", key); held->revision++; }
    if (!pressed && index < held->count) { memmove(held->keys[index], held->keys[index + 1], (size_t)(held->count - index - 1) * sizeof(held->keys[0])); held->count--; held->revision++; }
}

void pad_update(HeldState *held, int button, int pressed) {
    if (button < 0 || button >= 9 || held->pad[button] == !!pressed) return;
    held->pad[button] = !!pressed;
    held->revision++;
}

int poll_body(char *body, size_t size, const HeldState *held, int video_seq, int audio_offset) {
    int used, index; used = snprintf(body, size, "{\"input_revision\":%u,\"video_seq\":%d,\"audio_offset\":%d,\"keyboard_held\":[", held->revision, video_seq, audio_offset);
    if (used < 0 || (size_t)used >= size) return -1;
    for (index = 0; index < held->count; index++) { int added = snprintf(body + used, size - (size_t)used, "%s\"%s\"", index ? "," : "", held->keys[index]); if (added < 0 || (size_t)added >= size - (size_t)used) return -1; used += added; }
    if ((size_t)used + 20 >= size) return -1;
    memcpy(body + used, "],\"dance_pad_held\":[", 20); used += 20;
    for (index = 0; index < 9; index++) if (held->pad[index]) { int added = snprintf(body + used, size - (size_t)used, "%s%d", used > 0 && body[used - 1] != '[' ? "," : "", index); if (added < 0 || (size_t)added >= size - (size_t)used) return -1; used += added; }
    if ((size_t)used + 3 >= size) return -1;
    memcpy(body + used, "]}", 3);
    return used + 2;
}
