#include <SDL.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static void tone(void *unused, Uint8 *stream, int length) {
    static unsigned phase;
    int16_t *samples = (int16_t *)stream;
    int count = length / (int)sizeof(*samples);
    int index;
    (void)unused;
    for (index = 0; index < count; index++) {
        samples[index] = phase < 25 ? 9000 : -9000;
        phase = (phase + 1) % 50;
    }
}

int main(void) {
    SDL_AudioSpec wanted;
    if (SDL_Init(SDL_INIT_AUDIO) != 0) {
        fprintf(stderr, "SDL_Init audio: %s\n", SDL_GetError());
        return 1;
    }
    memset(&wanted, 0, sizeof(wanted));
    wanted.freq = 22050;
    wanted.format = AUDIO_S16SYS;
    wanted.channels = 2;
    wanted.samples = 1024;
    wanted.callback = tone;
    if (SDL_OpenAudio(&wanted, NULL) != 0) {
        fprintf(stderr, "SDL_OpenAudio: %s\n", SDL_GetError());
        SDL_Quit();
        return 1;
    }
    printf("SDL audio driver: %s\n", SDL_AudioDriverName(NULL, 0));
    SDL_PauseAudio(0);
    SDL_Delay(2000);
    SDL_CloseAudio();
    SDL_Quit();
    return 0;
}
