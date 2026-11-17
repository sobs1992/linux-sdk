#!/usr/bin/env python3
"""
mkdiagrams.py: the pictures of docs/wiki (SVG), drawn from the code below so
that they can be changed with the text. Run it from anywhere:

  python3 docs/wiki/img/mkdiagrams.py        # writes *.svg next to itself

No libraries: boxes, arrows and text as SVG elements. Fonts come from the
viewer (sans-serif); the sizes are chosen with room to spare.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))

FONT = "font-family='Segoe UI, Noto Sans, DejaVu Sans, Arial, sans-serif'"
# fills and strokes of the boxes, by role
C = {
    "sdk": ("#e8f1fb", "#4a79a8"),      # the SDK, its files
    "build": ("#fdf3e0", "#c48a2a"),    # build steps, output
    "board": ("#e9f6ea", "#4f9a56"),    # the board, its partitions
    "app": ("#efe9f8", "#7a5bb0"),      # bare_app
    "game": ("#fbe9e7", "#c0564a"),     # games, their processes
    "fs": ("#f3f3f3", "#7a7a7a"),       # file systems, directories
    "note": ("#fffbe6", "#b5a642"),     # remarks
    "white": ("#ffffff", "#555555"),
}
LINE_H = 17


class Svg:
    def __init__(self, w, h, title):
        self.w, self.h, self.title = w, h, title
        self.parts = []

    def box(self, x, y, w, h, lines, role="sdk", size=13, bold_first=False,
            anchor="middle", dashed=False, rx=6):
        fill, stroke = C[role]
        dash = " stroke-dasharray='6 4'" if dashed else ""
        self.parts.append(
            f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='{rx}' "
            f"fill='{fill}' stroke='{stroke}' stroke-width='1.5'{dash}/>")
        if isinstance(lines, str):
            lines = [lines]
        n = len(lines)
        ty = y + h / 2 - (n - 1) * LINE_H / 2 + size * 0.35
        tx = x + w / 2 if anchor == "middle" else x + 10
        for i, line in enumerate(lines):
            weight = " font-weight='bold'" if (bold_first and i == 0) else ""
            mono = ""
            if line.startswith("`") and line.endswith("`"):
                line = line[1:-1]
                mono = " font-family='DejaVu Sans Mono, Consolas, monospace'"
            self.parts.append(
                f"<text x='{tx}' y='{ty + i * LINE_H:.1f}' font-size='{size}' "
                f"text-anchor='{anchor if anchor == 'middle' else 'start'}'"
                f"{weight}{mono} fill='#222'>{esc(line)}</text>")
        return (x, y, w, h)

    def text(self, x, y, s, size=13, anchor="start", color="#333", bold=False,
             italic=False, mono=False):
        weight = " font-weight='bold'" if bold else ""
        style = " font-style='italic'" if italic else ""
        fam = " font-family='DejaVu Sans Mono, Consolas, monospace'" if mono else ""
        self.parts.append(
            f"<text x='{x}' y='{y}' font-size='{size}' text-anchor='{anchor}'"
            f"{weight}{style}{fam} fill='{color}'>{esc(s)}</text>")

    def arrow(self, x1, y1, x2, y2, label=None, dashed=False, color="#444",
              both=False, label_dy=-6, width=1.6):
        dash = " stroke-dasharray='6 4'" if dashed else ""
        start = " marker-start='url(#dot)'" if both else ""
        self.parts.append(
            f"<line x1='{x1}' y1='{y1}' x2='{x2}' y2='{y2}' stroke='{color}' "
            f"stroke-width='{width}' marker-end='url(#arr)'{start}{dash}/>")
        if label:
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2 + label_dy
            self.text(mx, my, label, size=12, anchor="middle", color="#333")

    def path_arrow(self, points, label=None, dashed=False, color="#444",
                   label_at=None, label_dy=-6, width=1.6):
        """An arrow with corners: points [(x, y), ...], drawn as lines (every
        renderer draws those; some skip <path>), the head on the last"""
        dash = " stroke-dasharray='6 4'" if dashed else ""
        for i in range(len(points) - 1):
            (x1, y1), (x2, y2) = points[i], points[i + 1]
            head = " marker-end='url(#arr)'" if i == len(points) - 2 else ""
            self.parts.append(
                f"<line x1='{x1}' y1='{y1}' x2='{x2}' y2='{y2}' stroke='{color}' "
                f"stroke-width='{width}' stroke-linecap='square'{head}{dash}/>")
        if label:
            x, y = label_at if label_at else points[len(points) // 2]
            self.text(x, y + label_dy, label, size=12, anchor="middle")

    def group(self, x, y, w, h, title, role="fs", dashed=True):
        fill, stroke = C[role]
        dash = " stroke-dasharray='8 5'" if dashed else ""
        self.parts.append(
            f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='10' fill='{fill}' "
            f"fill-opacity='0.45' stroke='{stroke}' stroke-width='1.2'{dash}/>")
        self.text(x + 12, y + 18, title, size=13, bold=True, color="#333")

    def save(self, name):
        head = (f"<svg xmlns='http://www.w3.org/2000/svg' width='{self.w}' height='{self.h}' "
                f"viewBox='0 0 {self.w} {self.h}' {FONT}>\n"
                f"<title>{esc(self.title)}</title>\n"
                "<defs>\n"
                "<marker id='arr' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='8' "
                "markerHeight='8' orient='auto-start-reverse'>"
                "<path d='M 0 0 L 10 5 L 0 10 z' fill='#444'/></marker>\n"
                "<marker id='dot' viewBox='0 0 10 10' refX='5' refY='5' markerWidth='6' "
                "markerHeight='6'><circle cx='5' cy='5' r='4' fill='#444'/></marker>\n"
                "</defs>\n"
                f"<rect width='{self.w}' height='{self.h}' fill='white'/>\n")
        with open(os.path.join(HERE, name), "w", encoding="utf-8") as f:
            f.write(head + "\n".join(self.parts) + "\n</svg>\n")
        print(name)


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
def overview():
    s = Svg(980, 575, "Устройство проекта: от репозитория до приставки")
    # the PC
    s.group(20, 20, 600, 540, "Компьютер разработчика: репозиторий OdroidLinux", "sdk")
    s.box(40, 55, 170, 70, ["configs/", "<fw>_defconfig", "что и как собрать"], "sdk", bold_first=True)
    s.box(230, 55, 170, 70, ["board/<плата>/", "фрагменты конфигов,", "патчи, overlay, блобы"], "sdk", bold_first=True)
    s.box(420, 55, 180, 70, ["board/common/buildroot/", "BR2_EXTERNAL «SDK»:", "пакеты игр и движков"], "sdk", bold_first=True)

    s.box(40, 160, 170, 90, ["src/ (сабмодули)", "tf-a · u-boot", "linux · buildroot"], "sdk", bold_first=True)
    s.box(230, 160, 170, 90, ["apps/bare_app", "(сабмодуль)", "лаунчер + порты:", "doom, wine, bench"], "app", bold_first=True)
    s.box(420, 160, 180, 90, ["games/", "games.manifest,", "wine.ini и prepare.sh", "каждой игры"], "game", bold_first=True)

    s.box(40, 290, 560, 60, ["Makefile — оркестратор", "make uboot · make linux · make rootfs · make image · make flash"], "build", bold_first=True)
    for x in (125, 315, 510):
        s.arrow(x, 250, x, 290)
    for x in (125, 315, 510):
        s.arrow(x, 125, x, 160, dashed=True, color="#888")

    s.box(40, 385, 260, 70, ["output/<fw>/images/", "<fw>.img, <fw>-emmc.img,", "u-boot, Image, rootfs.tar"], "build", bold_first=True)
    s.arrow(170, 350, 170, 385)
    s.box(40, 490, 260, 50, ["scripts/games-image.py", "игры по манифесту → карта"], "game", bold_first=True)
    s.box(340, 490, 260, 50, ["lab/ → /media/D/OdroidLab", "игры, образы, бэкапы (вне git)"], "fs", bold_first=True)
    s.path_arrow([(340, 515), (300, 515)])

    # the board
    s.group(660, 20, 300, 540, "Приставка (GO Ultra / GO Advance)", "board")
    s.box(680, 60, 260, 60, ["eMMC или SD: система", "FIP/U-Boot · BOOT · rootfs · /data"], "board", bold_first=True)
    s.box(680, 140, 260, 60, ["SD-карта игр (exFAT GAMES)", "/games/<игра>/ — файлы, wine.ini,", "game.ini, cover.png"], "board", bold_first=True)
    s.box(680, 225, 260, 70, ["bare_app (автостарт)", "главный экран с плитками игр,", "настройки, Wi-Fi, стрим, USB-диск"], "app", bold_first=True)
    s.box(680, 320, 120, 100, ["Процесс игры", "VCMI, Xash3D,", "bare_app_doom,", "SDL2-игра,", "bare_app_wine"], "game", bold_first=True, size=12)
    s.box(820, 320, 120, 100, ["Windows-игра", "Wine WoW64", "+ Box64", "winebare.drv"], "game", bold_first=True, size=12)
    s.arrow(740, 295, 740, 320, "кадры ↔ кнопки", label_dy=20)
    s.arrow(800, 370, 820, 370)
    s.box(680, 445, 260, 75, ["/data (ext4, переживает прошивку)", "сохранения, настройки, префикс Wine,", "controls.<игра>, recent, hibernate.swap"], "fs", bold_first=True, size=12)

    s.path_arrow([(300, 420), (640, 420), (640, 90), (680, 90)], "make flash / flash-emmc", label_at=(470, 420))
    s.path_arrow([(170, 540), (170, 552), (650, 552), (650, 170), (680, 170)], "карта в картридере или «USB-диск»", label_at=(420, 552), label_dy=-5)
    s.save("overview.svg")


def build_flow():
    s = Svg(980, 485, "Поток сборки прошивки")
    s.box(20, 30, 180, 50, ["make <fw>_defconfig", "→ output/.fw"], "sdk", bold_first=True)
    s.box(20, 110, 180, 60, ["configs/<fw>_defconfig", "включается в Makefile", "(FW=… разово)"], "sdk", bold_first=True, size=12)
    s.arrow(110, 80, 110, 110)

    y = 210
    cols = [
        ("make uboot", ["копия src/u-boot", "+ UBOOT_PATCHES", "фрагмент .config", "(TF-A BL31 / FIP / RK legacy)"], "u-boot*.bin, FIP"),
        ("make linux", ["копия src/linux (git archive)", "+ LINUX_PATCHES", "фрагмент .config, dtbs", "LINUX_EXT_MODULES"], "Image, dtb, модули"),
        ("make rootfs", ["Buildroot + BR2_EXTERNAL", "defconfig платы + APPS", "apps-config.sh: опции,", "purge удалённых пакетов"], "rootfs.tar"),
        ("make bootfw", ["блобы RPi / Amlogic", "скачать, sha256"], "start*.elf, bl2…"),
    ]
    x = 20
    for title, lines, out in cols:
        s.box(x, y, 225, 95, [title] + lines, "build", bold_first=True, size=12)
        s.box(x + 20, y + 130, 185, 40, out, "build")
        s.arrow(x + 112, y + 95, x + 112, y + 130)
        s.path_arrow([(200, 140), (x + 112, 140), (x + 112, y)], dashed=True, color="#888")
        x += 240
    s.box(250, 400, 480, 50, ["make image → scripts/mkimage.sh (без root: fakeroot, mke2fs -d, mtools)",
                              "MBR + raw-блобы + p1 BOOT (FAT32) + p2 rootfs (ext4) → images/<fw>.img"], "build", size=12)
    for cx in (132, 372, 612, 852):
        s.path_arrow([(cx, 380), (cx, 390), (490, 390), (490, 400)])
    s.text(490, 472, "запись: make flash DEV=/dev/sdX  ·  make flash-emmc (Vol+ при включении GO Ultra)", size=12, mono=True, color="#333", anchor="middle")
    s.save("build-flow.svg")


def sd_layout():
    s = Svg(980, 420, "Разметка дисков")
    s.text(20, 30, "Один диск (GO Advance, SD): образ несёт только p1 и p2, p3 и p4 создаёт первая загрузка (S05data)", size=13, bold=True)
    y = 50
    segs = [
        (20, 60, "MBR", "fs"), (80, 110, "raw-блобы\n(U-Boot) <16M", "build"),
        (190, 130, "p1 BOOT FAT32\nImage, dtb,\nextlinux.conf", "board"),
        (320, 260, "p2 rootfs ext4\nBuildroot + bare_app + движки\n(rootfs.tar + свободно 256M)", "board"),
        (580, 130, "p3 data ext4\n/data: сохранения,\nнастройки", "fs"),
        (710, 250, "p4 GAMES FAT32 (до конца карты)\n/games: файлы игр с ПК\n(только чтение)", "game"),
    ]
    for x, w, label, role in segs:
        s.box(x, y, w, 80, label.split("\n"), role, size=12, rx=2)
    s.text(580, 150, "IMAGE_DATA_START_MB", size=11, mono=True)
    s.text(770, 150, "+ IMAGE_DATA_SIZE_MB", size=11, mono=True)
    s.text(190, 150, "16M", size=11, mono=True)

    s.text(20, 205, "GO Ultra: система на eMMC, все игры на отдельной SD-карте с одним разделом exFAT GAMES", size=13, bold=True)
    y = 225
    segs = [
        (20, 60, "MBR +\nкод FIP", "fs"), (80, 110, "FIP @ сектор 1\nBL2/BL30/BL31\n+ U-Boot", "build"),
        (190, 130, "p1 BOOT FAT32\nboot.ini, u-boot.bin,\nImage, dtb, extlinux", "board"),
        (320, 200, "p2 rootfs ext4\n(до 2 ГиБ: Wine)", "board"),
        (520, 240, "p3 data ext4 — до конца eMMC\n/data: сохранения, префикс Wine,\nhibernate.swap 1,5 ГиБ", "fs"),
    ]
    for x, w, label, role in segs:
        s.box(x, y, w, 80, label.split("\n"), role, size=12, rx=2)
    s.text(20, 330, "eMMC", size=12, bold=True)
    s.box(790, 225, 170, 80, ["SD-карта: p1 exFAT GAMES", "/games/<игра>/…", "нет extlinux → не загрузочная"], "game", size=12, rx=2)
    s.text(790, 330, "SD (карта игр)", size=12, bold=True)
    s.text(20, 365, "root=PARTUUID=<disk id>-02; /boot по UUID раздела BOOT; у eMMC свой disk id (4f475545), у SD — 4f475531,", size=12)
    s.text(20, 385, "иначе при вставленной загрузочной карте оба диска подошли бы под root=. /games монтируется ro: питание можно просто выключить.", size=12)
    s.save("sd-layout.svg")


def boot_chains():
    s = Svg(980, 330, "Цепочки загрузки плат")
    rows = [
        ("GO Advance (RK3326)\nSPI пустой", ["BootROM", "TPL+SPL (idbloader @64)", "BL31 TF-A", "U-Boot (u-boot.itb)", "extlinux → Linux"]),
        ("GO Advance\nSPI с заводским", ["BootROM", "SPI miniloader (1.5M baud)", "trust.img (BL31 rkbin)", "uboot.img (mainline)", "extlinux → Linux"]),
        ("GO Ultra (S922X)", ["BootROM", "FIP @1: BL2 → BL30/BL31", "U-Boot (BL33) с eMMC", "SD с extlinux? иначе eMMC", "Linux"]),
        ("Raspberry Pi", ["GPU firmware (EEPROM)", "config.txt", "kernel=u-boot.bin", "U-Boot", "extlinux → Linux"]),
        ("BeagleBone Black", ["ROM AM335x", "MLO (SPL) с FAT", "u-boot.img", "U-Boot", "extlinux → Linux"]),
    ]
    y = 25
    for name, steps in rows:
        s.box(20, y, 150, 48, name.split("\n"), "board", size=12, bold_first=True)
        x = 190
        for i, st in enumerate(steps):
            role = "build" if i < len(steps) - 1 else "board"
            s.box(x, y, 145, 48, st.split(" (")[0].split("\n") if "(" not in st else [st.split(" (")[0], "(" + st.split(" (")[1]], role, size=11)
            if i < len(steps) - 1:
                s.arrow(x + 145, y + 24, x + 157, y + 24, width=1.2)
            x += 157
        y += 58
    s.text(20, 320, "Везде одинаково в конце: U-Boot выбирает dtb по модели платы и читает extlinux/extlinux.conf с раздела BOOT.", size=12)
    s.save("boot-chains.svg")


def bare_app_layers():
    s = Svg(980, 470, "Слои bare_app")
    layers = [
        ("gui/view/lvgl  (и headless)", "экраны и виджеты тулкита: home, game, controls, settings, wifi, usb_disk, layers, input_test, motion", "единственное место с LVGL", "app"),
        ("gui/view/core", "поток view: снимки контекста, подписки, геймпад → клавиши UI, захват ввода играми, видеослой, трансляция", "", "app"),
        ("gui/ctx · action · notify", "граница control ↔ view: контекст (снимки), очередь действий, очередь уведомлений", "", "app"),
        ("gui/control", "модули по областям: питание, экран, звук, Wi-Fi, навигация, система, sysmon", "", "app"),
        ("services · core · stream", "шина событий, главный цикл, логический геймпад, математика стика, RTSP/H.264", "", "app"),
        ("hal · drivers · platforms", "интерфейсы → реализации (DRM, fbdev, evdev, HID, ALSA, wpa, RK818…) → таблицы плат oga.c / ogu.c / pc.c", "", "app"),
    ]
    y = 25
    for title, body, note, role in layers:
        s.box(20, y, 700, 56, [title, body], role, bold_first=True, size=12)
        if note:
            s.text(735, y + 32, note, size=11, italic=True, color="#555")
        y += 64
    s.group(740, 110, 220, 290, "Игры (games/)", "game")
    s.box(755, 140, 190, 60, ["struct game_def", "реестр games.c:", "homm3, halflife, doom,", "native (game.ini), wine"], "game", size=11, bold_first=True)
    s.box(755, 215, 190, 50, ["game_proc.c", "fork/exec, SIGSTOP/SIGCONT,", "сокет + memfd (fd 3, 4)"], "game", size=11, bold_first=True)
    s.box(755, 280, 190, 50, ["ini.c", "wine.ini / game.ini,", "общий диалект"], "game", size=11, bold_first=True)
    s.box(755, 345, 190, 45, ["Процессы игр", "вне адресного пространства"], "white", size=11, bold_first=True, dashed=True)
    s.arrow(720, 117, 740, 117, width=1.2)
    s.text(20, 445, "Границу держит сборка: заголовки LVGL подключены только к цели bare_app_view_lvgl; подключение lvgl.h в другом месте ломает сборку.", size=12)
    s.save("bare_app-layers.svg")


def game_ipc():
    s = Svg(980, 520, "Игра — отдельный процесс: протокол game_ipc.h")
    s.group(20, 20, 380, 480, "bare_app (поток view)", "app")
    s.box(40, 55, 340, 60, ["game_proc_start()", "fork + exec программы игры; наследуются", "fd 3 — сокет SOCK_SEQPACKET, fd 4 — memfd"], "app", size=12, bold_first=True)
    s.box(40, 135, 340, 70, ["Видеослой (DRM-плоскость)", "берёт свежий кадр из shm, кладёт на экран;", "кадры 60/с, GAME_FRAME_SAME — «ничего не изменилось»"], "app", size=12, bold_first=True)
    s.box(40, 225, 340, 70, ["Геймпад → игра", "кнопки и оси после переназначений экрана", "«Управление»; клавиатура и мышь USB — как есть"], "app", size=12, bold_first=True)
    s.box(40, 315, 340, 80, ["bare_app оставляет себе", "F5 — свернуть (SIGSTOP), F5 удерж. — монитор,", "F6 удерж. 2 с — закрыть (SIGTERM → SIGKILL),", "громкость, кнопка питания"], "note", size=12, bold_first=True)
    s.box(40, 415, 340, 70, ["Экран игры", "«Загрузка…» до первого кадра, подсказка hint,", "«Не найдено: …» по missing(), код выхода"], "app", size=12, bold_first=True)

    # the channel
    s.box(430, 140, 130, 110, ["memfd", "struct game_shm", "3 кадра XRGB8888", "тройной буфер", "без блокировок"], "fs", size=12, bold_first=True)
    s.box(430, 270, 130, 90, ["сокет", "GAME_MSG_FRAME →", "← BUTTON, AXIS,", "← KEY, MOUSE_*"], "fs", size=12, bold_first=True)
    s.arrow(400, 170, 430, 170, width=1.2)
    s.arrow(400, 300, 430, 300, both=True, width=1.2)

    s.group(590, 20, 370, 480, "Процесс игры (своя лицензия, свой цикл)", "game")
    s.box(610, 55, 330, 50, ["game_ipc_client.h (MIT, только заголовок)", "game_link_open → recv → draw → publish"], "game", size=12, bold_first=True)
    s.box(610, 120, 155, 70, ["bare_app_doom", "doomgeneric, GPLv2", "рисует 320×200"], "game", size=11, bold_first=True)
    s.box(785, 120, 155, 70, ["VCMI (Герои III)", "патч 0001 клиента", "окно 854×600 → fit"], "game", size=11, bold_first=True)
    s.box(610, 205, 155, 70, ["Xash3D FWGS", "платформа bare_app", "GLES офскрин / soft"], "game", size=11, bold_first=True)
    s.box(785, 205, 155, 70, ["SDL2-игра как есть", "драйверы bareapp", "video + joystick"], "game", size=11, bold_first=True)
    s.box(610, 290, 330, 90, ["bare_app_wine (ports/wine)", "wine.ini → Wine WoW64 + Box64 → игра .exe;", "winebare.drv каждого процесса Wine отдаёт пиксели окон,", "мост собирает экран Windows, рисует курсор, масштабирует"], "game", size=11, bold_first=True)
    s.box(610, 395, 330, 90, ["Что получает игра", "размер слоя (854×480 / 480×320), ALSA PCM платы,", "язык (en/ru), каталог данных /data/<игра>,", "/games только для чтения"], "note", size=11, bold_first=True)
    s.arrow(560, 195, 590, 195, width=1.2)
    s.arrow(560, 315, 590, 315, both=True, width=1.2)
    s.save("game-ipc.svg")


def game_paths():
    s = Svg(980, 560, "Какой путь добавления игры выбрать")
    s.box(340, 20, 300, 50, ["Новая игра", "на чём она написана и для какой ОС?"], "note", bold_first=True)
    s.box(40, 120, 270, 60, ["Windows-игра (x86, 32-бит)", "D3D8/D3D9/DirectDraw, GDI"], "game", bold_first=True)
    s.box(355, 120, 270, 60, ["Linux-порт на SDL2", "есть в Buildroot или собирается"], "game", bold_first=True)
    s.box(670, 120, 270, 60, ["Свой движок без SDL", "или вывод нужен особый (лупа)"], "game", bold_first=True)
    s.path_arrow([(490, 70), (490, 95), (175, 95), (175, 120)])
    s.arrow(490, 70, 490, 120)
    s.path_arrow([(490, 70), (490, 95), (805, 95), (805, 120)])

    s.box(40, 215, 270, 150, ["Путь A: wine.ini — код не меняется",
                              "каталог /games/<id>/ с игрой",
                              "games/<id>/overlay/wine.ini",
                              "games/<id>/prepare.sh (если нужно)",
                              "секция в games/games.manifest",
                              "обложка cover = …",
                              "строка в games/README.md"], "sdk", size=12, bold_first=True)
    s.box(355, 215, 270, 150, ["Путь B: game.ini — код не меняется",
                               "пакет Buildroot движка",
                               "<pkg>.ini ставит сам пакет →",
                               "/usr/share/bare_app/games/",
                               "BR2_PACKAGE_BARE_APP_<GAME> (select)",
                               "bare-app.<GAME>=y в APPS_CONFIG",
                               "секция в манифесте с файлами игры"], "sdk", size=12, bold_first=True)
    s.box(670, 215, 270, 150, ["Путь C: struct game_def",
                               "программа с game_ipc_client.h",
                               "src/games/<игра>.c + строка в games.c",
                               "GAME_<ИГРА> в Kconfig, add_if() в CMake",
                               "строки i18n (en, ru)",
                               "пакет SDK + CONFIG_GAME_… в bare-app.mk",
                               "опция Config.in + APPS_CONFIG"], "sdk", size=12, bold_first=True)
    for x in (175, 490, 805):
        s.arrow(x, 180, x, 215)

    s.box(40, 400, 270, 60, ["Пересборка: нет", "games-image.py --card … --games <id>"], "build", size=12, bold_first=True)
    s.box(355, 400, 270, 60, ["Пересборка: пакет и rootfs", "make rootfs (проверка — tar по ssh)"], "build", size=12, bold_first=True)
    s.box(670, 400, 270, 60, ["Пересборка: bare_app, пакет, rootfs", "make rootfs-make BR=bare-app-rebuild"], "build", size=12, bold_first=True)
    for x in (175, 490, 805):
        s.arrow(x, 365, x, 400)

    s.box(40, 490, 900, 50, ["Общее для всех: файлы игры — /games/<id> (только чтение), сохранения — /data/<id> (Wine: /data/wine/…),",
                             "обложка cover.png 240×240 в каталоге игры, управление — [keys]/[labels], имена кнопок одни (a, b, l1, stick, rstick…)"], "note", size=12)
    s.save("game-paths.svg")


def games_image_flow():
    s = Svg(980, 400, "scripts/games-image.py: от манифеста до карты игр")
    s.box(20, 30, 230, 110, ["games/games.manifest", "[image]: fw, work, steam, installers", "[id]: source, exclude, file,", "overlay, run, env, data,", "cover, cover_crop, cover_back"], "sdk", size=12, bold_first=True)
    s.box(20, 170, 230, 90, ["Источники на ПК", "lab/games/<Игра> (вне git)", "${steam}/steamapps/common/…", "lab/redist: DLL и шрифты Windows"], "fs", size=12, bold_first=True)
    s.box(20, 290, 230, 80, ["games/<id>/", "overlay/ (wine.ini, profile)", "prepare.sh + python-помощники", "README.md игры"], "sdk", size=12, bold_first=True)

    s.box(300, 30, 250, 340, ["games-image.py", "", "1. install: copy / homm3 / halflife / none",
                              "   минус exclude", "2. file → в каталог игры", "3. overlay поверх",
                              "4. run prepare.sh", "   (GAME_DIR, SOURCE, SDK_DIR, DATA_DIR, env)",
                              "5. cover → cover.png 240×240", "   из png / .lod / .wad / .exe:icon / .bik:сек",
                              "6. проверка места", "7. rsync -rt на карту (только изменившееся)",
                              "8. data → /data платы по ssh (--board)"], "build", size=12, bold_first=True, anchor="left")
    for y in (85, 215, 330):
        s.arrow(250, y, 300, y, width=1.2)

    s.box(600, 30, 170, 90, ["<work>/games/<id>", "lab/images/work", "промежуточная сборка", "(--reuse: не трогать)"], "fs", size=12, bold_first=True)
    s.box(600, 150, 170, 90, ["<work>/data", "строки data:", "шрифты в префикс Wine"], "fs", size=12, bold_first=True)
    s.arrow(550, 75, 600, 75, width=1.2)
    s.arrow(550, 195, 600, 195, width=1.2)

    s.box(810, 30, 150, 90, ["Карта exFAT GAMES", "/media/$USER/GAMES", "в картридере или", "«USB-диск» приставки"], "game", size=12, bold_first=True)
    s.box(810, 150, 150, 90, ["Плата: /data", "root@192.168.7.2", "tar по ssh"], "board", size=12, bold_first=True)
    s.arrow(770, 75, 810, 75, "rsync", width=1.2)
    s.arrow(770, 195, 810, 195, "ssh", width=1.2)
    s.box(600, 270, 360, 100, ["Без --card: полный образ (GO Advance)", "p3 data и p4 GAMES дописываются в <fw>.img там,",
                               "где их ищет S05data; mke2fs -d + mkfs.vfat/mcopy,", "без root и loop; запись: make flash IMAGE_FILE=…"], "note", size=12, bold_first=True)
    s.save("games-image-flow.svg")


def wine_stack():
    s = Svg(980, 540, "Windows-игра на GO Ultra: стек Wine")
    s.box(20, 30, 300, 70, ["bare_app · src/games/wine.c", "каждый /games/<id>/wine.ini — плитка меню;", "запускает bare_app_wine <каталог игры>"], "app", size=12, bold_first=True)
    s.box(20, 130, 300, 110, ["bare_app_wine (ports/wine, ~2800 строк C)", "читает wine.ini, готовит префикс (wineboot),",
                              "диск D: = родитель каталога игры,", "собирает окна в экран Windows, курсор,",
                              "масштаб (aspect/fill, rows, gamma), [keys]"], "game", size=12, bold_first=True)
    s.arrow(170, 100, 170, 130)
    s.box(20, 270, 300, 90, ["Wine 11.0 WoW64 (пакет wine-wow64)", "Unix-часть и 64-битные DLL — aarch64,",
                             "32-битные DLL — i386 (llvm-mingw),", "25 патчей SDK"], "game", size=12, bold_first=True)
    s.arrow(170, 240, 170, 270, "WINEBARE_SOCKET, окружение env =", label_dy=-3)
    s.box(20, 390, 140, 70, ["wowbox64.dll", "Box64: x86 → arm64", "BIGBLOCK, CALLRET"], "game", size=11, bold_first=True)
    s.box(180, 390, 140, 70, ["winebare.drv", "драйвер экрана/ввода", "пиксели окон → мост"], "game", size=11, bold_first=True)
    s.arrow(90, 360, 90, 390)
    s.arrow(250, 360, 250, 390)
    s.path_arrow([(250, 460), (250, 490), (360, 490), (360, 185), (320, 185)], "пиксели, курсор, гамма", label_at=(450, 490))

    s.box(400, 30, 260, 70, ["Игра .exe (x86-32)", "Direct3D 8/9, DirectDraw, GDI,", "DirectInput, DirectSound"], "white", size=12, bold_first=True)
    s.box(400, 130, 260, 110, ["WineD3D → OpenGL", "Mesa 25.0 panfrost (пакет mesa-panfrost,", "5 патчей; PAN_MMAP_WINDOW для WoW64)",
                               "WINE_D3D_CONFIG=HeapMaps, SysmemMaps,", "GLStateCache; WINE_FAST_MUTEX"], "build", size=12, bold_first=True)
    s.arrow(530, 100, 530, 130)
    s.box(400, 270, 260, 60, ["GPU Mali-G52 (G12B)", "рендер в буфер вне экрана"], "board", size=12, bold_first=True)
    s.arrow(530, 240, 530, 270)

    s.group(700, 20, 260, 500, "Файловые системы", "fs")
    s.box(715, 50, 230, 90, ["/games/<id>/ (exFAT, ro)", "игра как установлена + wine.ini,", "redist DLL рядом (dlls = …=n,b),", "cover.png; имена без регистра"], "fs", size=11, bold_first=True)
    s.box(715, 160, 230, 90, ["/data/wine/prefix (ext4)", "один префикс на все игры:", "реестр, диск C:, шрифты Windows,", "Documents игр, prefs"], "fs", size=11, bold_first=True)
    s.box(715, 270, 230, 100, ["/data/wine/games/<dir>", "копия каталога игры для «writable»:", "перечисленные записи — копии,", "остальное — ссылки на /games;", "первый запуск копирует"], "fs", size=11, bold_first=True)
    s.box(715, 390, 230, 110, ["Патчи Wine 0013/0023/0024", "файлы на ro-ФС открываются", "как read-only без ошибок;", "поиск имён через stat() на FAT/exFAT", "(каталоги большие)"], "note", size=11, bold_first=True)
    s.arrow(660, 65, 715, 65, dashed=True, color="#888", width=1.2)
    s.save("wine-stack.svg")


def data_locations():
    s = Svg(980, 300, "Где что лежит на плате")
    cols = [
        ("/usr (rootfs, в образе)", ["bare_app, bare_app_wine, bare_app_doom", "движки: vcmi, xash3d, rbdoom3bfg,", "iowolfsp, wine, chocolate-doom",
                                      "/usr/share/bare_app/games/*.ini", "doom1.wad (shareware)", "перепрошивка заменяет"], "board"),
        ("/games (карта exFAT, ro)", ["heroes3/ Data Maps Mp3 Mods", "halflife/ valve valve_russian", "doom3/base, rtcw/main",
                                      "<wine-игра>/ *.exe wine.ini", "<sdl-игра>/game.ini", "cover.png в каждой"], "game"),
        ("/data (ext4, переживает прошивку)", ["vcmi/Saves, config/vcmi, cache/vcmi", "halflife/, doom/, doom3/, rtcw/",
                                                 "wine/prefix, wine/games/<dir>", "bare_app.conf: recent, controls.<key>", "hibernate.swap", "boottime.sh (OGA)"], "fs"),
        ("/tmp, /run, /var/log", ["bare_app.ctl, bare_app_wine.ctl (FIFO)", "/run/games/N — разделы игр",
                                  "/run/usb-disk, /run/hibernate.ready", "/var/log/bare_app.log —", "stdout/stderr игр тоже сюда"], "note"),
    ]
    x = 20
    for title, lines, role in cols:
        s.box(x, 25, 225, 240, [title] + lines, role, size=12, bold_first=True)
        x += 240
    s.text(20, 288, "Имя игры (id) = имя каталога на /games = имя каталога данных в /data: после первого запуска его лучше не менять.", size=12)
    s.save("data-locations.svg")


if __name__ == "__main__":
    overview()
    build_flow()
    sd_layout()
    boot_chains()
    bare_app_layers()
    game_ipc()
    game_paths()
    games_image_flow()
    wine_stack()
    data_locations()
