# Сторонні компоненти

Код самого mxfguard поширюється за ліцензією MIT (див. `LICENSE`).
Нижче — компоненти, які **не** є частиною mxfguard, але входять до повних
збірок (`mxfguard-1.0-standalone.zip`, `mxfguard-1.0-usb.zip`) і мають власні
ліцензії. У репозиторії їх немає: теки `tools/bin/` і `tools/python/` не
трекаються і збираються скриптом `make-standalone.ps1`.

---

## FFmpeg — GPL v3

**Що саме:** `tools/bin/ffmpeg.exe`, `tools/bin/ffprobe.exe`
**Збірка:** `9.0.1-full_build` від gyan.dev, зконфігурована з
`--enable-gpl --enable-version3`, тобто розповсюджується на умовах
**GNU General Public License версії 3**.

**Вихідні коди.** Відповідні вихідні коди цієї збірки доступні там само, звідки
взято бінарники:

- збірки та їх джерела — <https://www.gyan.dev/ffmpeg/builds/>
- апстрим FFmpeg — <https://ffmpeg.org/download.html>,
  <https://git.ffmpeg.org/ffmpeg.git>
- текст ліцензії — <https://www.gnu.org/licenses/gpl-3.0.html>

Хто отримав від нас повну збірку, має право отримати й ці вихідні коди на
умовах GPL v3.

**Чому це не поширюється на mxfguard.** mxfguard викликає `ffmpeg` і `ffprobe`
як окремі процеси через `subprocess`, не лінкується з бібліотеками FFmpeg і не
містить його коду. Це агрегація двох незалежних робіт на одному носії, тож
власний код mxfguard лишається під MIT. Обов'язки GPL стосуються поширення
самих бінарників FFmpeg.

**Якщо GPL заважає.** Візьміть легку збірку `mxfguard-1.0.zip` — у ній ffmpeg
немає взагалі, і машина використовує той, що вже стоїть у системі. Або зберіть
повну з іншим ffmpeg: `.\make-standalone.ps1 -FfmpegDir "шлях\до\bin"`.

---

## CPython — PSF License Agreement

**Що саме:** `tools/python/` — embeddable-збірка Python 3.13.15 з python.org.
Повний текст ліцензії лежить поруч, у `tools/python/LICENSE.txt`.

- <https://docs.python.org/3/license.html>
- <https://www.python.org/downloads/windows/>

Ліцензія дозволяє розповсюдження без додаткових умов, окрім збереження
повідомлення про авторські права.

---

## xxhash (модуль Python) — BSD 2-Clause

**Що саме:** `vendor/xxhash-4.0.1-*.whl` — колеса для офлайн-установки, а в
повних збірках модуль уже розгорнуто всередині `tools/python/`.

- <https://github.com/ifduyue/python-xxhash>
- сам алгоритм xxHash: <https://github.com/Cyan4973/xxHash> (BSD 2-Clause)

---

## Шрифти у документації

`docs/MANUAL.html` підключає Archivo, IBM Plex Sans і IBM Plex Mono з Google
Fonts (SIL Open Font License 1.1). Файли шрифтів не входять до збірок —
підвантажуються при відкритті сторінки, а без мережі підставляються системні.

---

## Що НЕ входить до жодної збірки

`mxf2raw` (bmxlib) — необов'язковий суворіший MXF-валідатор. Якщо він є в PATH,
mxfguard ним скористається, але в комплект не входить і ніде не розповсюджується.
