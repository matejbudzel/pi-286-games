#ifndef PI286_PRESENTER_H
#define PI286_PRESENTER_H

#include <stddef.h>

#define W 320
#define H 240
#define FRAME (W * H * 2)
#define TILE 16
#define VIDEO_HEADER 16
#define VIDEO_PACKET_MAX (VIDEO_HEADER + FRAME)
#define POLL_HEADER 16
#define POLL_PACKET_MAX (POLL_HEADER + VIDEO_PACKET_MAX + 65536)

typedef struct { char keys[64][20]; int count; unsigned int revision; } HeldState;

int apply_poll_packet(unsigned char *frame, const unsigned char *packet, size_t length,
                      int *video_capture, int *video_seq, const unsigned char **audio,
                      int *audio_length, int *next_audio);
void held_update(HeldState *held, const char *key, int pressed);
int poll_body(char *body, size_t size, const HeldState *held, int video_seq, int audio_offset);

#endif
