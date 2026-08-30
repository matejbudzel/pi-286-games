/* Minimal Pi 1 SDL 1.2 fbcon presenter for the experimental remote backend. */
#include <SDL.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define W 320
#define H 240
#define FRAME (W * H * 2)
#define TILE 16
#define VIDEO_HEADER 16
#define VIDEO_PACKET_MAX (VIDEO_HEADER + FRAME)
#define POLL_HEADER 16
#define POLL_PACKET_MAX (POLL_HEADER + VIDEO_PACKET_MAX + 65536)
#define AUDIO_RING (22050 * 2 * 3)
static unsigned char audio_ring[AUDIO_RING];
static size_t audio_head, audio_count;
static unsigned int audio_underruns;

typedef struct {
    int video_fps_tenths, video_last_ms, video_capture_ms, video_fail;
    int audio_queued_ms, audio_underruns, audio_fail;
    int input_last_ms, input_fail, net_kbytes;
} Metrics;
static void audio_metrics(Metrics *metrics);

typedef struct {
    long long started_ms, video_request_total, server_capture_total, audio_queue_total, input_rtt_total;
    unsigned long payload_bytes;
    unsigned int video_frames, video_failures, audio_samples, audio_failures, input_events, input_failures;
    int video_request_min, video_request_max, server_capture_min, server_capture_max;
    int audio_queue_min, audio_queue_max, input_rtt_min, input_rtt_max;
} SessionStats;

typedef struct { char keys[64][20]; int count; unsigned int revision; } HeldState;

static long long now_ms(void) {
    struct timespec value;
    clock_gettime(CLOCK_MONOTONIC, &value);
    return (long long)value.tv_sec * 1000 + value.tv_nsec / 1000000;
}

static void range_add(int value, int *minimum, int *maximum, long long *total) {
    if (value < *minimum) *minimum = value;
    if (value > *maximum) *maximum = value;
    *total += value;
}

static void write_session_stats(const char *session, const SessionStats *stats, Metrics *metrics) {
    char cache[512], directory[512], last[576], history[576]; const char *home = getenv("HOME"); FILE *file;
    long long duration = now_ms() - stats->started_ms;
    audio_metrics(metrics);
    if (!home || !*home) home = "/tmp";
    snprintf(cache, sizeof(cache), "%s/.cache", home);
    mkdir(cache, 0700);
    snprintf(directory, sizeof(directory), "%s/.cache/pi286-stream", home);
    mkdir(directory, 0700);
    snprintf(last, sizeof(last), "%s/last-session-stats.txt", directory);
    if ((file = fopen(last, "w"))) {
        fprintf(file, "session=%s\nduration_ms=%lld\nvideo_frames=%u\nvideo_fps_x10=%lld\nvideo_request_ms_avg=%lld\nvideo_request_ms_min=%d\nvideo_request_ms_max=%d\nserver_capture_ms_avg=%lld\nserver_capture_ms_min=%d\nserver_capture_ms_max=%d\nvideo_failures=%u\naudio_queue_ms_avg=%lld\naudio_queue_ms_min=%d\naudio_queue_ms_max=%d\naudio_underruns=%d\naudio_failures=%u\ninput_events=%u\ninput_rtt_ms_avg=%lld\ninput_rtt_ms_min=%d\ninput_rtt_ms_max=%d\ninput_failures=%u\npayload_bytes=%lu\npayload_kbytes_per_second=%lld\n",
                session, duration, stats->video_frames, duration ? stats->video_frames * 10000 / duration : 0,
                stats->video_frames ? stats->video_request_total / stats->video_frames : 0, stats->video_frames ? stats->video_request_min : 0, stats->video_request_max,
                stats->video_frames ? stats->server_capture_total / stats->video_frames : 0, stats->video_frames ? stats->server_capture_min : 0, stats->server_capture_max,
                stats->video_failures, stats->audio_samples ? stats->audio_queue_total / stats->audio_samples : 0,
                stats->audio_samples ? stats->audio_queue_min : 0, stats->audio_queue_max, metrics->audio_underruns, stats->audio_failures,
                stats->input_events, stats->input_events ? stats->input_rtt_total / stats->input_events : 0,
                stats->input_events ? stats->input_rtt_min : 0, stats->input_rtt_max, stats->input_failures, stats->payload_bytes,
                duration ? stats->payload_bytes * 1000 / duration / 1024 : 0);
        fclose(file);
    }
    snprintf(history, sizeof(history), "%s/session-history.tsv", directory);
    if ((file = fopen(history, "a"))) {
        fprintf(file, "%lld\t%s\t%lld\t%u\t%lld\t%d\t%u\t%d\t%u\t%lu\n", (long long)time(NULL), session, duration,
                stats->video_frames, duration ? stats->video_frames * 10000 / duration : 0, metrics->audio_underruns,
                stats->video_failures, metrics->audio_fail, stats->input_failures, stats->payload_bytes);
        fclose(file);
    }
}

static void audio_callback(void *unused, Uint8 *stream, int length) {
    size_t take, index; (void)unused;
    memset(stream, 0, length);
    take = audio_count < (size_t)length ? audio_count : (size_t)length;
    if (take < (size_t)length) audio_underruns++;
    for (index = 0; index < take; index++) stream[index] = audio_ring[(audio_head + index) % AUDIO_RING];
    audio_head = (audio_head + take) % AUDIO_RING; audio_count -= take;
}

static void audio_metrics(Metrics *metrics) {
    SDL_LockAudio();
    metrics->audio_queued_ms = (int)(audio_count * 1000 / (22050 * 2));
    metrics->audio_underruns = (int)audio_underruns;
    SDL_UnlockAudio();
}

static unsigned int read_be16(const unsigned char *value) {
    return ((unsigned int)value[0] << 8) | value[1];
}

static unsigned int read_be32(const unsigned char *value) {
    return ((unsigned int)value[0] << 24) | ((unsigned int)value[1] << 16) |
           ((unsigned int)value[2] << 8) | value[3];
}

static int apply_video_packet(unsigned char *frame, const unsigned char *packet, size_t length) {
    unsigned int kind, count, tile, tile_x, tile_y; size_t offset, row;
    if (length < VIDEO_HEADER || memcmp(packet, "P2V1", 4)) return 0;
    kind = packet[4]; count = read_be16(packet + 6);
    if (kind == 1) {
        if (count || length != VIDEO_HEADER + FRAME) return 0;
        memcpy(frame, packet + VIDEO_HEADER, FRAME); return 1;
    }
    if (kind != 2 || count > (W / TILE) * (H / TILE) || length != VIDEO_HEADER + count * (2 + TILE * TILE * 2)) return 0;
    offset = VIDEO_HEADER;
    for (tile = 0; tile < count; tile++) {
        tile_x = packet[offset++]; tile_y = packet[offset++];
        if (tile_x >= W / TILE || tile_y >= H / TILE) return 0;
        for (row = 0; row < TILE; row++) {
            memcpy(frame + ((tile_y * TILE + row) * W + tile_x * TILE) * 2, packet + offset, TILE * 2);
            offset += TILE * 2;
        }
    }
    (void)read_be32(packet + 8);
    return 2;
}

static int apply_poll_packet(unsigned char *frame, const unsigned char *packet, size_t length, int *video_capture, int *video_seq, const unsigned char **audio, int *audio_length, int *next_audio) {
    unsigned int video_length, pcm_length;
    if (length < POLL_HEADER || memcmp(packet, "P2P1", 4)) return 0;
    video_length = read_be32(packet + 4); pcm_length = read_be32(packet + 8);
    if (video_length > VIDEO_PACKET_MAX || pcm_length > 65536 || length != POLL_HEADER + video_length + pcm_length) return 0;
    if (!apply_video_packet(frame, packet + POLL_HEADER, video_length)) return 0;
    *video_capture = (int)read_be32(packet + POLL_HEADER + 12);
    *video_seq = (int)read_be32(packet + POLL_HEADER + 8);
    *audio = packet + POLL_HEADER + video_length;
    *audio_length = (int)pcm_length;
    *next_audio = (int)read_be32(packet + 12);
    return 1;
}

static void held_update(HeldState *held, const char *key, int pressed) {
    int index;
    for (index = 0; index < held->count; index++) if (!strcmp(held->keys[index], key)) break;
    if (pressed && index == held->count && held->count < 64) { snprintf(held->keys[held->count++], sizeof(held->keys[0]), "%s", key); held->revision++; }
    if (!pressed && index < held->count) { memmove(held->keys[index], held->keys[index + 1], (size_t)(held->count - index - 1) * sizeof(held->keys[0])); held->count--; held->revision++; }
}

static int poll_body(char *body, size_t size, const HeldState *held, int video_seq, int audio_offset) {
    int used, index;
    used = snprintf(body, size, "{\"input_revision\":%u,\"video_seq\":%d,\"audio_offset\":%d,\"held_keys\":[", held->revision, video_seq, audio_offset);
    if (used < 0 || (size_t)used >= size) return -1;
    for (index = 0; index < held->count; index++) {
        int added = snprintf(body + used, size - (size_t)used, "%s\"%s\"", index ? "," : "", held->keys[index]);
        if (added < 0 || (size_t)added >= size - (size_t)used) return -1;
        used += added;
    }
    if ((size_t)used + 3 >= size) return -1;
    memcpy(body + used, "]}", 3); return used + 2;
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

static int request(const char *host, const char *port, const char *token, const char *method, const char *path, const char *body, unsigned char *out, size_t cap, int *next_offset, int *capture_ms) {
    char header[2048], incoming[4097]; int fd, n, used = 0, length = -1; char *split;
    size_t body_len = body ? strlen(body) : 0;
    fd = connect_to(host, port); if (fd < 0) return -1;
    n = snprintf(header, sizeof(header), "%s %s HTTP/1.1\r\nHost: %s\r\nAuthorization: Bearer %s\r\nConnection: close\r\nContent-Length: %zu\r\nContent-Type: application/json\r\n\r\n%s", method, path, host, token, body_len, body ? body : "");
    if (n < 0 || (size_t)n >= sizeof(header) || write(fd, header, n) != n) { close(fd); return -1; }
    if (next_offset) *next_offset = -1;
    if (capture_ms) *capture_ms = -1;
    while ((n = read(fd, incoming, sizeof(incoming) - 1)) > 0) {
        incoming[n] = 0;
        if (!used) {
            split = NULL;
            for (int i = 0; i + 3 < n; i++) if (!memcmp(incoming + i, "\r\n\r\n", 4)) { split = incoming + i + 4; break; }
            if (!split || memcmp(incoming, "HTTP/1.0 200", 12) && memcmp(incoming, "HTTP/1.1 200", 12)) { close(fd); return -1; }
            char *length_text = strstr(incoming, "Content-Length:");
            if (!length_text || sscanf(length_text, "Content-Length: %d", &length) != 1 || length < 0 || (size_t)length > cap) { close(fd); return -1; }
            if (next_offset) { char *next = strstr(incoming, "X-Pi286-Audio-Next-Offset:"); if (next) sscanf(next, "X-Pi286-Audio-Next-Offset: %d", next_offset); }
            if (capture_ms) { char *capture = strstr(incoming, "X-Pi286-Capture-Ms:"); if (capture) sscanf(capture, "X-Pi286-Capture-Ms: %d", capture_ms); }
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
    case SDLK_BACKSPACE: return "BACKSPACE"; case SDLK_TAB: return "TAB"; case SDLK_CAPSLOCK: return "CAPSLOCK";
    case SDLK_NUMLOCK: return "NUMLOCK"; case SDLK_SCROLLOCK: return "SCROLLLOCK"; case SDLK_PAUSE: return "PAUSE";
    case SDLK_PRINT: return "PRINT"; case SDLK_INSERT: return "INSERT"; case SDLK_DELETE: return "DELETE";
    case SDLK_HOME: return "HOME"; case SDLK_END: return "END"; case SDLK_PAGEUP: return "PAGEUP"; case SDLK_PAGEDOWN: return "PAGEDOWN";
    case SDLK_LCTRL: case SDLK_RCTRL: return "CTRL"; case SDLK_LALT: case SDLK_RALT: return "ALT"; case SDLK_LSHIFT: case SDLK_RSHIFT: return "SHIFT";
    case SDLK_F1: return "F1"; case SDLK_F2: return "F2"; case SDLK_F3: return "F3"; case SDLK_F4: return "F4"; case SDLK_F5: return "F5";
    case SDLK_F6: return "F6"; case SDLK_F7: return "F7"; case SDLK_F8: return "F8"; case SDLK_F9: return "F9"; case SDLK_F10: return "F10";
    case SDLK_F11: return "F11"; case SDLK_F12: return "F12";
    case SDLK_MINUS: return "MINUS"; case SDLK_EQUALS: return "EQUALS"; case SDLK_LEFTBRACKET: return "LEFTBRACKET"; case SDLK_RIGHTBRACKET: return "RIGHTBRACKET";
    case SDLK_BACKSLASH: return "BACKSLASH"; case SDLK_SEMICOLON: return "SEMICOLON"; case SDLK_QUOTE: return "QUOTE"; case SDLK_BACKQUOTE: return "BACKQUOTE";
    case SDLK_COMMA: return "COMMA"; case SDLK_PERIOD: return "PERIOD"; case SDLK_SLASH: return "SLASH";
    case SDLK_KP0: return "KP0"; case SDLK_KP1: return "KP1"; case SDLK_KP2: return "KP2"; case SDLK_KP3: return "KP3"; case SDLK_KP4: return "KP4";
    case SDLK_KP5: return "KP5"; case SDLK_KP6: return "KP6"; case SDLK_KP7: return "KP7"; case SDLK_KP8: return "KP8"; case SDLK_KP9: return "KP9";
    case SDLK_KP_PERIOD: return "KP_PERIOD"; case SDLK_KP_DIVIDE: return "KP_DIVIDE"; case SDLK_KP_MULTIPLY: return "KP_MULTIPLY";
    case SDLK_KP_MINUS: return "KP_MINUS"; case SDLK_KP_PLUS: return "KP_PLUS"; case SDLK_KP_ENTER: return "KP_ENTER"; case SDLK_KP_EQUALS: return "KP_EQUALS";
    default: break;
    }
    if ((key >= SDLK_a && key <= SDLK_z) || (key >= SDLK_0 && key <= SDLK_9)) { letter[0] = (char)key; letter[1] = 0; return letter; }
}

static void parse_pad_map(char *map, const char **keys) {
    int index = 0; char *part = map;
    while (index < 9) { char *comma = strchr(part, ','); if (comma) *comma = 0; keys[index++] = *part ? part : NULL; if (!comma) break; part = comma + 1; }
}

static SDL_Surface *create_canvas(SDL_Surface *screen) {
    return SDL_CreateRGBSurface(SDL_SWSURFACE, screen->w, screen->h, 16,
                                screen->format->Rmask, screen->format->Gmask,
                                screen->format->Bmask, 0);
}

static const unsigned char *glyph(char value) {
    static const unsigned char digits[10][7] = {
        {14,17,19,21,25,17,14}, {4,12,4,4,4,4,14}, {14,17,1,2,4,8,31},
        {30,1,1,14,1,1,30}, {2,6,10,18,31,2,2}, {31,16,16,30,1,1,30},
        {14,16,16,30,17,17,14}, {31,1,2,4,8,8,8}, {14,17,17,14,17,17,14},
        {14,17,17,15,1,1,14}
    };
    static const unsigned char a[7] = {14,17,17,31,17,17,17};
    static const unsigned char e[7] = {31,16,16,30,16,16,31};
    static const unsigned char i[7] = {14,4,4,4,4,4,14};
    static const unsigned char k[7] = {17,18,20,24,20,18,17};
    static const unsigned char n[7] = {17,25,21,19,17,17,17};
    static const unsigned char u[7] = {17,17,17,17,17,17,14};
    static const unsigned char v[7] = {17,17,17,17,17,10,4};
    static const unsigned char colon[7] = {0,4,0,0,0,4,0};
    static const unsigned char dot[7] = {0,0,0,0,0,6,6};
    static const unsigned char slash[7] = {1,2,4,8,16,0,0};
    static const unsigned char dash[7] = {0,0,0,31,0,0,0};
    static const unsigned char blank[7] = {0,0,0,0,0,0,0};
    if (value >= '0' && value <= '9') return digits[value - '0'];
    switch (value) { case 'A': return a; case 'E': return e; case 'I': return i;
    case 'K': return k; case 'N': return n; case 'U': return u; case 'V': return v;
    case ':': return colon; case '.': return dot; case '/': return slash; case '-': return dash;
    default: return blank; }
}

static void draw_text(SDL_Surface *canvas, int left, int top, const char *text) {
    int character, row, column, dx, dy; const unsigned char *shape;
    unsigned short *line;
    for (character = 0; text[character]; character++) {
        shape = glyph(text[character]);
        for (row = 0; row < 7; row++) for (column = 0; column < 5; column++) if (shape[row] & (1 << (4 - column))) {
            for (dy = 0; dy < 2; dy++) {
                line = (unsigned short *)((unsigned char *)canvas->pixels + (top + row * 2 + dy) * canvas->pitch);
                for (dx = 0; dx < 2; dx++) line[left + character * 12 + column * 2 + dx] = 0x07e0;
            }
        }
    }
}

static void draw_overlay(SDL_Surface *canvas, const Metrics *metrics) {
    int row; unsigned short *line; char text[48];
    for (row = 0; row < 52; row++) {
        line = (unsigned short *)((unsigned char *)canvas->pixels + row * canvas->pitch);
        memset(line, 0, 324 * sizeof(*line));
    }
    snprintf(text, sizeof(text), "V:%d.%d %d/%d E%d", metrics->video_fps_tenths / 10,
             metrics->video_fps_tenths % 10, metrics->video_last_ms, metrics->video_capture_ms, metrics->video_fail);
    draw_text(canvas, 4, 2, text);
    snprintf(text, sizeof(text), "A:%d U%d E%d", metrics->audio_queued_ms, metrics->audio_underruns, metrics->audio_fail);
    draw_text(canvas, 4, 19, text);
    snprintf(text, sizeof(text), "I:%d E%d N:%dK", metrics->input_last_ms, metrics->input_fail, metrics->net_kbytes);
    draw_text(canvas, 4, 36, text);
}

static void render(SDL_Surface *screen, SDL_Surface *canvas, const unsigned char *frame, int overlay, const Metrics *metrics) {
    int x, y;
    SDL_LockSurface(canvas);
    memset(canvas->pixels, 0, canvas->pitch * canvas->h);
    for (y = 0; y < H; y++) for (x = 0; x < W; x++) {
        unsigned short pixel = frame[(y * W + x) * 2] | (frame[(y * W + x) * 2 + 1] << 8);
        unsigned short *row0 = (unsigned short *)((unsigned char *)canvas->pixels + (y * 2) * canvas->pitch);
        unsigned short *row1 = (unsigned short *)((unsigned char *)canvas->pixels + (y * 2 + 1) * canvas->pitch);
        row0[x * 2] = row0[x * 2 + 1] = row1[x * 2] = row1[x * 2 + 1] = pixel;
    }
    if (overlay) draw_overlay(canvas, metrics);
    SDL_UnlockSurface(canvas);
    SDL_BlitSurface(canvas, NULL, screen, NULL); SDL_Flip(screen);
}

static int local_pattern(void) {
    static unsigned char frame[FRAME];
    static const unsigned short colors[] = { 0xf800, 0x07e0, 0x001f, 0xffff, 0xffe0, 0xf81f };
    SDL_Surface *screen, *canvas; SDL_Event event; int x, y;
    if (SDL_Init(SDL_INIT_VIDEO) < 0) { fprintf(stderr, "SDL_Init failed: %s\n", SDL_GetError()); return 1; }
    if (!(screen = SDL_SetVideoMode(640, 480, 16, SDL_FULLSCREEN))) { fprintf(stderr, "SDL_SetVideoMode failed: %s\n", SDL_GetError()); SDL_Quit(); return 1; }
    if (!(canvas = create_canvas(screen))) { fprintf(stderr, "SDL_CreateRGBSurface failed: %s\n", SDL_GetError()); SDL_Quit(); return 1; }
    for (y = 0; y < H; y++) for (x = 0; x < W; x++) {
        unsigned short color = colors[((x / 40) + (y / 25)) % (sizeof(colors) / sizeof(colors[0]))];
        size_t offset = (size_t)(y * W + x) * 2;
        frame[offset] = color & 0xff; frame[offset + 1] = color >> 8;
    }
    render(screen, canvas, frame, 0, NULL);
    fprintf(stderr, "presenter: local RGB565 pattern ready; press F1 or ESC\n"); fflush(stderr);
    for (;;) {
        while (SDL_PollEvent(&event)) if (event.type == SDL_QUIT ||
            (event.type == SDL_KEYDOWN && (event.key.keysym.sym == SDLK_F1 || event.key.keysym.sym == SDLK_ESCAPE))) {
            SDL_FreeSurface(canvas); SDL_Quit(); return 0;
        }
        SDL_Delay(20);
    }
}

int main(int argc, char **argv) {
    const char *host, *port, *token_path, *session, *pad_keys[9] = {0}; FILE *file; char token[256], path[256], body[2048], pad_map[256]; SDL_Joystick *joystick = NULL;
    unsigned char frame[FRAME], packet[POLL_PACKET_MAX]; SDL_Surface *screen, *canvas; SDL_Event event; SDL_AudioSpec audio, obtained; Metrics metrics = {0}; SessionStats stats = {0}; HeldState held = {0}; int audio_offset = 0, next_offset, n, overlay = 0, video_count = 0, video_seq = 0, audio_length;
    const unsigned char *audio_data; unsigned int poll_revision, input_acked = 0;
    long long video_window = now_ms(), network_window = video_window; long long request_started, elapsed; size_t network_bytes = 0;
    fprintf(stderr, "presenter: starting\n"); fflush(stderr);
    if (argc == 2 && !strcmp(argv[1], "--local-pattern")) return local_pattern();
    if (argc != 6) { fprintf(stderr, "usage: %s HOST PORT TOKEN_FILE SESSION PAD_MAP\n", argv[0]); return 2; }
    host = argv[1]; port = argv[2]; token_path = argv[3]; session = argv[4];
    snprintf(pad_map, sizeof(pad_map), "%s", argv[5]); parse_pad_map(pad_map, pad_keys);
    if (!(file = fopen(token_path, "r")) || !fgets(token, sizeof(token), file)) { fprintf(stderr, "cannot read token file %s\n", token_path); return 2; }
    fclose(file); token[strcspn(token, "\r\n")] = 0;
    fprintf(stderr, "presenter: token read; initializing SDL\n"); fflush(stderr);
    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_AUDIO | SDL_INIT_JOYSTICK) < 0) { fprintf(stderr, "SDL_Init failed: %s\n", SDL_GetError()); return 1; }
    fprintf(stderr, "presenter: SDL initialized; opening framebuffer\n"); fflush(stderr);
    if (!(screen = SDL_SetVideoMode(640, 480, 16, SDL_FULLSCREEN))) { fprintf(stderr, "SDL_SetVideoMode failed: %s\n", SDL_GetError()); SDL_Quit(); return 1; }
    if (!(canvas = create_canvas(screen))) { fprintf(stderr, "SDL_CreateRGBSurface failed: %s\n", SDL_GetError()); SDL_Quit(); return 1; }
    fprintf(stderr, "presenter: surface %dx%d pitch=%d logical-pitch=%d bpp=%d bytes=%d masks=%08x/%08x/%08x\n",
            screen->w, screen->h, screen->pitch,
            screen->w * screen->format->BytesPerPixel, screen->format->BitsPerPixel,
            screen->format->BytesPerPixel, screen->format->Rmask,
            screen->format->Gmask, screen->format->Bmask); fflush(stderr);
    if (SDL_NumJoysticks() > 0) joystick = SDL_JoystickOpen(0);
    memset(&audio, 0, sizeof(audio)); audio.freq = 22050; audio.format = AUDIO_S16LSB; audio.channels = 1; audio.samples = 512; audio.callback = audio_callback;
    if (SDL_OpenAudio(&audio, &obtained) < 0) { fprintf(stderr, "SDL_OpenAudio failed: %s\n", SDL_GetError()); SDL_Quit(); return 1; }
    fprintf(stderr, "presenter: audio %d Hz format=%#x channels=%u samples=%u\n", obtained.freq, obtained.format, obtained.channels, obtained.samples); fflush(stderr);
    if (obtained.freq != 22050 || obtained.format != AUDIO_S16LSB || obtained.channels != 1) {
        fprintf(stderr, "presenter: unsupported negotiated audio format\n"); SDL_CloseAudio(); SDL_FreeSurface(canvas); SDL_Quit(); return 1;
    }
    fprintf(stderr, "presenter: ready\n"); fflush(stderr);
    SDL_PauseAudio(0);
    stats.started_ms = now_ms();
    stats.video_request_min = stats.server_capture_min = stats.audio_queue_min = stats.input_rtt_min = 1000000;
    for (;;) {
        snprintf(path, sizeof(path), "/v2/sessions/%s/poll", session);
        if (poll_body(body, sizeof(body), &held, video_seq, audio_offset) < 0) { fprintf(stderr, "presenter: poll body too large\n"); break; }
        poll_revision = held.revision;
        request_started = now_ms();
        n = request(host, port, token, "POST", path, body, packet, sizeof(packet), NULL, NULL);
        metrics.video_last_ms = (int)(now_ms() - request_started);
        if (n > 0 && apply_poll_packet(frame, packet, (size_t)n, &metrics.video_capture_ms, &video_seq, &audio_data, &audio_length, &next_offset)) {
            network_bytes += (size_t)n; video_count++; stats.video_frames++; stats.payload_bytes += (unsigned long)n;
            range_add(metrics.video_last_ms, &stats.video_request_min, &stats.video_request_max, &stats.video_request_total);
            if (metrics.video_capture_ms >= 0) range_add(metrics.video_capture_ms, &stats.server_capture_min, &stats.server_capture_max, &stats.server_capture_total);
            elapsed = now_ms() - video_window;
            if (elapsed >= 1000) { metrics.video_fps_tenths = (int)(video_count * 10000 / elapsed); video_count = 0; video_window = now_ms(); }
            audio_metrics(&metrics);
            render(screen, canvas, frame, overlay, &metrics);
            if (audio_length > 0 && next_offset >= audio_offset) { audio_put(audio_data, (size_t)audio_length); audio_offset = next_offset; }
            if (poll_revision > input_acked) { metrics.input_last_ms = metrics.video_last_ms; input_acked = poll_revision; range_add(metrics.input_last_ms, &stats.input_rtt_min, &stats.input_rtt_max, &stats.input_rtt_total); }
        } else { video_seq = 0; metrics.video_fail++; stats.video_failures++; metrics.audio_fail++; stats.audio_failures++; }
        audio_metrics(&metrics);
        stats.audio_samples++;
        range_add(metrics.audio_queued_ms, &stats.audio_queue_min, &stats.audio_queue_max, &stats.audio_queue_total);
        elapsed = now_ms() - network_window;
        if (elapsed >= 1000) { metrics.net_kbytes = (int)(network_bytes * 1000 / elapsed / 1024); network_bytes = 0; network_window = now_ms(); }
        while (SDL_PollEvent(&event)) {
            const char *key = NULL; int pressed = 0;
            if (event.type == SDL_QUIT || (event.type == SDL_KEYDOWN && event.key.keysym.sym == SDLK_F1)) { write_session_stats(session, &stats, &metrics); SDL_CloseAudio(); SDL_FreeSurface(canvas); SDL_Quit(); return 0; }
            if ((event.type == SDL_KEYDOWN || event.type == SDL_KEYUP) && event.key.keysym.sym == SDLK_F8) { if (event.type == SDL_KEYDOWN) overlay = !overlay; continue; }
            if ((event.type == SDL_KEYDOWN || event.type == SDL_KEYUP) && (key = dos_key(event.key.keysym.sym))) pressed = event.type == SDL_KEYDOWN;
            if ((event.type == SDL_JOYBUTTONDOWN || event.type == SDL_JOYBUTTONUP) && event.jbutton.button < 9) { key = pad_keys[event.jbutton.button]; pressed = event.type == SDL_JOYBUTTONDOWN; }
            if ((event.type == SDL_JOYBUTTONDOWN && event.jbutton.button == 9)) { if (joystick) SDL_JoystickClose(joystick); write_session_stats(session, &stats, &metrics); SDL_CloseAudio(); SDL_FreeSurface(canvas); SDL_Quit(); return 0; }
            if (key) {
                held_update(&held, key, pressed);
                stats.input_events++;
            }
        }
        SDL_Delay(30);
    }
}
