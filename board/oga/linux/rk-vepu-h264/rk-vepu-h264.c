// SPDX-License-Identifier: GPL-2.0+
/*
 * Rockchip VEPU2 (PX30/RK3326, RK3399...): the H.264 encoder of the Hantro
 * VPU as a V4L2 mem2mem stateful encoder (raw frames on OUTPUT, H.264
 * Annex B on CAPTURE). Mainline hantro drives only its JPEG part.
 *
 * The hardware encodes one picture: it converts RGB to YUV, searches the
 * motion against the one reference picture, and writes the slice with its
 * header (frame_num, idr_pic_id, QP...). The driver writes the SPS and PPS
 * in front of each IDR, keeps the reconstructed pictures (the reference)
 * and sets one QP per picture after the sizes of the last ones.
 *
 * What to write to the registers follows Rockchip's MPP (mpp/hal/vpu/h264e,
 * hal_h264e_vepu2_v2.c, Copyright 2015 Rockchip Electronics Co. LTD): the
 * picture setup, the mode penalty tables (indexed by QP), the RGB
 * conversion. The register names are those of the kernel's hantro driver.
 */

#include <linux/clk.h>
#include <linux/delay.h>
#include <linux/dma-mapping.h>
#include <linux/interrupt.h>
#include <linux/io.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/pm_runtime.h>
#include <linux/sizes.h>
#include <linux/slab.h>
#include <linux/unaligned.h>
#include <linux/workqueue.h>
#include <media/v4l2-ctrls.h>
#include <media/v4l2-device.h>
#include <media/v4l2-event.h>
#include <media/v4l2-ioctl.h>
#include <media/v4l2-mem2mem.h>
#include <media/videobuf2-dma-contig.h>

#include "vepu2_regs.h"

#define DRV_NAME	"rk-vepu-h264"

#define MIN_W		96
#define MIN_H		96
#define MAX_W		1920
#define MAX_H		1088

#define NUM_REGS	184		/* 0x000..0x2dc */
#define ACLK_RATE	(300 * 1000 * 1000)
#define TIMEOUT_MS	500
#define MAX_TRIES	3		/* encodings of a picture too big for the link */

/* the hardware writes the slice header: the SPS and PPS must agree */
#define LOG2_MAX_FRAME_NUM	16	/* frame_num is 16 bits */
#define PPS_INIT_QP		26

/* input formats of the hardware (IN_IMG_CTRL_FMT) */
#define FMT_YUV420SP	1
#define FMT_RGB888	7

static uint debug;
module_param(debug, uint, 0644);
MODULE_PARM_DESC(debug, "1: log each picture");

/* MPP's tables of mode penalties by QP (hal_h264e_vpu_tbl.c) */
static const u16 prev_mode_favor[52] = {
	7, 7, 8, 8, 9, 9, 10, 10, 11, 12, 12, 13, 14, 15, 16, 17, 18,
	19, 20, 21, 22, 24, 25, 27, 29, 30, 32, 34, 36, 38, 41, 43, 46,
	49, 51, 55, 58, 61, 65, 69, 73, 78, 82, 87, 93, 98, 104, 110,
	117, 124, 132, 140
};

static const u16 diff_mv_penalty[52] = {
	2, 2, 3, 3, 3, 4, 4, 4, 5, 6, 6, 7, 8, 9, 10, 11, 13, 14, 16, 18,
	20, 23, 26, 29, 32, 36, 40, 45, 51, 57, 64, 72, 81, 91, 102, 114,
	128, 144, 161, 181, 203, 228, 256, 287, 323, 362, 406, 456, 512,
	575, 645, 724
};

static const u16 diff_mv_penalty4p[52] = {
	2, 2, 2, 3, 3, 3, 4, 4, 5, 5, 6, 7, 8, 9, 10, 11, 12, 14, 16, 17,
	20, 22, 25, 28, 31, 35, 39, 44, 49, 55, 62, 70, 78, 88, 98, 110,
	124, 139, 156, 175, 197, 221, 248, 278, 312, 351, 394, 442, 496,
	557, 625, 701
};

static const u16 intra16_favor[52] = {
	24, 24, 24, 26, 27, 30, 32, 35, 39, 43, 48, 53, 58, 64, 71, 78,
	85, 93, 102, 111, 121, 131, 142, 154, 167, 180, 195, 211, 229,
	248, 271, 296, 326, 361, 404, 457, 523, 607, 714, 852, 1034,
	1272, 1588, 2008, 2568, 3318, 4323, 5672, 7486, 9928, 13216,
	17648
};

static const u16 inter_favor[52] = {
	0, 0, 0, 0, 0, 0, 45, 48, 51, 53, 55, 60, 62, 67, 69, 72,
	78, 84, 90, 96, 110, 120, 135, 152, 170, 189, 210, 235, 265,
	297, 335, 376, 420, 470, 522, 572, 620, 670, 724, 770, 820,
	867, 915, 970, 1020, 1076, 1132, 1180, 1230, 1275, 1320, 1370
};

static const u8 skip_sad_penalty[52] = {
	255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 233, 205, 182, 163,
	146, 132, 120, 109, 100, 92, 84, 78, 71, 66, 61, 56, 52, 48,
	44, 41, 38, 35, 32, 30, 27, 25, 23, 21, 19, 17, 15, 14,
	12, 11, 9, 8, 7, 5, 4, 3, 2, 1
};

struct vepu_fmt {
	u32 fourcc;
	u8 hw;		/* IN_IMG_CTRL_FMT */
	u8 bpp;		/* bytes per pixel of the first plane */
	u32 endian;	/* the INPUT_SWAP bits */
	u8 r, g, b;	/* RGB: the most significant bit of each colour */
};

/*
 * XBGR32 is B, G, R, X in memory: the 32-bit word X R G B, read as words
 * (only the halves of each 64 bits swapped, MPP's BGRA8888). NV12 as a
 * byte stream: all swaps.
 */
static const struct vepu_fmt vepu_formats[] = {
	{ V4L2_PIX_FMT_XBGR32, FMT_RGB888, 4, VEPU_REG_INPUT_SWAP32, 23, 15, 7 },
	{ V4L2_PIX_FMT_NV12, FMT_YUV420SP, 1,
	  VEPU_REG_INPUT_SWAP8 | VEPU_REG_INPUT_SWAP16 | VEPU_REG_INPUT_SWAP32 },
};

struct vepu_buf {
	void *cpu;
	dma_addr_t dma;
	size_t size;
};

struct vepu_dev {
	struct device *dev;
	void __iomem *regs;
	struct clk_bulk_data clks[2];
	int irq;

	struct v4l2_device v4l2_dev;
	struct video_device vfd;
	struct v4l2_m2m_dev *m2m;
	struct mutex lock;		/* ioctls, open, release */
	struct delayed_work watchdog;
	u32 shadow[NUM_REGS];		/* the registers of the next picture */
};

struct vepu_ctx {
	struct v4l2_fh fh;
	struct vepu_dev *dev;
	struct v4l2_ctrl_handler hdl;

	const struct vepu_fmt *fmt;
	u32 width, height;
	u32 bpl;			/* of the raw frame */
	u32 out_size;			/* sizeimage of the raw frame */
	u32 cap_size;
	struct v4l2_fract tpf;
	enum v4l2_colorspace colorspace;

	/* controls */
	u32 bitrate;
	u32 gop;
	bool rc;
	u32 qp_i, qp_p, qp_min, qp_max;
	bool force_key;

	/* per stream */
	struct vepu_buf rec[2];		/* reconstructed pictures: Y then UV */
	struct vepu_buf nal_tbl;	/* sizes of the NAL units, the hardware's */
	u32 mb_w, mb_h;
	int ref;			/* rec[] that holds the reference */
	u32 idr_pic_id, frame_num;
	u32 since_idr;
	u32 sequence;
	int qp;				/* of the next P picture */
	int qp_idr;			/* of the next IDR */
	s64 fullness;			/* bytes over the target, the RC buffer */

	/* the picture being encoded */
	bool idr;
	int cur_qp;
	int tries;			/* encodings of it so far */
	u32 hdr_len;			/* SPS and PPS in front of the slice */
	ktime_t t0;
};

static inline struct vepu_ctx *file_to_ctx(struct file *file)
{
	return container_of(file_to_v4l2_fh(file), struct vepu_ctx, fh);
}

static inline void vepu_write(struct vepu_dev *d, u32 val, u32 reg)
{
	writel(val, d->regs + reg);
}

static inline u32 vepu_read(struct vepu_dev *d, u32 reg)
{
	return readl(d->regs + reg);
}

static inline void reg_set(struct vepu_dev *d, u32 reg, u32 val)
{
	d->shadow[reg / 4] = val;
}

/* SPS and PPS */

struct bits {
	u8 *p;
	size_t size, pos;	/* in bits */
};

static void bit_put(struct bits *b, u32 v, int n)
{
	while (n--) {
		if (b->pos >= b->size)
			return;
		if ((v >> n) & 1)
			b->p[b->pos >> 3] |= 0x80 >> (b->pos & 7);
		b->pos++;
	}
}

static void ue_put(struct bits *b, u32 val)
{
	int n = 31 - __builtin_clz(val + 1);

	bit_put(b, 0, n);
	bit_put(b, val + 1, n + 1);
}

static void se_put(struct bits *b, int val)
{
	ue_put(b, val > 0 ? 2 * val - 1 : -2 * val);
}

static void trailing_bits(struct bits *b)
{
	bit_put(b, 1, 1);
	b->pos = ALIGN(b->pos, 8);
}

/* start code, NAL header, the RBSP with emulation prevention; the size */
static size_t nal_put(u8 *out, size_t cap, u8 header, const u8 *rbsp, size_t n)
{
	size_t i, o = 0, zeros = 0;

	if (cap < 5)
		return 0;
	out[o++] = 0;
	out[o++] = 0;
	out[o++] = 0;
	out[o++] = 1;
	out[o++] = header;
	for (i = 0; i < n && o + 2 <= cap; i++) {
		if (zeros >= 2 && rbsp[i] <= 3) {
			out[o++] = 3;
			zeros = 0;
		}
		zeros = rbsp[i] ? 0 : zeros + 1;
		out[o++] = rbsp[i];
	}
	return i < n ? 0 : o;
}

static u32 vepu_level(struct vepu_ctx *ctx)
{
	u32 fps = ctx->tpf.numerator ? ctx->tpf.denominator / ctx->tpf.numerator : 30;
	u32 mbs = ctx->mb_w * ctx->mb_h, rate = mbs * max(fps, 1u);

	if (mbs <= 1620 && rate <= 40500)
		return 30;
	if (mbs <= 3600 && rate <= 108000)
		return 31;
	if (mbs <= 5120 && rate <= 216000)
		return 32;
	return 40;
}

/*
 * Constrained Baseline, CAVLC. POC type 2 and a 16-bit frame_num, as the
 * hardware writes the slice header. The VUI says the levels are full range
 * (the RGB conversion has no offset) and that no picture waits for a later
 * one: decoders show each at once.
 */
static size_t vepu_headers(struct vepu_ctx *ctx, u8 *out, size_t cap)
{
	u8 rbsp[64];
	struct bits b = { rbsp, sizeof(rbsp) * 8, 0 };
	u32 right = (ctx->mb_w * 16 - ctx->width) / 2;
	u32 bottom = (ctx->mb_h * 16 - ctx->height) / 2;
	bool rgb = ctx->fmt->hw == FMT_RGB888;
	size_t n, total;

	memset(rbsp, 0, sizeof(rbsp));
	bit_put(&b, 66, 8);		/* profile_idc: Baseline */
	bit_put(&b, 0xc0, 8);		/* constraint_set0, set1: Constrained */
	bit_put(&b, vepu_level(ctx), 8);
	ue_put(&b, 0);			/* seq_parameter_set_id */
	ue_put(&b, LOG2_MAX_FRAME_NUM - 4);
	ue_put(&b, 2);			/* pic_order_cnt_type */
	ue_put(&b, 1);			/* max_num_ref_frames */
	bit_put(&b, 0, 1);		/* gaps_in_frame_num_value_allowed */
	ue_put(&b, ctx->mb_w - 1);
	ue_put(&b, ctx->mb_h - 1);
	bit_put(&b, 1, 1);		/* frame_mbs_only */
	bit_put(&b, 1, 1);		/* direct_8x8_inference */
	bit_put(&b, right || bottom, 1);
	if (right || bottom) {
		ue_put(&b, 0);
		ue_put(&b, right);
		ue_put(&b, 0);
		ue_put(&b, bottom);
	}
	bit_put(&b, 1, 1);		/* vui_parameters_present */
	bit_put(&b, 0, 1);		/* aspect_ratio_info_present */
	bit_put(&b, 0, 1);		/* overscan_info_present */
	bit_put(&b, 1, 1);		/* video_signal_type_present */
	bit_put(&b, 5, 3);		/* video_format: unspecified */
	bit_put(&b, rgb, 1);		/* video_full_range */
	bit_put(&b, 1, 1);		/* colour_description_present */
	bit_put(&b, 6, 8);		/* primaries: SMPTE 170M */
	bit_put(&b, 6, 8);		/* transfer: SMPTE 170M */
	bit_put(&b, 6, 8);		/* matrix: BT.601 */
	bit_put(&b, 0, 1);		/* chroma_loc_info_present */
	bit_put(&b, 0, 1);		/* timing_info_present */
	bit_put(&b, 0, 1);		/* nal_hrd_parameters_present */
	bit_put(&b, 0, 1);		/* vcl_hrd_parameters_present */
	bit_put(&b, 0, 1);		/* pic_struct_present */
	bit_put(&b, 1, 1);		/* bitstream_restriction */
	bit_put(&b, 1, 1);		/* motion_vectors_over_pic_boundaries */
	ue_put(&b, 0);			/* max_bytes_per_pic_denom */
	ue_put(&b, 0);			/* max_bits_per_mb_denom */
	ue_put(&b, 15);			/* log2_max_mv_length_horizontal */
	ue_put(&b, 15);			/* log2_max_mv_length_vertical */
	ue_put(&b, 0);			/* max_num_reorder_frames */
	ue_put(&b, 1);			/* max_dec_frame_buffering */
	trailing_bits(&b);
	total = nal_put(out, cap, 0x67, rbsp, b.pos / 8);
	if (!total)
		return 0;

	memset(rbsp, 0, sizeof(rbsp));
	b.pos = 0;
	ue_put(&b, 0);			/* pic_parameter_set_id */
	ue_put(&b, 0);			/* seq_parameter_set_id */
	bit_put(&b, 0, 1);		/* entropy_coding_mode: CAVLC */
	bit_put(&b, 0, 1);		/* bottom_field_pic_order_in_frame_present */
	ue_put(&b, 0);			/* num_slice_groups_minus1 */
	ue_put(&b, 0);			/* num_ref_idx_l0_default_active_minus1 */
	ue_put(&b, 0);			/* num_ref_idx_l1_default_active_minus1 */
	bit_put(&b, 0, 1);		/* weighted_pred */
	bit_put(&b, 0, 2);		/* weighted_bipred_idc */
	se_put(&b, PPS_INIT_QP - 26);	/* pic_init_qp_minus26 */
	se_put(&b, 0);			/* pic_init_qs_minus26 */
	se_put(&b, 0);			/* chroma_qp_index_offset */
	bit_put(&b, 1, 1);		/* deblocking_filter_control_present */
	bit_put(&b, 0, 1);		/* constrained_intra_pred */
	bit_put(&b, 0, 1);		/* redundant_pic_cnt_present */
	trailing_bits(&b);
	n = nal_put(out + total, cap - total, 0x68, rbsp, b.pos / 8);
	return n ? total + n : 0;
}

/* the picture */

static void vepu_set_regs(struct vepu_ctx *ctx, dma_addr_t src, dma_addr_t dst, u8 *dst_cpu,
			  size_t dst_size)
{
	struct vepu_dev *d = ctx->dev;
	const struct vepu_fmt *f = ctx->fmt;
	u32 mb_w = ctx->mb_w, mb_h = ctx->mb_h, qp = ctx->cur_qp;
	u32 off8 = ctx->hdr_len & ~7u, first_bit = (ctx->hdr_len - off8) * 8;
	u32 w = ctx->width, h = ctx->height, scaler, val, i;
	struct vepu_buf *rec = &ctx->rec[!ctx->ref], *ref = &ctx->rec[ctx->ref];
	u32 y_size = mb_w * mb_h * 256;

	memset(d->shadow, 0, sizeof(d->shadow));

	/* the stream goes on from the headers: their last bytes from 8 bytes */
	reg_set(d, VEPU_REG_ADDR_OUTPUT_STREAM, dst + off8);
	reg_set(d, VEPU_REG_STR_BUF_LIMIT, ((dst_size - off8) >> 3) & ~7u);
	if (first_bit) {
		reg_set(d, VEPU_REG_STR_HDR_REM_MSB, get_unaligned_be32(dst_cpu + off8));
		reg_set(d, VEPU_REG_STR_HDR_REM_LSB, get_unaligned_be32(dst_cpu + off8 + 4));
	}

	reg_set(d, VEPU_REG_AXI_CTRL, VEPU_REG_AXI_CTRL_BURST_LEN(16));

	val = VEPU_REG_H264_INTER4X4_MODE;
	if (mb_w * mb_h > 3600)
		val |= VEPU_REG_DISABLE_QUARTER_PIXEL_MV;
	reg_set(d, VEPU_REG_ENC_CTRL0, val);

	scaler = max(1u, 200 / (mb_w + mb_h));
	val = VEPU_REG_STREAM_START_OFFSET(first_bit) |
	      VEPU_REG_SKIP_MACROBLOCK_PENALTY(min(255u, skip_sad_penalty[qp] * scaler)) |
	      VEPU_REG_IN_IMG_CTRL_OVRFLR_D4((w & 15) ? (16 - (w & 15)) / 4 : 0) |
	      VEPU_REG_IN_IMG_CTRL_OVRFLB((h & 15) ? 16 - (h & 15) : 0);
	reg_set(d, VEPU_REG_ENC_OVER_FILL_STRM_OFFSET, val);

	reg_set(d, VEPU_REG_INPUT_LUMA_INFO, VEPU_REG_IN_IMG_CTRL_ROW_LEN(ctx->bpl / f->bpp));

	reg_set(d, VEPU_REG_ENC_CTRL1, VEPU_REG_IN_IMG_CTRL_FMT(f->hw) | VEPU_REG_SIZE_TABLE_PRESENT);
	reg_set(d, VEPU_REG_INTRA_INTER_MODE,
		VEPU_REG_INTRA16X16_MODE(intra16_favor[qp]) | VEPU_REG_INTER_MODE(inter_favor[qp]));
	reg_set(d, VEPU_REG_ENC_CTRL2,
		VEPU_REG_PPS_INIT_QP(PPS_INIT_QP) | VEPU_REG_IDR_PIC_ID(ctx->idr_pic_id));

	reg_set(d, VEPU_REG_ADDR_OUTPUT_CTRL, ctx->nal_tbl.dma);

	/* no regions of interest: both outside the picture */
	val = VEPU_REG_ROI1_TOP_MB(mb_h) | VEPU_REG_ROI1_BOTTOM_MB(mb_h) |
	      VEPU_REG_ROI1_LEFT_MB(mb_w) | VEPU_REG_ROI1_RIGHT_MB(mb_w);
	reg_set(d, VEPU_REG_ROI1, val);
	reg_set(d, VEPU_REG_ROI2, val);

	if (f->hw == FMT_RGB888) {
		/* BT.601, full range (MPP's MPP_FRAME_SPC_RGB) */
		reg_set(d, VEPU_REG_RGB2YUV_CONVERSION_COEF1,
			VEPU_REG_RGB2YUV_CONVERSION_COEFB(38443) |
			VEPU_REG_RGB2YUV_CONVERSION_COEFA(19589));
		reg_set(d, VEPU_REG_RGB2YUV_CONVERSION_COEF2,
			VEPU_REG_RGB2YUV_CONVERSION_COEFE(37008) |
			VEPU_REG_RGB2YUV_CONVERSION_COEFC(7504));
		reg_set(d, VEPU_REG_RGB2YUV_CONVERSION_COEF3,
			VEPU_REG_RGB2YUV_CONVERSION_COEFF(46740));
		reg_set(d, VEPU_REG_RGB_MASK_MSB, VEPU_REG_RGB_MASK_B_MSB(f->b) |
			VEPU_REG_RGB_MASK_G_MSB(f->g) | VEPU_REG_RGB_MASK_R_MSB(f->r));
	}

	reg_set(d, VEPU_REG_MV_PENALTY,
		VEPU_REG_1MV_PENALTY(diff_mv_penalty[qp]) | VEPU_REG_QMV_PENALTY(diff_mv_penalty[qp]) |
		VEPU_REG_4MV_PENALTY(diff_mv_penalty4p[qp]) | VEPU_REG_SPLIT_MV_MODE_EN);
	reg_set(d, VEPU_REG_QP_VAL, VEPU_REG_H264_LUMA_INIT_QP(qp) |
		VEPU_REG_H264_QP_MAX(ctx->qp_max) | VEPU_REG_H264_QP_MIN(ctx->qp_min));
	reg_set(d, VEPU_REG_MVC_RELATE, VEPU_REG_ZERO_MV_FAVOR_D2(10));
	reg_set(d, VEPU_REG_DATA_ENDIAN, VEPU_REG_OUTPUT_SWAP32 | VEPU_REG_OUTPUT_SWAP16 |
		VEPU_REG_OUTPUT_SWAP8 | f->endian);
	reg_set(d, VEPU_REG_ENC_CTRL3, VEPU_REG_PPS_ID(0) |
		VEPU_REG_INTRA_PRED_MODE(prev_mode_favor[qp]) | VEPU_REG_FRAME_NUM(ctx->frame_num));
	reg_set(d, VEPU_REG_INTERRUPT, VEPU_REG_INTERRUPT_TIMEOUT_EN);

	/* motion vector penalties: the difference, its exp-Golomb length */
	for (i = 0; i < 128; i += 4) {
		u32 j, p = 0, q = 0;

		for (j = 0; j < 4; j++) {
			u32 v = 2 * (i + j), len = 1;

			while (v >> len)
				len++;
			p |= (i + j) << (8 * (3 - j));
			q |= min(255u, 2 * len - 1) << (8 * (3 - j));
		}
		reg_set(d, VEPU_REG_DMV_PENALTY_TBL(i / 4), p);
		reg_set(d, VEPU_REG_DMV_Q_PIXEL_PENALTY_TBL(i / 4), q);
	}

	reg_set(d, VEPU_REG_ADDR_IN_PLANE_0, src);
	if (f->hw == FMT_YUV420SP)
		reg_set(d, VEPU_REG_ADDR_IN_PLANE_1, src + ctx->bpl * ALIGN(h, 16));

	reg_set(d, VEPU_REG_ADDR_REC_LUMA, rec->dma);
	reg_set(d, VEPU_REG_ADDR_REC_CHROMA, rec->dma + y_size);
	reg_set(d, VEPU_REG_ADDR_REF_LUMA, ref->dma);
	reg_set(d, VEPU_REG_ADDR_REF_CHROMA, ref->dma + y_size);

	reg_set(d, VEPU_REG_ENCODE_START, VEPU_REG_MB_HEIGHT(mb_h) | VEPU_REG_MB_WIDTH(mb_w) |
		(ctx->idr ? VEPU_REG_FRAME_TYPE_INTRA : VEPU_REG_FRAME_TYPE_INTER) |
		VEPU_REG_ENCODE_FORMAT_H264 | VEPU_REG_ENCODE_ENABLE);
}

static void vepu_start(struct vepu_dev *d)
{
	u32 i, start = VEPU_REG_ENCODE_START / 4;

	/* the format first: it selects what the other registers mean */
	vepu_write(d, VEPU_REG_ENCODE_FORMAT_H264, VEPU_REG_ENCODE_START);
	for (i = 0; i < NUM_REGS; i++)
		if (i != start)
			writel_relaxed(d->shadow[i], d->regs + 4 * i);
	vepu_write(d, d->shadow[start], VEPU_REG_ENCODE_START);
}

static void vepu_reset(struct vepu_dev *d)
{
	vepu_write(d, VEPU_REG_INTERRUPT_DIS_BIT, VEPU_REG_INTERRUPT);
	vepu_write(d, 0, VEPU_REG_ENCODE_START);
	vepu_write(d, 0, VEPU_REG_AXI_CTRL);
}

/* rate control */

/* the step of QP for a picture of bytes where aim was wanted */
static int rc_step(s64 bytes, s64 aim)
{
	if (bytes > aim * 2)
		return 3;
	if (bytes > aim * 3 / 2)
		return 2;
	if (bytes > aim * 23 / 20)
		return 1;
	if (bytes < aim * 2 / 5)
		return -2;
	if (bytes < aim * 17 / 20)
		return -1;
	return 0;
}

/*
 * One QP per picture after the bytes of the last ones. P pictures aim at
 * bitrate / fps, IDRs at four times that, each type with its own QP: an
 * IDR after a still screen (P pictures of a few bytes at the lowest QP)
 * would be huge at the QP of those.
 */
static s64 vepu_target(struct vepu_ctx *ctx)
{
	u32 fps = ctx->tpf.numerator ? ctx->tpf.denominator / ctx->tpf.numerator : 30;

	return max_t(s64, ctx->bitrate / 8 / max(fps, 1u), 64);
}

static void vepu_rc(struct vepu_ctx *ctx, bool idr, u32 bytes)
{
	s64 target = vepu_target(ctx);
	s64 lim = (s64)ctx->bitrate / 8;
	int step;

	if (!ctx->rc)
		return;
	ctx->fullness = clamp_t(s64, ctx->fullness + bytes - target, -lim / 2, lim);
	if (idr) {
		ctx->qp_idr += rc_step(bytes, target * 4);
	} else {
		step = rc_step(bytes, target);
		if (ctx->fullness > target * 4 && step < 1)
			step = 1;
		else if (ctx->fullness < -target * 4 && step > -1)
			step = -1;
		ctx->qp = clamp_t(int, ctx->qp + step, ctx->qp_min, ctx->qp_max);
	}
	/* not much finer than the P pictures; coarser as it needs: a still
	 * screen keeps P pictures at the lowest QP, not IDRs */
	ctx->qp_idr = clamp_t(int, ctx->qp_idr, max_t(int, ctx->qp - 6, ctx->qp_min), ctx->qp_max);
}

/* m2m */

static void vepu_device_run(void *priv)
{
	struct vepu_ctx *ctx = priv;
	struct vepu_dev *d = ctx->dev;
	struct vb2_v4l2_buffer *src = v4l2_m2m_next_src_buf(ctx->fh.m2m_ctx);
	struct vb2_v4l2_buffer *dst = v4l2_m2m_next_dst_buf(ctx->fh.m2m_ctx);
	u8 *out = vb2_plane_vaddr(&dst->vb2_buf, 0);
	size_t cap = vb2_plane_size(&dst->vb2_buf, 0);
	int ret;

	ctx->t0 = ktime_get();
	ctx->tries = 1;
	ctx->idr = ctx->since_idr == 0 || ctx->since_idr >= ctx->gop || ctx->force_key;
	if (ctx->rc)
		ctx->cur_qp = ctx->idr ? ctx->qp_idr : ctx->qp;
	else
		ctx->cur_qp = ctx->idr ? ctx->qp_i : ctx->qp_p;
	ctx->cur_qp = clamp_t(int, ctx->cur_qp, ctx->qp_min, ctx->qp_max);
	if (ctx->idr) {
		ctx->frame_num = 0;
		ctx->force_key = false;
	}

	ctx->hdr_len = 0;
	if (!out || cap < SZ_64K) {
		ret = -EINVAL;
		goto fail;
	}
	if (ctx->idr) {
		ctx->hdr_len = vepu_headers(ctx, out, 256);
		if (!ctx->hdr_len) {
			ret = -EINVAL;
			goto fail;
		}
	}

	ret = pm_runtime_resume_and_get(d->dev);
	if (ret < 0)
		goto fail;
	ret = clk_bulk_enable(ARRAY_SIZE(d->clks), d->clks);
	if (ret) {
		pm_runtime_put_autosuspend(d->dev);
		goto fail;
	}
	vepu_set_regs(ctx, vb2_dma_contig_plane_dma_addr(&src->vb2_buf, 0),
		      vb2_dma_contig_plane_dma_addr(&dst->vb2_buf, 0), out, cap);
	schedule_delayed_work(&d->watchdog, msecs_to_jiffies(TIMEOUT_MS));
	vepu_start(d);
	return;
fail:
	dev_err(d->dev, "picture not started: %d\n", ret);
	v4l2_m2m_buf_done_and_job_finish(d->m2m, ctx->fh.m2m_ctx, VB2_BUF_STATE_ERROR);
}

/*
 * A picture far over its share of the bit rate (a new screen coded as P,
 * mostly intra blocks) goes out as a burst the Wi-Fi link drops packets
 * of; one that does not fit the buffer is lost. Either is encoded again
 * (the reference is only read, the reconstruction written again), QP up by
 * 5 for each halving it needs: 6 would halve the bits, 5 errs on quality
 * and leaves the third try for what still does not fit. Called with the
 * clocks on; true: started.
 */
static bool vepu_retry(struct vepu_dev *d, struct vepu_ctx *ctx, u32 status, u32 bytes)
{
	struct vb2_v4l2_buffer *src, *dst;
	s64 limit, left = bytes;
	int step = 0;

	if (!ctx || ctx->tries >= MAX_TRIES || ctx->cur_qp >= (int)ctx->qp_max)
		return false;
	limit = vepu_target(ctx) * (ctx->idr ? 8 : 4);
	if (status & VEPU_REG_INTERRUPT_BUFFER_FULL)
		step = 8;
	else if (!(status & VEPU_REG_INTERRUPT_FRAME_READY) || !ctx->rc || bytes <= limit)
		return false;
	for (; left > limit; left /= 2)
		step += 5;
	if (debug)
		dev_info(d->dev, "%s qp %d: %u bytes, again at qp %d\n", ctx->idr ? "IDR" : "P",
			 ctx->cur_qp, bytes, min_t(int, ctx->cur_qp + step, ctx->qp_max));
	ctx->cur_qp = min_t(int, ctx->cur_qp + step, ctx->qp_max);
	ctx->tries++;
	src = v4l2_m2m_next_src_buf(ctx->fh.m2m_ctx);
	dst = v4l2_m2m_next_dst_buf(ctx->fh.m2m_ctx);
	vepu_set_regs(ctx, vb2_dma_contig_plane_dma_addr(&src->vb2_buf, 0),
		      vb2_dma_contig_plane_dma_addr(&dst->vb2_buf, 0), vb2_plane_vaddr(&dst->vb2_buf, 0),
		      vb2_plane_size(&dst->vb2_buf, 0));
	schedule_delayed_work(&d->watchdog, msecs_to_jiffies(TIMEOUT_MS));
	vepu_start(d);
	return true;
}

/* the end of a picture: from the interrupt or the watchdog */
static void vepu_done(struct vepu_dev *d, u32 status)
{
	struct vepu_ctx *ctx = v4l2_m2m_get_curr_priv(d->m2m);
	struct vb2_v4l2_buffer *src, *dst;
	bool ok = status & VEPU_REG_INTERRUPT_FRAME_READY;
	u32 bytes = 0;

	if (ok && ctx)
		bytes = (ctx->hdr_len & ~7u) + vepu_read(d, VEPU_REG_STR_BUF_LIMIT) / 8;
	if (vepu_retry(d, ctx, status, bytes))
		return;
	clk_bulk_disable(ARRAY_SIZE(d->clks), d->clks);
	pm_runtime_put_autosuspend(d->dev);
	if (!ctx)
		return;
	src = v4l2_m2m_next_src_buf(ctx->fh.m2m_ctx);
	dst = v4l2_m2m_next_dst_buf(ctx->fh.m2m_ctx);

	if (ok && bytes <= vb2_plane_size(&dst->vb2_buf, 0)) {
		/* the reference of the next one is the picture just built */
		ctx->ref = !ctx->ref;
		if (ctx->idr) {
			ctx->idr_pic_id = (ctx->idr_pic_id + 1) & 0xf;
			ctx->since_idr = 0;
		}
		ctx->since_idr++;
		ctx->frame_num = (ctx->frame_num + 1) & ((1u << LOG2_MAX_FRAME_NUM) - 1);
		if (ctx->tries > 1) {
			/* the QP that fitted is where the next ones start from */
			if (ctx->idr)
				ctx->qp_idr = ctx->cur_qp;
			else
				ctx->qp = ctx->cur_qp;
		}
		vepu_rc(ctx, ctx->idr, bytes - ctx->hdr_len);
		/*
		 * After a still screen P pictures are at the lowest QP: the one
		 * after an IDR at a higher QP would code the whole picture over
		 * again, finer, as big as the IDR. From near its QP, then down.
		 */
		if (ctx->idr && ctx->rc)
			ctx->qp = clamp_t(int, ctx->qp, ctx->cur_qp - 3, ctx->qp_max);
		vb2_set_plane_payload(&dst->vb2_buf, 0, bytes);
		dst->flags &= ~(V4L2_BUF_FLAG_KEYFRAME | V4L2_BUF_FLAG_PFRAME);
		dst->flags |= ctx->idr ? V4L2_BUF_FLAG_KEYFRAME : V4L2_BUF_FLAG_PFRAME;
		if (debug)
			dev_info(d->dev, "%s qp %d: %u bytes, %lld us%s\n", ctx->idr ? "IDR" : "P",
				 ctx->cur_qp, bytes, ktime_us_delta(ktime_get(), ctx->t0),
				 ctx->tries > 1 ? ", encoded again" : "");
	} else {
		dev_warn(d->dev, "%s picture failed: status %#x\n", ctx->idr ? "IDR" : "P", status);
		/* the reference may be broken: start again from an IDR */
		ctx->since_idr = 0;
		if (status & VEPU_REG_INTERRUPT_BUFFER_FULL) {
			ctx->qp = min_t(int, ctx->qp + 4, ctx->qp_max);
			ctx->qp_idr = min_t(int, ctx->qp_idr + 4, ctx->qp_max);
		}
		vb2_set_plane_payload(&dst->vb2_buf, 0, 0);
		ok = false;
	}
	v4l2_m2m_buf_copy_metadata(src, dst);
	dst->sequence = ctx->sequence++;
	v4l2_m2m_buf_done_and_job_finish(d->m2m, ctx->fh.m2m_ctx,
					 ok ? VB2_BUF_STATE_DONE : VB2_BUF_STATE_ERROR);
}

static irqreturn_t vepu_irq(int irq, void *data)
{
	struct vepu_dev *d = data;
	u32 status = vepu_read(d, VEPU_REG_INTERRUPT);

	if (!(status & VEPU_REG_INTERRUPT_BIT))
		return IRQ_NONE;
	vepu_write(d, 0, VEPU_REG_INTERRUPT);
	vepu_write(d, 0, VEPU_REG_AXI_CTRL);
	if (!cancel_delayed_work(&d->watchdog))
		return IRQ_HANDLED;	/* the watchdog has it */
	vepu_done(d, status);
	return IRQ_HANDLED;
}

static void vepu_watchdog(struct work_struct *work)
{
	struct vepu_dev *d = container_of(work, struct vepu_dev, watchdog.work);

	dev_warn(d->dev, "timeout: status %#x\n", vepu_read(d, VEPU_REG_INTERRUPT));
	vepu_reset(d);
	vepu_done(d, 0);
}

static const struct v4l2_m2m_ops vepu_m2m_ops = {
	.device_run = vepu_device_run,
};

/* buffers of a stream */

static void vepu_free(struct vepu_dev *d, struct vepu_buf *b)
{
	if (b->cpu)
		dma_free_coherent(d->dev, b->size, b->cpu, b->dma);
	b->cpu = NULL;
}

static int vepu_alloc(struct vepu_dev *d, struct vepu_buf *b, size_t size)
{
	b->size = PAGE_ALIGN(size);
	b->cpu = dma_alloc_coherent(d->dev, b->size, &b->dma, GFP_KERNEL);
	return b->cpu ? 0 : -ENOMEM;
}

static void vepu_free_all(struct vepu_ctx *ctx)
{
	vepu_free(ctx->dev, &ctx->rec[0]);
	vepu_free(ctx->dev, &ctx->rec[1]);
	vepu_free(ctx->dev, &ctx->nal_tbl);
}

static int vepu_alloc_all(struct vepu_ctx *ctx)
{
	struct vepu_dev *d = ctx->dev;
	u32 size;
	int ret;

	ctx->mb_w = DIV_ROUND_UP(ctx->width, 16);
	ctx->mb_h = DIV_ROUND_UP(ctx->height, 16);
	size = ctx->mb_w * ctx->mb_h * 256 * 3 / 2;
	ret = vepu_alloc(d, &ctx->rec[0], size);
	ret = ret ?: vepu_alloc(d, &ctx->rec[1], size);
	ret = ret ?: vepu_alloc(d, &ctx->nal_tbl, ALIGN((ctx->mb_h + 1) * 4, 8));
	if (ret)
		vepu_free_all(ctx);
	return ret;
}

/* vb2 */

static int vepu_queue_setup(struct vb2_queue *q, unsigned int *nbufs,
			    unsigned int *nplanes, unsigned int sizes[],
			    struct device *alloc_devs[])
{
	struct vepu_ctx *ctx = vb2_get_drv_priv(q);
	u32 size = V4L2_TYPE_IS_OUTPUT(q->type) ? ctx->out_size : ctx->cap_size;

	if (*nplanes)
		return sizes[0] < size ? -EINVAL : 0;
	*nplanes = 1;
	sizes[0] = size;
	return 0;
}

static int vepu_buf_prepare(struct vb2_buffer *vb)
{
	struct vepu_ctx *ctx = vb2_get_drv_priv(vb->vb2_queue);
	bool out = V4L2_TYPE_IS_OUTPUT(vb->vb2_queue->type);
	u32 size = out ? ctx->out_size : ctx->cap_size;

	if (vb2_plane_size(vb, 0) < size)
		return -EINVAL;
	if (out)
		vb2_set_plane_payload(vb, 0, size);
	return 0;
}

static void vepu_buf_queue(struct vb2_buffer *vb)
{
	struct vepu_ctx *ctx = vb2_get_drv_priv(vb->vb2_queue);

	v4l2_m2m_buf_queue(ctx->fh.m2m_ctx, to_vb2_v4l2_buffer(vb));
}

static void vepu_return_bufs(struct vepu_ctx *ctx, struct vb2_queue *q,
			     enum vb2_buffer_state state)
{
	struct vb2_v4l2_buffer *vb;

	for (;;) {
		vb = V4L2_TYPE_IS_OUTPUT(q->type) ? v4l2_m2m_src_buf_remove(ctx->fh.m2m_ctx) :
						    v4l2_m2m_dst_buf_remove(ctx->fh.m2m_ctx);
		if (!vb)
			break;
		v4l2_m2m_buf_done(vb, state);
	}
}

static int vepu_start_streaming(struct vb2_queue *q, unsigned int count)
{
	struct vepu_ctx *ctx = vb2_get_drv_priv(q);
	int ret;

	if (!V4L2_TYPE_IS_OUTPUT(q->type)) {
		ctx->sequence = 0;
		return 0;
	}
	ret = vepu_alloc_all(ctx);
	if (ret) {
		dev_err(ctx->dev->dev, "start: %d\n", ret);
		vepu_return_bufs(ctx, q, VB2_BUF_STATE_QUEUED);
		return ret;
	}
	ctx->since_idr = 0;
	ctx->idr_pic_id = 0;
	ctx->frame_num = 0;
	ctx->ref = 0;
	ctx->qp = ctx->qp_p;
	ctx->qp_idr = max_t(int, ctx->qp_p - 2, ctx->qp_min);
	ctx->fullness = 0;
	return 0;
}

static void vepu_stop_streaming(struct vb2_queue *q)
{
	struct vepu_ctx *ctx = vb2_get_drv_priv(q);

	vepu_return_bufs(ctx, q, VB2_BUF_STATE_ERROR);
	if (V4L2_TYPE_IS_OUTPUT(q->type))
		vepu_free_all(ctx);
}

static const struct vb2_ops vepu_qops = {
	.queue_setup = vepu_queue_setup,
	.buf_prepare = vepu_buf_prepare,
	.buf_queue = vepu_buf_queue,
	.start_streaming = vepu_start_streaming,
	.stop_streaming = vepu_stop_streaming,
};

static int vepu_queue_init(void *priv, struct vb2_queue *src, struct vb2_queue *dst)
{
	struct vepu_ctx *ctx = priv;
	int ret;

	src->type = V4L2_BUF_TYPE_VIDEO_OUTPUT;
	src->io_modes = VB2_MMAP | VB2_DMABUF;
	src->drv_priv = ctx;
	src->buf_struct_size = sizeof(struct v4l2_m2m_buffer);
	src->ops = &vepu_qops;
	src->mem_ops = &vb2_dma_contig_memops;
	src->dma_attrs = DMA_ATTR_ALLOC_SINGLE_PAGES | DMA_ATTR_NO_KERNEL_MAPPING;
	src->timestamp_flags = V4L2_BUF_FLAG_TIMESTAMP_COPY;
	src->lock = &ctx->dev->lock;
	src->dev = ctx->dev->dev;
	ret = vb2_queue_init(src);
	if (ret)
		return ret;

	/* the driver writes the SPS and PPS: mapped in the kernel too */
	dst->type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	dst->io_modes = VB2_MMAP | VB2_DMABUF;
	dst->drv_priv = ctx;
	dst->buf_struct_size = sizeof(struct v4l2_m2m_buffer);
	dst->ops = &vepu_qops;
	dst->mem_ops = &vb2_dma_contig_memops;
	dst->dma_attrs = DMA_ATTR_ALLOC_SINGLE_PAGES;
	dst->timestamp_flags = V4L2_BUF_FLAG_TIMESTAMP_COPY;
	dst->lock = &ctx->dev->lock;
	dst->dev = ctx->dev->dev;
	return vb2_queue_init(dst);
}

/* formats */

static const struct vepu_fmt *vepu_find_fmt(u32 fourcc)
{
	int i;

	for (i = 0; i < ARRAY_SIZE(vepu_formats); i++)
		if (vepu_formats[i].fourcc == fourcc)
			return &vepu_formats[i];
	return NULL;
}

/* the hardware reads whole macroblocks: 16-pixel rows, some rows more */
static void vepu_out_layout(const struct vepu_fmt *f, u32 w, u32 h, u32 *bpl, u32 *size)
{
	*bpl = ALIGN(w, 16) * f->bpp;
	*size = *bpl * ALIGN(h, 16);
	if (f->hw == FMT_YUV420SP)
		*size = *size * 3 / 2;
}

static u32 vepu_default_cap_size(u32 w, u32 h)
{
	return max_t(u32, SZ_512K, ALIGN(w * h * 3 / 4, SZ_4K));
}

static int vepu_querycap(struct file *file, void *priv, struct v4l2_capability *cap)
{
	strscpy(cap->driver, DRV_NAME, sizeof(cap->driver));
	strscpy(cap->card, "Rockchip VEPU2 H.264 encoder", sizeof(cap->card));
	strscpy(cap->bus_info, "platform:" DRV_NAME, sizeof(cap->bus_info));
	return 0;
}

static int vepu_enum_fmt_out(struct file *file, void *priv, struct v4l2_fmtdesc *f)
{
	if (f->index >= ARRAY_SIZE(vepu_formats))
		return -EINVAL;
	f->pixelformat = vepu_formats[f->index].fourcc;
	return 0;
}

static int vepu_enum_fmt_cap(struct file *file, void *priv, struct v4l2_fmtdesc *f)
{
	if (f->index)
		return -EINVAL;
	f->pixelformat = V4L2_PIX_FMT_H264;
	f->flags = V4L2_FMT_FLAG_COMPRESSED;
	return 0;
}

static int vepu_enum_framesizes(struct file *file, void *priv, struct v4l2_frmsizeenum *fs)
{
	if (fs->index || (fs->pixel_format != V4L2_PIX_FMT_H264 &&
			  !vepu_find_fmt(fs->pixel_format)))
		return -EINVAL;
	fs->type = V4L2_FRMSIZE_TYPE_STEPWISE;
	fs->stepwise.min_width = MIN_W;
	fs->stepwise.max_width = MAX_W;
	fs->stepwise.step_width = 2;
	fs->stepwise.min_height = MIN_H;
	fs->stepwise.max_height = MAX_H;
	fs->stepwise.step_height = 2;
	return 0;
}

static void vepu_fill_colors(struct vepu_ctx *ctx, struct v4l2_pix_format *p)
{
	p->field = V4L2_FIELD_NONE;
	p->colorspace = ctx->colorspace;
	p->xfer_func = V4L2_XFER_FUNC_DEFAULT;
	p->ycbcr_enc = V4L2_YCBCR_ENC_601;
	p->quantization = V4L2_QUANTIZATION_DEFAULT;
}

static int vepu_g_fmt_out(struct file *file, void *priv, struct v4l2_format *f)
{
	struct vepu_ctx *ctx = file_to_ctx(file);
	struct v4l2_pix_format *p = &f->fmt.pix;

	p->width = ctx->width;
	p->height = ctx->height;
	p->pixelformat = ctx->fmt->fourcc;
	p->bytesperline = ctx->bpl;
	p->sizeimage = ctx->out_size;
	vepu_fill_colors(ctx, p);
	return 0;
}

static int vepu_g_fmt_cap(struct file *file, void *priv, struct v4l2_format *f)
{
	struct vepu_ctx *ctx = file_to_ctx(file);
	struct v4l2_pix_format *p = &f->fmt.pix;

	p->width = ctx->width;
	p->height = ctx->height;
	p->pixelformat = V4L2_PIX_FMT_H264;
	p->bytesperline = 0;
	p->sizeimage = ctx->cap_size;
	vepu_fill_colors(ctx, p);
	return 0;
}

static int vepu_try_fmt_out(struct file *file, void *priv, struct v4l2_format *f)
{
	struct v4l2_pix_format *p = &f->fmt.pix;
	const struct vepu_fmt *fmt = vepu_find_fmt(p->pixelformat);

	if (!fmt) {
		fmt = &vepu_formats[0];
		p->pixelformat = fmt->fourcc;
	}
	p->width = clamp(ALIGN(p->width, 2), (u32)MIN_W, (u32)MAX_W);
	p->height = clamp(ALIGN(p->height, 2), (u32)MIN_H, (u32)MAX_H);
	p->field = V4L2_FIELD_NONE;
	vepu_out_layout(fmt, p->width, p->height, &p->bytesperline, &p->sizeimage);
	return 0;
}

static int vepu_try_fmt_cap(struct file *file, void *priv, struct v4l2_format *f)
{
	struct vepu_ctx *ctx = file_to_ctx(file);
	struct v4l2_pix_format *p = &f->fmt.pix;

	p->pixelformat = V4L2_PIX_FMT_H264;
	p->width = ctx->width;
	p->height = ctx->height;
	p->bytesperline = 0;
	p->sizeimage = clamp_t(u32, p->sizeimage, vepu_default_cap_size(p->width, p->height),
			       SZ_4M);
	vepu_fill_colors(ctx, p);
	return 0;
}

static int vepu_s_fmt_out(struct file *file, void *priv, struct v4l2_format *f)
{
	struct vepu_ctx *ctx = file_to_ctx(file);
	struct v4l2_pix_format *p = &f->fmt.pix;
	int ret;

	if (vb2_is_busy(v4l2_m2m_get_vq(ctx->fh.m2m_ctx, f->type)))
		return -EBUSY;
	ret = vepu_try_fmt_out(file, priv, f);
	if (ret)
		return ret;
	ctx->fmt = vepu_find_fmt(p->pixelformat);
	ctx->width = p->width;
	ctx->height = p->height;
	ctx->bpl = p->bytesperline;
	ctx->out_size = p->sizeimage;
	ctx->colorspace = p->colorspace ?: V4L2_COLORSPACE_SMPTE170M;
	ctx->cap_size = vepu_default_cap_size(ctx->width, ctx->height);
	vepu_fill_colors(ctx, p);
	return 0;
}

static int vepu_s_fmt_cap(struct file *file, void *priv, struct v4l2_format *f)
{
	struct vepu_ctx *ctx = file_to_ctx(file);
	int ret;

	if (vb2_is_busy(v4l2_m2m_get_vq(ctx->fh.m2m_ctx, f->type)))
		return -EBUSY;
	ret = vepu_try_fmt_cap(file, priv, f);
	if (ret)
		return ret;
	ctx->cap_size = f->fmt.pix.sizeimage;
	return 0;
}

static int vepu_g_parm(struct file *file, void *priv, struct v4l2_streamparm *a)
{
	struct vepu_ctx *ctx = file_to_ctx(file);

	if (a->type == V4L2_BUF_TYPE_VIDEO_OUTPUT) {
		a->parm.output.capability = V4L2_CAP_TIMEPERFRAME;
		a->parm.output.timeperframe = ctx->tpf;
	} else if (a->type == V4L2_BUF_TYPE_VIDEO_CAPTURE) {
		a->parm.capture.capability = V4L2_CAP_TIMEPERFRAME;
		a->parm.capture.timeperframe = ctx->tpf;
	} else {
		return -EINVAL;
	}
	return 0;
}

static int vepu_s_parm(struct file *file, void *priv, struct v4l2_streamparm *a)
{
	struct vepu_ctx *ctx = file_to_ctx(file);
	struct v4l2_fract *t = a->type == V4L2_BUF_TYPE_VIDEO_OUTPUT ?
		&a->parm.output.timeperframe : &a->parm.capture.timeperframe;

	if (a->type != V4L2_BUF_TYPE_VIDEO_OUTPUT && a->type != V4L2_BUF_TYPE_VIDEO_CAPTURE)
		return -EINVAL;
	if (t->numerator && t->denominator)
		ctx->tpf = *t;
	return vepu_g_parm(file, priv, a);
}

static const struct v4l2_ioctl_ops vepu_ioctl_ops = {
	.vidioc_querycap = vepu_querycap,
	.vidioc_enum_fmt_vid_cap = vepu_enum_fmt_cap,
	.vidioc_enum_fmt_vid_out = vepu_enum_fmt_out,
	.vidioc_g_fmt_vid_cap = vepu_g_fmt_cap,
	.vidioc_g_fmt_vid_out = vepu_g_fmt_out,
	.vidioc_try_fmt_vid_cap = vepu_try_fmt_cap,
	.vidioc_try_fmt_vid_out = vepu_try_fmt_out,
	.vidioc_s_fmt_vid_cap = vepu_s_fmt_cap,
	.vidioc_s_fmt_vid_out = vepu_s_fmt_out,
	.vidioc_enum_framesizes = vepu_enum_framesizes,
	.vidioc_g_parm = vepu_g_parm,
	.vidioc_s_parm = vepu_s_parm,

	.vidioc_reqbufs = v4l2_m2m_ioctl_reqbufs,
	.vidioc_querybuf = v4l2_m2m_ioctl_querybuf,
	.vidioc_qbuf = v4l2_m2m_ioctl_qbuf,
	.vidioc_dqbuf = v4l2_m2m_ioctl_dqbuf,
	.vidioc_prepare_buf = v4l2_m2m_ioctl_prepare_buf,
	.vidioc_create_bufs = v4l2_m2m_ioctl_create_bufs,
	.vidioc_expbuf = v4l2_m2m_ioctl_expbuf,
	.vidioc_streamon = v4l2_m2m_ioctl_streamon,
	.vidioc_streamoff = v4l2_m2m_ioctl_streamoff,

	.vidioc_subscribe_event = v4l2_ctrl_subscribe_event,
	.vidioc_unsubscribe_event = v4l2_event_unsubscribe,
};

/* controls */

static int vepu_s_ctrl(struct v4l2_ctrl *c)
{
	struct vepu_ctx *ctx = container_of(c->handler, struct vepu_ctx, hdl);

	switch (c->id) {
	case V4L2_CID_MPEG_VIDEO_BITRATE:
		ctx->bitrate = c->val;
		break;
	case V4L2_CID_MPEG_VIDEO_GOP_SIZE:
		ctx->gop = c->val;
		break;
	case V4L2_CID_MPEG_VIDEO_FRAME_RC_ENABLE:
		ctx->rc = c->val;
		break;
	case V4L2_CID_MPEG_VIDEO_H264_I_FRAME_QP:
		ctx->qp_i = c->val;
		break;
	case V4L2_CID_MPEG_VIDEO_H264_P_FRAME_QP:
		ctx->qp_p = c->val;
		break;
	case V4L2_CID_MPEG_VIDEO_H264_MIN_QP:
		ctx->qp_min = c->val;
		break;
	case V4L2_CID_MPEG_VIDEO_H264_MAX_QP:
		ctx->qp_max = c->val;
		break;
	case V4L2_CID_MPEG_VIDEO_FORCE_KEY_FRAME:
		ctx->force_key = true;
		break;
	case V4L2_CID_MPEG_VIDEO_HEADER_MODE:
		break;
	default:
		return -EINVAL;
	}
	return 0;
}

static const struct v4l2_ctrl_ops vepu_ctrl_ops = {
	.s_ctrl = vepu_s_ctrl,
};

static int vepu_init_ctrls(struct vepu_ctx *ctx)
{
	struct v4l2_ctrl_handler *h = &ctx->hdl;
	const struct v4l2_ctrl_ops *o = &vepu_ctrl_ops;

	v4l2_ctrl_handler_init(h, 10);
	v4l2_ctrl_new_std(h, o, V4L2_CID_MPEG_VIDEO_BITRATE, 100000, 20000000, 1, 2000000);
	v4l2_ctrl_new_std(h, o, V4L2_CID_MPEG_VIDEO_GOP_SIZE, 1, 1000, 1, 60);
	v4l2_ctrl_new_std(h, o, V4L2_CID_MPEG_VIDEO_FRAME_RC_ENABLE, 0, 1, 1, 1);
	v4l2_ctrl_new_std(h, o, V4L2_CID_MPEG_VIDEO_H264_I_FRAME_QP, 0, 51, 1, 26);
	v4l2_ctrl_new_std(h, o, V4L2_CID_MPEG_VIDEO_H264_P_FRAME_QP, 0, 51, 1, 28);
	v4l2_ctrl_new_std(h, o, V4L2_CID_MPEG_VIDEO_H264_MIN_QP, 0, 51, 1, 12);
	v4l2_ctrl_new_std(h, o, V4L2_CID_MPEG_VIDEO_H264_MAX_QP, 0, 51, 1, 46);
	v4l2_ctrl_new_std(h, o, V4L2_CID_MPEG_VIDEO_FORCE_KEY_FRAME, 0, 0, 0, 0);
	v4l2_ctrl_new_std_menu(h, o, V4L2_CID_MPEG_VIDEO_HEADER_MODE,
			       V4L2_MPEG_VIDEO_HEADER_MODE_JOINED_WITH_1ST_FRAME,
			       BIT(V4L2_MPEG_VIDEO_HEADER_MODE_SEPARATE),
			       V4L2_MPEG_VIDEO_HEADER_MODE_JOINED_WITH_1ST_FRAME);
	if (h->error) {
		int ret = h->error;

		v4l2_ctrl_handler_free(h);
		return ret;
	}
	ctx->fh.ctrl_handler = h;
	return v4l2_ctrl_handler_setup(h);
}

/* file */

static int vepu_open(struct file *file)
{
	struct vepu_dev *d = video_drvdata(file);
	struct vepu_ctx *ctx;
	int ret;

	ctx = kzalloc(sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;
	ctx->dev = d;
	ctx->fmt = &vepu_formats[0];
	ctx->width = 640;
	ctx->height = 480;
	vepu_out_layout(ctx->fmt, ctx->width, ctx->height, &ctx->bpl, &ctx->out_size);
	ctx->cap_size = vepu_default_cap_size(ctx->width, ctx->height);
	ctx->tpf.numerator = 1;
	ctx->tpf.denominator = 30;
	ctx->colorspace = V4L2_COLORSPACE_SMPTE170M;

	if (mutex_lock_interruptible(&d->lock)) {
		kfree(ctx);
		return -ERESTARTSYS;
	}
	v4l2_fh_init(&ctx->fh, video_devdata(file));
	ret = vepu_init_ctrls(ctx);
	if (ret)
		goto fail_fh;
	ctx->fh.m2m_ctx = v4l2_m2m_ctx_init(d->m2m, ctx, vepu_queue_init);
	if (IS_ERR(ctx->fh.m2m_ctx)) {
		ret = PTR_ERR(ctx->fh.m2m_ctx);
		goto fail_ctrl;
	}
	v4l2_fh_add(&ctx->fh, file);
	mutex_unlock(&d->lock);
	return 0;

fail_ctrl:
	v4l2_ctrl_handler_free(&ctx->hdl);
fail_fh:
	v4l2_fh_exit(&ctx->fh);
	mutex_unlock(&d->lock);
	kfree(ctx);
	return ret;
}

static int vepu_release(struct file *file)
{
	struct vepu_dev *d = video_drvdata(file);
	struct vepu_ctx *ctx = file_to_ctx(file);

	mutex_lock(&d->lock);
	v4l2_m2m_ctx_release(ctx->fh.m2m_ctx);
	mutex_unlock(&d->lock);
	v4l2_fh_del(&ctx->fh, file);
	v4l2_fh_exit(&ctx->fh);
	v4l2_ctrl_handler_free(&ctx->hdl);
	kfree(ctx);
	return 0;
}

static const struct v4l2_file_operations vepu_fops = {
	.owner = THIS_MODULE,
	.open = vepu_open,
	.release = vepu_release,
	.poll = v4l2_m2m_fop_poll,
	.unlocked_ioctl = video_ioctl2,
	.mmap = v4l2_m2m_fop_mmap,
};

/* device */

static int vepu_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct vepu_dev *d;
	int ret;

	d = devm_kzalloc(dev, sizeof(*d), GFP_KERNEL);
	if (!d)
		return -ENOMEM;
	d->dev = dev;
	platform_set_drvdata(pdev, d);

	/* the encoder's registers are the first 0x400 of the VPU */
	d->regs = devm_platform_ioremap_resource(pdev, 0);
	if (IS_ERR(d->regs))
		return PTR_ERR(d->regs);
	d->clks[0].id = "aclk";
	d->clks[1].id = "hclk";
	ret = devm_clk_bulk_get(dev, ARRAY_SIZE(d->clks), d->clks);
	if (ret)
		return dev_err_probe(dev, ret, "clocks\n");
	d->irq = platform_get_irq_byname(pdev, "vepu");
	if (d->irq < 0)
		return d->irq;

	ret = dma_set_coherent_mask(dev, DMA_BIT_MASK(32));
	if (ret)
		return ret;
	vb2_dma_contig_set_max_seg_size(dev, DMA_BIT_MASK(32));

	mutex_init(&d->lock);
	INIT_DELAYED_WORK(&d->watchdog, vepu_watchdog);
	ret = devm_request_irq(dev, d->irq, vepu_irq, 0, DRV_NAME, d);
	if (ret)
		return ret;

	clk_set_rate(d->clks[0].clk, ACLK_RATE);
	ret = clk_bulk_prepare(ARRAY_SIZE(d->clks), d->clks);
	if (ret)
		return ret;
	pm_runtime_set_autosuspend_delay(dev, 100);
	pm_runtime_use_autosuspend(dev);
	pm_runtime_enable(dev);

	ret = v4l2_device_register(dev, &d->v4l2_dev);
	if (ret)
		goto fail_pm;
	d->m2m = v4l2_m2m_init(&vepu_m2m_ops);
	if (IS_ERR(d->m2m)) {
		ret = PTR_ERR(d->m2m);
		goto fail_v4l2;
	}

	d->vfd = (struct video_device) {
		.name = DRV_NAME,
		.fops = &vepu_fops,
		.ioctl_ops = &vepu_ioctl_ops,
		.minor = -1,
		.release = video_device_release_empty,
		.lock = &d->lock,
		.v4l2_dev = &d->v4l2_dev,
		.vfl_dir = VFL_DIR_M2M,
		.device_caps = V4L2_CAP_VIDEO_M2M | V4L2_CAP_STREAMING,
	};
	video_set_drvdata(&d->vfd, d);
	ret = video_register_device(&d->vfd, VFL_TYPE_VIDEO, -1);
	if (ret)
		goto fail_m2m;
	dev_info(dev, "H.264 encoder at /dev/video%d\n", d->vfd.num);
	return 0;

fail_m2m:
	v4l2_m2m_release(d->m2m);
fail_v4l2:
	v4l2_device_unregister(&d->v4l2_dev);
fail_pm:
	pm_runtime_dont_use_autosuspend(dev);
	pm_runtime_disable(dev);
	clk_bulk_unprepare(ARRAY_SIZE(d->clks), d->clks);
	return ret;
}

static void vepu_remove(struct platform_device *pdev)
{
	struct vepu_dev *d = platform_get_drvdata(pdev);

	video_unregister_device(&d->vfd);
	v4l2_m2m_release(d->m2m);
	v4l2_device_unregister(&d->v4l2_dev);
	cancel_delayed_work_sync(&d->watchdog);
	pm_runtime_dont_use_autosuspend(d->dev);
	pm_runtime_disable(d->dev);
	clk_bulk_unprepare(ARRAY_SIZE(d->clks), d->clks);
}

/*
 * The whole VPU node: the encoder is its first 0x400 bytes and its "vepu"
 * interrupt. Hantro takes the same node; only one of them may be built.
 */
static const struct of_device_id vepu_of_match[] = {
	{ .compatible = "rockchip,px30-vpu" },
	{ }
};
MODULE_DEVICE_TABLE(of, vepu_of_match);

static const struct dev_pm_ops vepu_pm_ops = {
	SET_SYSTEM_SLEEP_PM_OPS(pm_runtime_force_suspend, pm_runtime_force_resume)
};

static struct platform_driver vepu_driver = {
	.probe = vepu_probe,
	.remove = vepu_remove,
	.driver = {
		.name = DRV_NAME,
		.of_match_table = vepu_of_match,
		.pm = &vepu_pm_ops,
	},
};
module_platform_driver(vepu_driver);

MODULE_DESCRIPTION("Rockchip VEPU2 H.264 encoder");
MODULE_LICENSE("GPL");
