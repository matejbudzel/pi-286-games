#include <SDL.h>
#include <stdio.h>
#include <unistd.h>
int main(void) {
    SDL_Surface *screen;
    if (SDL_Init(SDL_INIT_VIDEO) != 0) { fprintf(stderr, "SDL_Init: %s\n", SDL_GetError()); return 1; }
    screen = SDL_SetVideoMode(640, 480, 16, SDL_FULLSCREEN | SDL_HWSURFACE);
    if (!screen) { fprintf(stderr, "SDL_SetVideoMode: %s\n", SDL_GetError()); SDL_Quit(); return 1; }
    SDL_FillRect(screen, NULL, SDL_MapRGB(screen->format, 0, 100, 255));
    SDL_Flip(screen); sleep(3); SDL_Quit(); return 0;
}
