# meson-venc: аппаратный кодер H.264 Amlogic G12A/G12B (HCODEC)

Драйвер V4L2 mem2mem (stateful-кодер) для HCODEC — кодера H.264 в блоке DOS
S922X/S905X2. Собирается как внешний модуль ядра (`LINUX_EXT_MODULES` в
`configs/ogu_defconfig`), ставится в `/lib/modules/<версия>/updates/` и
грузится сам по узлу DT (`amlogic,g12a-hcodec`). Устройство — `/dev/videoN`
с именем драйвера `meson-venc`.

| Очередь | Форматы |
|---|---|
| OUTPUT (кадры) | `XR24` (V4L2 XBGR32 = DRM XRGB8888, память B,G,R,X) — MFDIN сам переводит RGB → YUV BT.601 studio range; `NV12` (одна плоскость, Y затем UV, шаг 32) |
| CAPTURE | `H264`: Annex B, Main profile (CABAC), один срез на кадр; у каждого IDR впереди SPS и PPS |

Размеры 64×64…1920×1088, чётные. Ширина/высота не кратные 16 кодируются целыми
макроблоками, а драйвер дописывает в SPS `frame_cropping` (854×480 → в потоке
854×480). Управление: `V4L2_CID_MPEG_VIDEO_BITRATE`, `GOP_SIZE`,
`FRAME_RC_ENABLE`, `H264_I_FRAME_QP`/`P_FRAME_QP` (без RC), `H264_MIN_QP`/`MAX_QP`,
`FORCE_KEY_FRAME`; частота кадров — `VIDIOC_S_PARM`. RC — свой, по кадрам: QP
P-кадров по их размеру против `битрейт/fps`, QP IDR отдельно (цель — 4 таких).

Параметры модуля: `debug=1` (каждый кадр: тип, QP, байты, время), `idle_ms`
(1000: питание HCODEC выключается через столько без кадров, включается с
первым кадром, ~10 мс), `rgb_endian` (порядок байтов RGB для MFDIN).

## Что нужно ещё

- Ядро с патчами `board/ogu/linux/patches`: 0019 (часы `hcodec` в
  `HHI_VDEC_CLK_CNTL`), 0020 (узел `video-encoder@ff624000` в DT, SPI 45).
- Микрокод `/lib/firmware/meson/venc/g12a_h264_enc_cabac.bin` — Buildroot-пакет
  `meson-venc-firmware` (вырезает `ga_h264_enc_cabac` из `h264_enc.bin`
  media_modules Amlogic, копия CoreELEC, закреплённый коммит, sha256 обоих).

## Проверка

`test/venc-test.c` — синтетические кадры (полосы, движущийся квадрат; `-p 1` —
с шумом) → `.h264`:

```sh
output/ogu/buildroot/host/bin/aarch64-buildroot-linux-gnu-gcc -O2 -o venc-test \
    board/ogu/linux/meson-venc/test/venc-test.c
# на плате (bare_app держит устройство, пока трансляция включена):
venc-test -f XR24 -s 854x480 -n 300 -b 3000000 -p 1 /tmp/out.h264
# на ПК:
ffmpeg -err_detect explode -i out.h264 -f null -
```

Проверено на GO Ultra (2026-11-10): 854×480 ~3,7 мс на кадр, 1920×1080 ~20 мс;
битрейт держится (3 Мбит/с → 2986 кбит/с); потоки декодируются ffmpeg без
ошибок (`-err_detect explode`), цвета и уровни совпадают с эталоном BT.601.

## Как устроено

HCODEC — ядро AMRISC с микрокодом Amlogic рядом с аппаратными ME/IE, DCT/квантом
и VLC. Микрокод пишет SPS (`ENCODER_SEQUENCE`), PPS (`ENCODER_PICTURE`) и срез
(`ENCODER_IDR`/`ENCODER_NON_IDR`); перед каждой командой драйвер, как
вендорский `amvenc_avc`, останавливает и сбрасывает HCODEC и заново
программирует его (буферы, канвы, таблицы QP, веса ME/IE, CBR-таблица). Конец
кадра — прерывание mailbox 2; этот микрокод и P-кадр заканчивает статусом
`ENCODER_IDR_DONE`. Опорный кадр — два буфера-реконструкции, меняются местами
после каждого кадра. Программирование регистров перенесено из драйвера Amlogic
(media_modules, `frame_sink/encoder/h264/encoder.c`, GPL-2.0+), раскладка
CBR-таблицы — из их библиотеки (`encoder_libs_aml`, `gx_enc_fast`).

Питание: `AO_RTI_GEN_PWR_SLEEP0[1:0]`/`ISO0[5:4]` через `ao-sysctrl` (как vdec в
mainline), `DOS_MEM_PD_HCODEC`, гейты `DOS_GCLK_EN0[26:12]`. Регистры DOS
отображаются без захвата области: ею владеет `meson-vdec`. Известное: старт
декодера (`vdec_1`) пишет `DOS_GCLK_EN0 = 0x3ff` и снимает гейты HCODEC —
одновременная работа декодера и кодера не проверялась.
