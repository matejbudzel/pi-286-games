/* Minimal Pi 1 SDL 1.2 fbcon presenter for the remote DOS backend. */
#include <SDL.h>
#include <libwebsockets.h>
#include "presenter.h"
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netdb.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <sys/socket.h>
#include <sys/select.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

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
    unsigned int video_frames, video_failures, audio_samples, audio_failures, input_events, input_acks, input_failures;
    unsigned int polls_started, polls_completed, polls_cancelled, polls_stale, polls_failed;
    int video_request_min, video_request_max, server_capture_min, server_capture_max;
    int audio_queue_min, audio_queue_max, input_rtt_min, input_rtt_max;
} SessionStats;

typedef struct { HeldState *held; int *overlay, *quit; SessionStats *stats; } EventState;
static EventState event_state;
static const char *dos_key(SDLKey key);
static int pump_events(void);

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
        fprintf(file, "session=%s\nduration_ms=%lld\npolls_started=%u\npolls_completed=%u\npolls_cancelled=%u\npolls_stale=%u\npolls_failed=%u\nvideo_frames=%u\nvideo_fps_x10=%lld\nvideo_request_ms_avg=%lld\nvideo_request_ms_min=%d\nvideo_request_ms_max=%d\nserver_capture_ms_avg=%lld\nserver_capture_ms_min=%d\nserver_capture_ms_max=%d\nvideo_failures=%u\naudio_queue_ms_avg=%lld\naudio_queue_ms_min=%d\naudio_queue_ms_max=%d\naudio_underruns=%d\naudio_failures=%u\ninput_events=%u\ninput_acks=%u\ninput_rtt_ms_avg=%lld\ninput_rtt_ms_min=%d\ninput_rtt_ms_max=%d\ninput_failures=%u\npayload_bytes=%lu\npayload_kbytes_per_second=%lld\n",
                session, duration, stats->polls_started, stats->polls_completed, stats->polls_cancelled, stats->polls_stale, stats->polls_failed,
                stats->video_frames, duration ? stats->video_frames * 10000 / duration : 0,
                stats->video_frames ? stats->video_request_total / stats->video_frames : 0, stats->video_frames ? stats->video_request_min : 0, stats->video_request_max,
                stats->video_frames ? stats->server_capture_total / stats->video_frames : 0, stats->video_frames ? stats->server_capture_min : 0, stats->server_capture_max,
                stats->video_failures, stats->audio_samples ? stats->audio_queue_total / stats->audio_samples : 0,
                stats->audio_samples ? stats->audio_queue_min : 0, stats->audio_queue_max, metrics->audio_underruns, stats->audio_failures,
                stats->input_events, stats->input_acks, stats->input_acks ? stats->input_rtt_total / stats->input_acks : 0,
                stats->input_acks ? stats->input_rtt_min : 0, stats->input_rtt_max, stats->input_failures, stats->payload_bytes,
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

static int request(const char *host, const char *port, const char *token, const char *method, const char *path, const char *body, unsigned char *out, size_t cap, int *next_offset, int *capture_ms, unsigned int revision) {
    char request_header[2048], response_header[4097], incoming[4097]; int fd, n, used = 0, length = -1, header_used = 0, headers_done = 0; char *split;
    size_t body_len = body ? strlen(body) : 0;
    fd = connect_to(host, port); if (fd < 0) return -1;
    n = snprintf(request_header, sizeof(request_header), "%s %s HTTP/1.1\r\nHost: %s\r\nAuthorization: Bearer %s\r\nConnection: close\r\nContent-Length: %zu\r\nContent-Type: application/json\r\n\r\n%s", method, path, host, token, body_len, body ? body : "");
    if (n < 0 || (size_t)n >= sizeof(request_header) || write(fd, request_header, n) != n) { close(fd); return -1; }
    if (next_offset) *next_offset = -1;
    if (capture_ms) *capture_ms = -1;
    for (;;) {
        fd_set readable; struct timeval timeout; int selected;
        FD_ZERO(&readable); FD_SET(fd, &readable); timeout.tv_sec = 0; timeout.tv_usec = 5000;
        selected = select(fd + 1, &readable, NULL, NULL, &timeout);
        if (!selected) { if (pump_events() || event_state.held->revision != revision) { close(fd); return -2; } continue; }
        if (selected < 0 || (n = read(fd, incoming, sizeof(incoming) - 1)) <= 0) break;
        if (!headers_done) {
            if (header_used + n >= (int)sizeof(response_header)) { close(fd); return -1; }
            memcpy(response_header + header_used, incoming, n); header_used += n; response_header[header_used] = 0;
            split = strstr(response_header, "\r\n\r\n");
            if (!split) continue;
            split += 4;
            if (!memcmp(response_header, "HTTP/1.0 204", 12) || !memcmp(response_header, "HTTP/1.1 204", 12)) { close(fd); return -3; }
            if (memcmp(response_header, "HTTP/1.0 200", 12) && memcmp(response_header, "HTTP/1.1 200", 12)) { close(fd); return -1; }
            char *length_text = strstr(response_header, "Content-Length:");
            if (!length_text || sscanf(length_text, "Content-Length: %d", &length) != 1 || length < 0 || (size_t)length > cap) { close(fd); return -1; }
            if (next_offset) { char *next = strstr(response_header, "X-Pi286-Audio-Next-Offset:"); if (next) sscanf(next, "X-Pi286-Audio-Next-Offset: %d", next_offset); }
            if (capture_ms) { char *capture = strstr(response_header, "X-Pi286-Capture-Ms:"); if (capture) sscanf(capture, "X-Pi286-Capture-Ms: %d", capture_ms); }
            used = header_used - (int)(split - response_header);
            if (used < 0 || (size_t)used > cap) { close(fd); return -1; }
            memcpy(out, split, used); headers_done = 1;
        } else { if ((size_t)(used + n) > cap) { close(fd); return -1; } memcpy(out + used, incoming, n); used += n; }
    }
    close(fd); return used == length ? used : -1;
}

static int write_all(int fd, const void *data, size_t length) {
    const unsigned char *cursor = data; ssize_t written;
    while (length) {
        written = write(fd, cursor, length);
        if (written < 0 && errno == EINTR) continue;
        if (written < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            fd_set writable; struct timeval timeout;
            FD_ZERO(&writable); FD_SET(fd, &writable); timeout.tv_sec = 0; timeout.tv_usec = 500000;
            if (select(fd + 1, NULL, &writable, NULL, &timeout) > 0) continue;
            return 0;
        }
        if (written <= 0) return 0;
        cursor += written; length -= (size_t)written;
    }
    return 1;
}

static int read_all(int fd, void *data, size_t length) {
    unsigned char *cursor = data; ssize_t received;
    while (length) {
        received = read(fd, cursor, length);
        if (received <= 0) return 0;
        cursor += received; length -= (size_t)received;
    }
    return 1;
}

static void random_bytes(unsigned char *data, size_t length) {
    int random = open("/dev/urandom", O_RDONLY); size_t got = 0;
    if (random >= 0) { while (got < length) { ssize_t n = read(random, data + got, length - got); if (n <= 0) break; got += (size_t)n; } close(random); }
    while (got < length) data[got++] = (unsigned char)rand();
}

static void base64_16(const unsigned char *source, char *output) {
    static const char alphabet[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    int source_at = 0, output_at = 0;
    while (source_at < 15) {
        output[output_at++] = alphabet[source[source_at] >> 2];
        output[output_at++] = alphabet[((source[source_at] & 3) << 4) | (source[source_at + 1] >> 4)];
        output[output_at++] = alphabet[((source[source_at + 1] & 15) << 2) | (source[source_at + 2] >> 6)];
        output[output_at++] = alphabet[source[source_at + 2] & 63]; source_at += 3;
    }
    output[output_at++] = alphabet[source[15] >> 2];
    output[output_at++] = alphabet[(source[15] & 3) << 4];
    output[output_at++] = '='; output[output_at++] = '='; output[output_at] = 0;
}

static int websocket_open(const char *host, const char *port, const char *token, const char *session) {
    char header[4096], key[25]; unsigned char nonce[16]; int fd, used = 0; ssize_t n;
    random_bytes(nonce, sizeof(nonce)); base64_16(nonce, key);
    fd = connect_to(host, port); if (fd < 0) return -1;
    n = snprintf(header, sizeof(header), "GET /v3/sessions/%s/stream HTTP/1.1\r\nHost: %s\r\nAuthorization: Bearer %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: %s\r\n\r\n", session, host, token, key);
    if (n < 0 || (size_t)n >= sizeof(header) || !write_all(fd, header, (size_t)n)) { close(fd); return -1; }
    while (used + 1 < (int)sizeof(header)) {
        n = read(fd, header + used, 1); if (n != 1) { close(fd); return -1; }
        used += 1; header[used] = 0;
        if (used >= 4 && !memcmp(header + used - 4, "\r\n\r\n", 4)) break;
    }
    if (memcmp(header, "HTTP/1.1 101", 12) && memcmp(header, "HTTP/1.0 101", 12)) { close(fd); return -1; }
    return fd;
}

static int websocket_send_text(int fd, const char *body) {
    unsigned char header[14], mask[4], masked[2048]; size_t length = strlen(body), index, header_length;
    if (length > sizeof(masked)) return 0;
    random_bytes(mask, sizeof(mask)); header[0] = 0x81;
    if (length < 126) { header[1] = 0x80 | (unsigned char)length; header_length = 2; }
    else { header[1] = 0x80 | 126; header[2] = (unsigned char)(length >> 8); header[3] = (unsigned char)length; header_length = 4; }
    memcpy(header + header_length, mask, sizeof(mask)); header_length += sizeof(mask);
    for (index = 0; index < length; index++) masked[index] = (unsigned char)body[index] ^ mask[index % 4];
    return write_all(fd, header, header_length) && write_all(fd, masked, length);
}

static void websocket_close(int fd) {
    unsigned char frame[6] = {0x88, 0x80, 0, 0, 0, 0};
    random_bytes(frame + 2, 4);
    write_all(fd, frame, sizeof(frame));
}

/* Return payload length, zero for close, or -1 for malformed/failed frame. */
/* Return a completed payload, 0 for close, -2 until more bytes arrive, or -1
 * for malformed data. Keeping incomplete frames buffered lets SDL process
 * keyboard and dance-pad events even while a large media frame trickles in. */
static int websocket_take_frame(unsigned char *wire, size_t *used, unsigned char *out, size_t capacity) {
    size_t header_length = 2, total; unsigned long long length; int opcode, index;
    if (*used < 2) return -2;
    if ((wire[0] & 0x70) || (wire[1] & 0x80) || !(wire[0] & 0x80)) return -1;
    opcode = wire[0] & 15; length = wire[1] & 127;
    if (length == 126) { if (*used < 4) return -2; length = ((unsigned long long)wire[2] << 8) | wire[3]; header_length = 4; }
    else if (length == 127) { if (*used < 10) return -2; length = 0; for (index = 0; index < 8; index++) length = (length << 8) | wire[2 + index]; header_length = 10; }
    if (length > capacity || (opcode != 2 && opcode != 8) || length > (unsigned long long)SIZE_MAX - header_length) return -1;
    total = header_length + (size_t)length;
    if (*used < total) return -2;
    if (opcode == 2) memcpy(out, wire + header_length, (size_t)length);
    memmove(wire, wire + total, *used - total); *used -= total;
    return opcode == 8 ? 0 : (int)length;
}

/* libwebsockets owns the HTTP upgrade, WebSocket framing, masking and partial
 * receives. The presenter only exchanges our already-defined JSON / P2P1
 * payloads with this small adapter. */
typedef struct { struct lws_context *context; struct lws *wsi; const char *host, *path; unsigned char packet[POLL_PACKET_MAX]; size_t used, length; char authorization[300], outgoing[2048]; int pending, ready, failed, closing; } LwsStream;

static int lws_presenter_callback(struct lws *wsi, enum lws_callback_reasons reason, void *user, void *in, size_t len) {
    LwsStream *stream = lws_context_user(lws_get_context(wsi)); unsigned char *cursor, *end; (void)user;
    if (!stream) return 0;
    switch (reason) {
    case LWS_CALLBACK_CLIENT_APPEND_HANDSHAKE_HEADER:
        cursor = *(unsigned char **)in; end = cursor + len;
        if (lws_add_http_header_by_name(wsi, (unsigned char *)"authorization:", (unsigned char *)stream->authorization, (int)strlen(stream->authorization), &cursor, end)) return -1;
        *(unsigned char **)in = cursor; break;
    case LWS_CALLBACK_CLIENT_ESTABLISHED: stream->wsi = wsi; if (stream->pending) lws_callback_on_writable(wsi); break;
    case LWS_CALLBACK_CLIENT_WRITEABLE:
        if (stream->pending) { unsigned char message[LWS_PRE + sizeof(stream->outgoing)]; size_t length = strlen(stream->outgoing); memcpy(message + LWS_PRE, stream->outgoing, length); if (lws_write(wsi, message + LWS_PRE, length, LWS_WRITE_TEXT) < (int)length) return -1; stream->pending = 0; } break;
    case LWS_CALLBACK_CLIENT_RECEIVE:
        if (stream->used + len > sizeof(stream->packet)) return -1;
        memcpy(stream->packet + stream->used, in, len); stream->used += len;
        if (lws_is_final_fragment(wsi) && !lws_remaining_packet_payload(wsi)) { stream->length = stream->used; stream->used = 0; stream->ready = 1; } break;
    case LWS_CALLBACK_CLIENT_CONNECTION_ERROR: case LWS_CALLBACK_CLIENT_CLOSED: if (!stream->closing) stream->failed = 1; break;
    default: break;
    }
    return 0;
}

static const struct lws_protocols lws_presenter_protocols[] = { { "pi286", lws_presenter_callback, 0, POLL_PACKET_MAX }, LWS_PROTOCOL_LIST_TERM };
static int lws_stream_open(LwsStream *stream, const char *host, const char *port, const char *token, const char *session, const char *body) {
    struct lws_context_creation_info context = {0}; struct lws_client_connect_info connect = {0}; static char path[128];
    memset(stream, 0, sizeof(*stream)); stream->host = host; snprintf(stream->authorization, sizeof(stream->authorization), "Bearer %s", token); snprintf(path, sizeof(path), "/v3/sessions/%s/stream", session); stream->path = path; snprintf(stream->outgoing, sizeof(stream->outgoing), "%s", body); stream->pending = 1;
    context.port = CONTEXT_PORT_NO_LISTEN; context.protocols = lws_presenter_protocols; context.user = stream;
    if (!(stream->context = lws_create_context(&context))) return 0;
    connect.context = stream->context; connect.address = host; connect.port = atoi(port); connect.path = stream->path; connect.host = host; connect.origin = host; connect.protocol = "pi286";
    if (!(stream->wsi = lws_client_connect_via_info(&connect))) { lws_context_destroy(stream->context); stream->context = NULL; return 0; }
    return 1;
}

static void lws_stream_queue(LwsStream *stream, const char *body) { snprintf(stream->outgoing, sizeof(stream->outgoing), "%s", body); stream->pending = 1; if (stream->wsi) lws_callback_on_writable(stream->wsi); }

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
    if (key >= SDLK_a && key <= SDLK_z) { letter[0] = (char)('A' + key - SDLK_a); letter[1] = 0; return letter; }
    if (key >= SDLK_0 && key <= SDLK_9) { letter[0] = (char)key; letter[1] = 0; return letter; }
    return NULL;
}

static int pump_events(void) {
    SDL_Event event; int changed = 0;
    while (SDL_PollEvent(&event)) {
        const char *key = NULL; int pressed = 0; unsigned int before = event_state.held->revision;
        if (event.type == SDL_QUIT) {
            fprintf(stderr, "presenter: SDL requested quit\n"); fflush(stderr);
            *event_state.quit = 1; return 1;
        }
        if (event.type == SDL_KEYDOWN && event.key.keysym.sym == SDLK_F1) {
            fprintf(stderr, "presenter: F1 requested quit\n"); fflush(stderr);
            *event_state.quit = 1; return 1;
        }
        if ((event.type == SDL_KEYDOWN || event.type == SDL_KEYUP) && event.key.keysym.sym == SDLK_F8) { if (event.type == SDL_KEYDOWN) *event_state.overlay = !*event_state.overlay; continue; }
        if ((event.type == SDL_KEYDOWN || event.type == SDL_KEYUP) && (key = dos_key(event.key.keysym.sym))) pressed = event.type == SDL_KEYDOWN;
        if ((event.type == SDL_JOYBUTTONDOWN || event.type == SDL_JOYBUTTONUP) && event.jbutton.button < 9) {
            pad_update(event_state.held, event.jbutton.button, event.type == SDL_JOYBUTTONDOWN);
        }
        if (event.type == SDL_JOYBUTTONDOWN && event.jbutton.button == 9) {
            fprintf(stderr, "presenter: dance-pad SELECT requested quit\n"); fflush(stderr);
            *event_state.quit = 1; return 1;
        }
        if (key) held_update(event_state.held, key, pressed);
        if (event_state.held->revision != before) { event_state.stats->input_events++; changed = 1; }
    }
    return changed;
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
    static const unsigned char t[7] = {31,4,4,4,4,4,4};
    static const unsigned char colon[7] = {0,4,0,0,0,4,0};
    static const unsigned char dot[7] = {0,0,0,0,0,6,6};
    static const unsigned char slash[7] = {1,2,4,8,16,0,0};
    static const unsigned char dash[7] = {0,0,0,31,0,0,0};
    static const unsigned char blank[7] = {0,0,0,0,0,0,0};
    if (value >= '0' && value <= '9') return digits[value - '0'];
    switch (value) { case 'A': return a; case 'E': return e; case 'I': return i;
    case 'K': return k; case 'N': return n; case 'U': return u; case 'V': return v; case 'T': return t;
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

static void draw_overlay(SDL_Surface *canvas, const Metrics *metrics, int diagnostic) {
    int row; unsigned short *line; char text[48];
    for (row = 0; row < (diagnostic ? 69 : 52); row++) {
        line = (unsigned short *)((unsigned char *)canvas->pixels + row * canvas->pitch);
        memset(line, 0, 324 * sizeof(*line));
    }
    if (diagnostic) draw_text(canvas, 4, 2, "TEST: A/V");
    snprintf(text, sizeof(text), "V:%d.%d %d/%d E%d", metrics->video_fps_tenths / 10,
             metrics->video_fps_tenths % 10, metrics->video_last_ms, metrics->video_capture_ms, metrics->video_fail);
    draw_text(canvas, 4, diagnostic ? 19 : 2, text);
    snprintf(text, sizeof(text), "A:%d U%d E%d", metrics->audio_queued_ms, metrics->audio_underruns, metrics->audio_fail);
    draw_text(canvas, 4, diagnostic ? 36 : 19, text);
    snprintf(text, sizeof(text), "I:%d E%d N:%dK", metrics->input_last_ms, metrics->input_fail, metrics->net_kbytes);
    draw_text(canvas, 4, diagnostic ? 53 : 36, text);
}

static void render(SDL_Surface *screen, SDL_Surface *canvas, const unsigned char *frame, int overlay, const Metrics *metrics, int diagnostic) {
    int x, y;
    SDL_LockSurface(canvas);
    memset(canvas->pixels, 0, canvas->pitch * canvas->h);
    for (y = 0; y < H; y++) for (x = 0; x < W; x++) {
        unsigned short pixel = frame[(y * W + x) * 2] | (frame[(y * W + x) * 2 + 1] << 8);
        unsigned short *row0 = (unsigned short *)((unsigned char *)canvas->pixels + (y * 2) * canvas->pitch);
        unsigned short *row1 = (unsigned short *)((unsigned char *)canvas->pixels + (y * 2 + 1) * canvas->pitch);
        row0[x * 2] = row0[x * 2 + 1] = row1[x * 2] = row1[x * 2 + 1] = pixel;
    }
    if (overlay) draw_overlay(canvas, metrics, diagnostic);
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
    render(screen, canvas, frame, 0, NULL, 0);
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
    const char *host, *port, *token_path, *session, *transport; FILE *file; char token[256], path[256], body[2048]; SDL_Joystick *joystick = NULL;
    unsigned char frame[FRAME], packet[POLL_PACKET_MAX]; SDL_Surface *screen, *canvas; SDL_Event event; SDL_AudioSpec audio, obtained; Metrics metrics = {0}; SessionStats stats = {0}; HeldState held = {0}; int audio_offset = 0, next_offset, n, overlay = 0, video_count = 0, video_seq = 0, audio_length, quit = 0;
    const unsigned char *audio_data; unsigned int poll_revision, input_acked = 0; int diagnostic;
    long long video_window = now_ms(), network_window = video_window; long long request_started, elapsed; size_t network_bytes = 0;
    fprintf(stderr, "presenter: starting\n"); fflush(stderr);
    if (argc == 2 && !strcmp(argv[1], "--local-pattern")) return local_pattern();
    if (argc != 5 && argc != 6) { fprintf(stderr, "usage: %s HOST PORT TOKEN_FILE SESSION [poll|websocket]\n", argv[0]); return 2; }
    host = argv[1]; port = argv[2]; token_path = argv[3]; session = argv[4];
    transport = argc == 6 ? argv[5] : "poll";
    if (strcmp(transport, "poll") && strcmp(transport, "websocket")) { fprintf(stderr, "presenter: invalid transport %s\n", transport); return 2; }
    diagnostic = !strncmp(session, "rainbow-cat-", 12);
    if (diagnostic) overlay = 1;
    if (!(file = fopen(token_path, "r")) || !fgets(token, sizeof(token), file)) { fprintf(stderr, "cannot read token file %s\n", token_path); return 2; }
    fclose(file); token[strcspn(token, "\r\n")] = 0;
    fprintf(stderr, "presenter: token read; initializing SDL\n"); fflush(stderr);
    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_AUDIO | SDL_INIT_JOYSTICK | SDL_INIT_EVENTTHREAD) < 0) { fprintf(stderr, "SDL_Init failed: %s\n", SDL_GetError()); return 1; }
    fprintf(stderr, "presenter: SDL initialized; opening framebuffer\n"); fflush(stderr);
    if (!(screen = SDL_SetVideoMode(640, 480, 16, SDL_FULLSCREEN))) { fprintf(stderr, "SDL_SetVideoMode failed: %s\n", SDL_GetError()); SDL_Quit(); return 1; }
    if (!(canvas = create_canvas(screen))) { fprintf(stderr, "SDL_CreateRGBSurface failed: %s\n", SDL_GetError()); SDL_Quit(); return 1; }
    fprintf(stderr, "presenter: surface %dx%d pitch=%d logical-pitch=%d bpp=%d bytes=%d masks=%08x/%08x/%08x\n",
            screen->w, screen->h, screen->pitch,
            screen->w * screen->format->BytesPerPixel, screen->format->BitsPerPixel,
            screen->format->BytesPerPixel, screen->format->Rmask,
            screen->format->Gmask, screen->format->Bmask); fflush(stderr);
    if (SDL_NumJoysticks() > 0) joystick = SDL_JoystickOpen(0);
    event_state = (EventState){&held, &overlay, &quit, &stats};
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
    if (!strcmp(transport, "websocket")) {
        LwsStream stream; int sent_revision;
        if (poll_body(body, sizeof(body), &held, video_seq, audio_offset) < 0 || !lws_stream_open(&stream, host, port, token, session, body)) { fprintf(stderr, "presenter: websocket connection failed\n"); SDL_CloseAudio(); SDL_FreeSurface(canvas); SDL_Quit(); return 1; }
        sent_revision = (int)held.revision;
        for (;;) {
            lws_service(stream.context, 10);
            if (stream.ready) {
                n = (int)stream.length; stream.ready = 0;
                request_started = now_ms(); metrics.video_last_ms = (int)(now_ms() - request_started);
                if (apply_poll_packet(frame, stream.packet, (size_t)n, &metrics.video_capture_ms, &video_seq, &audio_data, &audio_length, &next_offset)) {
                    stats.polls_completed++; network_bytes += (size_t)n; video_count++; stats.video_frames++; stats.payload_bytes += (unsigned long)n;
                    range_add(metrics.video_last_ms, &stats.video_request_min, &stats.video_request_max, &stats.video_request_total);
                    if (metrics.video_capture_ms >= 0) range_add(metrics.video_capture_ms, &stats.server_capture_min, &stats.server_capture_max, &stats.server_capture_total);
                    elapsed = now_ms() - video_window;
                    if (elapsed >= 1000) { metrics.video_fps_tenths = (int)(video_count * 10000 / elapsed); video_count = 0; video_window = now_ms(); }
                    if (audio_length > 0 && next_offset > audio_offset) { audio_put(audio_data, (size_t)audio_length); audio_offset = next_offset; }
                    if ((unsigned int)sent_revision > input_acked) { metrics.input_last_ms = metrics.video_last_ms; input_acked = (unsigned int)sent_revision; stats.input_acks++; range_add(metrics.input_last_ms, &stats.input_rtt_min, &stats.input_rtt_max, &stats.input_rtt_total); }
                    /* Media acknowledgements carry the latest delta sequence
                     * and PCM offset, even while no key state has changed. */
                    if (poll_body(body, sizeof(body), &held, video_seq, audio_offset) < 0) { stream.failed = 1; } else { lws_stream_queue(&stream, body); sent_revision = (int)held.revision; }
                    /* Keep the server and audio stream ahead of the expensive
                     * software scale.  The browser likewise sends its control
                     * update before its next paint gets a chance to run. */
                    if (!stream.failed) lws_service(stream.context, 0);
                    audio_metrics(&metrics); render(screen, canvas, frame, overlay, &metrics, diagnostic);
                } else { fprintf(stderr, "presenter: invalid websocket packet\n"); stream.failed = 1; }
            }
            if (pump_events()) { /* Send latest held state below without waiting for media. */ }
            if (!quit && (int)held.revision != sent_revision) {
                if (poll_body(body, sizeof(body), &held, video_seq, audio_offset) < 0) stream.failed = 1;
                else { lws_stream_queue(&stream, body); sent_revision = (int)held.revision; }
            }
            audio_metrics(&metrics); stats.audio_samples++;
            range_add(metrics.audio_queued_ms, &stats.audio_queue_min, &stats.audio_queue_max, &stats.audio_queue_total);
            elapsed = now_ms() - network_window;
            if (elapsed >= 1000) { metrics.net_kbytes = (int)(network_bytes * 1000 / elapsed / 1024); network_bytes = 0; network_window = now_ms(); }
            if (quit) {
                stream.closing = 1; lws_context_destroy(stream.context);
                if (joystick) SDL_JoystickClose(joystick); write_session_stats(session, &stats, &metrics); SDL_CloseAudio(); SDL_FreeSurface(canvas); SDL_Quit(); return quit ? 0 : 1;
            }
            if (stream.failed) {
                /* Brief Wi-Fi hiccups should not throw the player out of a
                 * running DOSBox session. The backend holds it for its idle
                 * grace period while this loop retries the same session. */
                fprintf(stderr, "presenter: reconnecting websocket\n"); fflush(stderr);
                SDL_Delay(500);
                lws_context_destroy(stream.context);
                if (poll_body(body, sizeof(body), &held, video_seq, audio_offset) >= 0 && lws_stream_open(&stream, host, port, token, session, body)) {
                    sent_revision = (int)held.revision;
                    fprintf(stderr, "presenter: websocket reconnected\n"); fflush(stderr);
                }
            }
        }
    }
    for (;;) {
        snprintf(path, sizeof(path), "/v2/sessions/%s/poll", session);
        if (poll_body(body, sizeof(body), &held, video_seq, audio_offset) < 0) { fprintf(stderr, "presenter: poll body too large\n"); break; }
        poll_revision = held.revision;
        request_started = now_ms();
        stats.polls_started++;
        n = request(host, port, token, "POST", path, body, packet, sizeof(packet), NULL, NULL, poll_revision);
        metrics.video_last_ms = (int)(now_ms() - request_started);
        if (n > 0 && apply_poll_packet(frame, packet, (size_t)n, &metrics.video_capture_ms, &video_seq, &audio_data, &audio_length, &next_offset)) {
            stats.polls_completed++;
            network_bytes += (size_t)n; video_count++; stats.video_frames++; stats.payload_bytes += (unsigned long)n;
            range_add(metrics.video_last_ms, &stats.video_request_min, &stats.video_request_max, &stats.video_request_total);
            if (metrics.video_capture_ms >= 0) range_add(metrics.video_capture_ms, &stats.server_capture_min, &stats.server_capture_max, &stats.server_capture_total);
            elapsed = now_ms() - video_window;
            if (elapsed >= 1000) { metrics.video_fps_tenths = (int)(video_count * 10000 / elapsed); video_count = 0; video_window = now_ms(); }
            audio_metrics(&metrics);
            render(screen, canvas, frame, overlay, &metrics, diagnostic);
            if (audio_length > 0 && next_offset > audio_offset) { audio_put(audio_data, (size_t)audio_length); audio_offset = next_offset; }
            if (poll_revision > input_acked) { metrics.input_last_ms = metrics.video_last_ms; input_acked = poll_revision; stats.input_acks++; range_add(metrics.input_last_ms, &stats.input_rtt_min, &stats.input_rtt_max, &stats.input_rtt_total); }
        } else if (n == -2) {
            /* Input changed while this request was in flight: its response is deliberately irrelevant. */
            stats.polls_cancelled++;
        } else if (n == -3) {
            /* The backend noticed a newer request and intentionally sent no media. */
            stats.polls_stale++;
        } else {
            video_seq = 0; metrics.video_fail++; stats.video_failures++; metrics.audio_fail++; stats.audio_failures++; stats.polls_failed++;
        }
        audio_metrics(&metrics);
        stats.audio_samples++;
        range_add(metrics.audio_queued_ms, &stats.audio_queue_min, &stats.audio_queue_max, &stats.audio_queue_total);
        elapsed = now_ms() - network_window;
        if (elapsed >= 1000) { metrics.net_kbytes = (int)(network_bytes * 1000 / elapsed / 1024); network_bytes = 0; network_window = now_ms(); }
        pump_events();
        if (quit) { if (joystick) SDL_JoystickClose(joystick); write_session_stats(session, &stats, &metrics); SDL_CloseAudio(); SDL_FreeSurface(canvas); SDL_Quit(); return 0; }
        SDL_Delay(30);
    }
}
