# Исходники и версии

## Какие версии брать

Правило простое: **последний стабильный релиз** каждого проекта. Не `master`, не
`-rc`, если только не нужна свежая поддержка железа, которой нет в релизе.

Узнать последние теги можно, не клонируя репозиторий, — командой `git ls-remote`:

```bash
ls-tags() {
  git ls-remote --tags --refs "$1" | awk -F/ '{print $NF}' |
    grep -E "$2" | sort -V | tail -4
}
ls-tags https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git '^v7\.[0-9]+(\.[0-9]+)?$'
ls-tags https://source.denx.de/u-boot/u-boot.git '^v20[0-9]{2}\.[0-9]{2}(-rc[0-9])?$'
ls-tags https://github.com/ARM-software/arm-trusted-firmware.git '^v[0-9]+\.[0-9]+\.[0-9]+$'
ls-tags https://gitlab.com/buildroot.org/buildroot.git '^20[0-9]{2}\.[0-9]{2}(\.[0-9]+)?$'
```

На момент сборки SDK ответ был таким:

| Проект | Последнее | Выбрано | Почему |
|---|---|---|---|
| Linux stable | v7.2.9; у Торвальдса v7.3-rc6 | **v7.2.9** | стабильная ветка с исправлениями |
| U-Boot | v2026.10-rc5 | **v2026.07** | последний релиз; 2026.10 ещё rc |
| TF-A | v2.15.0 | **v2.15.0** | последний релиз |
| Buildroot | 2026.08 | **2026.08** | последний релиз |

!!! note "Stable vs mainline"
    «Mainline» в широком смысле — официальный upstream, а не вендорский форк.
    Ветка `stable` ядра (v7.2.9) — тоже mainline: это v7.2 от Торвальдса плюс только
    исправления ошибок. Для SDK она лучше, чем свежий `-rc`.

## Откуда клонировать

| Компонент | Upstream | Замечание |
|---|---|---|
| Linux | `git.kernel.org/.../stable/linux.git` | полная история ≈ 5 ГБ |
| U-Boot | `source.denx.de/u-boot/u-boot.git` | зеркало: `github.com/u-boot/u-boot` |
| TF-A | `github.com/ARM-software/arm-trusted-firmware` | |
| Buildroot | `gitlab.com/buildroot.org/buildroot` | |

### Ядро: переиспользовать локальный клон

Полная история ядра весит гигабайты, а в `Kernel_test/linux` уже лежал клон
torvalds/linux. Его можно склонировать локально и дотянуть недостающее:

```bash
git clone --no-hardlinks ~/Documents/Odroid/Kernel_test/linux src/linux
cd src/linux
git remote set-url origin https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git
git fetch origin tag v7.2.9 --no-tags      # только этот тег и нужные объекты
git checkout -b oga v7.2.9
```

Локальный клон игнорирует собранные файлы в рабочем дереве (их нет в git) и копирует
только историю. `git fetch ... tag v7.2.9` докачивает лишь разницу от v7.2-rc5 до
v7.2.9 — мегабайты вместо гигабайт.

!!! tip "Про `--no-hardlinks`"
    Без этого ключа локальный `git clone` создаёт для объектов **жёсткие ссылки**, а не
    копии: клон почти не занимает места, пока оба каталога на одной файловой системе.
    Это удобно при нехватке места. С `--no-hardlinks` получается полностью независимая
    копия: старый каталог можно удалять, не думая о связях.

### U-Boot: когда upstream медленный

Клон с `source.denx.de` шёл очень медленно (сервер перенаправлял на
`git.u-boot-project.org`). Решение — параллельно клонировать официальное зеркало
GitHub, взять то, что закончится первым, и **вернуть канонический URL** в `origin`:

```bash
git clone https://github.com/u-boot/u-boot.git src/u-boot
cd src/u-boot
git remote set-url origin https://source.denx.de/u-boot/u-boot.git
git checkout -b oga v2026.07
```

Содержимое репозитория одинаковое, коммиты те же, хеши те же — неважно, откуда они
скачаны.

### Ветка `oga`

В каждом репозитории создана локальная ветка `oga` от выбранного тега. Ваши
изменения (патчи драйверов, свои defconfig) коммитятся в неё. Пока изменений нет,
она просто указывает на upstream-тег.

## Сабмодули

Верхний репозиторий SDK хранит компоненты как **git-сабмодули**. Сабмодуль — это
ссылка на конкретный коммит в другом репозитории плюс URL, откуда его брать.

```bash
git init -b main
git submodule add https://source.denx.de/u-boot/u-boot.git src/u-boot
```

Если в `src/u-boot` уже лежит репозиторий, `git submodule add` не клонирует заново,
а пишет «Adding existing repo at 'src/u-boot' to the index». Результат — файл
`.gitmodules`:

```ini
[submodule "src/u-boot"]
	path = src/u-boot
	url = https://source.denx.de/u-boot/u-boot.git
```

!!! warning "Ловушка: `branch =` в `.gitmodules`"
    `git submodule add -b oga` записал бы `branch = oga`. Но в upstream ветки `oga`
    нет, и `git submodule update --remote` упадёт. Сабмодуль и так пинуется по
    **коммиту**, поэтому строку `branch` убрали:
    `git config -f .gitmodules --unset submodule.src/u-boot.branch`.

Склонировать SDK целиком, не скачивая всю историю ядра:

```bash
git clone --recurse-submodules --shallow-submodules git@github.com:sobs1992/linux-sdk.git
```

Как перевести сабмодуль на свой форк, когда появятся изменения, — в главе 15.

## Кэш загрузок

Buildroot скачивает исходники сотен пакетов. Их кэш вынесен в общий каталог `dl/`
(переменная `BR2_DL_DIR`), который используется всеми прошивками. Кэш из старой
попытки (`Buildroot_test/.../dl`, 342 МБ) скопировали туда, чтобы не качать заново.
В `dl/` же складываются блобы прошивки Raspberry Pi (глава 13).

## Место на диске

На практике место кончалось дважды. Ориентиры для одной прошивки:

| Что | Размер |
|---|---|
| `output/<fw>/buildroot` (с тулчейном) | 5–9 ГБ |
| `output/<fw>/linux` (arm64 `defconfig`) | ≈ 3 ГБ |
| `output/<fw>/linux` (`omap2plus`, `bcm2835`) | 1–2 ГБ |
| `src/linux` (полная история) | ≈ 5,5 ГБ |
| `dl/` | 1–2 ГБ |

Проверяйте `df -h` перед полной сборкой новой платы.
