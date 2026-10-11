# Глоссарий

| Термин | Значение |
|---|---|
| **BL31** | Runtime-монитор TF-A в EL3: PSCI, SMC-сервисы |
| **BL32** | Безопасная ОС (OP-TEE) в TrustZone, опционально |
| **BL33** | Загрузчик «нормального мира» — у нас U-Boot |
| **binman** | Инструмент U-Boot, собирающий итоговые образы по описанию в dts |
| **BootROM** | Неизменяемый код в процессоре, первая стадия загрузки |
| **BR2_EXTERNAL** | Внешнее дерево Buildroot для своих defconfig, пакетов, overlay |
| **bootstd** | Механизм U-Boot «standard boot»: сам ищет `extlinux.conf`, EFI и т. п. |
| **defconfig** | Минимальная конфигурация Kconfig (только отличия от умолчаний) |
| **device tree (DT, dtb)** | Описание железа платы для ядра и U-Boot |
| **EL0–EL3** | Уровни привилегий ARMv8 (Exception Levels) |
| **extlinux.conf** | Простой конфиг загрузки (формат syslinux), понятный U-Boot |
| **fakeroot** | Утилита, имитирующая права root для создания файловых систем |
| **FIT (.itb)** | Контейнер образов U-Boot (сам устроен как device tree) |
| **fragment** | Короткий файл с изменениями Kconfig поверх defconfig |
| **idbloader** | TPL+SPL Rockchip с заголовком, по сектору 64 |
| **Kconfig** | Система конфигурации Linux, U-Boot, Buildroot |
| **MBR** | Классическая таблица разделов в секторе 0 |
| **mdev** | Менеджер `/dev` из busybox, подгружает модули по modalias |
| **miniloader** | Закрытый загрузчик Rockchip из rkbin (второй этап после DDR-блоба) |
| **MLO** | U-Boot SPL для TI AM335x с заголовком, грузится ROM с FAT |
| **OOM killer** | Механизм ядра, убивающий процессы при нехватке памяти |
| **out-of-tree** | Сборка с `O=`, при которой исходники не меняются |
| **PARTUUID** | Идентификатор раздела; для MBR — disk id + номер раздела |
| **PSCI** | Интерфейс управления питанием CPU через BL31 |
| **rkbin** | Набор бинарных блобов и утилит Rockchip |
| **SPL** | Урезанный U-Boot, инициализирует DRAM и грузит основной U-Boot |
| **TF-A** | Trusted Firmware-A, эталонная прошивка EL3 для ARMv8 |
| **TPL** | Ещё более ранняя стадия, чем SPL; на Rockchip инициализирует DDR |
| **trust.img** | Контейнер BL31/BL32 в формате Rockchip (`BL3X`) |
| **uboot.img** | U-Boot в формате Rockchip (`LOADER`), грузится miniloader |
| **UART** | Последовательный порт, консоль загрузки |
