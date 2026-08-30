# mxfguard

Інвентаризація, верифікація і контентна валідація медіа-архіву при
переносі даних: переставлення ОС, міграція сховищ, розбір наслідків
шифрувальника.

Інструмент розрізняє три різні питання, які зазвичай плутають в одне:

| Питання | Чим перевіряється |
|---|---|
| Чи файл доїхав біт-у-біт | хеш-маніфест + звірка |
| Чи він був цілим ДО копіювання | magic / ентропія / структура / декод |
| Чи це не пошифроване сміття | режим `--ransomware` + salvage-скан |

Хеш чесно переносить пошифроване сміття зі статусом OK — тому самого
хешу мало. Декод не ловить кожен перевернутий біт — тому самого декоду
теж мало. Потрібні обидва.

## З чого почати

1. `tools\0-preflight.cmd` — перевірка середовища
2. `tests\selftest.cmd` — доказ, що інструмент тут працює
3. `docs\MANUAL.html` — покроковий мануал
4. Далі — пронумеровані скрипти в `tools\`

## Склад

```
mxfguard.py              інструмент: scan / compare / report
tools\
  0-preflight.cmd        перевірка Python, ffmpeg, xxhash
  1-scan-source.cmd      маніфест джерела (до копіювання)
  2-scan-dest.cmd        маніфест приймача (швидкий, хеші)
  3-compare-report.cmd   звірка + HTML-звіт
  4-deep-validate.cmd    повна контентна валідація
  5-ransomware-triage.cmd оцінка шкоди від шифрувальника
  salvage-mxf.cmd        порятунок есенції з побитих MXF
  salvage.py             реалізація порятунку
  bin\                   ffmpeg.exe + ffprobe.exe (повна збірка)
  python\                Python 3.13 embeddable + xxhash (повна збірка)
tests\
  selftest.cmd           самоперевірка на цій машині
  selftest.py
docs\
  MANUAL.html            мануал для адміна на місці
  mxfguard-runbook.html  рунбук переносу, 6 фаз
  report-sample.html     приклад звіту
vendor\                  колеса xxhash для офлайн-установки
```

## Вимоги

Повна збірка (`mxfguard-1.0-standalone.zip`) не вимагає **нічого**:
Python і ffmpeg лежать усередині, скрипти підхоплюють їх самі.
Розпакував — працює, зокрема на щойно переставленій машині без мережі.

Легка збірка (`mxfguard-1.0.zip`, 246 КБ) розраховує на систему:

- **Python 3.9+** — обов'язково
- **ffmpeg / ffprobe** — для перевірок `struct` і `decode` та для
  порятунку есенції. Без них решта працює
- `xxhash` — не обов'язково, дає близько ×8 до швидкості хешування.
  Ставиться офлайн: `pip install --no-index --find-links vendor xxhash`
- `mxf2raw` (bmxlib) — не обов'язково, суворіший MXF-валідатор

Пріоритет завжди такий: комплектні `toolsin\` і `tools\python\`,
і лише якщо їх немає — те, що знайдеться в PATH.

## Збірка архівів

У git не трекаються `tools\bin\` (ffmpeg + ffprobe, по ~212 МБ — GitHub ріже
файли понад 100 МБ) і `tools\python\` (embeddable-збірка, яка лише дублює
python.org). Свіжий клон дає легку збірку; повну відновлює скрипт:

```powershell
.\make-standalone.ps1                              # рантайм + обидва архіви
.\make-standalone.ps1 -SkipArchives                # тільки рантайм
.\make-standalone.ps1 -FfmpegDir "C:\ffmpeg\bin"   # ffmpeg не в PATH
.\make-standalone.ps1 -Force                       # перезібрати наявне
```

Скрипт качає Python embeddable з python.org, розгортає в нього колесо `xxhash`
із `vendor\`, копіює ffmpeg із PATH і пакує обидва zip. Ідемпотентний.
Після нього варто прогнати `tests\selftest.cmd`.

## Ручний запуск, без обгорток

```
python mxfguard.py scan --root D:\Media --out src.csv --checks hash,magic,entropy
python mxfguard.py scan --root E:\Media --out dst.csv --checks hash
python mxfguard.py compare --src src.csv --dst dst.csv --out diff.csv
python mxfguard.py report --scan dst.csv --compare diff.csv --out report.html
```

`compare` повертає код виходу 1, якщо є MISSING / HASH_MISMATCH /
SIZE_MISMATCH — зручно вішати умову в обгортці.

## Що перевірено на практиці

Прогін на синтетичному дереві з наперед відомими поломками
(відтворюється через `tests\selftest.cmd`):

- обрив файлу посередині → `DECODE_ERROR`
- повне шифрування → `ENCRYPTED`
- шифрування голови (30% файлу) → `PARTIAL_ENCRYPTED` + `salvage_offset`
- підміна вмісту під розширенням → `BAD_MAGIC`
- записка шифрувальника → `RANSOM_NAME`
- порожній файл → `EMPTY_FILE`
- зниклий при копіюванні → `MISSING`
- 4 КБ перевернутих байтів у середині → `HASH_MISMATCH` + `DECODE_ERROR`

Порятунок перевірено наскрізь: з MXF, у якого знищено перші 6 МБ із
14 МБ, витягнуто 7,1 МБ есенції та реальні кадри.

## Межі

Інструмент нічого не розшифровує. Ентропія — евристика, не доказ.
Таблиця сигнатур не вичерпна: рідкісні формати дадуть `UNKNOWN_TYPE`.
Якість зображення не оцінюється — чорний кадр замість сюжету пройде
як OK. Це вимірювальний прилад, а не бекап.
