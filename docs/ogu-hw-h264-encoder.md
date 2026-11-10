# Аппаратный кодер H.264 на GO Ultra (S922X / G12B)

Состояние на 2026-11-10: **работает**. Трансляция bare_app (`STREAM`) кодирует
HCODEC-ом через драйвер `meson-venc` (V4L2 mem2mem): 854×480 за ~3,7 мс на кадр
вместо ~0,8 ядра A73 у OpenH264; OpenH264 остался запасным. Драйвер, его
устройство и проверка — `board/ogu/linux/meson-venc/README.md`.

## Что было и что сделано

- В блоке DOS у G12B есть HCODEC: ядро AMRISC с микрокодом кодера H.264 (до
  1080p) рядом с аппаратными ME/IE, DCT и VLC; регистры — слова DOS
  0x1000–0x1fff (`0xff624000`), прерывание — mailbox 2 (SPI 45). Есть ещё
  Wave420L (HEVC, `0xff610000`, SPI 187) — не трогали: для RTSP/VLC нужен H.264.
- Вендорское ядро 4.9: `amvenc_avc` (media_modules,
  `frame_sink/encoder/h264/encoder.c`) со своим ioctl и библиотекой
  (`encoder_libs_aml`, `gx_enc_fast`: таблицы QP, CBR, команды).
- Mainline 7.2 не имел ни часов HCODEC, ни питания, ни драйвера. Сделано:
  1. Патч ядра 0019: часы `hcodec_sel/div/gate` (`HHI_VDEC_CLK_CNTL` [27:25],
     [22:16], [24]) в `g12a.c` для G12A/G12B/SM1, `CLKID_HCODEC*` 279–281.
  2. Патч 0020: узел `video-encoder@ff624000` (`amlogic,g12a-hcodec`) в
     `meson-g12-common.dtsi`, выключен; включён в dts GO Ultra.
  3. Питание — в драйвере, как у `vdec_1.c`: `AO_RTI_GEN_PWR_SLEEP0[1:0]`,
     `ISO0[5:4]`, `DOS_MEM_PD_HCODEC`, гейты `DOS_GCLK_EN0[26:12]`. Включается с
     первым кадром, выключается через секунду простоя.
  4. Драйвер `meson-venc` — внешний модуль SDK (`LINUX_EXT_MODULES`): XR24 и NV12
     → H.264 Main (CABAC), свой покадровый RC, кадрирование в SPS для размеров,
     не кратных 16.
  5. Микрокод `ga_h264_enc_cabac` (24 КБ, код — первые ~11 КБ, грузится 16 КБ
     IMEM) — Buildroot-пакет `meson-venc-firmware`: из `h264_enc.bin`
     media_modules Amlogic (копия CoreELEC, закреплённый коммит, sha256), в
     `/lib/firmware/meson/venc/`. Тот же байт в байт, что в `video_ucode.bin`.
  6. bare_app: `stream/h264_v4l2.c` — первый V4L2 mem2mem-кодер XBGR32 → H.264 в
     системе, иначе OpenH264 (`BARE_APP_STREAM_SW=1` — программный всегда).

## Что выяснилось по ходу

- Этот микрокод заканчивает и P-кадр статусом `ENCODER_IDR_DONE` (9), не 10;
  вендорская библиотека так его и ждёт.
- RGB: MFDIN формат 12 читает кадр линейно по адресу и сам переводит в YUV;
  перестановка байтов `REG9_ENDN` вендора — для памяти R,G,B,A, для XRGB8888
  (B,G,R,X) нужна тождественная. Уровни — BT.601 studio range.
- Регистры MFDIN на GXBB+ сдвинуты на −8 слов от имён в `hcodec_regs.h`.
- SPS микрокод пишет целыми макроблоками без `frame_cropping`.
- Канвы кодера — без перестановки байтов (endian 0), в отличие от декодера.

## Что не сделано

- Не проверена одновременная работа с декодером `meson-vdec`: его старт пишет
  `DOS_GCLK_EN0 = 0x3ff` и снимает гейты HCODEC.
- Вход — копия кадра в MMAP-буфер V4L2 (~1,6 МБ на кадр); без копии можно через
  DMABUF кадра DRM.
- Драйвер вне дерева ядра; для апстрима — staging-патч и биндинг DT.
- На OGA (RK3326) аппаратного кодера в mainline нет — там остаётся OpenH264.
