// SPDX-License-Identifier: GPL-2.0+
/*
 * Amlogic G12A/G12B HCODEC: the H.264 encoder of the DOS block, as a V4L2
 * mem2mem stateful encoder (raw frames on OUTPUT, H.264 Annex B on CAPTURE).
 *
 * HCODEC is an AMRISC core running Amlogic's microcode (ga_h264_enc_cabac)
 * next to the motion search, transform and VLC hardware. The microcode
 * writes the SPS and PPS on ENCODER_SEQUENCE/ENCODER_PICTURE and one slice
 * per picture on ENCODER_IDR/ENCODER_NON_IDR; the driver sets up the
 * hardware before each picture, as Amlogic's amvenc_avc does.
 *
 * The programming of the registers follows Amlogic's driver (media_modules,
 * drivers/frame_sink/encoder/h264/encoder.c, GPL-2.0+, Copyright (C) 2015
 * Amlogic, Inc.) and the table layout its library (encoder_libs_aml,
 * gx_enc_fast). The rate control is the driver's own: one QP per picture.
 */

#include <linux/clk.h>
#include <linux/delay.h>
#include <linux/dma-mapping.h>
#include <linux/firmware.h>
#include <linux/math.h>
#include <linux/interrupt.h>
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/mfd/syscon.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>
#include <linux/sizes.h>
#include <linux/slab.h>
#include <linux/soc/amlogic/meson-canvas.h>
#include <linux/workqueue.h>
#include <media/v4l2-ctrls.h>
#include <media/v4l2-device.h>
#include <media/v4l2-event.h>
#include <media/v4l2-ioctl.h>
#include <media/v4l2-mem2mem.h>
#include <media/videobuf2-dma-contig.h>

#include "hcodec_regs.h"

#define DRV_NAME	"meson-venc"
#define FW_NAME		"meson/venc/g12a_h264_enc_cabac.bin"

#define MC_SIZE		(4096 * 4)	/* the AMRISC instruction memory */
#define HCODEC_RATE	666666666	/* fclk_div3, as the decoder's vdec_1 */

#define MIN_W		64
#define MIN_H		64
#define MAX_W		1920
#define MAX_H		1088

#define BS_SIZE		0x100000	/* bitstream of one picture */
#define ASSIST_SIZE	0xc0000		/* work memory of the microcode */
#define CBR_SIZE	0x2000
#define CBR_TABLE_SIZE	0x800		/* then the target size of each block */
#define DUMP_PER_MB	80		/* MB statistics the microcode writes */
#define CBR_BLOCKS	256		/* TARGET_BITS_TABLE_SIZE */

#define TIMEOUT_MS	500

/* tuning of Amlogic's driver */
#define ME_WEIGHT_OFFSET	0x520
#define I4MB_WEIGHT_OFFSET	0x655
#define I16MB_WEIGHT_OFFSET	0x560

#define ADV_MV_16x16_WEIGHT	0x080
#define ADV_MV_16_8_WEIGHT	0x0e0
#define ADV_MV_8x8_WEIGHT	0x240
#define ADV_MV_4x4x4_WEIGHT	0x3000
#define IE_SAD_SHIFT_I16	0x001
#define IE_SAD_SHIFT_I4		0x001
#define ME_SAD_SHIFT_INTER	0x001

#define V3_FORCE_SKIP_SAD_0	0x10
#define V3_FORCE_SKIP_SAD_1	0x60
#define V3_FORCE_SKIP_SAD_2	0x250
#define V3_ME_F_ZERO_SAD	(ME_WEIGHT_OFFSET + 0x10)
#define V3_IE_F_ZERO_SAD_I16	(I16MB_WEIGHT_OFFSET + 0x10)
#define V3_IE_F_ZERO_SAD_I4	(I4MB_WEIGHT_OFFSET + 0x20)
#define V3_SKIP_WEIGHT_0	0x10
#define V3_SKIP_WEIGHT_1	0x8
#define V3_SKIP_WEIGHT_2	0x3
#define V3_LEVEL_1_F_SKIP_MAX_SAD 0x0
#define V3_LEVEL_1_SKIP_MAX_SAD	0x6

#define I4_IPRED_WEIGHT_MOST	0x18
#define I4_IPRED_WEIGHT_ELSE	0x28
#define C_IPRED_WEIGHT_V	0x04
#define C_IPRED_WEIGHT_H	0x08
#define C_IPRED_WEIGHT_DC	0x0c
#define I16_IPRED_WEIGHT_V	0x04
#define I16_IPRED_WEIGHT_H	0x08
#define I16_IPRED_WEIGHT_DC	0x0c
#define V3_LEFT_SMALL_MAX_IE_SAD 0x00
#define V3_LEFT_SMALL_MAX_ME_SAD 0x40

#define V5_SIMPLE_MB_CTL_VAL \
	((0 << 7) | (1 << 6) | (1 << 5) | (1 << 4) | (1 << 3) | (1 << 2) | \
	 (0 << 1) | (1 << 0))
#define V5_SMALL_DIFF_Y		0x10
#define V5_SMALL_DIFF_C		0x18

#define CBR_SHORT_SHIFT		12	/* same as off */
#define CBR_LONG_MB_NUM		2
#define CBR_START_TABLE_ID	8
#define CBR_LONG_THRESH		4

static const u32 me_mv_merge_ctl =
	(0x1 << 31) | (0x1 << 30) | (0x1 << 29) | (0x1 << 28) |
	(0x1 << 27) | (0x1 << 26) | (0x1 << 25) | (0x1 << 24) |
	(0x12 << 18) | (0x2b << 12) | (0x80 << 0);
static const u32 me_sad_range_inc = 0x03030303;
static const u32 me_step0_close_mv = 0x003ffc21;
/* InitEncodeWeight(): GXTVBB on zeroes the skip and mv weights */
static const u32 me_sad_enough_01 = (0x04 << 12) | (0x00 << 0);
static const u32 me_sad_enough_23 = (0x20 << 12) | (0x11 << 0);

static const u32 v3_mv_sad[64] = {
	0x00000004, 0x00010008, 0x00020010, 0x00030018,
	0x00040020, 0x00050028, 0x00060038, 0x00070048,
	0x00080058, 0x00090068, 0x000a0080, 0x000b0098,
	0x000c00b0, 0x000d00c8, 0x000e00e8, 0x000f0110,
	0x00100002, 0x00110004, 0x00120008, 0x0013000c,
	0x00140010, 0x00150014, 0x0016001c, 0x00170024,
	0x0018002c, 0x00190034, 0x001a0044, 0x001b0054,
	0x001c0064, 0x001d0074, 0x001e0094, 0x001f00b4,
	0x00200006, 0x0021000c, 0x0022000c, 0x00230018,
	0x00240018, 0x00250018, 0x00260018, 0x00270030,
	0x00280030, 0x00290030, 0x002a0030, 0x002b0030,
	0x002c0030, 0x002d0030, 0x002e0030, 0x002f0050,
	0x00300001, 0x00310002, 0x00320002, 0x00330004,
	0x00340004, 0x00350004, 0x00360004, 0x00370006,
	0x00380006, 0x00390006, 0x003a0006, 0x003b0006,
	0x003c0006, 0x003d0006, 0x003e0006, 0x003f0006,
};

/* H.264 chroma QP for luma QP 30..51 */
static const u8 chroma_qp_hi[22] = {
	29, 30, 31, 32, 32, 33, 34, 34, 35, 35, 36,
	36, 37, 37, 37, 38, 38, 38, 39, 39, 39, 39,
};

/*
 * The byte order MFDIN takes 32-bit RGB in (REG9_ENDN: the source byte of
 * each of 8). In the order of memory MFDIN wants B, G, R, X: the bytes of
 * V4L2's XBGR32 (DRM's XRGB8888) as they are. Amlogic's RGBA_8888 (R, G,
 * B, A) used 2,1,0,3,6,5,4,7.
 */
static uint rgb_endian = (0 << 0) | (1 << 3) | (2 << 6) | (3 << 9) |
			 (4 << 12) | (5 << 15) | (6 << 18) | (7 << 21);
module_param(rgb_endian, uint, 0644);
MODULE_PARM_DESC(rgb_endian, "MFDIN byte order of 32-bit RGB input");

static uint idle_ms = 1000;
module_param(idle_ms, uint, 0644);
MODULE_PARM_DESC(idle_ms, "HCODEC powered off after this long without a picture");

static uint debug;
module_param(debug, uint, 0644);
MODULE_PARM_DESC(debug, "1: log each picture");

struct venc_fmt {
	u32 fourcc;
	u8 iformat;	/* MFDIN input format */
	u8 bpp;		/* bytes per pixel of the first plane */
	bool linear;	/* read by address, not through a canvas */
};

/*
 * MFDIN iformat 3: NV12 through two canvases; 12: 32-bit RGB read linearly
 * and converted to YUV by MFDIN (r2y). Amlogic used 12 for Android's
 * RGBA_8888; the bytes it takes are set by REG9_ENDN (rgb_endian).
 */
static const struct venc_fmt venc_formats[] = {
	{ V4L2_PIX_FMT_NV12, 3, 1, false },
	{ V4L2_PIX_FMT_XBGR32, 12, 4, true },
};

struct venc_buf {
	void *cpu;
	dma_addr_t dma;
	size_t size;
};

enum { CV_DEC0_Y, CV_DEC0_UV, CV_DEC0_V, CV_DEC1_Y, CV_DEC1_UV, CV_DEC1_V,
       CV_IN_0, CV_IN_1, CV_IN_2, CV_NUM };

struct venc_dev {
	struct device *dev;
	void __iomem *hcodec;
	void __iomem *dos_top;
	struct regmap *ao;
	struct meson_canvas *canvas;
	u8 cv[CV_NUM];
	struct clk *dos_clk;
	struct clk *hcodec_clk;
	int irq;

	struct v4l2_device v4l2_dev;
	struct video_device vfd;
	struct v4l2_m2m_dev *m2m;
	struct mutex lock;		/* ioctls, open, release */
	struct workqueue_struct *wq;
	struct work_struct run_work;
	struct delayed_work idle_work;	/* power off when no picture comes */

	struct mutex hw_lock;		/* power and the hardware */
	int users;			/* contexts streaming OUTPUT */
	bool powered;
	struct venc_buf mc;		/* the microcode, DMA'd to the IMEM */

	struct completion done;
	u32 wait_status;		/* the ENCODER_STATUS awaited */
	u32 irq_status;
};

struct venc_ctx {
	struct v4l2_fh fh;
	struct venc_dev *dev;
	struct v4l2_ctrl_handler hdl;

	const struct venc_fmt *fmt;
	u32 width, height;
	u32 bpl;			/* of the raw frame */
	u32 out_size;			/* sizeimage of the raw frame */
	u32 cap_size;
	struct v4l2_fract tpf;
	enum v4l2_colorspace colorspace;
	enum v4l2_xfer_func xfer_func;
	enum v4l2_ycbcr_encoding ycbcr_enc;
	enum v4l2_quantization quant;

	/* controls */
	u32 bitrate;
	u32 gop;
	bool rc;
	u32 qp_i, qp_p, qp_min, qp_max;
	bool force_key;

	/* per stream */
	struct venc_buf ref, bs, dct, assist, dump, cbr;
	u32 ref_y_size;			/* one reconstructed picture: Y then UV */
	u32 cv_w, cv_h;
	bool dec1_is_ref;		/* else dec0 holds the reference */
	u32 idr_pic_id, frame_number, poc;
	u32 since_idr;
	u32 sequence;
	int qp;				/* of the next P picture */
	int qp_idr;			/* of the next IDR, after the IDRs */
	s64 fullness;			/* bytes over the target, the RC buffer */
	u32 block_w, block_h, blocks_x, blocks_y;
};

static inline struct venc_ctx *file_to_ctx(struct file *file)
{
	return container_of(file_to_v4l2_fh(file), struct venc_ctx, fh);
}

/* registers */

static inline void hw(struct venc_dev *d, u32 reg, u32 val)
{
	writel_relaxed(val, d->hcodec + ((reg - HCODEC_BASE) << 2));
}

static inline u32 hr(struct venc_dev *d, u32 reg)
{
	return readl_relaxed(d->hcodec + ((reg - HCODEC_BASE) << 2));
}

static inline void dw(struct venc_dev *d, u32 reg, u32 val)
{
	writel_relaxed(val, d->dos_top + ((reg - DOS_TOP_BASE) << 2));
}

static inline u32 dr(struct venc_dev *d, u32 reg)
{
	return readl_relaxed(d->dos_top + ((reg - DOS_TOP_BASE) << 2));
}

static void dos_bits(struct venc_dev *d, u32 reg, u32 mask, u32 val)
{
	dw(d, reg, (dr(d, reg) & ~mask) | (val & mask));
}

/* DOS_SW_RESET1 pulse, with the reads Amlogic's driver puts around it */
static void dos_reset(struct venc_dev *d, u32 bits)
{
	dr(d, DOS_SW_RESET1);
	dr(d, DOS_SW_RESET1);
	dr(d, DOS_SW_RESET1);
	dw(d, DOS_SW_RESET1, bits);
	dw(d, DOS_SW_RESET1, 0);
	dr(d, DOS_SW_RESET1);
	dr(d, DOS_SW_RESET1);
	dr(d, DOS_SW_RESET1);
}

#define RESET_HCODEC_BLOCKS (BIT(2) | BIT(6) | BIT(7) | BIT(8) | BIT(14) | \
			     BIT(16) | BIT(17))
#define RESET_HCODEC_CPU (BIT(11) | BIT(12))

static void hc_stop(struct venc_dev *d)
{
	u32 v;

	hw(d, HCODEC_MPSR, 0);
	hw(d, HCODEC_CPSR, 0);
	readl_relaxed_poll_timeout(d->hcodec + ((HCODEC_IMEM_DMA_CTRL - HCODEC_BASE) << 2),
				   v, !(v & 0x8000), 10, 100000);
	dos_reset(d, RESET_HCODEC_CPU | RESET_HCODEC_BLOCKS);
}

static void hc_start(struct venc_dev *d)
{
	dos_reset(d, RESET_HCODEC_CPU);
	hw(d, HCODEC_MPSR, 1);
}

static int hc_load_mc(struct venc_dev *d)
{
	u32 v;
	int ret;

	hw(d, HCODEC_MPSR, 0);
	hw(d, HCODEC_CPSR, 0);
	hr(d, HCODEC_MPSR);
	hr(d, HCODEC_MPSR);
	hw(d, HCODEC_IMEM_DMA_ADR, d->mc.dma);
	hw(d, HCODEC_IMEM_DMA_COUNT, MC_SIZE / 4);
	hw(d, HCODEC_IMEM_DMA_CTRL, 0x8000 | (7 << 16));
	ret = readl_relaxed_poll_timeout(d->hcodec + ((HCODEC_IMEM_DMA_CTRL - HCODEC_BASE) << 2),
					 v, !(v & 0x8000), 10, 1000000);
	if (ret)
		dev_err(d->dev, "microcode DMA hangs\n");
	return ret;
}

static int venc_load_fw(struct venc_dev *d)
{
	const struct firmware *fw;
	int ret;

	if (d->mc.cpu)
		return 0;
	ret = request_firmware(&fw, FW_NAME, d->dev);
	if (ret)
		return ret;
	if (fw->size < MC_SIZE) {
		dev_err(d->dev, "%s: %zu bytes, %u expected\n", FW_NAME, fw->size, MC_SIZE);
		release_firmware(fw);
		return -EINVAL;
	}
	d->mc.size = MC_SIZE;
	d->mc.cpu = dma_alloc_coherent(d->dev, MC_SIZE, &d->mc.dma, GFP_KERNEL);
	if (!d->mc.cpu) {
		release_firmware(fw);
		return -ENOMEM;
	}
	memcpy(d->mc.cpu, fw->data, MC_SIZE);
	release_firmware(fw);
	return 0;
}

static int venc_power_on(struct venc_dev *d)
{
	int ret;

	ret = venc_load_fw(d);
	if (ret)
		return ret;
	ret = clk_prepare_enable(d->dos_clk);
	if (ret)
		return ret;
	clk_set_rate(d->hcodec_clk, HCODEC_RATE);
	ret = clk_prepare_enable(d->hcodec_clk);
	if (ret) {
		clk_disable_unprepare(d->dos_clk);
		return ret;
	}

	regmap_update_bits(d->ao, AO_RTI_GEN_PWR_SLEEP0, GEN_PWR_HCODEC, 0);
	udelay(10);
	dw(d, DOS_SW_RESET1, 0xffffffff);
	dw(d, DOS_SW_RESET1, 0);
	/* the HCODEC gates of DOS */
	dos_bits(d, DOS_GCLK_EN0, GENMASK(26, 12), GENMASK(26, 12));
	dw(d, DOS_MEM_PD_HCODEC, 0);
	regmap_update_bits(d->ao, AO_RTI_GEN_PWR_ISO0, GEN_ISO_HCODEC, 0);
	udelay(10);
	/* auto clock gating off */
	dos_bits(d, DOS_GEN_CTRL0, BIT(0), BIT(0));
	dos_bits(d, DOS_GEN_CTRL0, BIT(0), 0);
	usleep_range(10000, 11000);
	d->powered = true;

	hw(d, HCODEC_ASSIST_MMC_CTRL1, 0x32);
	ret = hc_load_mc(d);
	if (ret)
		return ret;
	if (debug)
		dev_info(d->dev, "on, hcodec %lu Hz\n", clk_get_rate(d->hcodec_clk));
	return 0;
}

static void venc_power_off(struct venc_dev *d)
{
	if (!d->powered)
		return;
	hc_stop(d);
	d->powered = false;
	if (debug)
		dev_info(d->dev, "off\n");
	regmap_update_bits(d->ao, AO_RTI_GEN_PWR_ISO0, GEN_ISO_HCODEC, GEN_ISO_HCODEC);
	dw(d, DOS_MEM_PD_HCODEC, 0xffffffff);
	dos_bits(d, DOS_GCLK_EN0, GENMASK(26, 12), 0);
	clk_disable_unprepare(d->hcodec_clk);
	regmap_update_bits(d->ao, AO_RTI_GEN_PWR_SLEEP0, GEN_PWR_HCODEC, GEN_PWR_HCODEC);
	clk_disable_unprepare(d->dos_clk);
}

/* the setup of one picture (avc_* of Amlogic's driver) */

static void cv_set(struct venc_ctx *ctx, int i, u32 addr, u32 stride, u32 h)
{
	meson_canvas_config(ctx->dev->canvas, ctx->dev->cv[i], addr, stride, h,
			    MESON_CANVAS_WRAP_NONE, MESON_CANVAS_BLKMODE_LINEAR, 0);
}

static u32 cv3(struct venc_dev *d, int first)
{
	return (d->cv[first + 2] << 16) | (d->cv[first + 1] << 8) | d->cv[first];
}

static void venc_canvas_init(struct venc_ctx *ctx)
{
	u32 y0 = ctx->ref.dma, y1 = ctx->ref.dma + ctx->ref.size / 2;

	cv_set(ctx, CV_DEC0_Y, y0, ctx->cv_w, ctx->cv_h);
	cv_set(ctx, CV_DEC0_UV, y0 + ctx->ref_y_size, ctx->cv_w, ctx->cv_h / 2);
	cv_set(ctx, CV_DEC0_V, y0 + ctx->ref_y_size, ctx->cv_w, ctx->cv_h / 2);
	cv_set(ctx, CV_DEC1_Y, y1, ctx->cv_w, ctx->cv_h);
	cv_set(ctx, CV_DEC1_UV, y1 + ctx->ref_y_size, ctx->cv_w, ctx->cv_h / 2);
	cv_set(ctx, CV_DEC1_V, y1 + ctx->ref_y_size, ctx->cv_w, ctx->cv_h / 2);
}

static void venc_init_encoder(struct venc_ctx *ctx, bool idr)
{
	struct venc_dev *d = ctx->dev;

	hw(d, HCODEC_VLC_TOTAL_BYTES, 0);
	hw(d, HCODEC_VLC_CONFIG, 0x07);
	hw(d, HCODEC_VLC_INT_CONTROL, 0);
	hw(d, HCODEC_ASSIST_AMR1_INT0, 0x15);
	hw(d, HCODEC_ASSIST_AMR1_INT1, 0x8);
	hw(d, HCODEC_ASSIST_AMR1_INT3, 0x14);
	hw(d, IDR_PIC_ID, ctx->idr_pic_id);
	hw(d, FRAME_NUMBER, idr ? 0 : ctx->frame_number);
	hw(d, PIC_ORDER_CNT_LSB, idr ? 0 : ctx->poc);
	hw(d, LOG2_MAX_PIC_ORDER_CNT_LSB, 4);
	hw(d, LOG2_MAX_FRAME_NUM, 4);
	hw(d, ANC0_BUFFER_ID, 0);
	hw(d, QPPICTURE, 26);
}

static void venc_init_buffers(struct venc_ctx *ctx)
{
	struct venc_dev *d = ctx->dev;

	/* QDCT */
	hw(d, HCODEC_QDCT_MB_START_PTR, ctx->dct.dma);
	hw(d, HCODEC_QDCT_MB_END_PTR, ctx->dct.dma + ctx->dct.size - 1);
	hw(d, HCODEC_QDCT_MB_WR_PTR, ctx->dct.dma);
	hw(d, HCODEC_QDCT_MB_RD_PTR, ctx->dct.dma);
	hw(d, HCODEC_QDCT_MB_BUFF, 0);
	/* the bitstream */
	hw(d, HCODEC_VLC_VB_MEM_CTL, (1 << 31) | (0x3f << 24) | (0x20 << 16) | (2 << 0));
	hw(d, HCODEC_VLC_VB_START_PTR, ctx->bs.dma);
	hw(d, HCODEC_VLC_VB_WR_PTR, ctx->bs.dma);
	hw(d, HCODEC_VLC_VB_SW_RD_PTR, ctx->bs.dma);
	hw(d, HCODEC_VLC_VB_END_PTR, ctx->bs.dma + ctx->bs.size - 1);
	hw(d, HCODEC_VLC_VB_CONTROL, 1);
	hw(d, HCODEC_VLC_VB_CONTROL, (0 << 14) | (7 << 3) | (1 << 1) | (0 << 0));
}

static void venc_prog_qtbl(struct venc_dev *d, u32 quant)
{
	u32 q = quant * 0x01010101;
	int t, i;

	/* I4, I16 and ME tables, 32 QPs each */
	for (t = 0; t < 3; t++) {
		hw(d, HCODEC_Q_QUANT_CONTROL, ((t * 8) << 23) | (1 << 22));
		for (i = 0; i < 8; i++)
			hw(d, HCODEC_QUANT_TABLE_DATA, q);
	}
}

static u32 chroma_qp(u32 qp)
{
	return qp < 30 ? qp : chroma_qp_hi[min(qp, 51u) - 30];
}

/* avc_prot_init() */
static void venc_prot_init(struct venc_ctx *ctx, u32 quant, bool idr)
{
	struct venc_dev *d = ctx->dev;
	u32 mb_w = DIV_ROUND_UP(ctx->width, 16);
	u32 qp = quant, qpc = chroma_qp(quant), v;
	int i;

	hw(d, HCODEC_HDEC_MC_OMEM_AUTO, (1 << 31) | ((mb_w - 1) << 16));
	hw(d, HCODEC_VLC_ADV_CONFIG,
	   (0 << 10) | (1 << 9) | (1 << 8) | (0 << 7) | (0 << 6) | (1 << 5) |
	   (1 << 4) | (1 << 3) | (1 << 2) | (1 << 1) | (0 << 0));
	hw(d, HCODEC_QDCT_ADV_CONFIG,
	   (1 << 29) | (1 << 28) | (1 << 27) | (1 << 26) | (1 << 25) |
	   (1 << 24) | (0 << 23) | (1 << 22) | (1 << 21) | (0 << 20) |
	   (1 << 19) | (1 << 18) | (0 << 17) | (0 << 16) | (0 << 15) |
	   (1 << 14) | (0 << 13) | (1 << 12) | (0 << 11) | (1 << 10) |
	   (1 << 9) | (1 << 8) | (0 << 7) | (1 << 6) | (1 << 5) | (1 << 4) |
	   (1 << 3) | (1 << 2) | (3 << 0));

	hw(d, HCODEC_IE_WEIGHT, (I16MB_WEIGHT_OFFSET << 16) | I4MB_WEIGHT_OFFSET);
	hw(d, HCODEC_ME_WEIGHT, ME_WEIGHT_OFFSET);
	hw(d, HCODEC_SAD_CONTROL_0, (I16MB_WEIGHT_OFFSET << 16) | I4MB_WEIGHT_OFFSET);
	hw(d, HCODEC_SAD_CONTROL_1, (IE_SAD_SHIFT_I16 << 24) | (IE_SAD_SHIFT_I4 << 20) |
	   (ME_SAD_SHIFT_INTER << 16) | ME_WEIGHT_OFFSET);
	hw(d, HCODEC_ADV_MV_CTL0, (1u << 31) | (1 << 30) | (ADV_MV_8x8_WEIGHT << 16) |
	   ADV_MV_4x4x4_WEIGHT);
	hw(d, HCODEC_ADV_MV_CTL1, (ADV_MV_16x16_WEIGHT << 16) | (1 << 15) |
	   ADV_MV_16_8_WEIGHT);

	venc_prog_qtbl(d, quant);

	/* CBR: the per-block tables in ctx->cbr */
	v = hr(d, HCODEC_SAD_CONTROL_1) & 0xffff;
	hw(d, HCODEC_SAD_CONTROL_1, v);
	hw(d, H264_ENC_CBR_TABLE_ADDR, ctx->cbr.dma);
	hw(d, H264_ENC_CBR_MB_SIZE_ADDR, ctx->cbr.dma + CBR_TABLE_SIZE);
	hw(d, H264_ENC_CBR_CTL, (CBR_START_TABLE_ID << 28) | (CBR_SHORT_SHIFT << 24) |
	   (CBR_LONG_MB_NUM << 16) | CBR_LONG_THRESH);
	hw(d, H264_ENC_CBR_REGION_SIZE, (ctx->block_w << 16) | ctx->block_h);

	hw(d, HCODEC_QDCT_VLC_QUANT_CTL_0, (0 << 19) | (qp << 13) | (0 << 6) | qp);
	hw(d, HCODEC_QDCT_VLC_QUANT_CTL_1, (14 << 6) | 13);
	hw(d, HCODEC_VLC_PIC_SIZE, ctx->width | (ctx->height << 16));
	hw(d, HCODEC_VLC_PIC_POSITION, 0);

	v = (qpc << 22) | (qp << 16) | ((qpc % 6) << 12) | ((qpc / 6) << 8) |
	    ((qp % 6) << 4) | (qp / 6);
	hw(d, HCODEC_QDCT_Q_QUANT_I, v);
	hw(d, HCODEC_QDCT_Q_QUANT_P, v);

	hw(d, HCODEC_IGNORE_CONFIG, 0);
	hw(d, HCODEC_IGNORE_CONFIG_2, 0);

	hw(d, HCODEC_QDCT_MB_CONTROL, (1 << 9) | (1 << 0));
	hw(d, HCODEC_QDCT_MB_CONTROL,
	   (1 << 28) | (1 << 29) | (1 << 19) | (1 << 20) | (1 << 18) |
	   (1 << 17) | (1 << 14) | (1 << 13) | (1 << 12) | (1 << 10));

	hw(d, HCODEC_SAD_CONTROL, (0 << 3) | (1 << 2) | (0 << 1) | (1 << 0));
	hw(d, HCODEC_IE_RESULT_BUFFER, 0);
	hw(d, HCODEC_SAD_CONTROL, (1 << 3) | (0 << 2) | (1 << 1) | (0 << 0));
	hw(d, HCODEC_IE_CONTROL, (1 << 30) | (0 << 1) | (1 << 0));
	hw(d, HCODEC_IE_CONTROL, (1 << 30) | (0 << 1) | (0 << 0));

	hw(d, HCODEC_ME_SKIP_LINE, (8 << 24) | (8 << 18) | (2 << 12) | (0 << 6));
	hw(d, HCODEC_ME_MV_MERGE_CTL, me_mv_merge_ctl);
	hw(d, HCODEC_ME_STEP0_CLOSE_MV, me_step0_close_mv);
	hw(d, HCODEC_ME_SAD_ENOUGH_01, me_sad_enough_01);
	hw(d, HCODEC_ME_SAD_ENOUGH_23, me_sad_enough_23);
	hw(d, HCODEC_ME_F_SKIP_SAD, 0);
	hw(d, HCODEC_ME_F_SKIP_WEIGHT, 0);
	hw(d, HCODEC_ME_MV_WEIGHT_01, 0);
	hw(d, HCODEC_ME_MV_WEIGHT_23, 0);
	hw(d, HCODEC_ME_SAD_RANGE_INC, me_sad_range_inc);

	/* TXL on */
	hw(d, HCODEC_V5_SIMPLE_MB_CTL, 0);
	hw(d, HCODEC_V5_SIMPLE_MB_CTL, V5_SIMPLE_MB_CTL_VAL);
	hw(d, HCODEC_V5_MB_DIFF_SUM, 0);
	hw(d, HCODEC_V5_SMALL_DIFF_CNT, (V5_SMALL_DIFF_C << 16) | V5_SMALL_DIFF_Y);
	hw(d, HCODEC_V5_SIMPLE_MB_DQUANT, 0);		/* qp_mode 1 */
	hw(d, HCODEC_V5_SIMPLE_MB_ME_WEIGHT, 0);
	hw(d, HCODEC_QDCT_CONFIG, 1 << 0);

	/* GXL on */
	hw(d, HCODEC_V4_FORCE_SKIP_CFG, (qp << 26) | (qp << 20) | (0 << 19) |
	   (5 << 16) | (6 << 12) | (0 << 0));
	hw(d, HCODEC_V3_SKIP_CONTROL, (1u << 31) | (0 << 30) | (1 << 28) | (1 << 27) |
	   (V3_FORCE_SKIP_SAD_1 << 12) | V3_FORCE_SKIP_SAD_0);
	hw(d, HCODEC_V3_SKIP_WEIGHT, (V3_SKIP_WEIGHT_1 << 16) | V3_SKIP_WEIGHT_0);
	hw(d, HCODEC_V3_L1_SKIP_MAX_SAD, (V3_LEVEL_1_F_SKIP_MAX_SAD << 16) |
	   V3_LEVEL_1_SKIP_MAX_SAD);
	hw(d, HCODEC_V3_L2_SKIP_WEIGHT, (V3_FORCE_SKIP_SAD_2 << 16) | V3_SKIP_WEIGHT_2);
	hw(d, HCODEC_V3_F_ZERO_CTL_0, (V3_IE_F_ZERO_SAD_I16 << 16) | V3_IE_F_ZERO_SAD_I4);
	hw(d, HCODEC_V3_F_ZERO_CTL_1, (0 << 25) | (0 << 24) | (3 << 16) | V3_ME_F_ZERO_SAD);

	for (i = 0; i < ARRAY_SIZE(v3_mv_sad); i++)
		hw(d, HCODEC_V3_MV_SAD_TABLE, v3_mv_sad[i]);
	hw(d, HCODEC_V3_IPRED_TYPE_WEIGHT_0, (C_IPRED_WEIGHT_H << 24) | (C_IPRED_WEIGHT_V << 16) |
	   (I4_IPRED_WEIGHT_ELSE << 8) | I4_IPRED_WEIGHT_MOST);
	hw(d, HCODEC_V3_IPRED_TYPE_WEIGHT_1, (I16_IPRED_WEIGHT_DC << 24) |
	   (I16_IPRED_WEIGHT_H << 16) | (I16_IPRED_WEIGHT_V << 8) | C_IPRED_WEIGHT_DC);
	hw(d, HCODEC_V3_LEFT_SMALL_MAX_SAD, (V3_LEFT_SMALL_MAX_ME_SAD << 16) |
	   V3_LEFT_SMALL_MAX_IE_SAD);

	hw(d, HCODEC_IE_DATA_FEED_BUFF_INFO, 0);
	hw(d, HCODEC_CURR_CANVAS_CTRL, 0);
	hw(d, HCODEC_VLC_CONFIG, hr(d, HCODEC_VLC_CONFIG) | (1 << 0));
	hw(d, INFO_DUMP_START_ADDR, ctx->dump.dma);

	hw(d, HCODEC_ASSIST_MBOX2_CLR_REG, 1);
	hw(d, HCODEC_ASSIST_MBOX2_MASK, 1);
}

/* mfdin_basic(): the input picture */
static void venc_mfdin(struct venc_ctx *ctx, u32 input)
{
	struct venc_dev *d = ctx->dev;
	const struct venc_fmt *f = ctx->fmt;
	u32 x = ALIGN(ctx->width, 16), y = ctx->height;
	u8 ifmt = f->iformat, r2y = f->linear;
	bool i444 = ifmt == 12;
	u8 dsample = i444, y_size = 0, interp = 0, r2y_mode = r2y;
	u8 bppx0 = 1, bppx1 = 1, bppy0 = 1, bppy1 = 0;

	/* noise reduction off (nr_mode 0); the rest as Amlogic sets it */
	hw(d, HCODEC_MFDIN_REG0D, (1 << 1) | (1 << 2) | ((0xff & -1) << 6) |
	   (48 << 14) | (0 << 20) | (63 << 26));
	hw(d, HCODEC_MFDIN_REG0E, (1 << 1) | (0 << 2) | (1 << 3) | (32 << 7) |
	   (63 << 13) | (0 << 19));
	hw(d, HCODEC_MFDIN_REG0F, (1 << 0) | (5 << 8) | (4 << 4) | (4 << 16) | (8 << 24));
	hw(d, HCODEC_MFDIN_REG10, (10 << 0) | (216 << 8) | (128 << 16) | (32 << 24));
	hw(d, HCODEC_MFDIN_REG11, (16 << 0) | (0 << 8) | (63 << 14));
	hw(d, HCODEC_MFDIN_REG12, (1 << 1) | (1 << 2) | ((0xff & -1) << 6) |
	   (48 << 14) | (0 << 20) | (63 << 26));
	hw(d, HCODEC_MFDIN_REG13, (1 << 1) | (0 << 2) | (1 << 3) | (32 << 7) |
	   (63 << 13) | (0 << 19));
	hw(d, HCODEC_MFDIN_REG14, (1 << 0) | (5 << 8) | (4 << 4) | (4 << 16) | (8 << 24));
	hw(d, HCODEC_MFDIN_REG15, (10 << 0) | (216 << 8) | (128 << 16) | (32 << 24));
	hw(d, HCODEC_MFDIN_REG16, (16 << 0) | (0 << 8) | (63 << 14));

	hw(d, HCODEC_MFDIN_REG1_CTRL, ifmt | (0 << 4) | (dsample << 6) | (y_size << 8) |
	   (interp << 9) | (r2y << 12) | (r2y_mode << 13));
	hw(d, HCODEC_MFDIN_REG8_DMBL, (x << 14) | y);

	if (!f->linear) {
		hw(d, HCODEC_MFDIN_REG3_CANV, (input & 0xffffff) | (bppy1 << 30) |
		   (bppy0 << 28) | (bppx1 << 26) | (bppx0 << 24));
		hw(d, HCODEC_MFDIN_REG4_LNR0, 0);
		hw(d, HCODEC_MFDIN_REG5_LNR1, 0);
		hw(d, HCODEC_MFDIN_REG9_ENDN, (7 << 0) | (6 << 3) | (5 << 6) | (4 << 9) |
		   (3 << 12) | (2 << 15) | (1 << 18) | (0 << 21));
	} else {
		hw(d, HCODEC_MFDIN_REG3_CANV, (bppy1 << 30) | (bppy0 << 28) |
		   (bppx1 << 26) | (bppx0 << 24));
		hw(d, HCODEC_MFDIN_REG4_LNR0, (3 << 16) | ctx->bpl);
		hw(d, HCODEC_MFDIN_REG5_LNR1, input);
		hw(d, HCODEC_MFDIN_REG9_ENDN, rgb_endian);
	}
}

static void venc_set_input(struct venc_ctx *ctx, dma_addr_t src)
{
	struct venc_dev *d = ctx->dev;
	u32 input;

	if (ctx->fmt->linear) {
		input = src;
	} else {
		cv_set(ctx, CV_IN_0, src, ctx->bpl, ctx->height);
		cv_set(ctx, CV_IN_1, src + ctx->bpl * ctx->height, ctx->bpl, ctx->height / 2);
		input = (d->cv[CV_IN_1] << 8) | d->cv[CV_IN_0];
	}
	venc_mfdin(ctx, input);
}

static void venc_ie_me(struct venc_ctx *ctx, u32 mb_type)
{
	struct venc_dev *d = ctx->dev;

	hw(d, IE_ME_MODE, 12);		/* ie_pippeline_block, no sub pixels */
	hw(d, IE_REF_SEL, 0);
	hw(d, IE_ME_MB_TYPE, mb_type);
	hw(d, FIXED_SLICE_CFG, 0);	/* one slice */
}

/*
 * Fill_CBR_Table() without rate control: every table and every QP the
 * same, no target per block. Converted to the microcode's order
 * (ConvertTable2Risc: the 16-bit words of each 64-bit word reversed).
 */
static void venc_fill_cbr(struct venc_ctx *ctx, u32 quant)
{
	u8 *t = ctx->cbr.cpu;
	u16 *s;
	int i, j, n = ctx->blocks_x * ctx->blocks_y;

	memset(t, 0, CBR_SIZE);
	for (i = 0; i < 16; i++, t += 128) {
		int k = i >= 13 ? i - 13 : 0;

		memset(t, min(quant, 51u), 96);
		s = (u16 *)(t + 96);
		s[0] = I4MB_WEIGHT_OFFSET + k * 0x380;
		s[1] = I16MB_WEIGHT_OFFSET;
		s[2] = ME_WEIGHT_OFFSET + k * 0x200;
		s[3] = V3_IE_F_ZERO_SAD_I4 + k * 0x480;
		s[4] = V3_IE_F_ZERO_SAD_I16 + k * 0x200;
		s[5] = V3_ME_F_ZERO_SAD + k * 0x280;
		s[6] = 0x55aa;
		s[7] = 0xaa55;
	}
	s = (u16 *)((u8 *)ctx->cbr.cpu + CBR_TABLE_SIZE);
	for (i = 0; i < n; i++)
		s[i] = 0xffff;

	s = ctx->cbr.cpu;
	for (i = 0; i < 0xa00 / 8; i++) {
		j = i * 4;
		swap(s[j], s[j + 3]);
		swap(s[j + 1], s[j + 2]);
	}
	wmb();
}

static int venc_wait(struct venc_ctx *ctx, u32 status)
{
	struct venc_dev *d = ctx->dev;

	if (!wait_for_completion_timeout(&d->done, msecs_to_jiffies(TIMEOUT_MS))) {
		dev_err(d->dev, "timeout waiting for %u: status %u, mb info %#x, qdct %#x, vlc %#x, me %#x, pc %#x, debug %#x\n",
			status, hr(d, ENCODER_STATUS), hr(d, HCODEC_VLC_MB_INFO),
			hr(d, HCODEC_QDCT_STATUS_CTRL), hr(d, HCODEC_VLC_STATUS_CTRL),
			hr(d, HCODEC_ME_STATUS), hr(d, HCODEC_MPC_E), hr(d, DEBUG_REG));
		return -ETIMEDOUT;
	}
	return 0;
}

static void venc_expect(struct venc_dev *d, u32 status)
{
	reinit_completion(&d->done);
	WRITE_ONCE(d->wait_status, status);
}

/* a reset HCODEC set up for cmd (amvenc_avc_start_cmd with need_reset) */
static void venc_setup(struct venc_ctx *ctx, u32 cmd, u32 quant)
{
	struct venc_dev *d = ctx->dev;
	bool idr = cmd != ENCODER_NON_IDR;

	hc_stop(d);
	dos_reset(d, RESET_HCODEC_BLOCKS);
	venc_canvas_init(ctx);
	venc_init_encoder(ctx, cmd == ENCODER_IDR);
	venc_init_buffers(ctx);
	venc_fill_cbr(ctx, quant);
	venc_prot_init(ctx, quant, idr);
	hw(d, MEM_OFFSET_REG, ctx->assist.dma);
}

/* SPS and PPS into ctx->bs; their size */
static int venc_headers(struct venc_ctx *ctx, u32 quant, u32 *size)
{
	struct venc_dev *d = ctx->dev;
	int ret;

	venc_setup(ctx, ENCODER_SEQUENCE, quant);
	venc_ie_me(ctx, 0);
	venc_expect(d, ENCODER_SEQUENCE_DONE);
	hw(d, ENCODER_STATUS, ENCODER_SEQUENCE);
	wmb();
	hc_start(d);
	ret = venc_wait(ctx, ENCODER_SEQUENCE_DONE);
	if (ret)
		return ret;

	/* the PPS by the same run of the microcode */
	venc_ie_me(ctx, 0);
	venc_expect(d, ENCODER_PICTURE_DONE);
	hw(d, ENCODER_STATUS, ENCODER_PICTURE);
	ret = venc_wait(ctx, ENCODER_PICTURE_DONE);
	if (ret)
		return ret;
	*size = hr(d, HCODEC_VLC_TOTAL_BYTES);
	return 0;
}

static int venc_picture(struct venc_ctx *ctx, dma_addr_t src, bool idr, u32 quant, u32 *size)
{
	struct venc_dev *d = ctx->dev;
	u32 cmd = idr ? ENCODER_IDR : ENCODER_NON_IDR;
	int dblk = ctx->dec1_is_ref ? CV_DEC0_Y : CV_DEC1_Y;
	int ref = ctx->dec1_is_ref ? CV_DEC1_Y : CV_DEC0_Y;
	int ret;

	venc_setup(ctx, cmd, quant);
	hw(d, H264_ENC_SVC_PIC_TYPE, ENC_SLC_REF);
	hw(d, HCODEC_REC_CANVAS_ADDR, cv3(d, dblk));
	hw(d, HCODEC_DBKR_CANVAS_ADDR, cv3(d, dblk));
	hw(d, HCODEC_DBKW_CANVAS_ADDR, cv3(d, dblk));
	hw(d, HCODEC_ANC0_CANVAS_ADDR, cv3(d, ref));
	hw(d, HCODEC_VLC_HCMD_CONFIG, 0);
	venc_set_input(ctx, src);
	venc_ie_me(ctx, idr ? HENC_MB_Type_I4MB :
		   (HENC_SKIP_RUN_AUTO << 16) | (HENC_MB_Type_AUTO << 4) | HENC_MB_Type_AUTO);
	venc_expect(d, ENCODER_IDR_DONE);	/* also for P, see venc_isr() */
	hw(d, ENCODER_STATUS, cmd);
	wmb();
	hc_start(d);
	ret = venc_wait(ctx, ENCODER_IDR_DONE);
	if (ret)
		return ret;
	*size = hr(d, HCODEC_VLC_TOTAL_BYTES);
	return 0;
}

/* AMVENC_AVC_IOC_SUBMIT: the counters and the reference for the next one */
static void venc_commit(struct venc_ctx *ctx, bool idr)
{
	if (idr) {
		ctx->idr_pic_id = (ctx->idr_pic_id + 1) & 0xffff;
		ctx->poc = 2;
		ctx->frame_number = 1;
	} else {
		ctx->frame_number = (ctx->frame_number + 1) & 0xffff;
		ctx->poc += 2;
	}
	ctx->dec1_is_ref = !ctx->dec1_is_ref;
}

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
static void venc_rc(struct venc_ctx *ctx, bool idr, u32 bytes)
{
	u32 fps = ctx->tpf.numerator ? ctx->tpf.denominator / ctx->tpf.numerator : 30;
	s64 target = max_t(s64, ctx->bitrate / 8 / max(fps, 1u), 64);
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
	ctx->qp_idr = clamp_t(int, ctx->qp_idr, max_t(int, ctx->qp - 6, ctx->qp_min),
			      min_t(int, ctx->qp + 4, ctx->qp_max));
}

/*
 * The SPS of the microcode codes whole macroblocks and no cropping. For a
 * width or height that is not a multiple of 16 the driver writes the SPS
 * again with frame_cropping (right and bottom): the bits before the
 * cropping flag and all after its fields as they were.
 */
struct bits {
	u8 *p;
	size_t size, pos;	/* in bits */
};

static int bit_get(struct bits *b)
{
	int v;

	if (b->pos >= b->size)
		return -1;
	v = (b->p[b->pos >> 3] >> (7 - (b->pos & 7))) & 1;
	b->pos++;
	return v;
}

static int ue_get(struct bits *b, u32 *val)
{
	int zeros = 0, i, v;
	u32 x = 0;

	while ((v = bit_get(b)) == 0)
		if (++zeros > 30)
			return -1;
	if (v < 0)
		return -1;
	for (i = 0; i < zeros; i++) {
		v = bit_get(b);
		if (v < 0)
			return -1;
		x = (x << 1) | v;
	}
	*val = (1u << zeros) - 1 + x;
	return 0;
}

static void bit_put(struct bits *b, int v)
{
	if (b->pos >= b->size)
		return;
	if (v)
		b->p[b->pos >> 3] |= 0x80 >> (b->pos & 7);
	else
		b->p[b->pos >> 3] &= ~(0x80 >> (b->pos & 7));
	b->pos++;
}

static void ue_put(struct bits *b, u32 val)
{
	int n = 31 - __builtin_clz(val + 1), i;

	for (i = 0; i < n; i++)
		bit_put(b, 0);
	for (i = n; i >= 0; i--)
		bit_put(b, ((val + 1) >> i) & 1);
}

/* NAL payload without emulation prevention bytes */
static size_t nal_unescape(const u8 *in, size_t n, u8 *out)
{
	size_t i, o = 0, zeros = 0;

	for (i = 0; i < n; i++) {
		if (zeros >= 2 && in[i] == 3) {
			zeros = 0;
			continue;
		}
		zeros = in[i] ? 0 : zeros + 1;
		out[o++] = in[i];
	}
	return o;
}

static size_t nal_escape(const u8 *in, size_t n, u8 *out, size_t cap)
{
	size_t i, o = 0, zeros = 0;

	for (i = 0; i < n && o + 2 <= cap; i++) {
		if (zeros >= 2 && in[i] <= 3) {
			out[o++] = 3;
			zeros = 0;
		}
		zeros = in[i] ? 0 : zeros + 1;
		out[o++] = in[i];
	}
	return o;
}

/* the SPS (rbsp, without the NAL header) with cropping; its size or 0 */
static size_t sps_crop(const u8 *rbsp, size_t n, u8 *out, size_t cap, u32 right, u32 bottom)
{
	struct bits in = { (u8 *)rbsp, n * 8, 0 };
	struct bits o = { out, cap * 8, 0 };
	size_t crop_at, rest_at, end;
	u32 v, i, profile = rbsp[0], poc_type;
	int f;

	if (n < 4 || (profile != 66 && profile != 77))	/* no chroma format fields */
		return 0;
	in.pos = 24;
	if (ue_get(&in, &v) || ue_get(&in, &v) || ue_get(&in, &poc_type))
		return 0;
	if (poc_type == 0) {
		if (ue_get(&in, &v))
			return 0;
	} else if (poc_type == 1) {
		return 0;
	}
	if (ue_get(&in, &v))			/* max_num_ref_frames */
		return 0;
	in.pos++;				/* gaps_in_frame_num_allowed */
	if (ue_get(&in, &v) || ue_get(&in, &v))	/* width, height in MBs */
		return 0;
	f = bit_get(&in);			/* frame_mbs_only_flag */
	if (f < 0)
		return 0;
	if (!f)
		in.pos++;
	in.pos++;				/* direct_8x8_inference */
	crop_at = in.pos;
	f = bit_get(&in);
	if (f < 0)
		return 0;
	if (f)
		for (i = 0; i < 4; i++)
			if (ue_get(&in, &v))
				return 0;
	rest_at = in.pos;
	/* up to and with rbsp_stop_one_bit, the last bit set */
	for (end = n * 8; end > rest_at && !((rbsp[(end - 1) >> 3] >> (7 - ((end - 1) & 7))) & 1); end--)
		;
	if (end <= rest_at)
		return 0;

	memset(out, 0, cap);
	for (in.pos = 0; in.pos < crop_at;)
		bit_put(&o, bit_get(&in));
	bit_put(&o, 1);
	ue_put(&o, 0);
	ue_put(&o, right);
	ue_put(&o, 0);
	ue_put(&o, bottom);
	for (in.pos = rest_at; in.pos < end;)
		bit_put(&o, bit_get(&in));
	if (o.pos >= o.size)
		return 0;
	return DIV_ROUND_UP(o.pos, 8);
}

/* SPS and PPS (Annex B) from src to dst, the SPS cropped if it needs; size */
static size_t venc_copy_headers(struct venc_ctx *ctx, const u8 *src, size_t n, u8 *dst,
				size_t cap)
{
	u32 right = (ALIGN(ctx->width, 16) - ctx->width) / 2;
	u32 bottom = (ALIGN(ctx->height, 16) - ctx->height) / 2;
	u8 *rbsp, *sps;
	size_t i, sps_at = 0, sps_end = 0, rn, sn, en, total;

	if (!right && !bottom)
		goto as_is;
	/* the SPS: from its start code to the next one */
	for (i = 0; i + 4 < n; i++) {
		if (src[i] || src[i + 1] || src[i + 2] != 1)
			continue;
		if (!sps_at && (src[i + 3] & 0x1f) == 7) {
			sps_at = i + 3;
		} else if (sps_at && i > sps_at) {
			sps_end = (i && !src[i - 1]) ? i - 1 : i;
			break;
		}
	}
	if (!sps_at || !sps_end)
		goto as_is;
	rbsp = kmalloc(2 * (sps_end - sps_at) + 32, GFP_KERNEL);
	if (!rbsp)
		goto as_is;
	sps = rbsp + (sps_end - sps_at);
	rn = nal_unescape(src + sps_at + 1, sps_end - sps_at - 1, rbsp);
	sn = sps_crop(rbsp, rn, sps, sps_end - sps_at + 32, right, bottom);
	if (!sn || sps_at + 1 + 2 * sn + (n - sps_end) > cap) {
		kfree(rbsp);
		goto as_is;
	}
	memcpy(dst, src, sps_at + 1);			/* start code, NAL header */
	en = nal_escape(sps, sn, dst + sps_at + 1, cap - sps_at - 1);
	total = sps_at + 1 + en;
	memcpy(dst + total, src + sps_end, n - sps_end);
	total += n - sps_end;
	kfree(rbsp);
	return total;
as_is:
	memcpy(dst, src, min(n, cap));
	return min(n, cap);
}

static int venc_encode(struct venc_ctx *ctx, struct vb2_v4l2_buffer *src,
		       struct vb2_v4l2_buffer *dst, u32 *len, bool *key)
{
	u8 *out = vb2_plane_vaddr(&dst->vb2_buf, 0);
	size_t cap = vb2_plane_size(&dst->vb2_buf, 0);
	dma_addr_t in = vb2_dma_contig_plane_dma_addr(&src->vb2_buf, 0);
	bool idr = ctx->since_idr == 0 || ctx->since_idr >= ctx->gop || ctx->force_key;
	u32 quant, n = 0, size;
	ktime_t t0 = ktime_get();
	int ret;

	if (!out)
		return -EFAULT;
	if (ctx->rc)
		quant = idr ? ctx->qp_idr : ctx->qp;
	else
		quant = idr ? ctx->qp_i : ctx->qp_p;

	if (idr) {
		ret = venc_headers(ctx, quant, &size);
		if (ret)
			return ret;
		if (size > cap || size > ctx->bs.size)
			return -ENOSPC;
		n = venc_copy_headers(ctx, ctx->bs.cpu, size, out, cap);
	}
	ret = venc_picture(ctx, in, idr, quant, &size);
	if (ret)
		return ret;
	if (size > ctx->bs.size || n + size > cap)
		return -ENOSPC;
	memcpy(out + n, ctx->bs.cpu, size);
	n += size;

	venc_commit(ctx, idr);
	if (idr) {
		ctx->since_idr = 0;
		ctx->force_key = false;
	}
	ctx->since_idr++;
	venc_rc(ctx, idr, size);
	if (debug)
		dev_info(ctx->dev->dev, "%s qp %u: %u bytes, %lld us\n", idr ? "IDR" : "P", quant, n,
			 ktime_us_delta(ktime_get(), t0));
	*len = n;
	*key = idr;
	return 0;
}

static void venc_run(struct work_struct *work)
{
	struct venc_dev *d = container_of(work, struct venc_dev, run_work);
	struct venc_ctx *ctx = v4l2_m2m_get_curr_priv(d->m2m);
	struct vb2_v4l2_buffer *src, *dst;
	bool key = false;
	u32 len = 0;
	int ret;

	if (!ctx)
		return;
	src = v4l2_m2m_src_buf_remove(ctx->fh.m2m_ctx);
	dst = v4l2_m2m_dst_buf_remove(ctx->fh.m2m_ctx);
	if (!src || !dst) {
		ret = -EINVAL;
		goto done;
	}

	mutex_lock(&d->hw_lock);
	ret = 0;
	if (!d->powered) {
		ret = venc_power_on(d);
		if (ret)
			venc_power_off(d);
	}
	if (!ret)
		ret = venc_encode(ctx, src, dst, &len, &key);
	if (ret == -ETIMEDOUT) {
		/* amvenc_avc_light_reset(): power cycle, the microcode again */
		venc_power_off(d);
		msleep(30);
		if (venc_power_on(d))
			venc_power_off(d);
		ctx->since_idr = 0;
	}
	mutex_unlock(&d->hw_lock);
	mod_delayed_work(system_dfl_wq, &d->idle_work, msecs_to_jiffies(idle_ms));

	v4l2_m2m_buf_copy_metadata(src, dst);
	dst->flags &= ~(V4L2_BUF_FLAG_KEYFRAME | V4L2_BUF_FLAG_PFRAME);
	dst->flags |= key ? V4L2_BUF_FLAG_KEYFRAME : V4L2_BUF_FLAG_PFRAME;
	dst->sequence = ctx->sequence++;
	vb2_set_plane_payload(&dst->vb2_buf, 0, ret ? 0 : len);
done:
	if (src)
		v4l2_m2m_buf_done(src, ret ? VB2_BUF_STATE_ERROR : VB2_BUF_STATE_DONE);
	if (dst)
		v4l2_m2m_buf_done(dst, ret ? VB2_BUF_STATE_ERROR : VB2_BUF_STATE_DONE);
	v4l2_m2m_job_finish(d->m2m, ctx->fh.m2m_ctx);
}

static void venc_idle(struct work_struct *work)
{
	struct venc_dev *d = container_of(work, struct venc_dev, idle_work.work);

	mutex_lock(&d->hw_lock);
	venc_power_off(d);
	mutex_unlock(&d->hw_lock);
}

static void venc_device_run(void *priv)
{
	struct venc_ctx *ctx = priv;

	queue_work(ctx->dev->wq, &ctx->dev->run_work);
}

static const struct v4l2_m2m_ops venc_m2m_ops = {
	.device_run = venc_device_run,
};

static irqreturn_t venc_isr(int irq, void *data)
{
	struct venc_dev *d = data;
	u32 st;

	if (!d->powered)
		return IRQ_NONE;
	hw(d, HCODEC_ASSIST_MBOX2_CLR_REG, 1);
	st = hr(d, ENCODER_STATUS);
	/*
	 * This microcode ends a P picture with ENCODER_IDR_DONE too (Amlogic's
	 * library takes IDR_DONE as "done" for both); either ends a picture.
	 */
	if (st == ENCODER_NON_IDR_DONE)
		st = ENCODER_IDR_DONE;
	if (st == READ_ONCE(d->wait_status)) {
		d->irq_status = st;
		complete(&d->done);
	}
	return IRQ_HANDLED;
}

/* buffers of a stream */

static void venc_free(struct venc_dev *d, struct venc_buf *b)
{
	if (b->cpu)
		dma_free_coherent(d->dev, b->size, b->cpu, b->dma);
	b->cpu = NULL;
}

static int venc_alloc(struct venc_dev *d, struct venc_buf *b, size_t size)
{
	b->size = PAGE_ALIGN(size);
	b->cpu = dma_alloc_coherent(d->dev, b->size, &b->dma, GFP_KERNEL);
	return b->cpu ? 0 : -ENOMEM;
}

static void venc_free_all(struct venc_ctx *ctx)
{
	struct venc_dev *d = ctx->dev;

	venc_free(d, &ctx->ref);
	venc_free(d, &ctx->bs);
	venc_free(d, &ctx->dct);
	venc_free(d, &ctx->assist);
	venc_free(d, &ctx->dump);
	venc_free(d, &ctx->cbr);
}

/* get_block_resolution() of Amlogic's library: about 256 CBR blocks */
static void venc_blocks(struct venc_ctx *ctx)
{
	u32 mb_w = DIV_ROUND_UP(ctx->width, 16), mb_h = DIV_ROUND_UP(ctx->height, 16);
	u32 nh = max(int_sqrt(CBR_BLOCKS * mb_h / mb_w), 1ul);
	u32 nw = max(int_sqrt(CBR_BLOCKS * mb_w / mb_h), 1ul);

	ctx->block_w = DIV_ROUND_UP(mb_w, nw);
	ctx->block_h = DIV_ROUND_UP(mb_h, nh);
	ctx->blocks_x = DIV_ROUND_UP(mb_w, ctx->block_w);
	ctx->blocks_y = DIV_ROUND_UP(mb_h, ctx->block_h);
}

static int venc_alloc_all(struct venc_ctx *ctx)
{
	struct venc_dev *d = ctx->dev;
	u32 mbs = DIV_ROUND_UP(ctx->width, 16) * DIV_ROUND_UP(ctx->height, 16);
	int ret;

	ctx->cv_w = ALIGN(ctx->width, 32);
	ctx->cv_h = ALIGN(ctx->height, 16);
	ctx->ref_y_size = ctx->cv_w * ctx->cv_h;
	ret = venc_alloc(d, &ctx->ref, 2 * PAGE_ALIGN(ctx->ref_y_size * 3 / 2));
	ret = ret ?: venc_alloc(d, &ctx->bs, BS_SIZE);
	/* 4 bytes a pixel, as Amlogic's 0x800000 for 1920x1088 */
	ret = ret ?: venc_alloc(d, &ctx->dct, mbs * 256 * 4);
	ret = ret ?: venc_alloc(d, &ctx->assist, ASSIST_SIZE);
	ret = ret ?: venc_alloc(d, &ctx->dump, mbs * DUMP_PER_MB);
	ret = ret ?: venc_alloc(d, &ctx->cbr, CBR_SIZE);
	if (ret) {
		venc_free_all(ctx);
		return ret;
	}
	venc_blocks(ctx);
	return 0;
}

/* vb2 */

static int venc_queue_setup(struct vb2_queue *q, unsigned int *nbufs,
			    unsigned int *nplanes, unsigned int sizes[],
			    struct device *alloc_devs[])
{
	struct venc_ctx *ctx = vb2_get_drv_priv(q);
	u32 size = V4L2_TYPE_IS_OUTPUT(q->type) ? ctx->out_size : ctx->cap_size;

	if (*nplanes)
		return sizes[0] < size ? -EINVAL : 0;
	*nplanes = 1;
	sizes[0] = size;
	return 0;
}

static int venc_buf_prepare(struct vb2_buffer *vb)
{
	struct venc_ctx *ctx = vb2_get_drv_priv(vb->vb2_queue);
	bool out = V4L2_TYPE_IS_OUTPUT(vb->vb2_queue->type);
	u32 size = out ? ctx->out_size : ctx->cap_size;

	if (vb2_plane_size(vb, 0) < size)
		return -EINVAL;
	if (out)
		vb2_set_plane_payload(vb, 0, size);
	return 0;
}

static void venc_buf_queue(struct vb2_buffer *vb)
{
	struct venc_ctx *ctx = vb2_get_drv_priv(vb->vb2_queue);

	v4l2_m2m_buf_queue(ctx->fh.m2m_ctx, to_vb2_v4l2_buffer(vb));
}

static void venc_return_bufs(struct venc_ctx *ctx, struct vb2_queue *q,
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

static int venc_start_streaming(struct vb2_queue *q, unsigned int count)
{
	struct venc_ctx *ctx = vb2_get_drv_priv(q);
	struct venc_dev *d = ctx->dev;
	int ret = 0;

	if (!V4L2_TYPE_IS_OUTPUT(q->type)) {
		ctx->sequence = 0;
		return 0;
	}
	ret = venc_alloc_all(ctx);
	if (ret)
		goto fail;
	ctx->since_idr = 0;
	ctx->idr_pic_id = 0;
	ctx->frame_number = 0;
	ctx->poc = 0;
	ctx->dec1_is_ref = true;	/* the first picture is built in dec0 */
	ctx->qp = ctx->qp_p;
	ctx->qp_idr = max_t(int, ctx->qp_p - 2, ctx->qp_min);
	ctx->fullness = 0;

	/* powered with the first picture, see venc_run() */
	mutex_lock(&d->hw_lock);
	d->users++;
	mutex_unlock(&d->hw_lock);
	return 0;
fail:
	dev_err(d->dev, "start: %d\n", ret);
	venc_return_bufs(ctx, q, VB2_BUF_STATE_QUEUED);
	return ret;
}

static void venc_stop_streaming(struct vb2_queue *q)
{
	struct venc_ctx *ctx = vb2_get_drv_priv(q);
	struct venc_dev *d = ctx->dev;
	bool last;

	venc_return_bufs(ctx, q, VB2_BUF_STATE_ERROR);
	if (!V4L2_TYPE_IS_OUTPUT(q->type))
		return;

	mutex_lock(&d->hw_lock);
	last = d->users && !--d->users;
	mutex_unlock(&d->hw_lock);
	if (last) {
		cancel_delayed_work_sync(&d->idle_work);
		mutex_lock(&d->hw_lock);
		if (!d->users)
			venc_power_off(d);
		mutex_unlock(&d->hw_lock);
	}
	venc_free_all(ctx);
}

static const struct vb2_ops venc_qops = {
	.queue_setup = venc_queue_setup,
	.buf_prepare = venc_buf_prepare,
	.buf_queue = venc_buf_queue,
	.start_streaming = venc_start_streaming,
	.stop_streaming = venc_stop_streaming,
};

static int venc_queue_init(void *priv, struct vb2_queue *src, struct vb2_queue *dst)
{
	struct venc_ctx *ctx = priv;
	int ret;

	src->type = V4L2_BUF_TYPE_VIDEO_OUTPUT;
	src->io_modes = VB2_MMAP | VB2_DMABUF;
	src->drv_priv = ctx;
	src->buf_struct_size = sizeof(struct v4l2_m2m_buffer);
	src->ops = &venc_qops;
	src->mem_ops = &vb2_dma_contig_memops;
	src->timestamp_flags = V4L2_BUF_FLAG_TIMESTAMP_COPY;
	src->lock = &ctx->dev->lock;
	src->dev = ctx->dev->dev;
	ret = vb2_queue_init(src);
	if (ret)
		return ret;

	dst->type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	dst->io_modes = VB2_MMAP | VB2_DMABUF;
	dst->drv_priv = ctx;
	dst->buf_struct_size = sizeof(struct v4l2_m2m_buffer);
	dst->ops = &venc_qops;
	dst->mem_ops = &vb2_dma_contig_memops;
	dst->timestamp_flags = V4L2_BUF_FLAG_TIMESTAMP_COPY;
	dst->lock = &ctx->dev->lock;
	dst->dev = ctx->dev->dev;
	return vb2_queue_init(dst);
}

/* formats */

static const struct venc_fmt *venc_find_fmt(u32 fourcc)
{
	int i;

	for (i = 0; i < ARRAY_SIZE(venc_formats); i++)
		if (venc_formats[i].fourcc == fourcc)
			return &venc_formats[i];
	return NULL;
}

static void venc_out_layout(const struct venc_fmt *f, u32 w, u32 h, u32 *bpl, u32 *size)
{
	if (f->linear) {
		/* MFDIN reads whole MBs: a 16-pixel multiple, some rows more */
		*bpl = ALIGN(w, 16) * f->bpp;
		*size = *bpl * ALIGN(h, 16);
	} else {
		*bpl = ALIGN(w, 32);
		*size = *bpl * ALIGN(h, 16) * 3 / 2;
	}
}

static u32 venc_default_cap_size(u32 w, u32 h)
{
	return max_t(u32, SZ_512K, ALIGN(w * h * 3 / 4, SZ_4K));
}

static int venc_querycap(struct file *file, void *priv, struct v4l2_capability *cap)
{
	strscpy(cap->driver, DRV_NAME, sizeof(cap->driver));
	strscpy(cap->card, "Amlogic HCODEC H.264 encoder", sizeof(cap->card));
	strscpy(cap->bus_info, "platform:" DRV_NAME, sizeof(cap->bus_info));
	return 0;
}

static int venc_enum_fmt_out(struct file *file, void *priv, struct v4l2_fmtdesc *f)
{
	if (f->index >= ARRAY_SIZE(venc_formats))
		return -EINVAL;
	f->pixelformat = venc_formats[f->index].fourcc;
	return 0;
}

static int venc_enum_fmt_cap(struct file *file, void *priv, struct v4l2_fmtdesc *f)
{
	if (f->index)
		return -EINVAL;
	f->pixelformat = V4L2_PIX_FMT_H264;
	f->flags = V4L2_FMT_FLAG_COMPRESSED;
	return 0;
}

static int venc_enum_framesizes(struct file *file, void *priv, struct v4l2_frmsizeenum *fs)
{
	if (fs->index || (fs->pixel_format != V4L2_PIX_FMT_H264 &&
			  !venc_find_fmt(fs->pixel_format)))
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

static void venc_fill_colors(struct venc_ctx *ctx, struct v4l2_pix_format *p)
{
	p->field = V4L2_FIELD_NONE;
	p->colorspace = ctx->colorspace;
	p->xfer_func = ctx->xfer_func;
	p->ycbcr_enc = ctx->ycbcr_enc;
	p->quantization = ctx->quant;
}

static int venc_g_fmt_out(struct file *file, void *priv, struct v4l2_format *f)
{
	struct venc_ctx *ctx = file_to_ctx(file);
	struct v4l2_pix_format *p = &f->fmt.pix;

	p->width = ctx->width;
	p->height = ctx->height;
	p->pixelformat = ctx->fmt->fourcc;
	p->bytesperline = ctx->bpl;
	p->sizeimage = ctx->out_size;
	venc_fill_colors(ctx, p);
	return 0;
}

static int venc_g_fmt_cap(struct file *file, void *priv, struct v4l2_format *f)
{
	struct venc_ctx *ctx = file_to_ctx(file);
	struct v4l2_pix_format *p = &f->fmt.pix;

	p->width = ctx->width;
	p->height = ctx->height;
	p->pixelformat = V4L2_PIX_FMT_H264;
	p->bytesperline = 0;
	p->sizeimage = ctx->cap_size;
	venc_fill_colors(ctx, p);
	return 0;
}

static int venc_try_fmt_out(struct file *file, void *priv, struct v4l2_format *f)
{
	struct v4l2_pix_format *p = &f->fmt.pix;
	const struct venc_fmt *fmt = venc_find_fmt(p->pixelformat);

	if (!fmt) {
		fmt = &venc_formats[0];
		p->pixelformat = fmt->fourcc;
	}
	p->width = clamp(ALIGN(p->width, 2), (u32)MIN_W, (u32)MAX_W);
	p->height = clamp(ALIGN(p->height, 2), (u32)MIN_H, (u32)MAX_H);
	p->field = V4L2_FIELD_NONE;
	venc_out_layout(fmt, p->width, p->height, &p->bytesperline, &p->sizeimage);
	return 0;
}

static int venc_try_fmt_cap(struct file *file, void *priv, struct v4l2_format *f)
{
	struct venc_ctx *ctx = file_to_ctx(file);
	struct v4l2_pix_format *p = &f->fmt.pix;

	p->pixelformat = V4L2_PIX_FMT_H264;
	p->width = ctx->width;
	p->height = ctx->height;
	p->bytesperline = 0;
	p->sizeimage = clamp_t(u32, p->sizeimage, venc_default_cap_size(p->width, p->height),
			       BS_SIZE * 2);
	venc_fill_colors(ctx, p);
	return 0;
}

static int venc_s_fmt_out(struct file *file, void *priv, struct v4l2_format *f)
{
	struct venc_ctx *ctx = file_to_ctx(file);
	struct v4l2_pix_format *p = &f->fmt.pix;
	int ret;

	if (vb2_is_busy(v4l2_m2m_get_vq(ctx->fh.m2m_ctx, f->type)))
		return -EBUSY;
	ret = venc_try_fmt_out(file, priv, f);
	if (ret)
		return ret;
	ctx->fmt = venc_find_fmt(p->pixelformat);
	ctx->width = p->width;
	ctx->height = p->height;
	ctx->bpl = p->bytesperline;
	ctx->out_size = p->sizeimage;
	ctx->colorspace = p->colorspace;
	ctx->xfer_func = p->xfer_func;
	ctx->ycbcr_enc = p->ycbcr_enc;
	ctx->quant = p->quantization;
	ctx->cap_size = venc_default_cap_size(ctx->width, ctx->height);
	return 0;
}

static int venc_s_fmt_cap(struct file *file, void *priv, struct v4l2_format *f)
{
	struct venc_ctx *ctx = file_to_ctx(file);
	int ret;

	if (vb2_is_busy(v4l2_m2m_get_vq(ctx->fh.m2m_ctx, f->type)))
		return -EBUSY;
	ret = venc_try_fmt_cap(file, priv, f);
	if (ret)
		return ret;
	ctx->cap_size = f->fmt.pix.sizeimage;
	return 0;
}

static int venc_g_parm(struct file *file, void *priv, struct v4l2_streamparm *a)
{
	struct venc_ctx *ctx = file_to_ctx(file);

	if (a->type != V4L2_BUF_TYPE_VIDEO_OUTPUT && a->type != V4L2_BUF_TYPE_VIDEO_CAPTURE)
		return -EINVAL;
	if (a->type == V4L2_BUF_TYPE_VIDEO_OUTPUT) {
		a->parm.output.capability = V4L2_CAP_TIMEPERFRAME;
		a->parm.output.timeperframe = ctx->tpf;
	} else {
		a->parm.capture.capability = V4L2_CAP_TIMEPERFRAME;
		a->parm.capture.timeperframe = ctx->tpf;
	}
	return 0;
}

static int venc_s_parm(struct file *file, void *priv, struct v4l2_streamparm *a)
{
	struct venc_ctx *ctx = file_to_ctx(file);
	struct v4l2_fract *t = a->type == V4L2_BUF_TYPE_VIDEO_OUTPUT ?
		&a->parm.output.timeperframe : &a->parm.capture.timeperframe;

	if (a->type != V4L2_BUF_TYPE_VIDEO_OUTPUT && a->type != V4L2_BUF_TYPE_VIDEO_CAPTURE)
		return -EINVAL;
	if (t->numerator && t->denominator)
		ctx->tpf = *t;
	return venc_g_parm(file, priv, a);
}

static const struct v4l2_ioctl_ops venc_ioctl_ops = {
	.vidioc_querycap = venc_querycap,
	.vidioc_enum_fmt_vid_cap = venc_enum_fmt_cap,
	.vidioc_enum_fmt_vid_out = venc_enum_fmt_out,
	.vidioc_g_fmt_vid_cap = venc_g_fmt_cap,
	.vidioc_g_fmt_vid_out = venc_g_fmt_out,
	.vidioc_try_fmt_vid_cap = venc_try_fmt_cap,
	.vidioc_try_fmt_vid_out = venc_try_fmt_out,
	.vidioc_s_fmt_vid_cap = venc_s_fmt_cap,
	.vidioc_s_fmt_vid_out = venc_s_fmt_out,
	.vidioc_enum_framesizes = venc_enum_framesizes,
	.vidioc_g_parm = venc_g_parm,
	.vidioc_s_parm = venc_s_parm,

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

static int venc_s_ctrl(struct v4l2_ctrl *c)
{
	struct venc_ctx *ctx = container_of(c->handler, struct venc_ctx, hdl);

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

static const struct v4l2_ctrl_ops venc_ctrl_ops = {
	.s_ctrl = venc_s_ctrl,
};

static int venc_init_ctrls(struct venc_ctx *ctx)
{
	struct v4l2_ctrl_handler *h = &ctx->hdl;
	const struct v4l2_ctrl_ops *o = &venc_ctrl_ops;

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

static int venc_open(struct file *file)
{
	struct venc_dev *d = video_drvdata(file);
	struct venc_ctx *ctx;
	int ret;

	ctx = kzalloc(sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;
	ctx->dev = d;
	ctx->fmt = &venc_formats[0];
	ctx->width = 640;
	ctx->height = 480;
	venc_out_layout(ctx->fmt, ctx->width, ctx->height, &ctx->bpl, &ctx->out_size);
	ctx->cap_size = venc_default_cap_size(ctx->width, ctx->height);
	ctx->tpf.numerator = 1;
	ctx->tpf.denominator = 30;
	ctx->colorspace = V4L2_COLORSPACE_SMPTE170M;

	if (mutex_lock_interruptible(&d->lock)) {
		kfree(ctx);
		return -ERESTARTSYS;
	}
	v4l2_fh_init(&ctx->fh, video_devdata(file));
	ret = venc_init_ctrls(ctx);
	if (ret)
		goto fail_fh;
	ctx->fh.m2m_ctx = v4l2_m2m_ctx_init(d->m2m, ctx, venc_queue_init);
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

static int venc_release(struct file *file)
{
	struct venc_dev *d = video_drvdata(file);
	struct venc_ctx *ctx = file_to_ctx(file);

	mutex_lock(&d->lock);
	v4l2_m2m_ctx_release(ctx->fh.m2m_ctx);
	mutex_unlock(&d->lock);
	v4l2_fh_del(&ctx->fh, file);
	v4l2_fh_exit(&ctx->fh);
	v4l2_ctrl_handler_free(&ctx->hdl);
	kfree(ctx);
	return 0;
}

static const struct v4l2_file_operations venc_fops = {
	.owner = THIS_MODULE,
	.open = venc_open,
	.release = venc_release,
	.poll = v4l2_m2m_fop_poll,
	.unlocked_ioctl = video_ioctl2,
	.mmap = v4l2_m2m_fop_mmap,
};

/* device */

static int venc_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct venc_dev *d;
	struct resource *r;
	int i, ret;

	d = devm_kzalloc(dev, sizeof(*d), GFP_KERNEL);
	if (!d)
		return -ENOMEM;
	d->dev = dev;
	platform_set_drvdata(pdev, d);

	/* inside the DOS block the decoder claims: mapped without a claim */
	r = platform_get_resource_byname(pdev, IORESOURCE_MEM, "hcodec");
	if (!r)
		return -EINVAL;
	d->hcodec = devm_ioremap(dev, r->start, resource_size(r));
	r = platform_get_resource_byname(pdev, IORESOURCE_MEM, "dos-top");
	if (!r)
		return -EINVAL;
	d->dos_top = devm_ioremap(dev, r->start, resource_size(r));
	if (!d->hcodec || !d->dos_top)
		return -ENOMEM;

	d->ao = syscon_regmap_lookup_by_phandle(dev->of_node, "amlogic,ao-sysctrl");
	if (IS_ERR(d->ao))
		return dev_err_probe(dev, PTR_ERR(d->ao), "ao-sysctrl\n");
	d->canvas = meson_canvas_get(dev);
	if (IS_ERR(d->canvas))
		return dev_err_probe(dev, PTR_ERR(d->canvas), "canvas\n");
	d->dos_clk = devm_clk_get(dev, "dos");
	if (IS_ERR(d->dos_clk))
		return dev_err_probe(dev, PTR_ERR(d->dos_clk), "dos clock\n");
	d->hcodec_clk = devm_clk_get(dev, "hcodec");
	if (IS_ERR(d->hcodec_clk))
		return dev_err_probe(dev, PTR_ERR(d->hcodec_clk), "hcodec clock\n");

	ret = dma_set_mask_and_coherent(dev, DMA_BIT_MASK(32));
	if (ret)
		return ret;

	for (i = 0; i < CV_NUM; i++) {
		ret = meson_canvas_alloc(d->canvas, &d->cv[i]);
		if (ret) {
			while (i--)
				meson_canvas_free(d->canvas, d->cv[i]);
			return ret;
		}
	}

	mutex_init(&d->lock);
	mutex_init(&d->hw_lock);
	init_completion(&d->done);
	INIT_WORK(&d->run_work, venc_run);
	INIT_DELAYED_WORK(&d->idle_work, venc_idle);
	d->wq = alloc_ordered_workqueue(DRV_NAME, WQ_HIGHPRI);
	if (!d->wq) {
		ret = -ENOMEM;
		goto fail_canvas;
	}

	d->irq = platform_get_irq(pdev, 0);
	if (d->irq < 0) {
		ret = d->irq;
		goto fail_wq;
	}
	ret = devm_request_irq(dev, d->irq, venc_isr, 0, DRV_NAME, d);
	if (ret)
		goto fail_wq;

	ret = v4l2_device_register(dev, &d->v4l2_dev);
	if (ret)
		goto fail_wq;
	d->m2m = v4l2_m2m_init(&venc_m2m_ops);
	if (IS_ERR(d->m2m)) {
		ret = PTR_ERR(d->m2m);
		goto fail_v4l2;
	}

	d->vfd = (struct video_device) {
		.name = DRV_NAME,
		.fops = &venc_fops,
		.ioctl_ops = &venc_ioctl_ops,
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
fail_wq:
	destroy_workqueue(d->wq);
fail_canvas:
	for (i = 0; i < CV_NUM; i++)
		meson_canvas_free(d->canvas, d->cv[i]);
	return ret;
}

static void venc_remove(struct platform_device *pdev)
{
	struct venc_dev *d = platform_get_drvdata(pdev);
	int i;

	video_unregister_device(&d->vfd);
	v4l2_m2m_release(d->m2m);
	v4l2_device_unregister(&d->v4l2_dev);
	destroy_workqueue(d->wq);
	cancel_delayed_work_sync(&d->idle_work);
	mutex_lock(&d->hw_lock);
	venc_power_off(d);
	mutex_unlock(&d->hw_lock);
	venc_free(d, &d->mc);
	for (i = 0; i < CV_NUM; i++)
		meson_canvas_free(d->canvas, d->cv[i]);
}

static const struct of_device_id venc_of_match[] = {
	{ .compatible = "amlogic,g12a-hcodec" },
	{ }
};
MODULE_DEVICE_TABLE(of, venc_of_match);

static struct platform_driver venc_driver = {
	.probe = venc_probe,
	.remove = venc_remove,
	.driver = {
		.name = DRV_NAME,
		.of_match_table = venc_of_match,
	},
};
module_platform_driver(venc_driver);

MODULE_DESCRIPTION("Amlogic G12 HCODEC H.264 encoder");
MODULE_LICENSE("GPL");
MODULE_FIRMWARE(FW_NAME);
