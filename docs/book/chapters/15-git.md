# Git: сабмодули, форки и обновления

## Как устроен репозиторий SDK

Верхний репозиторий (`linux-sdk`) хранит Makefile, конфиги, скрипты, файлы плат —
и **ссылки** на четыре сабмодуля. Сабмодуль в верхнем репозитории — это одна запись:
путь + хеш коммита. URL лежит в `.gitmodules`.

```text
$ git submodule status
 d518030...  src/buildroot (2026.08)
 5fce161...  src/linux (v7.2.9)
 da738d5...  src/tf-a (v2.15.0)
 ece349a...  src/u-boot (v2026.07)
```

Склонировать SDK со всем содержимым:

```bash
git clone --recurse-submodules --shallow-submodules git@github.com:sobs1992/linux-sdk.git
```

`--shallow-submodules` берёт только нужный коммит каждого сабмодуля без истории —
это экономит гигабайты на ядре. Если позже понадобится история:
`git -C src/linux fetch --unshallow`.

## Вносить изменения в компонент

Допустим, нужен патч драйвера панели.

```bash
cd src/linux
git switch oga                       # работаем в своей ветке
$EDITOR drivers/gpu/drm/panel/panel-elida-kd35t133.c
git commit -am "drm/panel: kd35t133: ..."
cd ../..
make linux image                     # SDK собирает ваш код
```

Пока коммит есть только у вас локально. Чтобы SDK мог на него ссылаться из любого
клона, его нужно опубликовать в **свой форк**:

```bash
# один раз: форк на GitHub (kernel.org не позволяет push, поэтому форк обязателен)
cd src/linux
git remote add mine git@github.com:<you>/linux.git
git push mine oga

cd ../..
git config -f .gitmodules submodule.src/linux.url git@github.com:<you>/linux.git
git submodule sync src/linux
git add .gitmodules src/linux
git commit -m "linux: kd35t133 fix"
```

Теперь `src/linux` в SDK указывает на ваш коммит в вашем форке.

!!! warning "Ловушка: коммит в сабмодуле без push"
    Если закоммитить новый хеш сабмодуля в SDK, но не запушить сам коммит в форк,
    у всех, кто склонирует SDK, `git submodule update` упадёт с «reference is not a
    tree». Порядок всегда: push сабмодуля → commit/push SDK.

## Обновить версию компонента

Например, перейти на U-Boot v2026.10, когда он выйдет:

```bash
cd src/u-boot
git fetch origin tag v2026.10 --no-tags
git switch oga
git rebase v2026.10                  # ваши патчи — поверх нового релиза
cd ../..
make FW=oga uboot-clean uboot        # чистая сборка: конфиг мог измениться
make image
# проверить на железе, затем:
git add src/u-boot && git commit -m "u-boot: v2026.10"
```

Что проверить после обновления:

- `make uboot` не показывает новых предупреждений `kconfig-check.sh` (фрагмент мог
  перестать применяться, если опцию переименовали);
- для OGA не изменились значения `CONFIG_SPL_PAD_TO` и
  `CONFIG_SYS_MMCSD_RAW_MODE_U_BOOT_SECTOR` (глава 12);
- `dumpimage -l u-boot.itb` показывает BL31 и все dtb.

## Что хранить в SDK, а что — в компоненте

| Изменение | Где хранить |
|---|---|
| Опции ядра/U-Boot для платы | фрагмент в `board/<плата>/` |
| Новый драйвер, исправление ошибки | коммит в сабмодуле (ветка `oga`), в идеале — отправить upstream |
| Новый DTS платы | коммит в сабмодуле |
| Пакет для rootfs | `board/common/buildroot/package/` |
| Файлы в rootfs | `board/common/buildroot/rootfs-overlay/` |
| Разметка карты, версия прошивки RPi | конфиг прошивки `configs/<fw>_defconfig` |

Чем меньше изменений в сабмодулях, тем проще обновляться. Если изменение полезно
другим — отправьте его upstream (`scripts/get_maintainer.pl` в ядре и U-Boot
подскажет, кому писать).

## .gitignore

```text
/output/
/dl/
/logs/
```

Результаты сборки, кэш загрузок и логи в репозиторий не попадают. Бинарники,
которые всё же лежат в репозитории (`board/oga/rkbin/`), лежат вместе со своей
лицензией: лицензия Rockchip разрешает распространение без изменения уведомлений.
Прошивку Raspberry Pi в репозиторий не кладём: хранятся только её sha256, а сами
файлы скачивает `make bootfw`.
