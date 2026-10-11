// SPDX-License-Identifier: GPL-2.0
/*
 * sdk-gpio-led: platform driver that blinks a GPIO described in device tree.
 *
 *	sdk-led {
 *		compatible = "sdk,gpio-led";
 *		led-gpios = <&gpio 17 GPIO_ACTIVE_HIGH>;
 *	};
 *
 * MODULE_DEVICE_TABLE(of, ...) makes the module load automatically (mdev
 * runs modprobe for the node's modalias) once it is installed in the image.
 */
#include <linux/gpio/consumer.h>
#include <linux/jiffies.h>
#include <linux/mod_devicetable.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/workqueue.h>

static unsigned int period_ms = 1000;
module_param(period_ms, uint, 0644);	/* writable: /sys/module/sdk_gpio_led/parameters/period_ms */
MODULE_PARM_DESC(period_ms, "Blink period in milliseconds");

struct sdk_led {
	struct gpio_desc *gpio;
	struct delayed_work work;
	bool on;
};

static void sdk_led_work(struct work_struct *work)
{
	struct sdk_led *led = container_of(to_delayed_work(work), struct sdk_led, work);

	led->on = !led->on;
	gpiod_set_value_cansleep(led->gpio, led->on);
	schedule_delayed_work(&led->work, msecs_to_jiffies(max(period_ms, 20U) / 2));
}

static int sdk_led_probe(struct platform_device *pdev)
{
	struct sdk_led *led;

	led = devm_kzalloc(&pdev->dev, sizeof(*led), GFP_KERNEL);
	if (!led)
		return -ENOMEM;

	/* "led-gpios" in DT; logical value 1 = on, GPIO_ACTIVE_LOW is handled for us */
	led->gpio = devm_gpiod_get(&pdev->dev, "led", GPIOD_OUT_LOW);
	if (IS_ERR(led->gpio))
		return dev_err_probe(&pdev->dev, PTR_ERR(led->gpio), "no led-gpios\n");

	INIT_DELAYED_WORK(&led->work, sdk_led_work);
	platform_set_drvdata(pdev, led);
	schedule_delayed_work(&led->work, 0);
	dev_info(&pdev->dev, "blinking, period %u ms\n", period_ms);
	return 0;
}

static void sdk_led_remove(struct platform_device *pdev)
{
	struct sdk_led *led = platform_get_drvdata(pdev);

	cancel_delayed_work_sync(&led->work);
	gpiod_set_value_cansleep(led->gpio, 0);
}

static const struct of_device_id sdk_led_of_match[] = {
	{ .compatible = "sdk,gpio-led" },
	{ }
};
MODULE_DEVICE_TABLE(of, sdk_led_of_match);

static struct platform_driver sdk_led_driver = {
	.probe	= sdk_led_probe,
	.remove	= sdk_led_remove,
	.driver	= {
		.name		= "sdk-gpio-led",
		.of_match_table	= sdk_led_of_match,
	},
};
module_platform_driver(sdk_led_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SDK example: blink a GPIO from device tree");
