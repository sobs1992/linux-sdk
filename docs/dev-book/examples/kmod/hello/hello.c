// SPDX-License-Identifier: GPL-2.0
/* Minimal module with a parameter: insmod hello.ko who=OGA */
#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/init.h>
#include <linux/module.h>
#include <linux/moduleparam.h>
#include <linux/utsname.h>

static char *who = "SDK";
module_param(who, charp, 0444);		/* visible in /sys/module/hello/parameters/who */
MODULE_PARM_DESC(who, "Whom to greet");

static int __init hello_init(void)
{
	pr_info("hello, %s! kernel %s on %s\n", who, init_utsname()->release,
		init_utsname()->machine);
	return 0;
}

static void __exit hello_exit(void)
{
	pr_info("bye, %s\n", who);
}

module_init(hello_init);
module_exit(hello_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SDK example: hello world module");
