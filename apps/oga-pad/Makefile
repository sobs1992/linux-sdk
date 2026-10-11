# Cross-compile: make CC=<sdk>/bin/aarch64-buildroot-linux-gnu-gcc
CC     ?= gcc
CFLAGS ?= -O2 -g -Wall -Wextra

oga-pad: oga-pad.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<

install: oga-pad
	install -D -m 0755 oga-pad $(DESTDIR)/usr/bin/oga-pad

clean:
	rm -f oga-pad

.PHONY: install clean
