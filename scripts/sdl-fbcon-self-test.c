#include <SDL.h>
#include <stdio.h>
#include <unistd.h>

static void rectangle(SDL_Surface *screen, int x, int y, int w, int h, Uint32 color) {
    SDL_Rect rect = { x, y, w, h };
    SDL_FillRect(screen, &rect, color);
}

int main(void) {
    SDL_Surface *screen;
    if (SDL_Init(SDL_INIT_VIDEO) != 0) { fprintf(stderr, "SDL_Init: %s\n", SDL_GetError()); return 1; }
    screen = SDL_SetVideoMode(640, 480, 16, SDL_FULLSCREEN | SDL_HWSURFACE);
    if (!screen) { fprintf(stderr, "SDL_SetVideoMode: %s\n", SDL_GetError()); SDL_Quit(); return 1; }
    SDL_FillRect(screen, NULL, SDL_MapRGB(screen->format, 0, 70, 200));
    rectangle(screen, 0, 0, 640, 8, SDL_MapRGB(screen->format, 255, 255, 255));
    rectangle(screen, 0, 472, 640, 8, SDL_MapRGB(screen->format, 255, 255, 255));
    rectangle(screen, 0, 0, 8, 480, SDL_MapRGB(screen->format, 255, 255, 255));
    rectangle(screen, 632, 0, 8, 480, SDL_MapRGB(screen->format, 255, 255, 255));
    rectangle(screen, 316, 8, 8, 464, SDL_MapRGB(screen->format, 255, 220, 0));
    SDL_Flip(screen); sleep(3); SDL_Quit(); return 0;
}
