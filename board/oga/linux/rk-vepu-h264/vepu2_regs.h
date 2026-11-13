/* SPDX-License-Identifier: GPL-2.0 */
/*
 * Hantro VPU codec driver: the encoder registers of
 * drivers/media/platform/verisilicon/rockchip_vpu2_regs.h, copied for
 * rk-vepu-h264
 *
 * Copyright (C) 2018 Rockchip Electronics Co., Ltd.
 *	Alpha Lin <alpha.lin@rock-chips.com>
 */

#ifndef ROCKCHIP_VPU2_REGS_H_
#define ROCKCHIP_VPU2_REGS_H_

/* Encoder registers. */
#define VEPU_REG_VP8_QUT_1ST(i)			(0x000 + ((i) * 0x24))
#define     VEPU_REG_VP8_QUT_DC_Y2(x)			(((x) & 0x3fff) << 16)
#define     VEPU_REG_VP8_QUT_DC_Y1(x)			(((x) & 0x3fff) << 0)
#define VEPU_REG_VP8_QUT_2ND(i)			(0x004 + ((i) * 0x24))
#define     VEPU_REG_VP8_QUT_AC_Y1(x)			(((x) & 0x3fff) << 16)
#define     VEPU_REG_VP8_QUT_DC_CHR(x)			(((x) & 0x3fff) << 0)
#define VEPU_REG_VP8_QUT_3RD(i)			(0x008 + ((i) * 0x24))
#define     VEPU_REG_VP8_QUT_AC_CHR(x)			(((x) & 0x3fff) << 16)
#define     VEPU_REG_VP8_QUT_AC_Y2(x)			(((x) & 0x3fff) << 0)
#define VEPU_REG_VP8_QUT_4TH(i)			(0x00c + ((i) * 0x24))
#define     VEPU_REG_VP8_QUT_ZB_DC_CHR(x)		(((x) & 0x1ff) << 18)
#define     VEPU_REG_VP8_QUT_ZB_DC_Y2(x)		(((x) & 0x1ff) << 9)
#define     VEPU_REG_VP8_QUT_ZB_DC_Y1(x)		(((x) & 0x1ff) << 0)
#define VEPU_REG_VP8_QUT_5TH(i)			(0x010 + ((i) * 0x24))
#define     VEPU_REG_VP8_QUT_ZB_AC_CHR(x)		(((x) & 0x1ff) << 18)
#define     VEPU_REG_VP8_QUT_ZB_AC_Y2(x)		(((x) & 0x1ff) << 9)
#define     VEPU_REG_VP8_QUT_ZB_AC_Y1(x)		(((x) & 0x1ff) << 0)
#define VEPU_REG_VP8_QUT_6TH(i)			(0x014 + ((i) * 0x24))
#define     VEPU_REG_VP8_QUT_RND_DC_CHR(x)		(((x) & 0xff) << 16)
#define     VEPU_REG_VP8_QUT_RND_DC_Y2(x)		(((x) & 0xff) << 8)
#define     VEPU_REG_VP8_QUT_RND_DC_Y1(x)		(((x) & 0xff) << 0)
#define VEPU_REG_VP8_QUT_7TH(i)			(0x018 + ((i) * 0x24))
#define     VEPU_REG_VP8_QUT_RND_AC_CHR(x)		(((x) & 0xff) << 16)
#define     VEPU_REG_VP8_QUT_RND_AC_Y2(x)		(((x) & 0xff) << 8)
#define     VEPU_REG_VP8_QUT_RND_AC_Y1(x)		(((x) & 0xff) << 0)
#define VEPU_REG_VP8_QUT_8TH(i)			(0x01c + ((i) * 0x24))
#define     VEPU_REG_VP8_SEG_FILTER_LEVEL(x)		(((x) & 0x3f) << 25)
#define     VEPU_REG_VP8_DEQUT_DC_CHR(x)		(((x) & 0xff) << 17)
#define     VEPU_REG_VP8_DEQUT_DC_Y2(x)			(((x) & 0x1ff) << 8)
#define     VEPU_REG_VP8_DEQUT_DC_Y1(x)			(((x) & 0xff) << 0)
#define VEPU_REG_VP8_QUT_9TH(i)			(0x020 + ((i) * 0x24))
#define     VEPU_REG_VP8_DEQUT_AC_CHR(x)		(((x) & 0x1ff) << 18)
#define     VEPU_REG_VP8_DEQUT_AC_Y2(x)			(((x) & 0x1ff) << 9)
#define     VEPU_REG_VP8_DEQUT_AC_Y1(x)			(((x) & 0x1ff) << 0)
#define VEPU_REG_ADDR_VP8_SEG_MAP		0x06c
#define VEPU_REG_VP8_INTRA_4X4_PENALTY(i)	(0x070 + ((i) * 0x4))
#define     VEPU_REG_VP8_INTRA_4X4_PENALTY_0(x)		(((x) & 0xfff) << 0)
#define     VEPU_REG_VP8_INTRA_4x4_PENALTY_1(x)		(((x) & 0xfff) << 16)
#define VEPU_REG_VP8_INTRA_16X16_PENALTY(i)	(0x084 + ((i) * 0x4))
#define     VEPU_REG_VP8_INTRA_16X16_PENALTY_0(x)	(((x) & 0xfff) << 0)
#define     VEPU_REG_VP8_INTRA_16X16_PENALTY_1(x)	(((x) & 0xfff) << 16)
#define VEPU_REG_VP8_CONTROL			0x0a0
#define     VEPU_REG_VP8_LF_MODE_DELTA_BPRED(x)		(((x) & 0x1f) << 24)
#define     VEPU_REG_VP8_LF_REF_DELTA_INTRA_MB(x)	(((x) & 0x7f) << 16)
#define     VEPU_REG_VP8_INTER_TYPE_BIT_COST(x)		(((x) & 0xfff) << 0)
#define VEPU_REG_VP8_REF_FRAME_VAL		0x0a4
#define     VEPU_REG_VP8_COEF_DMV_PENALTY(x)		(((x) & 0xfff) << 16)
#define     VEPU_REG_VP8_REF_FRAME(x)			(((x) & 0xfff) << 0)
#define VEPU_REG_VP8_LOOP_FILTER_REF_DELTA	0x0a8
#define     VEPU_REG_VP8_LF_REF_DELTA_ALT_REF(x)	(((x) & 0x7f) << 16)
#define     VEPU_REG_VP8_LF_REF_DELTA_LAST_REF(x)	(((x) & 0x7f) << 8)
#define     VEPU_REG_VP8_LF_REF_DELTA_GOLDEN(x)		(((x) & 0x7f) << 0)
#define VEPU_REG_VP8_LOOP_FILTER_MODE_DELTA	0x0ac
#define     VEPU_REG_VP8_LF_MODE_DELTA_SPLITMV(x)	(((x) & 0x7f) << 16)
#define     VEPU_REG_VP8_LF_MODE_DELTA_ZEROMV(x)	(((x) & 0x7f) << 8)
#define     VEPU_REG_VP8_LF_MODE_DELTA_NEWMV(x)		(((x) & 0x7f) << 0)
#define	VEPU_REG_JPEG_LUMA_QUAT(i)		(0x000 + ((i) * 0x4))
#define	VEPU_REG_JPEG_CHROMA_QUAT(i)		(0x040 + ((i) * 0x4))
#define VEPU_REG_INTRA_SLICE_BITMAP(i)		(0x0b0 + ((i) * 0x4))
#define VEPU_REG_ADDR_VP8_DCT_PART(i)		(0x0b0 + ((i) * 0x4))
#define VEPU_REG_INTRA_AREA_CTRL		0x0b8
#define     VEPU_REG_INTRA_AREA_TOP(x)			(((x) & 0xff) << 24)
#define     VEPU_REG_INTRA_AREA_BOTTOM(x)		(((x) & 0xff) << 16)
#define     VEPU_REG_INTRA_AREA_LEFT(x)			(((x) & 0xff) << 8)
#define     VEPU_REG_INTRA_AREA_RIGHT(x)		(((x) & 0xff) << 0)
#define VEPU_REG_CIR_INTRA_CTRL			0x0bc
#define     VEPU_REG_CIR_INTRA_FIRST_MB(x)		(((x) & 0xffff) << 16)
#define     VEPU_REG_CIR_INTRA_INTERVAL(x)		(((x) & 0xffff) << 0)
#define VEPU_REG_ADDR_IN_PLANE_0		0x0c0
#define VEPU_REG_ADDR_IN_PLANE_1		0x0c4
#define VEPU_REG_ADDR_IN_PLANE_2		0x0c8
#define VEPU_REG_STR_HDR_REM_MSB		0x0cc
#define VEPU_REG_STR_HDR_REM_LSB		0x0d0
#define VEPU_REG_STR_BUF_LIMIT			0x0d4
#define VEPU_REG_AXI_CTRL			0x0d8
#define     VEPU_REG_AXI_CTRL_READ_ID(x)		(((x) & 0xff) << 24)
#define     VEPU_REG_AXI_CTRL_WRITE_ID(x)		(((x) & 0xff) << 16)
#define     VEPU_REG_AXI_CTRL_BURST_LEN(x)		(((x) & 0x3f) << 8)
#define     VEPU_REG_AXI_CTRL_INCREMENT_MODE(x)		(((x) & 0x01) << 2)
#define     VEPU_REG_AXI_CTRL_BIRST_DISCARD(x)		(((x) & 0x01) << 1)
#define     VEPU_REG_AXI_CTRL_BIRST_DISABLE		BIT(0)
#define VEPU_QP_ADJUST_MAD_DELTA_ROI		0x0dc
#define     VEPU_REG_ROI_QP_DELTA_1			(((x) & 0xf) << 12)
#define     VEPU_REG_ROI_QP_DELTA_2			(((x) & 0xf) << 8)
#define     VEPU_REG_MAD_QP_ADJUSTMENT			(((x) & 0xf) << 0)
#define VEPU_REG_ADDR_REF_LUMA			0x0e0
#define VEPU_REG_ADDR_REF_CHROMA		0x0e4
#define VEPU_REG_QP_SUM_DIV2			0x0e8
#define     VEPU_REG_QP_SUM(x)				(((x) & 0x001fffff) * 2)
#define VEPU_REG_ENC_CTRL0			0x0ec
#define     VEPU_REG_DISABLE_QUARTER_PIXEL_MV		BIT(28)
#define     VEPU_REG_DEBLOCKING_FILTER_MODE(x)		(((x) & 0x3) << 24)
#define     VEPU_REG_CABAC_INIT_IDC(x)			(((x) & 0x3) << 21)
#define     VEPU_REG_ENTROPY_CODING_MODE		BIT(20)
#define     VEPU_REG_H264_TRANS8X8_MODE			BIT(17)
#define     VEPU_REG_H264_INTER4X4_MODE			BIT(16)
#define     VEPU_REG_H264_STREAM_MODE			BIT(15)
#define     VEPU_REG_H264_SLICE_SIZE(x)			(((x) & 0x7f) << 8)
#define VEPU_REG_ENC_OVER_FILL_STRM_OFFSET	0x0f0
#define     VEPU_REG_STREAM_START_OFFSET(x)		(((x) & 0x3f) << 16)
#define     VEPU_REG_SKIP_MACROBLOCK_PENALTY(x)		(((x) & 0xff) << 8)
#define     VEPU_REG_IN_IMG_CTRL_OVRFLR_D4(x)		(((x) & 0x3) << 4)
#define     VEPU_REG_IN_IMG_CTRL_OVRFLB(x)		(((x) & 0xf) << 0)
#define VEPU_REG_INPUT_LUMA_INFO		0x0f4
#define     VEPU_REG_IN_IMG_CHROMA_OFFSET(x)		(((x) & 0x7) << 20)
#define     VEPU_REG_IN_IMG_LUMA_OFFSET(x)		(((x) & 0x7) << 16)
#define     VEPU_REG_IN_IMG_CTRL_ROW_LEN(x)		(((x) & 0x3fff) << 0)
#define VEPU_REG_RLC_SUM			0x0f8
#define     VEPU_REG_RLC_SUM_OUT(x)			(((x) & 0x007fffff) * 4)
#define VEPU_REG_SPLIT_PENALTY_4X4		0x0f8
#define	    VEPU_REG_VP8_SPLIT_PENALTY_4X4		(((x) & 0x1ff) << 19)
#define VEPU_REG_ADDR_REC_LUMA			0x0fc
#define VEPU_REG_ADDR_REC_CHROMA		0x100
#define VEPU_REG_CHECKPOINT(i)			(0x104 + ((i) * 0x4))
#define     VEPU_REG_CHECKPOINT_CHECK0(x)		(((x) & 0xffff))
#define     VEPU_REG_CHECKPOINT_CHECK1(x)		(((x) & 0xffff) << 16)
#define     VEPU_REG_CHECKPOINT_RESULT(x) \
		((((x) >> (16 - 16 * ((i) & 1))) & 0xffff) * 32)
#define VEPU_REG_VP8_SEG0_QUANT_AC_Y1		0x104
#define     VEPU_REG_VP8_SEG0_RND_AC_Y1(x)		(((x) & 0xff) << 23)
#define     VEPU_REG_VP8_SEG0_ZBIN_AC_Y1(x)		(((x) & 0x1ff) << 14)
#define     VEPU_REG_VP8_SEG0_QUT_AC_Y1(x)		(((x) & 0x3fff) << 0)
#define VEPU_REG_VP8_SEG0_QUANT_DC_Y2		0x108
#define     VEPU_REG_VP8_SEG0_RND_DC_Y2(x)		(((x) & 0xff) << 23)
#define     VEPU_REG_VP8_SEG0_ZBIN_DC_Y2(x)		(((x) & 0x1ff) << 14)
#define     VEPU_REG_VP8_SEG0_QUT_DC_Y2(x)		(((x) & 0x3fff) << 0)
#define VEPU_REG_VP8_SEG0_QUANT_AC_Y2		0x10c
#define     VEPU_REG_VP8_SEG0_RND_AC_Y2(x)		(((x) & 0xff) << 23)
#define     VEPU_REG_VP8_SEG0_ZBIN_AC_Y2(x)		(((x) & 0x1ff) << 14)
#define     VEPU_REG_VP8_SEG0_QUT_AC_Y2(x)		(((x) & 0x3fff) << 0)
#define VEPU_REG_VP8_SEG0_QUANT_DC_CHR		0x110
#define     VEPU_REG_VP8_SEG0_RND_DC_CHR(x)		(((x) & 0xff) << 23)
#define     VEPU_REG_VP8_SEG0_ZBIN_DC_CHR(x)		(((x) & 0x1ff) << 14)
#define     VEPU_REG_VP8_SEG0_QUT_DC_CHR(x)		(((x) & 0x3fff) << 0)
#define VEPU_REG_VP8_SEG0_QUANT_AC_CHR		0x114
#define     VEPU_REG_VP8_SEG0_RND_AC_CHR(x)		(((x) & 0xff) << 23)
#define     VEPU_REG_VP8_SEG0_ZBIN_AC_CHR(x)		(((x) & 0x1ff) << 14)
#define     VEPU_REG_VP8_SEG0_QUT_AC_CHR(x)		(((x) & 0x3fff) << 0)
#define VEPU_REG_VP8_SEG0_QUANT_DQUT		0x118
#define     VEPU_REG_VP8_MV_REF_IDX1(x)			(((x) & 0x03) << 26)
#define     VEPU_REG_VP8_SEG0_DQUT_DC_Y2(x)		(((x) & 0x1ff) << 17)
#define     VEPU_REG_VP8_SEG0_DQUT_AC_Y1(x)		(((x) & 0x1ff) << 8)
#define     VEPU_REG_VP8_SEG0_DQUT_DC_Y1(x)		(((x) & 0xff) << 0)
#define VEPU_REG_CHKPT_WORD_ERR(i)		(0x118 + ((i) * 0x4))
#define     VEPU_REG_CHKPT_WORD_ERR_CHK0(x)		(((x) & 0xffff))
#define     VEPU_REG_CHKPT_WORD_ERR_CHK1(x)		(((x) & 0xffff) << 16)
#define VEPU_REG_VP8_SEG0_QUANT_DQUT_1		0x11c
#define     VEPU_REG_VP8_SEGMENT_MAP_UPDATE		BIT(30)
#define     VEPU_REG_VP8_SEGMENT_EN			BIT(29)
#define     VEPU_REG_VP8_MV_REF_IDX2_EN			BIT(28)
#define     VEPU_REG_VP8_MV_REF_IDX2(x)			(((x) & 0x03) << 26)
#define     VEPU_REG_VP8_SEG0_DQUT_AC_CHR(x)		(((x) & 0x1ff) << 17)
#define     VEPU_REG_VP8_SEG0_DQUT_DC_CHR(x)		(((x) & 0xff) << 9)
#define     VEPU_REG_VP8_SEG0_DQUT_AC_Y2(x)		(((x) & 0x1ff) << 0)
#define VEPU_REG_VP8_BOOL_ENC_VALUE		0x120
#define VEPU_REG_CHKPT_DELTA_QP			0x124
#define     VEPU_REG_CHKPT_DELTA_QP_CHK0(x)		(((x) & 0x0f) << 0)
#define     VEPU_REG_CHKPT_DELTA_QP_CHK1(x)		(((x) & 0x0f) << 4)
#define     VEPU_REG_CHKPT_DELTA_QP_CHK2(x)		(((x) & 0x0f) << 8)
#define     VEPU_REG_CHKPT_DELTA_QP_CHK3(x)		(((x) & 0x0f) << 12)
#define     VEPU_REG_CHKPT_DELTA_QP_CHK4(x)		(((x) & 0x0f) << 16)
#define     VEPU_REG_CHKPT_DELTA_QP_CHK5(x)		(((x) & 0x0f) << 20)
#define     VEPU_REG_CHKPT_DELTA_QP_CHK6(x)		(((x) & 0x0f) << 24)
#define VEPU_REG_VP8_ENC_CTRL2			0x124
#define     VEPU_REG_VP8_ZERO_MV_PENALTY_FOR_REF2(x)	(((x) & 0xff) << 24)
#define     VEPU_REG_VP8_FILTER_SHARPNESS(x)		(((x) & 0x07) << 21)
#define     VEPU_REG_VP8_FILTER_LEVEL(x)		(((x) & 0x3f) << 15)
#define     VEPU_REG_VP8_DCT_PARTITION_CNT(x)		(((x) & 0x03) << 13)
#define     VEPU_REG_VP8_BOOL_ENC_VALUE_BITS(x)		(((x) & 0x1f) << 8)
#define     VEPU_REG_VP8_BOOL_ENC_RANGE(x)		(((x) & 0xff) << 0)
#define VEPU_REG_ENC_CTRL1			0x128
#define     VEPU_REG_MAD_THRESHOLD(x)			(((x) & 0x3f) << 24)
#define     VEPU_REG_COMPLETED_SLICES(x)		(((x) & 0xff) << 16)
#define     VEPU_REG_IN_IMG_CTRL_FMT(x)			(((x) & 0xf) << 4)
#define     VEPU_REG_IN_IMG_ROTATE_MODE(x)		(((x) & 0x3) << 2)
#define     VEPU_REG_SIZE_TABLE_PRESENT			BIT(0)
#define VEPU_REG_INTRA_INTER_MODE		0x12c
#define     VEPU_REG_INTRA16X16_MODE(x)			(((x) & 0xffff) << 16)
#define     VEPU_REG_INTER_MODE(x)			(((x) & 0xffff) << 0)
#define VEPU_REG_ENC_CTRL2			0x130
#define     VEPU_REG_PPS_INIT_QP(x)			(((x) & 0x3f) << 26)
#define     VEPU_REG_SLICE_FILTER_ALPHA(x)		(((x) & 0xf) << 22)
#define     VEPU_REG_SLICE_FILTER_BETA(x)		(((x) & 0xf) << 18)
#define     VEPU_REG_CHROMA_QP_OFFSET(x)		(((x) & 0x1f) << 13)
#define     VEPU_REG_FILTER_DISABLE			BIT(5)
#define     VEPU_REG_IDR_PIC_ID(x)			(((x) & 0xf) << 1)
#define     VEPU_REG_CONSTRAINED_INTRA_PREDICTION	BIT(0)
#define VEPU_REG_ADDR_OUTPUT_STREAM		0x134
#define VEPU_REG_ADDR_OUTPUT_CTRL		0x138
#define VEPU_REG_ADDR_NEXT_PIC			0x13c
#define VEPU_REG_ADDR_MV_OUT			0x140
#define VEPU_REG_ADDR_CABAC_TBL			0x144
#define VEPU_REG_ROI1				0x148
#define     VEPU_REG_ROI1_TOP_MB(x)			(((x) & 0xff) << 24)
#define     VEPU_REG_ROI1_BOTTOM_MB(x)			(((x) & 0xff) << 16)
#define     VEPU_REG_ROI1_LEFT_MB(x)			(((x) & 0xff) << 8)
#define     VEPU_REG_ROI1_RIGHT_MB(x)			(((x) & 0xff) << 0)
#define VEPU_REG_ROI2				0x14c
#define     VEPU_REG_ROI2_TOP_MB(x)			(((x) & 0xff) << 24)
#define     VEPU_REG_ROI2_BOTTOM_MB(x)			(((x) & 0xff) << 16)
#define     VEPU_REG_ROI2_LEFT_MB(x)			(((x) & 0xff) << 8)
#define     VEPU_REG_ROI2_RIGHT_MB(x)			(((x) & 0xff) << 0)
#define VEPU_REG_STABLE_MATRIX(i)		(0x150 + ((i) * 0x4))
#define VEPU_REG_STABLE_MOTION_SUM		0x174
#define VEPU_REG_STABILIZATION_OUTPUT		0x178
#define     VEPU_REG_STABLE_MIN_VALUE(x)		(((x) & 0xffffff) << 8)
#define     VEPU_REG_STABLE_MODE_SEL(x)			(((x) & 0x3) << 6)
#define     VEPU_REG_STABLE_HOR_GMV(x)			(((x) & 0x3f) << 0)
#define VEPU_REG_RGB2YUV_CONVERSION_COEF1	0x17c
#define     VEPU_REG_RGB2YUV_CONVERSION_COEFB(x)	(((x) & 0xffff) << 16)
#define     VEPU_REG_RGB2YUV_CONVERSION_COEFA(x)	(((x) & 0xffff) << 0)
#define VEPU_REG_RGB2YUV_CONVERSION_COEF2	0x180
#define     VEPU_REG_RGB2YUV_CONVERSION_COEFE(x)	(((x) & 0xffff) << 16)
#define     VEPU_REG_RGB2YUV_CONVERSION_COEFC(x)	(((x) & 0xffff) << 0)
#define VEPU_REG_RGB2YUV_CONVERSION_COEF3	0x184
#define     VEPU_REG_RGB2YUV_CONVERSION_COEFF(x)	(((x) & 0xffff) << 0)
#define VEPU_REG_RGB_MASK_MSB			0x188
#define     VEPU_REG_RGB_MASK_B_MSB(x)			(((x) & 0x1f) << 16)
#define     VEPU_REG_RGB_MASK_G_MSB(x)			(((x) & 0x1f) << 8)
#define     VEPU_REG_RGB_MASK_R_MSB(x)			(((x) & 0x1f) << 0)
#define VEPU_REG_MV_PENALTY			0x18c
#define     VEPU_REG_1MV_PENALTY(x)			(((x) & 0x3ff) << 21)
#define     VEPU_REG_QMV_PENALTY(x)			(((x) & 0x3ff) << 11)
#define     VEPU_REG_4MV_PENALTY(x)			(((x) & 0x3ff) << 1)
#define     VEPU_REG_SPLIT_MV_MODE_EN			BIT(0)
#define VEPU_REG_QP_VAL				0x190
#define     VEPU_REG_H264_LUMA_INIT_QP(x)		(((x) & 0x3f) << 26)
#define     VEPU_REG_H264_QP_MAX(x)			(((x) & 0x3f) << 20)
#define     VEPU_REG_H264_QP_MIN(x)			(((x) & 0x3f) << 14)
#define     VEPU_REG_H264_CHKPT_DISTANCE(x)		(((x) & 0xfff) << 0)
#define VEPU_REG_VP8_SEG0_QUANT_DC_Y1		0x190
#define     VEPU_REG_VP8_SEG0_RND_DC_Y1(x)		(((x) & 0xff) << 23)
#define     VEPU_REG_VP8_SEG0_ZBIN_DC_Y1(x)		(((x) & 0x1ff) << 14)
#define     VEPU_REG_VP8_SEG0_QUT_DC_Y1(x)		(((x) & 0x3fff) << 0)
#define VEPU_REG_MVC_RELATE			0x198
#define     VEPU_REG_ZERO_MV_FAVOR_D2(x)		(((x) & 0xf) << 20)
#define     VEPU_REG_PENALTY_4X4MV(x)			(((x) & 0x1ff) << 11)
#define     VEPU_REG_MVC_VIEW_ID(x)			(((x) & 0x7) << 8)
#define     VEPU_REG_MVC_ANCHOR_PIC_FLAG		BIT(7)
#define     VEPU_REG_MVC_PRIORITY_ID(x)			(((x) & 0x7) << 4)
#define     VEPU_REG_MVC_TEMPORAL_ID(x)			(((x) & 0x7) << 1)
#define     VEPU_REG_MVC_INTER_VIEW_FLAG		BIT(0)
#define VEPU_REG_ENCODE_START			0x19c
#define     VEPU_REG_MB_HEIGHT(x)			(((x) & 0x1ff) << 20)
#define     VEPU_REG_MB_WIDTH(x)			(((x) & 0x1ff) << 8)
#define     VEPU_REG_FRAME_TYPE_INTER			(0x0 << 6)
#define     VEPU_REG_FRAME_TYPE_INTRA			(0x1 << 6)
#define     VEPU_REG_FRAME_TYPE_MVCINTER		(0x2 << 6)
#define     VEPU_REG_ENCODE_FORMAT_JPEG			(0x2 << 4)
#define     VEPU_REG_ENCODE_FORMAT_H264			(0x3 << 4)
#define     VEPU_REG_ENCODE_ENABLE			BIT(0)
#define VEPU_REG_MB_CTRL			0x1a0
#define     VEPU_REG_MB_CNT_OUT(x)			(((x) & 0xffff) << 16)
#define     VEPU_REG_MB_CNT_SET(x)			(((x) & 0xffff) << 0)
#define VEPU_REG_DATA_ENDIAN			0x1a4
#define     VEPU_REG_INPUT_SWAP8			BIT(31)
#define     VEPU_REG_INPUT_SWAP16			BIT(30)
#define     VEPU_REG_INPUT_SWAP32			BIT(29)
#define     VEPU_REG_OUTPUT_SWAP8			BIT(28)
#define     VEPU_REG_OUTPUT_SWAP16			BIT(27)
#define     VEPU_REG_OUTPUT_SWAP32			BIT(26)
#define     VEPU_REG_TEST_IRQ				BIT(24)
#define     VEPU_REG_TEST_COUNTER(x)			(((x) & 0xf) << 20)
#define     VEPU_REG_TEST_REG				BIT(19)
#define     VEPU_REG_TEST_MEMORY			BIT(18)
#define     VEPU_REG_TEST_LEN(x)			(((x) & 0x3ffff) << 0)
#define VEPU_REG_ENC_CTRL3			0x1a8
#define     VEPU_REG_PPS_ID(x)				(((x) & 0xff) << 24)
#define     VEPU_REG_INTRA_PRED_MODE(x)			(((x) & 0xff) << 16)
#define     VEPU_REG_FRAME_NUM(x)			(((x) & 0xffff) << 0)
#define VEPU_REG_ENC_CTRL4			0x1ac
#define     VEPU_REG_MV_PENALTY_16X8_8X16(x)		(((x) & 0x3ff) << 20)
#define     VEPU_REG_MV_PENALTY_8X8(x)			(((x) & 0x3ff) << 10)
#define     VEPU_REG_MV_PENALTY_8X4_4X8(x)		(((x) & 0x3ff) << 0)
#define VEPU_REG_ADDR_VP8_PROB_CNT		0x1b0
#define VEPU_REG_INTERRUPT			0x1b4
#define     VEPU_REG_INTERRUPT_NON			BIT(28)
#define     VEPU_REG_MV_WRITE_EN			BIT(24)
#define     VEPU_REG_RECON_WRITE_DIS			BIT(20)
#define     VEPU_REG_INTERRUPT_SLICE_READY_EN		BIT(16)
#define     VEPU_REG_CLK_GATING_EN			BIT(12)
#define     VEPU_REG_INTERRUPT_TIMEOUT_EN		BIT(10)
#define     VEPU_REG_INTERRUPT_RESET			BIT(9)
#define     VEPU_REG_INTERRUPT_DIS_BIT			BIT(8)
#define     VEPU_REG_INTERRUPT_TIMEOUT			BIT(6)
#define     VEPU_REG_INTERRUPT_BUFFER_FULL		BIT(5)
#define     VEPU_REG_INTERRUPT_BUS_ERROR		BIT(4)
#define     VEPU_REG_INTERRUPT_FUSE			BIT(3)
#define     VEPU_REG_INTERRUPT_SLICE_READY		BIT(2)
#define     VEPU_REG_INTERRUPT_FRAME_READY		BIT(1)
#define     VEPU_REG_INTERRUPT_BIT			BIT(0)
#define VEPU_REG_DMV_PENALTY_TBL(i)		(0x1E0 + ((i) * 0x4))
#define     VEPU_REG_DMV_PENALTY_TABLE_BIT(x, i)        ((x) << (i) * 8)
#define VEPU_REG_DMV_Q_PIXEL_PENALTY_TBL(i)	(0x260 + ((i) * 0x4))
#define     VEPU_REG_DMV_Q_PIXEL_PENALTY_TABLE_BIT(x, i)	((x) << (i) * 8)


#endif /* ROCKCHIP_VPU2_REGS_H_ */
