/*
 * Blink one GPIO line through the GPIO character device (uAPI v2).
 *
 *   gpio-blink <chip> <line> [count] [period_ms]
 *   gpio-blink /dev/gpiochip0 17 10 500      Raspberry Pi: GPIO17, header pin 11
 *   gpio-blink /dev/gpiochip1 28 10 500      BeagleBone Black: GPIO1_28, P9_12
 *
 * Which /dev/gpiochipN is which bank: "gpiodetect" or
 * /sys/bus/gpio/devices/gpiochipN/label.
 */
#include <errno.h>
#include <fcntl.h>
#include <linux/gpio.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

int main(int argc, char **argv)
{
	struct gpio_v2_line_request req;
	struct gpio_v2_line_values val;
	int fd, count, period, i;

	if (argc < 3) {
		fprintf(stderr, "usage: %s <chip> <line> [count] [period_ms]\n", argv[0]);
		return 2;
	}
	count = argc > 3 ? atoi(argv[3]) : 10;
	period = argc > 4 ? atoi(argv[4]) : 500;

	fd = open(argv[1], O_RDONLY | O_CLOEXEC);
	if (fd < 0) {
		perror(argv[1]);
		return 1;
	}

	memset(&req, 0, sizeof(req));
	req.offsets[0] = atoi(argv[2]);
	req.num_lines = 1;
	req.config.flags = GPIO_V2_LINE_FLAG_OUTPUT;
	strncpy(req.consumer, "gpio-blink", sizeof(req.consumer) - 1);
	if (ioctl(fd, GPIO_V2_GET_LINE_IOCTL, &req) < 0) {
		fprintf(stderr, "line %s: %s\n", argv[2], strerror(errno));
		return 1;
	}
	close(fd);

	val.mask = 1;
	for (i = 0; i < count * 2; i++) {
		val.bits = !(i & 1);
		if (ioctl(req.fd, GPIO_V2_LINE_SET_VALUES_IOCTL, &val) < 0) {
			perror("set value");
			return 1;
		}
		usleep(period * 1000 / 2);
	}
	close(req.fd);		/* the line is released, the pin keeps its last value */
	return 0;
}
