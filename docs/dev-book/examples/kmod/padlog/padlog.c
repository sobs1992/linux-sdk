// SPDX-License-Identifier: GPL-2.0
/*
 * padlog: log every key/button press of every input device to the kernel log.
 *
 * An input *handler* sits next to evdev and receives the same events. On the
 * ODROID-GO Advance it shows the gamepad codes (BTN_DPAD_UP = 544, ...).
 */
#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/input.h>
#include <linux/module.h>
#include <linux/slab.h>

static void padlog_event(struct input_handle *handle, unsigned int type,
			 unsigned int code, int value)
{
	if (type == EV_KEY && value == 1)
		pr_info("%s: code %u pressed\n", handle->dev->name, code);
}

static int padlog_connect(struct input_handler *handler, struct input_dev *dev,
			  const struct input_device_id *id)
{
	struct input_handle *handle;
	int err;

	handle = kzalloc(sizeof(*handle), GFP_KERNEL);
	if (!handle)
		return -ENOMEM;
	handle->dev = dev;
	handle->handler = handler;
	handle->name = "padlog";

	err = input_register_handle(handle);
	if (err)
		goto err_free;
	err = input_open_device(handle);
	if (err)
		goto err_unregister;
	pr_info("watching %s\n", dev->name);
	return 0;

err_unregister:
	input_unregister_handle(handle);
err_free:
	kfree(handle);
	return err;
}

static void padlog_disconnect(struct input_handle *handle)
{
	input_close_device(handle);
	input_unregister_handle(handle);
	kfree(handle);
}

/* Any device that can send EV_KEY: buttons, keyboards */
static const struct input_device_id padlog_ids[] = {
	{ .flags = INPUT_DEVICE_ID_MATCH_EVBIT, .evbit = { BIT_MASK(EV_KEY) } },
	{ }
};
MODULE_DEVICE_TABLE(input, padlog_ids);

static struct input_handler padlog_handler = {
	.name		= "padlog",
	.event		= padlog_event,
	.connect	= padlog_connect,
	.disconnect	= padlog_disconnect,
	.id_table	= padlog_ids,
};

static int __init padlog_init(void)
{
	return input_register_handler(&padlog_handler);
}

static void __exit padlog_exit(void)
{
	input_unregister_handler(&padlog_handler);
}

module_init(padlog_init);
module_exit(padlog_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SDK example: log input key presses");
