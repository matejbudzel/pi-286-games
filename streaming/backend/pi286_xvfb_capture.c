/* Native Xvfb framebuffer converter for the Pi286 streaming backend.
 * This is an x86_64/Linux server helper, never a Raspberry Pi component.
 */
#define _POSIX_C_SOURCE 200809L
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

enum { OUTPUT_WIDTH = 320, OUTPUT_HEIGHT = 240, OUTPUT_BYTES = OUTPUT_WIDTH * OUTPUT_HEIGHT * 2 };

static uint32_t be32(const unsigned char *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}

static int read_frame(const char *path, unsigned char **data, size_t *size) {
    struct stat st;
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0 || fstat(fd, &st) || st.st_size < 100) {
        if (fd >= 0) close(fd);
        return -1;
    }
    *size = (size_t)st.st_size;
    *data = malloc(*size);
    if (!*data) { close(fd); return -1; }
    size_t at = 0;
    while (at < *size) {
        ssize_t got = read(fd, *data + at, *size - at);
        if (got <= 0) { free(*data); *data = NULL; close(fd); return -1; }
        at += (size_t)got;
    }
    close(fd);
    return 0;
}

/* Return a stable copy, or 75 when Xvfb was updating the shared image. */
static int stable_frame(const char *path, unsigned char **frame, size_t *size) {
    for (int attempt = 0; attempt < 3; ++attempt) {
        unsigned char *first = NULL, *second = NULL;
        size_t first_size = 0, second_size = 0;
        if (read_frame(path, &first, &first_size) || read_frame(path, &second, &second_size)) {
            free(first); free(second); return 75;
        }
        if (first_size == second_size && !memcmp(first, second, first_size)) {
            free(first); *frame = second; *size = second_size; return 0;
        }
        free(first); free(second);
    }
    return 75;
}

static unsigned char blend(unsigned char current, unsigned char following, int remainder) {
    return (unsigned char)((current * (OUTPUT_HEIGHT - remainder) + following * remainder) / OUTPUT_HEIGHT);
}

static int convert(const unsigned char *source, size_t source_size, const char *scaling,
                   unsigned char output[OUTPUT_BYTES]) {
    if (source_size < 100) return -1;
    uint32_t header_size = be32(source), width = be32(source + 16), height = be32(source + 20);
    uint32_t byte_order = be32(source + 28), bits_per_pixel = be32(source + 44), bytes_per_line = be32(source + 48);
    uint32_t colors = be32(source + 76);
    size_t pixels = (size_t)header_size + (size_t)colors * 12;
    if (width != 640 || height != 480 || byte_order != 0 || bits_per_pixel != 32 || bytes_per_line != 2560 ||
        pixels > source_size || source_size - pixels < (size_t)bytes_per_line * height) return -1;
    int linear = !strcmp(scaling, "linear-v") || !strcmp(scaling, "crt-lite");
    int crt = !strcmp(scaling, "crt-lite");
    size_t destination = 0;
    for (int y = 0; y < OUTPUT_HEIGHT; ++y) {
        int source_y = y * 200 / OUTPUT_HEIGHT;
        int remainder = (y * 200) % OUTPUT_HEIGHT;
        const unsigned char *row = source + pixels + (size_t)(40 + 2 * source_y) * bytes_per_line;
        const unsigned char *next = source + pixels + (size_t)(40 + 2 * (source_y < 199 ? source_y + 1 : 199)) * bytes_per_line;
        for (int x = 0; x < OUTPUT_WIDTH; ++x) {
            const unsigned char *pixel = row + x * 8;
            unsigned char blue = pixel[0], green = pixel[1], red = pixel[2];
            if (linear && remainder) {
                const unsigned char *following = next + x * 8;
                blue = blend(blue, following[0], remainder);
                green = blend(green, following[1], remainder);
                red = blend(red, following[2], remainder);
            }
            uint16_t color = (uint16_t)(((red & 0xf8) << 8) | ((green & 0xfc) << 3) | (blue >> 3));
            if (crt && (y & 1)) color = (uint16_t)((((color & 0xf800) * 7 / 8) & 0xf800) |
                                                    (((color & 0x07e0) * 7 / 8) & 0x07e0) |
                                                    (((color & 0x001f) * 7 / 8) & 0x001f));
            output[destination++] = (unsigned char)color;
            output[destination++] = (unsigned char)(color >> 8);
        }
    }
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 3) { fprintf(stderr, "usage: %s Xvfb_screen0 nearest|linear-v|crt-lite\n", argv[0]); return 64; }
    unsigned char *source = NULL, output[OUTPUT_BYTES];
    size_t source_size = 0;
    int result = stable_frame(argv[1], &source, &source_size);
    if (!result) result = convert(source, source_size, argv[2], output);
    free(source);
    if (result) return result == 75 ? 75 : 65;
    return fwrite(output, 1, sizeof(output), stdout) == sizeof(output) ? 0 : 74;
}
