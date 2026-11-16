# Патчи и свои изменения в компонентах

Исходники компонентов — сабмодули в `src/`, и собираются они из закоммиченного
состояния: правка в рабочем дереве сабмодуля в сборку не попадает. Свои изменения
живут в двух видах.

## Патчи SDK (основной путь)

| Что | Где | Как применяется | Что пересобирается при изменении |
|---|---|---|---|
| ядро платы | `board/<board>/linux/patches/*.patch` (`LINUX_PATCHES`) | `make linux` копирует закоммиченный `src/linux` (`git archive`) в `output/<fw>/linux-src` и накладывает патчи по именам | копия дерева делается заново; пересобираются файлы, которых касаются старые и новые патчи (им ставится новое время), остальное — по зависимостям; ядро целиком около 1,8 ГБ на копию |
| U-Boot платы | `board/<board>/u-boot/patches/*.patch` (`UBOOT_PATCHES`) | так же, в `output/<fw>/u-boot-src` | U-Boot целиком (он небольшой) |
| пакет Buildroot | `board/common/buildroot/package/<pkg>/*.patch` | Buildroot применяет при распаковке пакета | пакет целиком: `make rootfs-make BR=<pkg>-dirclean && make rootfs` (Wine и VCMI — самые долгие) |
| SDL2 для игр bare_app | `board/common/buildroot/package/bare-app/sdl2/*.patch` | хук `SDL2_POST_PATCH_HOOKS` пакета bare-app (`bare-app.SDL=y`) | `make rootfs-make BR=sdl2-dirclean` затем `make rootfs` |
| SDL2_mixer для VCMI | `board/common/buildroot/package/vcmi/sdl2_mixer/*.patch` | хук пакета vcmi | `sdl2_mixer-dirclean` |
| Mesa (panfrost) | `board/common/buildroot/package/mesa-panfrost/*.patch` | свой пакет Mesa | `mesa-panfrost-dirclean`, затем всё, что от неё зависит, пересобирать не нужно |

Патч — обычный `git format-patch` из рабочего дерева сабмодуля или распакованного
пакета (`output/<fw>/buildroot/build/<pkg>-<version>`); у Buildroot есть
`make rootfs-make BR=<pkg>-rebuild` для проверки правки без патча — это только
проверка, в образ попадает патч. Первая строка темы патча — что он меняет; в теле —
зачем и как измерено. Порядок — по имени (`0001-...`), нумерация сплошная.

Сколько их сейчас: ядро GO Ultra 31, ядро GO Advance 3, U-Boot GO Ultra 17; пакеты:
wine-wow64 24, rbdoom3-bfg 19, vcmi 13, xash3d-fwgs 10, mesa-panfrost 5, iortcw 5,
wowbox64 3, SDL2 5, SDL2_mixer 2. Темы всех патчей каталога:

```sh
grep -h '^Subject' board/ogu/linux/patches/*.patch
```

Что в каком патче и зачем — в разделах плат (`docs/boards/*.md`) и игр
(`apps/bare_app/README.md`, `games/README.md`).

## Ветка в сабмодуле (для отправки upstream)

```sh
cd src/linux
git checkout oga && git commit ...                    # работа в ветке oga
git remote add mine git@github.com:<you>/linux.git && git push mine oga
cd ../.. && git config -f .gitmodules submodule.src/linux.url git@github.com:<you>/linux.git
git add .gitmodules src/linux && git commit           # SDK пинует новый коммит
```
