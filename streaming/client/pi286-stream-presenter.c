/* Minimal Pi 1 SDL 1.2 fbcon presenter for the experimental remote backend. */
#include <SDL.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#define W 320
#define H 200
#define FRAME (W * H * 2)

static int connect_to(const char *host, const char *port) {
    struct addrinfo hints = {0}, *info, *p; int fd = -1;
    hints.ai_socktype = SOCK_STREAM; hints.ai_family = AF_UNSPEC;
    if (getaddrinfo(host, port, &hints, &info)) return -1;
    for (p = info; p; p = p->ai_next) {
        fd = socket(p->ai_family, p->ai_socktype, p->ai_protocol);
        if (fd >= 0 && !connect(fd, p->ai_addr, p->ai_addrlen)) break;
        if (fd >= 0) close(fd); fd = -1;
    }
    freeaddrinfo(info); return fd;
}

static int request(const char *host, const char *port, const char *token, const char *method, const char *path, const char *body, unsigned char *out, size_t cap) {
    char header[2048], incoming[4096]; int fd, n, used = 0, length = -1; char *split;
    size_t body_len = body ? strlen(body) : 0;
    fd = connect_to(host, port); if (fd < 0) return -1;
    n = snprintf(header, sizeof(header), "%s %s HTTP/1.1\r\nHost: %s\r\nAuthorization: Bearer %s\r\nConnection: close\r\nContent-Length: %zu\r\nContent-Type: application/json\r\n\r\n%s", method, path, host, token, body_len, body ? body : "");
    if (n < 0 || (size_t)n >= sizeof(header) || write(fd, header, n) != n) { close(fd); return -1; }
    while ((n = read(fd, incoming, sizeof(incoming))) > 0) {
        if (!used) {
            split = NULL;
            for (int i = 0; i + 3 < n; i++) if (!memcmp(incoming + i, "\r\n\r\n", 4)) { split = incoming + i + 4; break; }
            if (!split || memcmp(incoming, "HTTP/1.0 200", 12) && memcmp(incoming, "HTTP/1.1 200", 12)) { close(fd); return -1; }
            char *length_text = strstr(incoming, "Content-Length:");
            if (!length_text || sscanf(length_text, "Content-Length: %d", &length) != 1 || length < 0 || (size_t)length > cap) { close(fd); return -1; }
            used = (int)(incoming + n - split);
            memcpy(out, split, used);
        } else { if ((size_t)(used + n) > cap) { close(fd); return -1; } memcpy(out + used, incoming, n); used += n; }
    }
    close(fd); return used == length ? used : -1;
}

static const char *dos_key(SDLKey key) {
    switch (key) {
    case SDLK_UP: return "UP"; case SDLK_DOWN: return "DOWN"; case SDLK_LEFT: return "LEFT"; case SDLK_RIGHT: return "RIGHT";
    case SDLK_RETURN: return "ENTER"; case SDLK_ESCAPE: return "ESC"; case SDLK_SPACE: return "SPACE";
    case SDLK_LCTRL: case SDLK_RCTRL: return "CTRL"; case SDLK_LALT: case SDLK_RALT: return "ALT"; case SDLK_LSHIFT: case SDLK_RSHIFT: return "SHIFT";
    default: return NULL;
    }
}

static void render(SDL_Surface *screen, const unsigned char *frame) {
    int x, y; SDL_LockSurface(screen);
    memset(screen->pixels, 0, screen->pitch * screen->h);
    for (y = 0; y < H; y++) for (x = 0; x < W; x++) {
        unsigned short pixel = frame[(y * W + x) * 2] | (frame[(y * W + x) * 2 + 1] << 8);
        unsigned short *row0 = (unsigned short *)((unsigned char *)screen->pixels + (y * 2 + 40) * screen->pitch);
        unsigned short *row1 = (unsigned short *)((unsigned char *)screen->pixels + (y * 2 + 41) * screen->pitch);
        row0[x * 2] = row0[x * 2 + 1] = row1[x * 2] = row1[x * 2 + 1] = pixel;
    }
    SDL_UnlockSurface(screen); SDL_Flip(screen);
}

int main(int argc, char **argv) {
    const char *host, *port, *token_path, *session; FILE *file; char token[256], path[256], body[128];
    unsigned char frame[FRAME]; SDL_Surface *screen; SDL_Event event;
    if (argc != 5) { fprintf(stderr, "usage: %s HOST PORT TOKEN_FILE SESSION\n", argv[0]); return 2; }
    host = argv[1]; port = argv[2]; token_path = argv[3]; session = argv[4];
    if (!(file = fopen(token_path, "r")) || !fgets(token, sizeof(token), file)) return 2;
    fclose(file); token[strcspn(token, "\r\n")] = 0;
    if (SDL_Init(SDL_INIT_VIDEO) < 0 || !(screen = SDL_SetVideoMode(640, 480, 16, SDL_FULLSCREEN))) return 1;
    for (;;) {
        snprintf(path, sizeof(path), "/v1/sessions/%s/video", session);
        if (request(host, port, token, "GET", path, NULL, frame, sizeof(frame)) == FRAME) render(screen, frame);
        while (SDL_PollEvent(&event)) {
            const char *key;
            if (event.type == SDL_QUIT || (event.type == SDL_KEYDOWN && event.key.keysym.sym == SDLK_F1)) { SDL_Quit(); return 0; }
            if ((event.type == SDL_KEYDOWN || event.type == SDL_KEYUP) && (key = dos_key(event.key.keysym.sym))) {
                snprintf(path, sizeof(path), "/v1/sessions/%s/input", session);
                snprintf(body, sizeof(body), "{\"events\":[{\"key\":\"%s\",\"pressed\":%s}]}", key, event.type == SDL_KEYDOWN ? "true" : "false");
                request(host, port, token, "POST", path, body, frame, sizeof(frame));
            }
        }
        SDL_Delay(30);
    }
}
