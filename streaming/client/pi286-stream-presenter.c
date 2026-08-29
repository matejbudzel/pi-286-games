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
#define AUDIO_RING (22050 * 2 * 3)
static unsigned char audio_ring[AUDIO_RING];
static size_t audio_head, audio_count;

static void audio_callback(void *unused, Uint8 *stream, int length) {
    size_t take, index; (void)unused;
    memset(stream, 0, length);
    take = audio_count < (size_t)length ? audio_count : (size_t)length;
    for (index = 0; index < take; index++) stream[index] = audio_ring[(audio_head + index) % AUDIO_RING];
    audio_head = (audio_head + take) % AUDIO_RING; audio_count -= take;
}

static void audio_put(const unsigned char *data, size_t length) {
    size_t index;
    SDL_LockAudio();
    for (index = 0; index < length; index++) {
        if (audio_count == AUDIO_RING) { audio_head = (audio_head + 1) % AUDIO_RING; audio_count--; }
        audio_ring[(audio_head + audio_count) % AUDIO_RING] = data[index]; audio_count++;
    }
    SDL_UnlockAudio();
}

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

static int request(const char *host, const char *port, const char *token, const char *method, const char *path, const char *body, unsigned char *out, size_t cap, int *next_offset) {
    char header[2048], incoming[4097]; int fd, n, used = 0, length = -1; char *split;
    size_t body_len = body ? strlen(body) : 0;
    fd = connect_to(host, port); if (fd < 0) return -1;
    n = snprintf(header, sizeof(header), "%s %s HTTP/1.1\r\nHost: %s\r\nAuthorization: Bearer %s\r\nConnection: close\r\nContent-Length: %zu\r\nContent-Type: application/json\r\n\r\n%s", method, path, host, token, body_len, body ? body : "");
    if (n < 0 || (size_t)n >= sizeof(header) || write(fd, header, n) != n) { close(fd); return -1; }
    if (next_offset) *next_offset = -1;
    while ((n = read(fd, incoming, sizeof(incoming) - 1)) > 0) {
        incoming[n] = 0;
        if (!used) {
            split = NULL;
            for (int i = 0; i + 3 < n; i++) if (!memcmp(incoming + i, "\r\n\r\n", 4)) { split = incoming + i + 4; break; }
            if (!split || memcmp(incoming, "HTTP/1.0 200", 12) && memcmp(incoming, "HTTP/1.1 200", 12)) { close(fd); return -1; }
            char *length_text = strstr(incoming, "Content-Length:");
            if (!length_text || sscanf(length_text, "Content-Length: %d", &length) != 1 || length < 0 || (size_t)length > cap) { close(fd); return -1; }
            if (next_offset) { char *next = strstr(incoming, "X-Pi286-Audio-Next-Offset:"); if (next) sscanf(next, "X-Pi286-Audio-Next-Offset: %d", next_offset); }
            used = (int)(incoming + n - split);
            memcpy(out, split, used);
        } else { if ((size_t)(used + n) > cap) { close(fd); return -1; } memcpy(out + used, incoming, n); used += n; }
    }
    close(fd); return used == length ? used : -1;
}

static const char *dos_key(SDLKey key) {
    static char letter[2];
    switch (key) {
    case SDLK_UP: return "UP"; case SDLK_DOWN: return "DOWN"; case SDLK_LEFT: return "LEFT"; case SDLK_RIGHT: return "RIGHT";
    case SDLK_RETURN: return "ENTER"; case SDLK_ESCAPE: return "ESC"; case SDLK_SPACE: return "SPACE";
    case SDLK_LCTRL: case SDLK_RCTRL: return "CTRL"; case SDLK_LALT: case SDLK_RALT: return "ALT"; case SDLK_LSHIFT: case SDLK_RSHIFT: return "SHIFT";
    case SDLK_F1: return "F1"; case SDLK_F2: return "F2"; case SDLK_F3: return "F3"; case SDLK_F4: return "F4"; case SDLK_F5: return "F5";
    case SDLK_F6: return "F6"; case SDLK_F7: return "F7"; case SDLK_F8: return "F8"; case SDLK_F9: return "F9"; case SDLK_F10: return "F10";
    default: break;
    }
    if ((key >= SDLK_a && key <= SDLK_z) || (key >= SDLK_0 && key <= SDLK_9)) { letter[0] = (char)key; letter[1] = 0; return letter; }
}

static void parse_pad_map(char *map, const char **keys) {
    int index = 0; char *part = map;
    while (index < 9) { char *comma = strchr(part, ','); if (comma) *comma = 0; keys[index++] = *part ? part : NULL; if (!comma) break; part = comma + 1; }
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
    const char *host, *port, *token_path, *session, *pad_keys[9] = {0}; FILE *file; char token[256], path[256], body[128], pad_map[256]; SDL_Joystick *joystick = NULL;
    unsigned char frame[FRAME], pcm[65536]; SDL_Surface *screen; SDL_Event event; SDL_AudioSpec audio; int audio_offset = 0, next_offset, n;
    fprintf(stderr, "presenter: starting\n"); fflush(stderr);
    if (argc != 6) { fprintf(stderr, "usage: %s HOST PORT TOKEN_FILE SESSION PAD_MAP\n", argv[0]); return 2; }
    host = argv[1]; port = argv[2]; token_path = argv[3]; session = argv[4];
    snprintf(pad_map, sizeof(pad_map), "%s", argv[5]); parse_pad_map(pad_map, pad_keys);
    if (!(file = fopen(token_path, "r")) || !fgets(token, sizeof(token), file)) { fprintf(stderr, "cannot read token file %s\n", token_path); return 2; }
    fclose(file); token[strcspn(token, "\r\n")] = 0;
    fprintf(stderr, "presenter: token read; initializing SDL\n"); fflush(stderr);
    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_AUDIO | SDL_INIT_JOYSTICK) < 0) { fprintf(stderr, "SDL_Init failed: %s\n", SDL_GetError()); return 1; }
    fprintf(stderr, "presenter: SDL initialized; opening framebuffer\n"); fflush(stderr);
    if (!(screen = SDL_SetVideoMode(640, 480, 16, SDL_FULLSCREEN))) { fprintf(stderr, "SDL_SetVideoMode failed: %s\n", SDL_GetError()); SDL_Quit(); return 1; }
    if (SDL_NumJoysticks() > 0) joystick = SDL_JoystickOpen(0);
    memset(&audio, 0, sizeof(audio)); audio.freq = 22050; audio.format = AUDIO_S16LSB; audio.channels = 1; audio.samples = 512; audio.callback = audio_callback;
    if (SDL_OpenAudio(&audio, NULL) < 0) { fprintf(stderr, "SDL_OpenAudio failed: %s\n", SDL_GetError()); SDL_Quit(); return 1; }
    fprintf(stderr, "presenter: ready\n"); fflush(stderr);
    SDL_PauseAudio(0);
    for (;;) {
        snprintf(path, sizeof(path), "/v1/sessions/%s/video", session);
        if (request(host, port, token, "GET", path, NULL, frame, sizeof(frame), NULL) == FRAME) render(screen, frame);
        snprintf(path, sizeof(path), "/v1/sessions/%s/audio?offset=%d", session, audio_offset);
        n = request(host, port, token, "GET", path, NULL, pcm, sizeof(pcm), &next_offset);
        if (n > 0 && next_offset >= audio_offset) { audio_put(pcm, n); audio_offset = next_offset; }
        while (SDL_PollEvent(&event)) {
            const char *key = NULL; int pressed = 0;
            if (event.type == SDL_QUIT || (event.type == SDL_KEYDOWN && event.key.keysym.sym == SDLK_F1)) { SDL_Quit(); return 0; }
            if ((event.type == SDL_KEYDOWN || event.type == SDL_KEYUP) && (key = dos_key(event.key.keysym.sym))) pressed = event.type == SDL_KEYDOWN;
            if ((event.type == SDL_JOYBUTTONDOWN || event.type == SDL_JOYBUTTONUP) && event.jbutton.button < 9) { key = pad_keys[event.jbutton.button]; pressed = event.type == SDL_JOYBUTTONDOWN; }
            if ((event.type == SDL_JOYBUTTONDOWN && event.jbutton.button == 9)) { if (joystick) SDL_JoystickClose(joystick); SDL_Quit(); return 0; }
            if (key) {
                snprintf(path, sizeof(path), "/v1/sessions/%s/input", session);
                snprintf(body, sizeof(body), "{\"events\":[{\"key\":\"%s\",\"pressed\":%s}]}", key, pressed ? "true" : "false");
                request(host, port, token, "POST", path, body, frame, sizeof(frame), NULL);
            }
        }
        SDL_Delay(30);
    }
}
