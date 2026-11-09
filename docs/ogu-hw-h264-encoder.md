# Аппаратный кодер H.264 на GO Ultra (S922X / G12B): оценка переноса

Состояние на 2026-11-09: **не перенесён**, трансляция (`bare_app`, `STREAM`) кодирует
программно (OpenH264, ~0,8 ядра A73 на 854×480 при 30 кадр/с). Здесь — что есть, чего
нет и план работ.

## Что есть в железе и в ядрах

- В блоке DOS у G12B есть HCODEC: отдельный микроконтроллер AMRISC с микрокодом
  кодера H.264 (до 1080p). Регистры HCODEC лежат в той же области DOS
  (`0xff620000`), что и у декодера.
- Вендорское ядро Amlogic/Hardkernel 4.9: драйвер `amvenc_avc`
  (`media_modules`, `frame_sink/encoder/h264/encoder.c`, ~4000 строк) со своим
  ioctl-интерфейсом `/dev/amvenc_avc` и библиотекой `libvpcodec` в userspace;
  опирается на вендорские подсистемы `codec_mm` (CMA), `canvas`, `vdec`-питание,
  загрузку микрокода из `video_ucode.bin`.
- Mainline 7.2: только декодер `meson-vdec` (staging, V4L2 M2M stateful); драйвер
  `meson-canvas` есть; часы `dos` есть, а отдельных часов HCODEC (`hcodec_sel/div/gate`)
  в `g12a.c` нет; домена питания HCODEC для G12A в `meson-ee-pwrc` нет. Amlogic сейчас
  выкладывает stateless-декодер для S4, G12B у них в списке «потом», кодера в планах нет.

## План переноса (оценка — недели, не ночь)

1. Часы: `hcodec` mux/div/gate в `drivers/clk/meson/g12a.c` (по образцу `vdec_1`),
   номер в dt-bindings.
2. Питание: биты HCODEC в `AO_RTI_GEN_PWR_SLEEP0/ISO0` и `DOS_MEM_PD_HCODEC` —
   либо домен в `meson-ee-pwrc`, либо как это делает `vdec_1.c` сам.
3. Драйвер V4L2 M2M stateful-кодера `meson-venc` (staging/media/meson): очереди
   NV12/I420 → H.264, буферы через `dma_alloc_coherent`/CMA вместо `codec_mm`,
   канвы через `meson_canvas_*`, загрузка микрокода через `request_firmware`
   (`meson/venc/g12b_h264_enc.bin` — блоб нужно извлечь из `video_ucode.bin`;
   его лицензия — как у остального микрокода Amlogic, в linux-firmware его нет).
4. Перенос программирования регистров из `encoder.c` (ME/MC, rate control, CABAC
   выключен, refs) — основной объём, без документации, сверяясь с вендорским кодом.
5. Узел в DT (`video-encoder@...` с часами, прерыванием HCODEC, канвой).
6. В bare_app: бэкенд кодера `stream/h264_v4l2.c` рядом с `h264.c` (тот же интерфейс
   `h264_new/encode`), выбор при старте: V4L2-устройство есть — оно, иначе OpenH264.

Риски: микрокод и регистры без документации; вендорский драйвер ждёт
выравниваний и форматов памяти canvas; отладка только на железе (ядро через SD,
см. ogu-port). Выигрыш: ~0,8 ядра CPU и меньше задержка — для трансляции в
854×480 программный кодер уже держит 30 кадр/с.
