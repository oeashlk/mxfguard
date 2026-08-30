#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mxfguard — інвентаризація, верифікація та контентна валідація медіа-архіву
при переносі даних (переставлення ОС, міграція сховищ, розбір наслідків
шифрувальника).

Три речі, які цей інструмент розрізняє, бо це три різні задачі:

  1. Цілісність передачі   — файл доїхав біт-у-біт          (хеш-маніфест + звірка)
  2. Валідність контенту   — файл був цілим ДО копіювання   (magic / ентропія / структура / декод)
  3. Слід шифрувальника    — файл не є пошифрованим сміттям (ransomware-режим + salvage-скан)

Режими
------
  scan     — обійти дерево, порахувати хеші й перевірки, записати маніфест CSV
  compare  — звірити маніфест джерела з маніфестом приймача
  report   — зібрати самодостатній HTML-звіт із CSV

Приклади
--------
  # 1. Маніфест джерела (з чистого середовища / read-only монтування)
  python3 mxfguard.py scan --root /mnt/src --out src.csv --checks hash,magic,entropy

  # 2. Копіювання робиться зовні (robocopy / rsync / FastCopy)

  # 3. Маніфест приймача + повна валідація контенту
  python3 mxfguard.py scan --root E:\\Media --out dst.csv \\
      --checks hash,magic,entropy,struct,decode --jobs 8 --decode-jobs 3

  # 4. Звірка та звіт
  python3 mxfguard.py compare --src src.csv --dst dst.csv --out diff.csv
  python3 mxfguard.py report --scan dst.csv --compare diff.csv --out report.html

Залежності: тільки стандартна бібліотека.
Опційно: xxhash (швидший хеш), ffmpeg/ffprobe у PATH (struct/decode), bmxlib mxf2raw.
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

VERSION = "1.0"


# ---------------------------------------------------------------------------
# 0. Комплектний ffmpeg
# ---------------------------------------------------------------------------
def _use_bundled_tools() -> None:
    """
    Додати комплектний tools/bin у PATH, якщо він поруч зі скриптом.

    Без цього запуск напряму (не через .cmd-обгортку) не бачив би
    вкладений ffmpeg і мовчки пропускав перевірки struct і decode,
    видаючи маніфест, який виглядає чистим.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    up = os.path.dirname(here)
    for cand in (os.path.join(here, "tools", "bin"),
                 os.path.join(here, "bin"),
                 os.path.join(up, "tools", "bin"),
                 os.path.join(up, "bin")):
        if os.path.isdir(cand):
            os.environ["PATH"] = cand + os.pathsep + os.environ.get("PATH", "")
            return


_use_bundled_tools()


# ---------------------------------------------------------------------------
# 1. Сигнатури типів файлів
# ---------------------------------------------------------------------------
# (offset, bytes) — достатньо збігу за будь-яким записом зі списку.
# MXF: перші 4 байти — SMPTE Universal Label prefix 06 0E 2B 34 (SMPTE ST 377-1).
# Повний ключ Header Partition Pack: 06 0E 2B 34 02 05 01 01 0D 01 02 01 01 02 xx 00

MXF_UL_PREFIX = b"\x06\x0e\x2b\x34"
# Спільний 13-байтовий префікс усіх Partition Pack / Primer / RIP ключів.
# 14-й байт задає тип: 02 Header, 03 Body, 04 Footer, 05 Primer, 11 Random Index Pack.
MXF_PARTITION_KEY = b"\x06\x0e\x2b\x34\x02\x05\x01\x01\x0d\x01\x02\x01\x01"
MXF_PACK_TYPE = {0x02: "Header Partition", 0x03: "Body Partition",
                 0x04: "Footer Partition", 0x05: "Primer Pack",
                 0x11: "Random Index Pack"}

MAGIC: dict[str, list[tuple[int, bytes]]] = {
    # --- broadcast / video ---
    "mxf":  [(0, MXF_UL_PREFIX)],
    "gxf":  [(0, b"\x00\x00\x00\x00\x01\xbc")],
    "mov":  [(4, b"ftyp"), (4, b"moov"), (4, b"mdat"), (4, b"free"),
             (4, b"skip"), (4, b"wide"), (4, b"pnot")],
    "mp4":  [(4, b"ftyp")],
    "m4v":  [(4, b"ftyp")],
    "m4a":  [(4, b"ftyp")],
    "mkv":  [(0, b"\x1a\x45\xdf\xa3")],
    "webm": [(0, b"\x1a\x45\xdf\xa3")],
    "avi":  [(0, b"RIFF")],
    "ts":   [(0, b"\x47")],
    "m2ts": [(4, b"\x47"), (0, b"\x47")],
    "mts":  [(4, b"\x47"), (0, b"\x47")],
    "mpg":  [(0, b"\x00\x00\x01\xba"), (0, b"\x00\x00\x01\xb3")],
    "mpeg": [(0, b"\x00\x00\x01\xba"), (0, b"\x00\x00\x01\xb3")],
    "vob":  [(0, b"\x00\x00\x01\xba")],
    "flv":  [(0, b"FLV\x01")],
    "webp": [(0, b"RIFF")],
    "r3d":  [(4, b"RED1"), (4, b"RED2")],
    # --- audio ---
    "wav":  [(0, b"RIFF"), (0, b"RF64")],
    "bwf":  [(0, b"RIFF"), (0, b"RF64")],
    "aif":  [(0, b"FORM")],
    "aiff": [(0, b"FORM")],
    "flac": [(0, b"fLaC")],
    "ogg":  [(0, b"OggS")],
    "opus": [(0, b"OggS")],
    "mp3":  [(0, b"ID3"), (0, b"\xff\xfb"), (0, b"\xff\xf3"),
             (0, b"\xff\xf2"), (0, b"\xff\xfa")],
    # --- images ---
    "jpg":  [(0, b"\xff\xd8\xff")],
    "jpeg": [(0, b"\xff\xd8\xff")],
    "png":  [(0, b"\x89PNG\r\n\x1a\n")],
    "gif":  [(0, b"GIF87a"), (0, b"GIF89a")],
    "tif":  [(0, b"II*\x00"), (0, b"MM\x00*")],
    "tiff": [(0, b"II*\x00"), (0, b"MM\x00*")],
    "bmp":  [(0, b"BM")],
    "psd":  [(0, b"8BPS")],
    "dpx":  [(0, b"SDPX"), (0, b"XPDS")],
    "exr":  [(0, b"\x76\x2f\x31\x01")],
    "ico":  [(0, b"\x00\x00\x01\x00")],
    "heic": [(4, b"ftyp")],
    # --- documents / archives ---
    "pdf":  [(0, b"%PDF-")],
    "zip":  [(0, b"PK\x03\x04"), (0, b"PK\x05\x06"), (0, b"PK\x07\x08")],
    "docx": [(0, b"PK\x03\x04")],
    "xlsx": [(0, b"PK\x03\x04")],
    "pptx": [(0, b"PK\x03\x04")],
    "odt":  [(0, b"PK\x03\x04")],
    "ods":  [(0, b"PK\x03\x04")],
    "epub": [(0, b"PK\x03\x04")],
    "doc":  [(0, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")],
    "xls":  [(0, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")],
    "ppt":  [(0, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")],
    "msg":  [(0, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")],
    "rar":  [(0, b"Rar!\x1a\x07")],
    "7z":   [(0, b"7z\xbc\xaf\x27\x1c")],
    "gz":   [(0, b"\x1f\x8b")],
    "tgz":  [(0, b"\x1f\x8b")],
    "bz2":  [(0, b"BZh")],
    "xz":   [(0, b"\xfd7zXZ\x00")],
    "iso":  [(32769, b"CD001"), (0, b"\x00")],
    "pst":  [(0, b"!BDN")],
    "ost":  [(0, b"!BDN")],
    "sqlite": [(0, b"SQLite format 3\x00")],
    "db":   [(0, b"SQLite format 3\x00")],
    "exe":  [(0, b"MZ")],
    "dll":  [(0, b"MZ")],
    "prproj": [(0, b"\x1f\x8b")],
    "aep":  [(0, b"RIFX"), (0, b"RIFF")],
    "veg":  [(0, b"RIFF")],
    "drp":  [(0, b"SQLite format 3\x00"), (0, b"PK\x03\x04")],
}

# Текстові типи — перевіряються декодуванням, а не магією
TEXT_EXT = {"txt", "csv", "tsv", "md", "log", "xml", "json", "srt", "vtt", "sub",
            "ini", "cfg", "conf", "yml", "yaml", "html", "htm", "css", "js",
            "py", "ps1", "bat", "cmd", "sh", "sql", "edl", "aaf_xml", "fcpxml"}

# Формати, у яких висока ентропія — норма (стиснуті/зашифровані за природою).
# Для них ентропія не є сигналом, покладаємось на magic + структуру.
HIGH_ENTROPY_BY_DESIGN = {
    "zip", "docx", "xlsx", "pptx", "odt", "ods", "epub", "rar", "7z", "gz",
    "tgz", "bz2", "xz", "jpg", "jpeg", "png", "webp", "heic", "mp3", "m4a",
    "aac", "ogg", "opus", "flac", "mp4", "mov", "m4v", "mkv", "webm", "flv",
    "prproj", "pdf",
}

MEDIA_EXT = {
    "mxf", "mov", "mp4", "m4v", "mkv", "webm", "avi", "ts", "m2ts", "mts",
    "mpg", "mpeg", "vob", "flv", "gxf", "wav", "bwf", "aif", "aiff", "flac",
    "ogg", "opus", "mp3", "m4a", "dv", "r3d",
}

# Імена файлів, характерні для записок шифрувальників
RANSOM_NOTE_RE = re.compile(
    r"^(.*(readme|read_me|how[\W_]*to[\W_]*(decrypt|restore|recover)|"
    r"decrypt[\W_]*(me|instruction|files)|restore[\W_]*files|recovery[\W_]*key|"
    r"your[\W_]*files|unlock[\W_]*files|!.*recover).*)\.(txt|html|hta|url|rtf)$",
    re.IGNORECASE,
)

# Розширення, що виглядають як «дописані поверх» справжнього
DOUBLE_EXT_RE = re.compile(
    r"\.(mxf|mov|mp4|wav|mkv|avi|mpg|jpg|png|pdf|docx|xlsx|psd|aep|prproj)"
    r"\.[A-Za-z0-9_\-]{2,12}$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# 2. Статуси і їх «вага». Підсумковий статус файлу = найважчий зі спрацьованих.
# ---------------------------------------------------------------------------
STATUS_SEVERITY = {
    "OK": 0,
    "UNKNOWN_TYPE": 10,
    "SKIPPED": 5,
    "EMPTY_FILE": 30,
    "SUSPECT_ENTROPY": 40,
    "STRUCT_FAIL": 50,
    "DECODE_ERROR": 60,
    "BAD_MAGIC": 70,
    "RANSOM_NAME": 75,
    "PARTIAL_ENCRYPTED": 85,
    "ENCRYPTED": 90,
    "READ_ERROR": 100,
}
# Статуси, що додаються на етапі compare
COMPARE_SEVERITY = {
    "OK": 0,
    "EXTRA": 20,
    "MTIME_DIFF": 25,
    "SIZE_MISMATCH": 80,
    "HASH_MISMATCH": 95,
    "MISSING": 100,
}

STATUS_HINT = {
    "OK": "Перевірки пройдено",
    "UNKNOWN_TYPE": "Тип файлу не в таблиці сигнатур — перевірено лише хеш",
    "SKIPPED": "Перевірки вимкнено для цього файлу",
    "EMPTY_FILE": "Файл нульового розміру",
    "SUSPECT_ENTROPY": "Ентропія вища за норму для цього типу — можлива підміна вмісту",
    "STRUCT_FAIL": "ffprobe/mxf2raw не змогли розібрати контейнер або він обрізаний",
    "DECODE_ERROR": "Помилки під час повного декодування — биті кадри або обрив",
    "BAD_MAGIC": "Перші байти не відповідають розширенню — вміст не той, що заявлено",
    "RANSOM_NAME": "Ім'я файлу схоже на записку або дописане розширення шифрувальника",
    "PARTIAL_ENCRYPTED": "Голова файлу зашифрована, тіло схоже на живе — есенцію ймовірно можна врятувати",
    "ENCRYPTED": "Файл зашифрований повністю",
    "READ_ERROR": "Файл не читається (I/O, права доступу, битий сектор)",
    "MISSING": "Є на джерелі, немає на приймачі",
    "EXTRA": "Є на приймачі, немає в маніфесті джерела",
    "SIZE_MISMATCH": "Розмір не збігається з джерелом",
    "HASH_MISMATCH": "Хеш не збігається з джерелом — файл змінився під час переносу",
    "MTIME_DIFF": "Час модифікації відрізняється (не завжди помилка)",
}

FIELDS = [
    "rel", "size", "mtime", "hash", "algo", "ext", "magic",
    "ent_head", "ent_mid", "ent_tail", "struct", "duration",
    "decode", "salvage_offset", "status", "notes",
]

CHUNK = 8 * 1024 * 1024
SAMPLE = 1024 * 1024

# Системний сміттєсбір, який тільки шумить у звіті
DEFAULT_EXCLUDE = ["Thumbs.db", "desktop.ini", ".DS_Store", "._*",
                   "$RECYCLE.BIN", "System Volume Information",
                   ".Trash-*", "*.tmp", "~$*", "mxfguard_*.csv"]


# ---------------------------------------------------------------------------
# 3. Хешування
# ---------------------------------------------------------------------------
def make_hasher(algo: str):
    if algo == "xxh128":
        import xxhash  # type: ignore
        return xxhash.xxh128()
    if algo == "xxh64":
        import xxhash  # type: ignore
        return xxhash.xxh64()
    if algo == "blake2b":
        return hashlib.blake2b(digest_size=16)
    if algo == "sha256":
        return hashlib.sha256()
    if algo == "md5":
        return hashlib.md5()
    raise ValueError(f"невідомий алгоритм: {algo}")


def resolve_algo(requested: str) -> str:
    """xxh128 -> blake2b, якщо модуль xxhash не встановлено."""
    if requested.startswith("xxh"):
        try:
            import xxhash  # noqa: F401
            return requested
        except ImportError:
            sys.stderr.write(
                "[!] модуль xxhash не знайдено -> використовую blake2b "
                "(стандартна бібліотека, ~1 ГБ/с). "
                "Для максимальної швидкості: pip install xxhash\n")
            return "blake2b"
    return requested


def hash_file(path: str, algo: str) -> str:
    h = make_hasher(algo)
    with open(path, "rb", buffering=0) as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# 4. Ентропія
# ---------------------------------------------------------------------------
def shannon(buf: bytes) -> float:
    if not buf:
        return 0.0
    c = Counter(buf)
    n = len(buf)
    return -sum((v / n) * math.log2(v / n) for v in c.values())


def sample_entropy(path: str, size: int) -> tuple[float, float, float, bytes]:
    """Ентропія голови/середини/хвоста + буфер голови (для magic та salvage)."""
    with open(path, "rb", buffering=0) as f:
        head = f.read(min(SAMPLE, size))
        if size <= 3 * SAMPLE:
            f.seek(0)
            whole = f.read()
            e = shannon(whole)
            return e, e, e, whole[:64]
        f.seek(size // 2)
        mid = f.read(SAMPLE)
        f.seek(max(0, size - SAMPLE))
        tail = f.read(SAMPLE)
    return shannon(head), shannon(mid), shannon(tail), head[:64]


# ---------------------------------------------------------------------------
# 5. Перевірка сигнатури
# ---------------------------------------------------------------------------
def read_head(path: str, n: int = 65536) -> bytes:
    with open(path, "rb", buffering=0) as f:
        return f.read(n)


def check_magic(path: str, ext: str, head: bytes) -> tuple[str, str]:
    """-> ('ok' | 'bad' | 'unknown', note)"""
    if ext in MAGIC:
        for off, sig in MAGIC[ext]:
            if head[off:off + len(sig)] == sig:
                return "ok", ""
        # спецвипадок: RIFF-контейнери мають ще й підтип
        if ext in ("wav", "bwf") and head[:4] in (b"RIFF", b"RF64"):
            return "ok", ""
        found = head[:8].hex(" ")
        return "bad", f"очікував {MAGIC[ext][0][1].hex(' ')}, отримав {found}"
    if ext in TEXT_EXT:
        try:
            head[:4096].decode("utf-8")
            return "ok", ""
        except UnicodeDecodeError:
            try:
                head[:4096].decode("utf-16")
                return "ok", ""
            except UnicodeDecodeError:
                nonprint = sum(1 for b in head[:4096] if b < 9 or (13 < b < 32))
                if nonprint > len(head[:4096]) * 0.05:
                    return "bad", "текстовий файл із бінарним вмістом"
                return "ok", "не UTF-8, але схоже на текст"
    return "unknown", ""


def find_first_mxf_partition(path: str, window: int, skip: int = 0) -> tuple[int, str]:
    """
    Salvage-скан: шукає перший неушкоджений ключ MXF Partition Pack.
    Повертає (зсув, тип) або (-1, ""). Сучасні шифрувальники часто
    шифрують лише перші N МБ великих файлів (partial/intermittent
    encryption), тож есенція за цим зсувом зазвичай жива.
    """
    key = MXF_PARTITION_KEY
    step = 4 * 1024 * 1024
    overlap = len(key) + 2
    pos = skip
    with open(path, "rb", buffering=0) as f:
        while pos < window:
            f.seek(pos)
            buf = f.read(step + overlap)
            if not buf:
                break
            i = buf.find(key)
            if i != -1:
                t = buf[i + len(key)] if i + len(key) < len(buf) else 0
                return pos + i, MXF_PACK_TYPE.get(t, f"тип 0x{t:02x}")
            pos += step
    return -1, ""


# ---------------------------------------------------------------------------
# 6. Структура і декод через ffmpeg
# ---------------------------------------------------------------------------
HAVE_FFPROBE = shutil.which("ffprobe") is not None
HAVE_FFMPEG = shutil.which("ffmpeg") is not None
HAVE_MXF2RAW = shutil.which("mxf2raw") is not None


def probe_struct(path: str, size: int, timeout: int) -> tuple[str, str, str]:
    """-> (status, duration, note); status: ok | fail | skip"""
    if not HAVE_FFPROBE:
        return "skip", "", "ffprobe не знайдено в PATH"
    cmd = ["ffprobe", "-v", "error", "-show_format", "-show_streams",
           "-of", "json", "-i", path]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "fail", "", "ffprobe timeout"
    if p.returncode != 0:
        err = p.stderr.decode("utf-8", "replace").strip().splitlines()
        return "fail", "", (err[-1] if err else "ffprobe non-zero exit")[:200]
    try:
        data = json.loads(p.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return "fail", "", "ffprobe повернув невалідний JSON"
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    dur = fmt.get("duration", "")
    notes = []
    if not streams:
        return "fail", dur, "контейнер без потоків"
    try:
        if dur and float(dur) <= 0:
            notes.append("нульова тривалість")
    except ValueError:
        pass
    try:
        declared = int(fmt.get("size", size))
        if declared != size:
            notes.append(f"розмір у контейнері {declared} != {size} на диску")
    except (TypeError, ValueError):
        pass
    # MXF: додатковий суворий валідатор, якщо є bmxlib
    if HAVE_MXF2RAW and path.lower().endswith(".mxf"):
        try:
            q = subprocess.run(["mxf2raw", "--info", path],
                               capture_output=True, timeout=timeout)
            if q.returncode != 0:
                e = q.stderr.decode("utf-8", "replace").strip().splitlines()
                return "fail", dur, "mxf2raw: " + (e[-1] if e else "non-zero exit")[:160]
        except (subprocess.TimeoutExpired, OSError):
            notes.append("mxf2raw timeout")
    return ("ok" if not notes else "fail"), dur, "; ".join(notes)


def decode_check(path: str, timeout: int, edges: int = 0) -> tuple[str, str]:
    """Повний (або крайовий) декод. -> (ok | fail | skip, note)"""
    if not HAVE_FFMPEG:
        return "skip", "ffmpeg не знайдено в PATH"
    runs = []
    if edges > 0:
        runs.append(["ffmpeg", "-nostdin", "-v", "error", "-xerror",
                     "-t", str(edges), "-i", path, "-f", "null", "-"])
        runs.append(["ffmpeg", "-nostdin", "-v", "error", "-xerror",
                     "-sseof", f"-{edges}", "-i", path, "-f", "null", "-"])
    else:
        runs.append(["ffmpeg", "-nostdin", "-v", "error", "-xerror",
                     "-i", path, "-f", "null", "-"])
    for cmd in runs:
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return "fail", f"ffmpeg timeout > {timeout}s"
        err = p.stderr.decode("utf-8", "replace").strip()
        if p.returncode != 0 or err:
            line = err.splitlines()[-1] if err else f"exit {p.returncode}"
            return "fail", line[:200]
    return "ok", ""


# ---------------------------------------------------------------------------
# 7. Обробка одного файлу
# ---------------------------------------------------------------------------
class Opts:
    pass


def classify(row: dict, opt) -> None:
    """Виставляє row['status'] і дописує notes на основі зібраних перевірок."""
    hits: list[str] = []
    notes: list[str] = [row["notes"]] if row["notes"] else []
    ext = row["ext"]

    if row["size"] == 0:
        hits.append("EMPTY_FILE")

    if row["magic"] == "bad":
        hits.append("BAD_MAGIC")
    elif row["magic"] == "unknown":
        hits.append("UNKNOWN_TYPE")

    # ентропія
    eh, em, et = row["ent_head"], row["ent_mid"], row["ent_tail"]
    if eh is not None and ext not in HIGH_ENTROPY_BY_DESIGN:
        thr = opt.entropy_threshold
        body_max = max(x for x in (em, et) if x is not None)
        looks_wrong = row["magic"] == "bad" or bool(row.get("_ransom_name"))
        if eh >= thr and body_max >= thr:
            hits.append("ENCRYPTED" if looks_wrong else "SUSPECT_ENTROPY")
        elif eh >= thr and body_max < thr - opt.entropy_delta:
            hits.append("PARTIAL_ENCRYPTED")
            notes.append(f"ентропія голови {eh:.3f} проти тіла {body_max:.3f}")
        elif eh >= thr:
            hits.append("SUSPECT_ENTROPY")

    if row["struct"] == "fail":
        hits.append("STRUCT_FAIL")
    if row["decode"] == "fail":
        hits.append("DECODE_ERROR")
    if row.get("_ransom_name"):
        hits.append("RANSOM_NAME")
    if row.get("_read_error"):
        hits.append("READ_ERROR")

    if row["salvage_offset"] not in ("", None, -1):
        notes.append(f"перший цілий MXF Partition Pack на зсуві {row['salvage_offset']} "
                     f"({int(row['salvage_offset'])/1048576:.1f} МБ) — есенція ймовірно рятується")

    row["status"] = max(hits, key=lambda s: STATUS_SEVERITY.get(s, 0)) if hits else "OK"
    if len(hits) > 1:
        others = [h for h in sorted(set(hits), key=lambda s: -STATUS_SEVERITY.get(s, 0))
                  if h != row["status"]]
        if others:
            notes.append("також: " + ", ".join(others))
    row["notes"] = " | ".join(n for n in notes if n)
    row.pop("_ransom_name", None)
    row.pop("_read_error", None)


def process_file(root: str, rel: str, opt) -> dict:
    full = os.path.join(root, rel)
    row = {k: "" for k in FIELDS}
    row.update({"rel": rel, "ext": os.path.splitext(rel)[1].lstrip(".").lower(),
                "algo": opt.hash_algo if opt.do_hash else "",
                "magic": "", "struct": "", "decode": "",
                "ent_head": None, "ent_mid": None, "ent_tail": None,
                "salvage_offset": "", "notes": "", "status": ""})
    base = os.path.basename(rel)
    if RANSOM_NOTE_RE.match(base) or DOUBLE_EXT_RE.search(base):
        row["_ransom_name"] = True

    try:
        st = os.stat(full)
        row["size"] = st.st_size
        row["mtime"] = datetime.fromtimestamp(
            st.st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
    except OSError as e:
        row["size"] = 0
        row["_read_error"] = True
        row["notes"] = f"stat: {e}"
        classify(row, opt)
        return row

    size = row["size"]
    try:
        if size > 0 and (opt.do_magic or opt.do_entropy or opt.ransomware):
            eh, em, et, _ = sample_entropy(full, size)
            if opt.do_entropy:
                row["ent_head"], row["ent_mid"], row["ent_tail"] = (
                    round(eh, 3), round(em, 3), round(et, 3))
            if opt.do_magic:
                head = read_head(full, 65536)
                row["magic"], note = check_magic(full, row["ext"], head)
                if note:
                    row["notes"] = note
        if opt.do_hash:
            row["hash"] = hash_file(full, opt.hash_algo)
    except OSError as e:
        row["_read_error"] = True
        row["notes"] = (row["notes"] + f" | read: {e}").strip(" |")
        classify(row, opt)
        return row

    # структура / декод — тільки для медіа і тільки якщо файл не є явним сміттям
    obviously_broken = row["magic"] == "bad"
    if opt.do_struct and row["ext"] in MEDIA_EXT and size > 0 and not obviously_broken:
        row["struct"], row["duration"], note = probe_struct(full, size, opt.probe_timeout)
        if note:
            row["notes"] = (row["notes"] + " | " + note).strip(" |")
    if (opt.do_decode and row["ext"] in MEDIA_EXT and size > 0
            and not obviously_broken and row["struct"] != "fail"):
        row["decode"], note = decode_check(full, opt.decode_timeout, opt.decode_edges)
        if note:
            row["notes"] = (row["notes"] + " | ffmpeg: " + note).strip(" |")

    # salvage-скан: чи є десь у голові цілий MXF Partition Pack.
    # Робимо для файлів, які колись були MXF (за розширенням або за дописаним
    # розширенням шифрувальника) і які зараз виглядають зіпсованими.
    if opt.ransomware and size > 0:
        was_mxf = row["ext"] == "mxf" or ".mxf." in base.lower()
        looks_broken = row["magic"] == "bad" or bool(row.get("_ransom_name"))
        if was_mxf and looks_broken:
            off, kind = find_first_mxf_partition(full, min(size, opt.salvage_window))
            if off >= 0:
                row["salvage_offset"] = off
                row["notes"] = (row["notes"] + f" | знайдено {kind}").strip(" |")

    classify(row, opt)
    return row


# ---------------------------------------------------------------------------
# 8. Обхід дерева
# ---------------------------------------------------------------------------
def walk(root: str, opt):
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames
                       if not any(fnmatch.fnmatch(d, p) for p in opt.exclude)]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            if any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(fn, p)
                   for p in opt.exclude):
                continue
            if opt.include_ext:
                if os.path.splitext(fn)[1].lstrip(".").lower() not in opt.include_ext:
                    continue
            if opt.min_size and os.path.exists(full):
                try:
                    if os.path.getsize(full) < opt.min_size:
                        continue
                except OSError:
                    pass
            yield rel.replace("\\", "/")


def cmd_scan(a) -> int:
    root = os.path.abspath(a.root)
    if not os.path.isdir(root):
        sys.stderr.write(f"[x] не каталог: {root}\n")
        return 2

    checks = {c.strip() for c in a.checks.split(",") if c.strip()}
    opt = Opts()
    opt.do_hash = "hash" in checks
    opt.do_magic = "magic" in checks
    opt.do_entropy = "entropy" in checks
    opt.do_struct = "struct" in checks
    opt.do_decode = "decode" in checks
    opt.ransomware = a.ransomware
    # не турбувати попередженням про xxhash, якщо хешування взагалі не просили
    opt.hash_algo = resolve_algo(a.hash) if opt.do_hash else a.hash
    opt.entropy_threshold = a.entropy_threshold
    opt.entropy_delta = a.entropy_delta
    opt.probe_timeout = a.probe_timeout
    opt.decode_timeout = a.decode_timeout
    opt.decode_edges = a.decode_edges
    opt.salvage_window = a.salvage_window
    opt.exclude = list(a.exclude) + ([] if a.no_default_exclude else DEFAULT_EXCLUDE)
    opt.include_ext = ({e.strip().lstrip(".").lower()
                        for e in a.include_ext.split(",") if e.strip()}
                       if a.include_ext else None)
    opt.min_size = a.min_size

    done: set[str] = set()
    mode = "w"
    if a.resume and os.path.exists(a.out):
        with open(a.out, "r", encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                done.add(r["rel"])
        mode = "a"
        sys.stderr.write(f"[i] resume: {len(done)} рядків уже в {a.out}\n")

    files = [r for r in walk(root, opt) if r not in done]
    total = len(files)
    sys.stderr.write(
        f"[i] mxfguard {VERSION} | корінь: {root}\n"
        f"[i] файлів до обробки: {total} | перевірки: {','.join(sorted(checks)) or 'немає'}"
        f" | хеш: {opt.hash_algo if opt.do_hash else '-'}\n"
        f"[i] ffprobe={'так' if HAVE_FFPROBE else 'НІ'} "
        f"ffmpeg={'так' if HAVE_FFMPEG else 'НІ'} "
        f"mxf2raw={'так' if HAVE_MXF2RAW else 'ні'}\n")
    if total == 0:
        sys.stderr.write("[i] нічого робити\n")
        return 0

    lock = threading.Lock()
    counter = {"n": 0, "bad": 0}
    t0 = time.time()

    fh = open(a.out, mode, encoding="utf-8", newline="")
    w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
    if mode == "w":
        w.writeheader()

    # декод дорогий і однопотоковим ffmpeg не є — тримаємо окремий, вужчий пул
    io_jobs = max(1, a.jobs)
    dec_jobs = max(1, a.decode_jobs)
    pool_size = io_jobs if not opt.do_decode else max(io_jobs, dec_jobs)
    sem = threading.Semaphore(dec_jobs)

    def task(rel: str) -> dict:
        if opt.do_decode:
            with sem:
                return process_file(root, rel, opt)
        return process_file(root, rel, opt)

    try:
        with ThreadPoolExecutor(max_workers=pool_size) as ex:
            futs = {ex.submit(task, r): r for r in files}
            for fut in as_completed(futs):
                rel = futs[fut]
                try:
                    row = fut.result()
                except Exception as e:  # noqa: BLE001
                    row = {k: "" for k in FIELDS}
                    row.update({"rel": rel, "status": "READ_ERROR", "notes": repr(e)})
                with lock:
                    w.writerow(row)
                    fh.flush()
                    counter["n"] += 1
                    if row["status"] != "OK":
                        counter["bad"] += 1
                    if counter["n"] % a.progress_every == 0 or counter["n"] == total:
                        el = time.time() - t0
                        rate = counter["n"] / el if el else 0
                        eta = (total - counter["n"]) / rate if rate else 0
                        sys.stderr.write(
                            f"\r[{counter['n']}/{total}] проблемних: {counter['bad']} "
                            f"| {rate:.1f} файл/с | ETA {eta/60:.1f} хв      ")
                        sys.stderr.flush()
    finally:
        fh.close()
    sys.stderr.write(f"\n[i] готово за {(time.time()-t0)/60:.1f} хв -> {a.out}\n")
    if counter["bad"]:
        sys.stderr.write(f"[!] файлів зі статусом != OK: {counter['bad']}\n")
    return 0


# ---------------------------------------------------------------------------
# 9. Звірка джерело / приймач
# ---------------------------------------------------------------------------
def load_manifest(path: str) -> dict[str, dict]:
    out = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            out[r["rel"]] = r
    return out


def cmd_compare(a) -> int:
    src = load_manifest(a.src)
    dst = load_manifest(a.dst)
    rows = []
    counts = Counter()
    for rel, s in src.items():
        d = dst.get(rel)
        if d is None:
            st, note = "MISSING", ""
        elif str(s.get("size")) != str(d.get("size")):
            st, note = "SIZE_MISMATCH", f"{s.get('size')} -> {d.get('size')}"
        elif s.get("hash") and d.get("hash") and s["hash"] != d["hash"]:
            st, note = "HASH_MISMATCH", f"{s['hash'][:16]}… -> {d['hash'][:16]}…"
        elif not s.get("hash") or not d.get("hash"):
            st, note = "OK", "розмір збігається, хеш не рахувався"
        elif a.check_mtime and s.get("mtime") != d.get("mtime"):
            st, note = "MTIME_DIFF", f"{s.get('mtime')} -> {d.get('mtime')}"
        else:
            st, note = "OK", ""
        counts[st] += 1
        rows.append({"rel": rel, "transfer": st, "src_size": s.get("size", ""),
                     "dst_size": (d or {}).get("size", ""),
                     "src_hash": s.get("hash", ""), "dst_hash": (d or {}).get("hash", ""),
                     "note": note})
    for rel, d in dst.items():
        if rel not in src:
            counts["EXTRA"] += 1
            rows.append({"rel": rel, "transfer": "EXTRA", "src_size": "",
                         "dst_size": d.get("size", ""), "src_hash": "",
                         "dst_hash": d.get("hash", ""), "note": ""})
    rows.sort(key=lambda r: (-COMPARE_SEVERITY.get(r["transfer"], 0), r["rel"]))
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["rel", "transfer", "src_size", "dst_size",
                                          "src_hash", "dst_hash", "note"])
        w.writeheader()
        w.writerows(rows)
    sys.stderr.write(f"[i] джерело: {len(src)} | приймач: {len(dst)}\n")
    for k in sorted(counts, key=lambda x: -COMPARE_SEVERITY.get(x, 0)):
        sys.stderr.write(f"    {k:<14} {counts[k]}\n")
    sys.stderr.write(f"[i] -> {a.out}\n")
    bad = sum(v for k, v in counts.items() if COMPARE_SEVERITY.get(k, 0) >= 80)
    return 1 if bad else 0


# ---------------------------------------------------------------------------
# 10. HTML-звіт
# ---------------------------------------------------------------------------
HTML_TMPL = """<!doctype html>
<html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>mxfguard — звіт переносу</title>
<style>
:root{color-scheme:light dark;--bg:#fbfbf9;--fg:#1a1a18;--mut:#6b6b63;--line:#e2e2db;
--card:#fff;--ok:#2f7d4f;--warn:#a8791a;--err:#c0453a;--crit:#8f2119;--accent:#4a5fd0}
@media(prefers-color-scheme:dark){:root{--bg:#16161a;--fg:#e8e8e4;--mut:#9a9a92;
--line:#2e2e35;--card:#1e1e24;--ok:#5fbf85;--warn:#d9a83f;--err:#e8695c;--crit:#ff8a7a;--accent:#8b9bf0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.55 ui-sans-serif,system-ui,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1500px;margin:0 auto;padding:28px 20px 80px}
h1{font-size:22px;margin:0 0 4px}.sub{color:var(--mut);font-size:13px;margin-bottom:24px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:22px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;cursor:pointer}
.tile:hover{border-color:var(--accent)}.tile.on{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.tile .n{font-size:24px;font-weight:600;font-variant-numeric:tabular-nums}
.tile .l{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em;margin-top:2px}
.bar{display:flex;height:8px;border-radius:4px;overflow:hidden;margin-bottom:22px;background:var(--line)}
.bar i{display:block}
.ctl{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
input[type=search]{flex:1;min-width:220px;padding:8px 11px;border:1px solid var(--line);
border-radius:8px;background:var(--card);color:var(--fg);font:inherit}
button{padding:7px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);
color:var(--fg);font:inherit;cursor:pointer}button:hover{border-color:var(--accent)}
.tblwrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{position:sticky;top:0;background:var(--card);font-size:11px;text-transform:uppercase;
letter-spacing:.04em;color:var(--mut);cursor:pointer;white-space:nowrap}
td.p{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;word-break:break-all;max-width:520px}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.pill{display:inline-block;padding:1px 7px;border-radius:999px;font-size:11px;font-weight:600;white-space:nowrap}
.s0{background:color-mix(in srgb,var(--ok) 18%,transparent);color:var(--ok)}
.s1{background:color-mix(in srgb,var(--warn) 20%,transparent);color:var(--warn)}
.s2{background:color-mix(in srgb,var(--err) 18%,transparent);color:var(--err)}
.s3{background:color-mix(in srgb,var(--crit) 22%,transparent);color:var(--crit)}
.note{color:var(--mut);font-size:12px;max-width:420px}
.legend{margin-top:26px;font-size:12.5px;color:var(--mut)}
.legend b{color:var(--fg)}.legend li{margin-bottom:3px}
.more{text-align:center;padding:14px}
</style></head><body><div class="wrap">
<h1>mxfguard — звіт переносу даних</h1>
<div class="sub">__SUB__</div>
<div class="bar" id="bar"></div>
<div class="tiles" id="tiles"></div>
<div class="ctl">
  <input type="search" id="q" placeholder="фільтр за шляхом, статусом або приміткою…">
  <button id="clear">Скинути фільтри</button>
  <button id="csv">Експорт видимого в CSV</button>
</div>
<div class="tblwrap"><table id="t"><thead><tr>
<th data-k="rel">Шлях</th><th data-k="size" class="num">Розмір</th>
<th data-k="status">Контент</th><th data-k="transfer">Перенос</th>
<th data-k="ent_head" class="num">Ент. голови</th><th data-k="ent_mid" class="num">Ент. тіла</th>
<th data-k="struct">Структура</th><th data-k="decode">Декод</th>
<th data-k="notes">Примітка</th></tr></thead><tbody id="tb"></tbody></table>
<div class="more" id="more"></div></div>
<div class="legend"><b>Що означають статуси</b><ul id="lg"></ul></div>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);
const SEV=D.severity, HINT=D.hints, R=D.rows;
const cls=s=>{const v=SEV[s]||0;return v===0?'s0':v<50?'s1':v<85?'s2':'s3'};
const fmt=b=>{b=+b||0;const u=['B','KB','MB','GB','TB'];let i=0;while(b>=1024&&i<4){b/=1024;i++}
  return b.toFixed(i?1:0)+' '+u[i]};
let filter=null,q='',limit=500,sortK='__sev',sortD=-1;
const counts={};R.forEach(r=>{const k=r.worst;counts[k]=(counts[k]||0)+1});
const order=Object.keys(counts).sort((a,b)=>(SEV[b]||0)-(SEV[a]||0));
document.getElementById('bar').innerHTML=order.map(k=>
  `<i class="${cls(k)}" style="width:${counts[k]/R.length*100}%;background:currentColor" title="${k}: ${counts[k]}"></i>`).join('');
document.getElementById('tiles').innerHTML=
  `<div class="tile" data-f=""><div class="n">${R.length}</div><div class="l">усього файлів</div></div>`+
  order.map(k=>`<div class="tile" data-f="${k}"><div class="n ${cls(k)}" style="background:none;padding:0">${counts[k]}</div><div class="l">${k}</div></div>`).join('');
document.getElementById('lg').innerHTML=order.map(k=>`<li><b>${k}</b> — ${HINT[k]||''}</li>`).join('');
function view(){let v=R;if(filter)v=v.filter(r=>r.worst===filter);
 if(q){const s=q.toLowerCase();v=v.filter(r=>(r.rel+' '+r.status+' '+r.transfer+' '+r.notes).toLowerCase().includes(s))}
 v=v.slice().sort((a,b)=>{const x=sortK==='__sev'?(SEV[a.worst]||0):a[sortK],y=sortK==='__sev'?(SEV[b.worst]||0):b[sortK];
  if(x===y)return a.rel<b.rel?-1:1;return (x>y?1:-1)*sortD});return v}
function render(){const v=view();document.getElementById('tb').innerHTML=v.slice(0,limit).map(r=>
 `<tr><td class="p">${r.rel}</td><td class="num">${fmt(r.size)}</td>
  <td><span class="pill ${cls(r.status)}">${r.status}</span></td>
  <td>${r.transfer?`<span class="pill ${cls(r.transfer)}">${r.transfer}</span>`:''}</td>
  <td class="num">${r.ent_head??''}</td><td class="num">${r.ent_mid??''}</td>
  <td>${r.struct||''}</td><td>${r.decode||''}</td><td class="note">${r.notes||''}</td></tr>`).join('');
 document.getElementById('more').textContent=v.length>limit?`показано ${limit} з ${v.length} — натисніть, щоб показати ще`:`${v.length} рядків`;
 document.getElementById('more').style.cursor=v.length>limit?'pointer':'default';
 document.querySelectorAll('.tile').forEach(t=>t.classList.toggle('on',t.dataset.f===(filter||'')))}
document.getElementById('tiles').onclick=e=>{const t=e.target.closest('.tile');if(!t)return;
 filter=t.dataset.f||null;limit=500;render()};
document.getElementById('q').oninput=e=>{q=e.target.value;limit=500;render()};
document.getElementById('clear').onclick=()=>{filter=null;q='';document.getElementById('q').value='';limit=500;render()};
document.getElementById('more').onclick=()=>{limit+=2000;render()};
document.querySelectorAll('th').forEach(th=>th.onclick=()=>{const k=th.dataset.k;
 if(sortK===k)sortD=-sortD;else{sortK=k;sortD=1}render()});
document.getElementById('csv').onclick=()=>{const v=view();
 const head=['rel','size','status','transfer','ent_head','ent_mid','struct','decode','notes'];
 const esc=s=>'"'+String(s??'').replace(/"/g,'""')+'"';
 const txt=[head.join(',')].concat(v.map(r=>head.map(h=>esc(r[h])).join(','))).join('\\n');
 const ta=document.createElement('textarea');ta.value=txt;document.body.appendChild(ta);ta.select();
 try{document.execCommand('copy');alert('CSV видимих рядків скопійовано в буфер обміну ('+v.length+' шт.)')}
 catch(e){alert('Не вдалося скопіювати')}document.body.removeChild(ta)};
render();
</script></body></html>"""


def cmd_report(a) -> int:
    scan = load_manifest(a.scan)
    comp: dict[str, dict] = {}
    if a.compare:
        with open(a.compare, "r", encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                comp[r["rel"]] = r

    rows = []
    for rel, s in scan.items():
        t = comp.get(rel, {}).get("transfer", "")
        note = s.get("notes", "")
        cn = comp.get(rel, {}).get("note", "")
        if cn:
            note = (note + " | " + cn).strip(" |")
        worst = max([s.get("status", "OK") or "OK", t or "OK"],
                    key=lambda x: max(STATUS_SEVERITY.get(x, 0),
                                      COMPARE_SEVERITY.get(x, 0)))
        rows.append({
            "rel": rel, "size": int(s.get("size") or 0),
            "status": s.get("status", ""), "transfer": t,
            "ent_head": s.get("ent_head") or None, "ent_mid": s.get("ent_mid") or None,
            "struct": s.get("struct", ""), "decode": s.get("decode", ""),
            "notes": note, "worst": worst,
        })
    # файли, яких немає на приймачі — є тільки у звірці
    for rel, c in comp.items():
        if rel not in scan and c["transfer"] in ("MISSING",):
            rows.append({"rel": rel, "size": int(c.get("src_size") or 0),
                         "status": "", "transfer": c["transfer"],
                         "ent_head": None, "ent_mid": None, "struct": "",
                         "decode": "", "notes": c.get("note", ""),
                         "worst": c["transfer"]})

    sev = {**STATUS_SEVERITY}
    for k, v in COMPARE_SEVERITY.items():
        sev[k] = max(sev.get(k, 0), v)

    payload = {"rows": rows, "severity": sev, "hints": STATUS_HINT}
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    bad = sum(1 for r in rows if sev.get(r["worst"], 0) >= 50)
    sub = (f"Джерело маніфесту: {html.escape(os.path.basename(a.scan))}"
           + (f" · звірка: {html.escape(os.path.basename(a.compare))}" if a.compare else "")
           + f" · файлів: {len(rows)} · потребують уваги: {bad}"
           + f" · сформовано {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    out = HTML_TMPL.replace("__SUB__", sub).replace("__DATA__", data)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(out)
    sys.stderr.write(f"[i] звіт -> {a.out} ({len(rows)} рядків, {bad} потребують уваги)\n")
    return 0


# ---------------------------------------------------------------------------
# 11. CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="mxfguard",
        description="Інвентаризація, верифікація і контентна валідація медіа-архіву",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"mxfguard {VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="обійти дерево і зібрати маніфест")
    s.add_argument("--root", required=True, help="корінь дерева")
    s.add_argument("--out", required=True, help="вихідний CSV-маніфест")
    s.add_argument("--checks", default="hash,magic,entropy",
                   help="hash,magic,entropy,struct,decode (через кому)")
    s.add_argument("--hash", default="xxh128",
                   choices=["xxh128", "xxh64", "blake2b", "sha256", "md5"],
                   help="алгоритм хешу (xxh128 -> blake2b, якщо немає модуля xxhash)")
    s.add_argument("--jobs", type=int, default=max(2, (os.cpu_count() or 4) // 2),
                   help="потоків на хешування/читання")
    s.add_argument("--decode-jobs", type=int, default=max(1, (os.cpu_count() or 4) // 4),
                   help="паралельних ffmpeg-декодів")
    s.add_argument("--decode-edges", type=int, default=0, metavar="SEC",
                   help="декодувати лише перші й останні SEC секунд замість усього файлу")
    s.add_argument("--decode-timeout", type=int, default=3600)
    s.add_argument("--probe-timeout", type=int, default=120)
    s.add_argument("--ransomware", action="store_true",
                   help="режим розбору наслідків шифрувальника: salvage-скан MXF, "
                        "детект записок і дописаних розширень")
    s.add_argument("--salvage-window", type=int, default=256 * 1024 * 1024,
                   help="скільки байтів голови сканувати в пошуках цілого MXF Partition Pack")
    s.add_argument("--entropy-threshold", type=float, default=7.95)
    s.add_argument("--entropy-delta", type=float, default=0.15,
                   help="наскільки тіло має бути 'спокійнішим' за голову, щоб вважати "
                        "це частковим шифруванням")
    s.add_argument("--exclude", action="append", default=[],
                   help="glob-патерн виключення (можна кілька разів)")
    s.add_argument("--no-default-exclude", action="store_true",
                   help=f"не виключати системне сміття за замовчуванням "
                        f"({', '.join(DEFAULT_EXCLUDE[:4])}…)")
    s.add_argument("--include-ext", default="",
                   help="обробляти лише ці розширення, через кому")
    s.add_argument("--min-size", type=int, default=0)
    s.add_argument("--resume", action="store_true",
                   help="дописати в наявний CSV, пропустивши вже оброблені шляхи")
    s.add_argument("--progress-every", type=int, default=25)
    s.set_defaults(func=cmd_scan)

    c = sub.add_parser("compare", help="звірити маніфест джерела з маніфестом приймача")
    c.add_argument("--src", required=True)
    c.add_argument("--dst", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--check-mtime", action="store_true")
    c.set_defaults(func=cmd_compare)

    r = sub.add_parser("report", help="зібрати HTML-звіт")
    r.add_argument("--scan", required=True, help="CSV-маніфест приймача")
    r.add_argument("--compare", default="", help="CSV звірки (опційно)")
    r.add_argument("--out", required=True)
    r.set_defaults(func=cmd_report)

    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.stderr.write("\n[!] перервано користувачем\n")
        sys.exit(130)
