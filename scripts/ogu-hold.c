/*
 * ogu-hold DEV MS CODE VALUE [CODE VALUE...]: keep EV_ABS values on an
 * evdev device for MS milliseconds, written every 2 ms. A polled stick
 * (adc-joystick) reports its real position every 10 ms and would take a
 * single injected value back at once. Built and copied to the board by
 * scripts/ogu-ctl.py.
 */
#include <fcntl.h>
#include <linux/input.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static void put(int fd, int type, int code, int value)
{
	struct input_event e;

	memset(&e, 0, sizeof(e));
	e.type = type;
	e.code = code;
	e.value = value;
	if (write(fd, &e, sizeof(e)) != sizeof(e))
		exit(1);
}

int main(int argc, char **argv)
{
	struct timespec ts = { 0, 2000000 };
	int fd, i, n;

	if (argc < 5 || (fd = open(argv[1], O_WRONLY)) < 0)
		return 1;
	for (n = atoi(argv[2]) / 2; n > 0; n--) {
		for (i = 3; i + 1 < argc; i += 2)
			put(fd, EV_ABS, atoi(argv[i]), atoi(argv[i + 1]));
		put(fd, EV_SYN, SYN_REPORT, 0);
		nanosleep(&ts, NULL);
	}
	return 0;
}
