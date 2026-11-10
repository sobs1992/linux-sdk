// SPDX-License-Identifier: GPL-2.0+
/*
 * Test of the meson-venc V4L2 encoder: synthetic frames in, H.264 out.
 *
 *   venc-test [-d /dev/videoN] [-f XR24|NV12] [-s WxH] [-n frames]
 *             [-b bitrate] [-g gop] [-q qp (rate control off)] out.h264
 *
 * The picture: eight colour bars (white, yellow, cyan, green, magenta,
 * red, blue, black) and a grey square moving to the right, so that the
 * colours and the motion can be checked in the decoded stream.
 */
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include <linux/videodev2.h>

#define NBUF 4

struct buf {
	void *p;
	size_t len;
};

static int xioctl(int fd, unsigned long req, void *arg)
{
	int r;

	do
		r = ioctl(fd, req, arg);
	while (r < 0 && errno == EINTR);
	return r;
}

static double now(void)
{
	struct timespec t;

	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec + t.tv_nsec / 1e9;
}

static const uint8_t bars[8][3] = {
	{ 235, 235, 235 }, { 235, 235, 16 }, { 16, 235, 235 }, { 16, 235, 16 },
	{ 235, 16, 235 }, { 235, 16, 16 }, { 16, 16, 235 }, { 16, 16, 16 },
};

static int pattern;
static int wait_ms;	/* pause before each frame after the first ones */	/* 0 bars, 1 bars with moving noise (hard to code) */

static void rgb_at(int w, int x, int y, int n, uint8_t c[3])
{
	int sq = 64, sx = (n * 4) % (w - sq), sy = 100;

	if (x >= sx && x < sx + sq && y >= sy && y < sy + sq) {
		c[0] = c[1] = c[2] = 128;
		return;
	}
	memcpy(c, bars[x * 8 / w], 3);
	if (pattern == 1 && y > 200) {
		uint32_t h = (uint32_t)(x + n * 3) * 2654435761u ^ (uint32_t)y * 40503u;
		int d = (int)((h >> 13) & 63) - 32, i;

		for (i = 0; i < 3; i++)
			c[i] = (uint8_t)(c[i] + d < 0 ? 0 : c[i] + d > 255 ? 255 : c[i] + d);
	}
}

static void fill(void *p, uint32_t fourcc, int w, int h, int bpl, int n)
{
	int x, y;
	uint8_t c[3];

	if (fourcc == V4L2_PIX_FMT_XBGR32) {
		for (y = 0; y < h; y++) {
			uint8_t *row = (uint8_t *)p + (size_t)y * bpl;

			for (x = 0; x < w; x++) {
				rgb_at(w, x, y, n, c);
				row[4 * x + 0] = c[2];	/* B G R X, as DRM XRGB8888 */
				row[4 * x + 1] = c[1];
				row[4 * x + 2] = c[0];
				row[4 * x + 3] = 0xff;
			}
		}
		return;
	}
	/* NV12, BT.601 studio range */
	for (y = 0; y < h; y++) {
		uint8_t *Y = (uint8_t *)p + (size_t)y * bpl;
		uint8_t *UV = (uint8_t *)p + (size_t)bpl * h + (size_t)(y / 2) * bpl;

		for (x = 0; x < w; x++) {
			int r, g, b;

			rgb_at(w, x, y, n, c);
			r = c[0];
			g = c[1];
			b = c[2];
			Y[x] = (uint8_t)(((66 * r + 129 * g + 25 * b + 128) >> 8) + 16);
			if (!(x & 1) && !(y & 1)) {
				UV[x] = (uint8_t)(((-38 * r - 74 * g + 112 * b + 128) >> 8) + 128);
				UV[x + 1] = (uint8_t)(((112 * r - 94 * g - 18 * b + 128) >> 8) + 128);
			}
		}
	}
}

static int find_device(char *path, size_t n)
{
	int i, fd;
	struct v4l2_capability cap;

	for (i = 0; i < 16; i++) {
		snprintf(path, n, "/dev/video%d", i);
		fd = open(path, O_RDWR);
		if (fd < 0)
			continue;
		if (!xioctl(fd, VIDIOC_QUERYCAP, &cap) && !strcmp((char *)cap.driver, "meson-venc"))
			return fd;
		close(fd);
	}
	return -1;
}

static int set_ctrl(int fd, uint32_t id, int val)
{
	struct v4l2_control c = { .id = id, .value = val };

	if (xioctl(fd, VIDIOC_S_CTRL, &c) < 0) {
		fprintf(stderr, "S_CTRL %#x=%d: %s\n", id, val, strerror(errno));
		return -1;
	}
	return 0;
}

static int setup_queue(int fd, enum v4l2_buf_type type, struct buf *b)
{
	struct v4l2_requestbuffers rb = { .count = NBUF, .type = type, .memory = V4L2_MEMORY_MMAP };
	unsigned int i;

	if (xioctl(fd, VIDIOC_REQBUFS, &rb) < 0) {
		perror("REQBUFS");
		return -1;
	}
	for (i = 0; i < rb.count; i++) {
		struct v4l2_buffer vb = { .type = type, .memory = V4L2_MEMORY_MMAP, .index = i };

		if (xioctl(fd, VIDIOC_QUERYBUF, &vb) < 0) {
			perror("QUERYBUF");
			return -1;
		}
		b[i].len = vb.length;
		b[i].p = mmap(NULL, vb.length, PROT_READ | PROT_WRITE, MAP_SHARED, fd, vb.m.offset);
		if (b[i].p == MAP_FAILED) {
			perror("mmap");
			return -1;
		}
	}
	return (int)rb.count;
}

int main(int argc, char **argv)
{
	char dev[32] = "";
	uint32_t fourcc = V4L2_PIX_FMT_XBGR32;
	int w = 864, h = 480, frames = 120, bitrate = 3000000, gop = 60, qp = -1;
	int fd, opt, i, nout, ncap, done = 0, queued = 0;
	struct buf out[NBUF], cap[NBUF];
	struct v4l2_format f;
	struct v4l2_streamparm parm;
	enum v4l2_buf_type type;
	FILE *o;
	double t0;
	size_t total = 0;

	while ((opt = getopt(argc, argv, "d:f:s:n:b:g:q:p:w:")) != -1) {
		switch (opt) {
		case 'd':
			snprintf(dev, sizeof(dev), "%s", optarg);
			break;
		case 'f':
			fourcc = v4l2_fourcc(optarg[0], optarg[1], optarg[2], optarg[3]);
			break;
		case 's':
			sscanf(optarg, "%dx%d", &w, &h);
			break;
		case 'n':
			frames = atoi(optarg);
			break;
		case 'b':
			bitrate = atoi(optarg);
			break;
		case 'g':
			gop = atoi(optarg);
			break;
		case 'q':
			qp = atoi(optarg);
			break;
		case 'p':
			pattern = atoi(optarg);
			break;
		case 'w':
			wait_ms = atoi(optarg);
			break;
		default:
			return 2;
		}
	}
	if (optind >= argc) {
		fprintf(stderr, "usage: %s [options] out.h264\n", argv[0]);
		return 2;
	}
	fd = dev[0] ? open(dev, O_RDWR) : find_device(dev, sizeof(dev));
	if (fd < 0) {
		fprintf(stderr, "no meson-venc device\n");
		return 1;
	}
	o = fopen(argv[optind], "wb");
	if (!o) {
		perror(argv[optind]);
		return 1;
	}

	memset(&f, 0, sizeof(f));
	f.type = V4L2_BUF_TYPE_VIDEO_OUTPUT;
	f.fmt.pix.width = w;
	f.fmt.pix.height = h;
	f.fmt.pix.pixelformat = fourcc;
	if (xioctl(fd, VIDIOC_S_FMT, &f) < 0) {
		perror("S_FMT out");
		return 1;
	}
	printf("%s: %.4s %ux%u bpl %u size %u\n", dev, (char *)&f.fmt.pix.pixelformat,
	       f.fmt.pix.width, f.fmt.pix.height, f.fmt.pix.bytesperline, f.fmt.pix.sizeimage);
	w = f.fmt.pix.width;
	h = f.fmt.pix.height;
	int bpl = f.fmt.pix.bytesperline;

	memset(&f, 0, sizeof(f));
	f.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	f.fmt.pix.pixelformat = V4L2_PIX_FMT_H264;
	if (xioctl(fd, VIDIOC_S_FMT, &f) < 0) {
		perror("S_FMT cap");
		return 1;
	}

	memset(&parm, 0, sizeof(parm));
	parm.type = V4L2_BUF_TYPE_VIDEO_OUTPUT;
	parm.parm.output.timeperframe.numerator = 1;
	parm.parm.output.timeperframe.denominator = 30;
	xioctl(fd, VIDIOC_S_PARM, &parm);
	set_ctrl(fd, V4L2_CID_MPEG_VIDEO_BITRATE, bitrate);
	set_ctrl(fd, V4L2_CID_MPEG_VIDEO_GOP_SIZE, gop);
	if (qp >= 0) {
		set_ctrl(fd, V4L2_CID_MPEG_VIDEO_FRAME_RC_ENABLE, 0);
		set_ctrl(fd, V4L2_CID_MPEG_VIDEO_H264_I_FRAME_QP, qp);
		set_ctrl(fd, V4L2_CID_MPEG_VIDEO_H264_P_FRAME_QP, qp);
	}

	nout = setup_queue(fd, V4L2_BUF_TYPE_VIDEO_OUTPUT, out);
	ncap = setup_queue(fd, V4L2_BUF_TYPE_VIDEO_CAPTURE, cap);
	if (nout <= 0 || ncap <= 0)
		return 1;
	for (i = 0; i < ncap; i++) {
		struct v4l2_buffer vb = { .type = V4L2_BUF_TYPE_VIDEO_CAPTURE,
					  .memory = V4L2_MEMORY_MMAP, .index = i };

		if (xioctl(fd, VIDIOC_QBUF, &vb) < 0) {
			perror("QBUF cap");
			return 1;
		}
	}
	type = V4L2_BUF_TYPE_VIDEO_OUTPUT;
	if (xioctl(fd, VIDIOC_STREAMON, &type) < 0) {
		perror("STREAMON out");
		return 1;
	}
	type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	if (xioctl(fd, VIDIOC_STREAMON, &type) < 0) {
		perror("STREAMON cap");
		return 1;
	}

	t0 = now();
	/* fill all OUTPUT buffers, then one in for each one out */
	for (i = 0; i < nout && queued < frames; i++, queued++) {
		struct v4l2_buffer vb = { .type = V4L2_BUF_TYPE_VIDEO_OUTPUT,
					  .memory = V4L2_MEMORY_MMAP, .index = i };

		fill(out[i].p, fourcc, w, h, bpl, queued);
		vb.timestamp.tv_usec = queued;
		vb.bytesused = out[i].len;
		if (xioctl(fd, VIDIOC_QBUF, &vb) < 0) {
			perror("QBUF out");
			return 1;
		}
	}
	while (done < frames) {
		struct v4l2_buffer vb = { .type = V4L2_BUF_TYPE_VIDEO_CAPTURE,
					  .memory = V4L2_MEMORY_MMAP };
		struct v4l2_buffer ob = { .type = V4L2_BUF_TYPE_VIDEO_OUTPUT,
					  .memory = V4L2_MEMORY_MMAP };

		if (xioctl(fd, VIDIOC_DQBUF, &vb) < 0) {
			perror("DQBUF cap");
			return 1;
		}
		if (vb.flags & V4L2_BUF_FLAG_ERROR) {
			fprintf(stderr, "frame %d: error\n", done);
			return 1;
		}
		fwrite(cap[vb.index].p, 1, vb.bytesused, o);
		total += vb.bytesused;
		if (done < 3 || (vb.flags & V4L2_BUF_FLAG_KEYFRAME))
			printf("frame %d: %u bytes%s\n", done, vb.bytesused,
			       vb.flags & V4L2_BUF_FLAG_KEYFRAME ? " key" : "");
		done++;
		if (xioctl(fd, VIDIOC_QBUF, &vb) < 0) {
			perror("QBUF cap");
			return 1;
		}
		if (xioctl(fd, VIDIOC_DQBUF, &ob) < 0) {
			perror("DQBUF out");
			return 1;
		}
		if (queued < frames) {
			if (wait_ms)
				usleep(wait_ms * 1000);
			fill(out[ob.index].p, fourcc, w, h, bpl, queued);
			ob.timestamp.tv_usec = queued++;
			ob.bytesused = out[ob.index].len;
			if (xioctl(fd, VIDIOC_QBUF, &ob) < 0) {
				perror("QBUF out");
				return 1;
			}
		}
	}
	printf("%d frames, %zu bytes, %.1f fps (filling included), %.0f kbit/s at 30 fps\n",
	       done, total, done / (now() - t0), total * 8.0 * 30 / done / 1000);
	fclose(o);
	close(fd);
	return 0;
}
