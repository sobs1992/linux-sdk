// SPDX-License-Identifier: GPL-2.0
/*
 * /dev/sdkchar: a misc character device that keeps the last 4 KiB written to it.
 *
 *   echo hello > /dev/sdkchar ; cat /dev/sdkchar
 */
#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/fs.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/mutex.h>

#define BUF_SIZE 4096

static char buf[BUF_SIZE];
static size_t buf_len;
static DEFINE_MUTEX(buf_lock);

static ssize_t sdkchar_read(struct file *f, char __user *ubuf, size_t len, loff_t *pos)
{
	ssize_t ret;

	mutex_lock(&buf_lock);
	ret = simple_read_from_buffer(ubuf, len, pos, buf, buf_len);
	mutex_unlock(&buf_lock);
	return ret;
}

static ssize_t sdkchar_write(struct file *f, const char __user *ubuf, size_t len, loff_t *pos)
{
	ssize_t ret;

	mutex_lock(&buf_lock);
	if (*pos == 0)
		buf_len = 0;		/* a new write replaces the content */
	ret = simple_write_to_buffer(buf, BUF_SIZE, pos, ubuf, len);
	if (ret > 0)
		buf_len = max_t(size_t, buf_len, *pos);
	mutex_unlock(&buf_lock);
	return ret;
}

static const struct file_operations sdkchar_fops = {
	.owner	= THIS_MODULE,
	.read	= sdkchar_read,
	.write	= sdkchar_write,
	.llseek	= default_llseek,
};

static struct miscdevice sdkchar_dev = {
	.minor	= MISC_DYNAMIC_MINOR,
	.name	= "sdkchar",		/* mdev creates /dev/sdkchar */
	.fops	= &sdkchar_fops,
	.mode	= 0666,
};

module_misc_device(sdkchar_dev);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SDK example: misc character device");
