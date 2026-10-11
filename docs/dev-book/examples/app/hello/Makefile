# Cross-compile: make CC=<sdk>/bin/aarch64-buildroot-linux-gnu-gcc
CC     ?= gcc
CFLAGS ?= -O2 -g -Wall -Wextra

hello: hello.c
	$(CC) $(CFLAGS) -o $@ $<

install: hello
	install -D -m 0755 hello $(DESTDIR)/usr/bin/hello

clean:
	rm -f hello

.PHONY: install clean
