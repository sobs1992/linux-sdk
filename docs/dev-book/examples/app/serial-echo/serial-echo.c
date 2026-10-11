/*
 * serial-echo <tty> [baud]: echo every received line back, prefixed.
 *
 * ODROID-GO Advance: /dev/ttyS1 is UART1 on the expansion header P2
 * (pin 2 RXD, pin 3 TXD). Do not use the console UART (ttyS2): getty owns it.
 */
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <termios.h>
#include <unistd.h>

static speed_t to_speed(int baud)
{
	switch (baud) {
	case 9600:   return B9600;
	case 57600:  return B57600;
	case 115200: return B115200;
	case 921600: return B921600;
	default:     return 0;
	}
}

int main(int argc, char **argv)
{
	char line[256], c;
	struct termios t;
	size_t len = 0;
	speed_t speed;
	int fd;

	if (argc < 2) {
		fprintf(stderr, "usage: %s <tty> [baud]\n", argv[0]);
		return 2;
	}
	speed = to_speed(argc > 2 ? atoi(argv[2]) : 115200);
	if (!speed) {
		fputs("unsupported baud rate\n", stderr);
		return 2;
	}
	fd = open(argv[1], O_RDWR | O_NOCTTY | O_CLOEXEC);
	if (fd < 0 || tcgetattr(fd, &t) < 0) {
		perror(argv[1]);
		return 1;
	}
	cfmakeraw(&t);			/* 8N1, no echo, no line editing */
	t.c_cflag |= CLOCAL | CREAD;
	t.c_cc[VMIN] = 1;
	t.c_cc[VTIME] = 0;
	cfsetispeed(&t, speed);
	cfsetospeed(&t, speed);
	if (tcsetattr(fd, TCSANOW, &t) < 0) {
		perror("tcsetattr");
		return 1;
	}

	while (read(fd, &c, 1) == 1) {
		if (c == '\r')
			continue;
		if (c != '\n' && len < sizeof(line) - 1) {
			line[len++] = c;
			continue;
		}
		line[len] = '\0';
		dprintf(fd, "echo: %s\r\n", line);
		printf("rx: %s\n", line);
		len = 0;
	}
	return 0;
}
