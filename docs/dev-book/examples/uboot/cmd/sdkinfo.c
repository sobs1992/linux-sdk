// SPDX-License-Identifier: GPL-2.0+
/*
 * sdkinfo: print what U-Boot knows about the board before booting Linux.
 * Goes to cmd/sdkinfo.c; see cmd/Kconfig and cmd/Makefile snippets.
 */
#include <command.h>
#include <env.h>
#include <vsprintf.h>
#include <asm/global_data.h>

DECLARE_GLOBAL_DATA_PTR;

static const char *env_or(const char *name)
{
	const char *v = env_get(name);

	return v ? v : "(not set)";
}

static int do_sdkinfo(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
	printf("board:     %s\n", env_or("board_name"));
	printf("fdtfile:   %s\n", env_or("fdtfile"));
	printf("RAM:       %lu MiB\n", (unsigned long)(gd->ram_size >> 20));
	printf("bootdelay: %s\n", env_or("bootdelay"));
	if (argc > 1)
		printf("note:      %s\n", argv[1]);
	return CMD_RET_SUCCESS;
}

U_BOOT_CMD(sdkinfo, 2, 0, do_sdkinfo,
	   "show board info collected by U-Boot",
	   "[note]\n"
	   "    - print board name, selected dtb, RAM size; echo an optional note");
