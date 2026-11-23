/*
 * game-frame VIDEO SECONDS > FRAME.ppm: the first frame of VIDEO at or
 * after SECONDS, as a binary PPM (P6) on stdout, what "ffmpeg -ss SECONDS
 * -i VIDEO -frames:v 1" gives. The device's game_pictures.py makes covers
 * from game videos (games.manifest "cover = VIDEO.bik:SECONDS") with it:
 * the system's ffmpeg is its libraries only (no ffmpeg program, no
 * libavfilter). Decodes from the start: a cover's frame is a few seconds
 * in, and Bink's seeking is coarse.
 */
#include <stdio.h>
#include <stdlib.h>

#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/imgutils.h>
#include <libswscale/swscale.h>

static int fail(const char *what)
{
	fprintf(stderr, "game-frame: %s\n", what);
	return 1;
}

/* frames of the decoder into *last until one at or after want; 1 that one came */
static int take(AVCodecContext *cc, AVFrame *fr, AVFrame *last, int *have, int64_t want)
{
	while (avcodec_receive_frame(cc, fr) >= 0) {
		int64_t ts = fr->best_effort_timestamp;

		av_frame_unref(last);
		av_frame_move_ref(last, fr);
		*have = 1;
		if (ts != AV_NOPTS_VALUE && ts >= want)
			return 1;
	}
	return 0;
}

int main(int argc, char **argv)
{
	AVFormatContext *fc = NULL;
	const AVCodec *dec = NULL;
	AVCodecContext *cc;
	AVPacket *pkt;
	AVFrame *fr, *last;
	struct SwsContext *sw;
	uint8_t *rgb[4];
	int linesize[4], si, have = 0, done = 0;
	double t;
	int64_t want;

	if (argc != 3) {
		fprintf(stderr, "usage: game-frame VIDEO SECONDS > FRAME.ppm\n");
		return 2;
	}
	t = strtod(argv[2], NULL);
	av_log_set_level(AV_LOG_ERROR);
	if (avformat_open_input(&fc, argv[1], NULL, NULL) < 0)
		return fail("cannot open the video");
	if (avformat_find_stream_info(fc, NULL) < 0)
		return fail("no streams in it");
	si = av_find_best_stream(fc, AVMEDIA_TYPE_VIDEO, -1, -1, &dec, 0);
	if (si < 0 || !dec)
		return fail("no video stream it decodes");
	cc = avcodec_alloc_context3(dec);
	if (!cc || avcodec_parameters_to_context(cc, fc->streams[si]->codecpar) < 0 ||
	    avcodec_open2(cc, dec, NULL) < 0)
		return fail("the decoder does not open");
	want = (int64_t)(t / av_q2d(fc->streams[si]->time_base));
	pkt = av_packet_alloc();
	fr = av_frame_alloc();
	last = av_frame_alloc();
	if (!pkt || !fr || !last)
		return fail("out of memory");
	while (!done && av_read_frame(fc, pkt) >= 0) {
		if (pkt->stream_index == si && avcodec_send_packet(cc, pkt) >= 0)
			done = take(cc, fr, last, &have, want);
		av_packet_unref(pkt);
	}
	if (!done && avcodec_send_packet(cc, NULL) >= 0)	/* the decoder's last frames */
		take(cc, fr, last, &have, want);
	if (!have)
		return fail("no frame there");
	sw = sws_getContext(last->width, last->height, last->format, last->width, last->height,
			    AV_PIX_FMT_RGB24, SWS_BICUBIC, NULL, NULL, NULL);
	if (!sw || av_image_alloc(rgb, linesize, last->width, last->height, AV_PIX_FMT_RGB24, 1) < 0)
		return fail("no conversion to RGB");
	sws_scale(sw, (const uint8_t *const *)last->data, last->linesize, 0, last->height, rgb, linesize);
	printf("P6\n%d %d\n255\n", last->width, last->height);
	for (int y = 0; y < last->height; y++)
		fwrite(rgb[0] + (size_t)y * linesize[0], 3, (size_t)last->width, stdout);
	return fflush(stdout) ? fail("write") : 0;
}
