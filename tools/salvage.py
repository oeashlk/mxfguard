#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
salvage.py — витягнути відеоесенцію з MXF, у якого шифрувальник
знищив голову файлу.

Працює у парі з `mxfguard.py scan --ransomware`: той знаходить зсув
першого неушкодженого MXF Partition Pack і пише його у стовпець
salvage_offset. Цей скрипт бере файл із цього зсуву і намагається
демультиплексувати те, що лишилось.

Чому просто "обрізати і відкрити" не працює
-------------------------------------------
Заголовок MXF несе описувачі есенції: роздільність, edit rate,
розкладку доріжок, таймкод. Він знищений разом із першими мегабайтами.
Хвіст містить самі кадри, але контейнер уже не самоописний — ffmpeg
має бути примушений читати потік як сирий, із явно заданим кодеком.

Що з цього виходить і чого не виходить
--------------------------------------
Виходить: картинка і рух, тобто сам матеріал.
Не виходить: оригінальний таймкод, розкладка аудіодоріжок, метадані
MXF. Звук у MXF лежить окремими KLV-пакетами і сирим демуксером
не витягується — його рятують окремо і рідко успішно.

Використання
------------
  python salvage.py --file "Q:\\quarantine\\news.mxf" --offset 7515648
  python salvage.py --csv C:\\mxfguard-audit\\HOST\\quarantine.csv --root Q:\\quarantine
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys

CHUNK = 8 * 1024 * 1024

# Кандидати сирих демуксерів. Порядок має значення: той, що дає
# найбільше пакетів, і виграє.
DEMUXERS = [
    ("mpegvideo", "m2v", "MPEG-2 (XDCAM, IMX, D-10, більшість мовного MXF)"),
    ("h264", "h264", "AVC-Intra / H.264"),
    ("hevc", "hevc", "HEVC"),
    ("dnxhd", "dnxhd", "DNxHD / DNxHR (Avid)"),
    ("mxf", "mxf", "MXF, якщо вцілів пізніший самоописний Partition"),
]


def _use_bundled_tools() -> None:
    """
    Додати комплектний tools/bin у PATH, якщо він поруч зі скриптом.
    Потрібне для запуску напряму, повз .cmd-обгортку.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    up = os.path.dirname(here)
    for cand in (os.path.join(here, "bin"),
                 os.path.join(here, "tools", "bin"),
                 os.path.join(up, "tools", "bin")):
        if os.path.isdir(cand):
            os.environ["PATH"] = cand + os.pathsep + os.environ.get("PATH", "")
            return


_use_bundled_tools()


def need(tool: str) -> None:
    if shutil.which(tool) is None:
        sys.exit(f"[x] {tool} не знайдено ні в комплекті (tools/bin), "
                 f"ні в PATH.\n    Постав ffmpeg: winget install Gyan.FFmpeg")


def cut_tail(src: str, offset: int, dst: str) -> int:
    """Скопіювати все від offset до кінця. Джерело не змінюється."""
    total = 0
    with open(src, "rb", buffering=0) as f, open(dst, "wb", buffering=0) as o:
        f.seek(offset)
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            o.write(b)
            total += len(b)
    return total


def count_frames(path: str, fmt: str, timeout: int = 300) -> tuple[int, int, str]:
    """
    -> (пакетів, площа кадру, опис)

    Площа кадру — головний критерій відбору, а не кількість пакетів.
    Сирі демуксери h264/hevc «знаходять» тисячі фальшивих пакетів
    у випадковому смітті, але роздільність у них виходить 0x0.
    Реальна есенція дає ненульові width/height.
    """
    cmd = ["ffprobe", "-v", "error", "-f", fmt, "-count_packets",
           "-select_streams", "v:0",
           "-show_entries", "stream=nb_read_packets,width,height,codec_name",
           "-of", "default=nw=1", "-i", path]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 0, 0, "timeout"
    info = {}
    for line in p.stdout.decode("utf-8", "replace").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()

    def num(key: str) -> int:
        try:
            return int(info.get(key, "0") or 0)
        except ValueError:
            return 0

    n, w, h = num("nb_read_packets"), num("width"), num("height")
    codec = info.get("codec_name", "?")
    return n, w * h, f"{codec} {w}x{h}"


def salvage_one(src: str, offset: int, outdir: str, keep_bin: bool) -> int:
    base = os.path.splitext(os.path.basename(src))[0]
    os.makedirs(outdir, exist_ok=True)
    raw = os.path.join(outdir, base + ".tail.bin")

    size = os.path.getsize(src)
    if offset >= size:
        print(f"[x] зсув {offset} за межами файлу ({size} байт)")
        return 1

    print(f"[i] {os.path.basename(src)}")
    print(f"    розмір {size/1048576:.1f} МБ, зсув {offset/1048576:.1f} МБ, "
          f"рятуємо {(size-offset)/1048576:.1f} МБ")

    n = cut_tail(src, offset, raw)
    print(f"[i] хвіст вирізано -> {raw} ({n/1048576:.1f} МБ)")

    print("[i] підбираю демуксер:")
    best = None
    for fmt, ext, human in DEMUXERS:
        cnt, area, desc = count_frames(raw, fmt)
        ok = cnt > 0 and area > 0
        mark = "->" if ok else "  "
        print(f"   {mark} {fmt:<10}{cnt:>8} пакетів  {desc:<20} {human}")
        # відбір за роздільністю; кількість пакетів — лише тайбрейк
        if ok and (best is None or (area, cnt) > (best[1], best[0])):
            best = (cnt, area, fmt, ext, desc)

    if best is None:
        print("[x] жоден демуксер не дав кадрів із валідною роздільністю.")
        print("    Ймовірно, зсув хибний або кодек поза списком.")
        print(f"    Спробуй вручну: ffmpeg -f <формат> -i {raw}")
        return 1

    cnt, area, fmt, ext, desc = best
    out = os.path.join(outdir, f"{base}.salvaged.{ext}")
    print(f"[i] найкраще: {fmt} ({cnt} пакетів, {desc})")

    p = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", fmt,
                        "-i", raw, "-c", "copy", "-y", out],
                       capture_output=True)
    if p.returncode != 0 or not os.path.exists(out):
        err = p.stderr.decode("utf-8", "replace").strip().splitlines()
        print("[x] ffmpeg:", err[-1] if err else f"exit {p.returncode}")
        return 1

    # контрольний кадр, щоб очима переконатися, що це справді матеріал
    shot = os.path.join(outdir, f"{base}.preview.png")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", fmt, "-i", raw,
                    "-frames:v", "1", "-y", shot], capture_output=True)

    if not keep_bin:
        try:
            os.remove(raw)
        except OSError:
            pass

    print(f"[OK] {out} ({os.path.getsize(out)/1048576:.1f} МБ)")
    if os.path.exists(shot):
        print(f"[OK] контрольний кадр: {shot} — ВІДКРИЙ І ПОДИВИСЬ ОЧИМА")
    print("     Таймкод і аудіо втрачені разом із заголовком MXF.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="salvage",
        description="Витягнути есенцію з MXF із зашифрованою головою")
    p.add_argument("--file", help="один файл")
    p.add_argument("--offset", type=int, help="зсув зі стовпця salvage_offset")
    p.add_argument("--csv", help="маніфест mxfguard: обробити всі зі зсувом")
    p.add_argument("--root", help="корінь, відносно якого шляхи в CSV")
    p.add_argument("--outdir", default="salvaged", help="куди складати результат")
    p.add_argument("--keep-bin", action="store_true",
                   help="не видаляти проміжний .tail.bin")
    a = p.parse_args(argv)

    need("ffmpeg")
    need("ffprobe")

    if a.file:
        if a.offset is None:
            p.error("--file вимагає --offset")
        return salvage_one(a.file, a.offset, a.outdir, a.keep_bin)

    if not a.csv:
        p.error("вкажи або --file з --offset, або --csv")
    if not a.root:
        p.error("--csv вимагає --root")

    todo = []
    with open(a.csv, "r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            off = (r.get("salvage_offset") or "").strip()
            if off and off not in ("-1", "None"):
                try:
                    todo.append((r["rel"], int(off)))
                except ValueError:
                    continue

    if not todo:
        print("[i] у маніфесті немає рядків зі salvage_offset.")
        print("    Скан робився з --ransomware? Без нього зсув не рахується.")
        return 0

    print(f"[i] знайдено {len(todo)} файлів із придатним зсувом\n")
    bad = 0
    for rel, off in todo:
        full = os.path.join(a.root, rel.replace("/", os.sep))
        if not os.path.exists(full):
            print(f"[!] немає на диску: {rel}")
            bad += 1
            continue
        sub = os.path.join(a.outdir, os.path.dirname(rel.replace("/", os.sep)))
        bad += salvage_one(full, off, sub, a.keep_bin)
        print()
    print(f"[i] готово. невдалих: {bad} з {len(todo)}")
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.stderr.write("\n[!] перервано\n")
        sys.exit(130)
