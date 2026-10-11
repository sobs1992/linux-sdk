/*
 * oga-pad: move a square across the screen with the D-pad (ODROID-GO Advance).
 *
 * Shows three things: finding an input device by name (evdev), drawing on
 * the framebuffer (/dev/fb0, DRM fbdev emulation) and switching the text
 * console off while drawing (KD_GRAPHICS), so fbcon does not draw over us.
 *
 * The OGA panel is mounted rotated: the framebuffer keeps the panel's native
 * (portrait) orientation, and only the text console is turned by fbcon
 * (fbcon=rotate:N, needs CONFIG_FRAMEBUFFER_CONSOLE_ROTATION). The program
 * works in "screen" coordinates as the user sees them and maps every pixel
 * the same way fbcon does. The rotation is taken from
 * /sys/class/graphics/fbcon/rotate; "oga-pad N" overrides it.
 *
 * A/B/X/Y change the colour, F6 (BTN_TRIGGER_HAPPY6) or Ctrl-C quits.
 */
#include <fcntl.h>
#include <linux/fb.h>
#include <linux/input.h>
#include <linux/kd.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

#define SIZE 40
#define STEP 20

static volatile sig_atomic_t quit;
static uint8_t *fb;
static struct fb_var_screeninfo var;
static struct fb_fix_screeninfo fix;
static int rotate;		/* like fbcon=rotate: 0, 1 = 90 cw, 2 = 180, 3 = 270 cw */
static int scr_w, scr_h;	/* screen size as the user sees it */

/* Current text console rotation, 0 if fbcon rotation is not available */
static int fbcon_rotation(void)
{
	FILE *f = fopen("/sys/class/graphics/fbcon/rotate", "r");
	int r = 0;

	if (f) {
		if (fscanf(f, "%d", &r) != 1)
			r = 0;
		fclose(f);
	}
	return r & 3;
}

static void on_signal(int sig)
{
	(void)sig;
	quit = 1;
}

/* Open /dev/input/eventN whose device name is 'want' ("gpio-keys" on OGA) */
static int open_input(const char *want)
{
	char path[32], name[64];
	int i, fd;

	for (i = 0; i < 32; i++) {
		snprintf(path, sizeof(path), "/dev/input/event%d", i);
		fd = open(path, O_RDONLY | O_CLOEXEC);
		if (fd < 0)
			continue;
		memset(name, 0, sizeof(name));
		if (ioctl(fd, EVIOCGNAME(sizeof(name) - 1), name) >= 0 && !strcmp(name, want))
			return fd;
		close(fd);
	}
	return -1;
}

static void put_pixel(int sx, int sy, uint32_t rgb)
{
	int x, y, bpp = var.bits_per_pixel / 8;
	uint8_t *p;

	switch (rotate) {	/* screen -> framebuffer coordinates */
	case 1:  x = var.xres - 1 - sy; y = sx; break;
	case 2:  x = var.xres - 1 - sx; y = var.yres - 1 - sy; break;
	case 3:  x = sy; y = var.yres - 1 - sx; break;
	default: x = sx; y = sy; break;
	}
	p = fb + (size_t)y * fix.line_length + (size_t)x * bpp;
	if (bpp == 4)
		*(uint32_t *)p = rgb;
	else if (bpp == 2)	/* RGB565 */
		*(uint16_t *)p = ((rgb >> 8) & 0xf800) | ((rgb >> 5) & 0x07e0) | ((rgb >> 3) & 0x001f);
}

static void fill(int x0, int y0, int w, int h, uint32_t rgb)
{
	int x, y;

	for (y = y0; y < y0 + h && y < scr_h; y++)
		for (x = x0; x < x0 + w && x < scr_w; x++)
			put_pixel(x, y, rgb);
}

int main(int argc, char **argv)
{
	uint32_t colour = 0xffffff;
	int px, py, fbfd, in, tty;
	struct input_event ev;
	struct pollfd pfd;

	in = open_input("gpio-keys");
	if (in < 0) {
		fputs("gpio-keys input device not found\n", stderr);
		return 1;
	}
	fbfd = open("/dev/fb0", O_RDWR | O_CLOEXEC);
	if (fbfd < 0 || ioctl(fbfd, FBIOGET_VSCREENINFO, &var) < 0 ||
	    ioctl(fbfd, FBIOGET_FSCREENINFO, &fix) < 0) {
		perror("/dev/fb0");
		return 1;
	}
	fb = mmap(NULL, fix.smem_len, PROT_READ | PROT_WRITE, MAP_SHARED, fbfd, 0);
	if (fb == MAP_FAILED) {
		perror("mmap");
		return 1;
	}
	rotate = argc > 1 ? atoi(argv[1]) & 3 : fbcon_rotation();
	scr_w = rotate & 1 ? var.yres : var.xres;
	scr_h = rotate & 1 ? var.xres : var.yres;
	printf("fb0: %ux%u, %u bpp; screen %dx%d (rotate %d)\n", var.xres, var.yres,
	       var.bits_per_pixel, scr_w, scr_h, rotate);

	/* Keep fbcon (the blinking cursor) away from our pixels */
	tty = open("/dev/tty1", O_RDWR | O_CLOEXEC);
	if (tty >= 0)
		ioctl(tty, KDSETMODE, KD_GRAPHICS);
	signal(SIGINT, on_signal);
	signal(SIGTERM, on_signal);

	px = (scr_w - SIZE) / 2;
	py = (scr_h - SIZE) / 2;
	fill(0, 0, scr_w, scr_h, 0);
	fill(px, py, SIZE, SIZE, colour);

	pfd.fd = in;
	pfd.events = POLLIN;
	while (!quit) {
		if (poll(&pfd, 1, 200) <= 0)
			continue;
		if (read(in, &ev, sizeof(ev)) != sizeof(ev) || ev.type != EV_KEY || ev.value != 1)
			continue;

		fill(px, py, SIZE, SIZE, 0);
		switch (ev.code) {
		case BTN_DPAD_UP:    py -= STEP; break;
		case BTN_DPAD_DOWN:  py += STEP; break;
		case BTN_DPAD_LEFT:  px -= STEP; break;
		case BTN_DPAD_RIGHT: px += STEP; break;
		case BTN_SOUTH:      colour = 0xff3030; break;
		case BTN_EAST:       colour = 0x30ff30; break;
		case BTN_WEST:       colour = 0x3080ff; break;
		case BTN_NORTH:      colour = 0xffff30; break;
		case BTN_TRIGGER_HAPPY6: quit = 1; break;
		}
		if (px < 0) px = 0;
		if (py < 0) py = 0;
		if (px > scr_w - SIZE) px = scr_w - SIZE;
		if (py > scr_h - SIZE) py = scr_h - SIZE;
		fill(px, py, SIZE, SIZE, colour);
	}

	if (tty >= 0)
		ioctl(tty, KDSETMODE, KD_TEXT);
	munmap(fb, fix.smem_len);
	return 0;
}
