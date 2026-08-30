#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
selftest.py — самоперевірка mxfguard на цій конкретній машині.

Створює тимчасове дерево з файлами, кожен з яких зіпсований наперед
відомим способом, проганяє повний цикл scan/compare/report і звіряє,
що інструмент виставив саме ті статуси, які мав виставити.

Навіщо це потрібно на місці
---------------------------
Перед тим як довіряти звіту на десятки терабайт, треба побачити, що
на цій машині, з цим Python і цим ffmpeg інструмент справді ловить
поломки, а не малює суцільні OK. Прогін займає до хвилини.

  python selftest.py            # повний
  python selftest.py --keep     # не прибирати дерево після прогону
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MXFGUARD = os.path.join(os.path.dirname(HERE), "mxfguard.py")

HAVE_FFMPEG = shutil.which("ffmpeg") is not None
MXF_HDR = bytes.fromhex("060e2b34020501010d01020101020400")


def run(args: list[str]) -> tuple[int, str]:
    p = subprocess.run([sys.executable, MXFGUARD] + args,
                       capture_output=True)
    return p.returncode, p.stderr.decode("utf-8", "replace")


def make_mxf(path: str, seconds: int = 40) -> bool:
    """Справжній MXF через ffmpeg. -> чи вдалося."""
    if not HAVE_FFMPEG:
        return False
    cmd = ["ffmpeg", "-v", "error", "-nostdin",
           "-f", "lavfi", "-i", f"testsrc=size=720x576:rate=25:duration={seconds}",
           "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}:sample_rate=48000",
           "-c:v", "mpeg2video", "-b:v", "8M",
           "-c:a", "pcm_s16le", "-ar", "48000", "-y", path]
    p = subprocess.run(cmd, capture_output=True)
    return p.returncode == 0 and os.path.getsize(path) > 0


def build_tree(root: str) -> dict[str, str]:
    """Створює дерево. -> {відносний шлях: очікуваний статус}"""
    rnd = random.Random(20260830)
    media = os.path.join(root, "media")
    docs = os.path.join(root, "docs")
    os.makedirs(media, exist_ok=True)
    os.makedirs(docs, exist_ok=True)
    expect: dict[str, str] = {}

    def rand_bytes(n: int) -> bytes:
        return bytes(rnd.getrandbits(8) for _ in range(n))

    # --- цілий MXF ---
    ok_mxf = os.path.join(media, "master_ok.mxf")
    real = make_mxf(ok_mxf)
    if real:
        # Увага: у дереві-приймачі цей файл буде побитий посеред тіла
        # (див. build_dst), тож очікуваний статус саме там — DECODE_ERROR.
        # Це і є доказ, що повний декод ловить биті байти всередині.
        expect["media/master_ok.mxf"] = "DECODE_ERROR"

        # --- обрізаний посередині ---
        trunc = os.path.join(media, "studio_truncated.mxf")
        shutil.copyfile(ok_mxf, trunc)
        n = os.path.getsize(trunc)
        with open(trunc, "r+b") as f:
            f.truncate(int(n * 0.55))
        # без ffmpeg декоду це STRUCT_FAIL або DECODE_ERROR
        expect["media/studio_truncated.mxf"] = "DECODE_ERROR|STRUCT_FAIL"

        # --- частково зашифрований: голова мертва, тіло живе ---
        # Шифруємо 30% файлу. Вибірка «тіла» береться рівно на середині,
        # тож 30% гарантовано лишають її чистою -> PARTIAL_ENCRYPTED.
        part = os.path.join(media, "news_partial_enc.mxf")
        shutil.copyfile(ok_mxf, part)
        size = os.path.getsize(part)
        with open(part, "r+b") as f:
            f.write(rand_bytes(int(size * 0.30)))
        expect["media/news_partial_enc.mxf"] = "PARTIAL_ENCRYPTED"

        # --- шифрування зайшло за середину файлу ---
        # Окремий випадок, який адміни плутають: якщо шифрувальник
        # дістав більше половини файлу, вибірка «тіла» теж потрапляє
        # в шифр і статус буде ENCRYPTED, а не PARTIAL_ENCRYPTED.
        # Але salvage_offset усе одно рахується і хвіст усе одно
        # рятується — саме тому зсув треба дивитись і в ENCRYPTED.
        deep = os.path.join(media, "sport_deep_enc.mxf")
        shutil.copyfile(ok_mxf, deep)
        size = os.path.getsize(deep)
        with open(deep, "r+b") as f:
            f.write(rand_bytes(int(size * 0.70)))
        expect["media/sport_deep_enc.mxf"] = "ENCRYPTED"
    else:
        # без ffmpeg робимо синтетичний MXF-подібний файл
        with open(ok_mxf, "wb") as f:
            f.write(MXF_HDR + b"\x00" * (5 * 1024 * 1024))
        expect["media/master_ok.mxf"] = "OK"

    # --- зашифрований повністю ---
    with open(os.path.join(media, "promo_full_enc.mxf"), "wb") as f:
        f.write(rand_bytes(4 * 1024 * 1024))
    expect["media/promo_full_enc.mxf"] = "ENCRYPTED"

    # --- дописане розширення шифрувальника ---
    with open(os.path.join(media, "archive_2024.mxf.LOCKED"), "wb") as f:
        f.write(rand_bytes(4 * 1024 * 1024))
    expect["media/archive_2024.mxf.LOCKED"] = "ENCRYPTED"

    # --- записка шифрувальника ---
    with open(os.path.join(root, "HOW_TO_DECRYPT_FILES.txt"), "w",
              encoding="utf-8") as f:
        f.write("All your files have been encrypted.\n")
    expect["HOW_TO_DECRYPT_FILES.txt"] = "RANSOM_NAME"

    # --- підмінений вміст: .jpg, а всередині текст ---
    with open(os.path.join(docs, "logo.jpg"), "w", encoding="utf-8") as f:
        f.write("Це звичайний текст, а не картинка.\n" * 700)
    expect["docs/logo.jpg"] = "BAD_MAGIC"

    # --- порожній файл ---
    open(os.path.join(docs, "empty.wav"), "wb").close()
    expect["docs/empty.wav"] = "EMPTY_FILE"

    # --- нормальний текст ---
    with open(os.path.join(docs, "edit_list.txt"), "w", encoding="utf-8") as f:
        f.write("A0001 V C 00:00:01:00 00:00:05:00\n" * 40)
    expect["docs/edit_list.txt"] = "OK"

    # --- файл, який зникне при копіюванні ---
    with open(os.path.join(docs, "tone.wav"), "wb") as f:
        f.write(b"RIFF" + b"\x00" * 200000)
    expect["docs/tone.wav"] = "OK"

    return expect


def build_dst(src: str, dst: str) -> None:
    """Копія джерела з двома дефектами переносу."""
    shutil.copytree(src, dst)
    # 1. файл не доїхав
    os.remove(os.path.join(dst, "docs", "tone.wav"))
    # 2. биті байти посеред файлу: розмір той самий, вміст інший
    p = os.path.join(dst, "media", "master_ok.mxf")
    if os.path.getsize(p) > 700_000:
        with open(p, "r+b") as f:
            f.seek(600_000)
            b = f.read(4096)
            f.seek(600_000)
            f.write(bytes(x ^ 0xFF for x in b))


def load(path: str) -> dict[str, dict]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return {r["rel"]: r for r in csv.DictReader(f)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true",
                    help="не прибирати тимчасове дерево")
    a = ap.parse_args()

    if not os.path.exists(MXFGUARD):
        print(f"[x] не бачу {MXFGUARD}")
        return 2

    print("=" * 62)
    print("  mxfguard — самоперевірка")
    print("=" * 62)
    print(f"  Python : {sys.version.split()[0]}")
    print(f"  ffmpeg : {'є' if HAVE_FFMPEG else 'НЕМАЄ — decode/struct пропущено'}")
    try:
        import xxhash  # noqa: F401
        print("  xxhash : є")
    except ImportError:
        print("  xxhash : немає, працюю на blake2b")
    print()

    work = tempfile.mkdtemp(prefix="mxfguard_selftest_")
    src = os.path.join(work, "src")
    dst = os.path.join(work, "dst")
    audit = os.path.join(work, "audit")
    os.makedirs(audit)

    fails: list[str] = []
    try:
        print("[1/5] будую дерево з наперед відомими поломками...")
        expect = build_tree(src)
        build_dst(src, dst)
        print(f"      файлів: {len(expect)}")

        print("[2/5] маніфест джерела...")
        rc, _ = run(["scan", "--root", src, "--out", os.path.join(audit, "src.csv"),
                     "--checks", "hash,magic,entropy", "--hash", "sha256", "--jobs", "4"])
        if rc != 0:
            fails.append(f"scan джерела повернув {rc}")

        print("[3/5] повний скан приймача (magic/ентропія/структура/декод)...")
        checks = "hash,magic,entropy,struct,decode" if HAVE_FFMPEG else "hash,magic,entropy"
        rc, _ = run(["scan", "--root", dst, "--out", os.path.join(audit, "dst.csv"),
                     "--checks", checks, "--ransomware", "--hash", "sha256",
                     "--jobs", "4", "--decode-jobs", "2"])
        if rc != 0:
            fails.append(f"scan приймача повернув {rc}")

        print("[4/5] звірка джерела з приймачем...")
        rc, _ = run(["compare", "--src", os.path.join(audit, "src.csv"),
                     "--dst", os.path.join(audit, "dst.csv"),
                     "--out", os.path.join(audit, "diff.csv")])
        if rc != 1:
            fails.append(f"compare мав повернути 1 (є розбіжності), повернув {rc}")

        print("[5/5] звіт...")
        rc, _ = run(["report", "--scan", os.path.join(audit, "dst.csv"),
                     "--compare", os.path.join(audit, "diff.csv"),
                     "--out", os.path.join(audit, "report.html")])
        if rc != 0:
            fails.append(f"report повернув {rc}")

        # ---------- звірка контентних статусів ----------
        print()
        print("-" * 62)
        print("  Контент: чого чекали / що отримали")
        print("-" * 62)
        got = load(os.path.join(audit, "dst.csv"))
        for rel, want in sorted(expect.items()):
            if rel == "docs/tone.wav":
                continue  # його на приймачі немає навмисне
            row = got.get(rel)
            if row is None:
                print(f"  [X] {rel:<34} файлу немає в маніфесті")
                fails.append(f"{rel}: немає в маніфесті")
                continue
            actual = row["status"]
            variants = want.split("|")
            if not HAVE_FFMPEG and want.startswith("DECODE_ERROR"):
                variants += ["OK", "STRUCT_FAIL"]  # без ffmpeg це не ловиться
            ok = actual in variants
            mark = "[OK]" if ok else "[X] "
            print(f"  {mark} {rel:<34} {want:<26} -> {actual}")
            if not ok:
                fails.append(f"{rel}: чекав {want}, отримав {actual}")

        # ---------- salvage ----------
        # Зсув має рахуватися і для PARTIAL_ENCRYPTED, і для ENCRYPTED,
        # якщо шифрування зайшло за середину файлу.
        if HAVE_FFMPEG:
            for rel in ("media/news_partial_enc.mxf", "media/sport_deep_enc.mxf"):
                row = got.get(rel)
                if row is None:
                    continue
                off = (row.get("salvage_offset") or "").strip()
                if off and off != "-1":
                    print(f"  [OK] salvage_offset {rel:<30} "
                          f"{int(off)/1048576:6.1f} МБ — хвіст рятується")
                else:
                    print(f"  [X]  salvage_offset {rel:<30} не порахувався")
                    fails.append(f"salvage_offset порожній: {rel}")

        # ---------- звірка переносу ----------
        print()
        print("-" * 62)
        print("  Перенос: чого чекали / що отримали")
        print("-" * 62)
        diff = {}
        with open(os.path.join(audit, "diff.csv"), "r",
                  encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                diff[r["rel"]] = r["transfer"]

        for rel, want in (("docs/tone.wav", "MISSING"),
                          ("media/master_ok.mxf", "HASH_MISMATCH")):
            actual = diff.get(rel, "—")
            ok = actual == want
            print(f"  {'[OK]' if ok else '[X] '} {rel:<34} {want:<26} -> {actual}")
            if not ok:
                fails.append(f"перенос {rel}: чекав {want}, отримав {actual}")

        print()
        print("=" * 62)
        if fails:
            print(f"  ПРОВАЛЕНО: {len(fails)}")
            for x in fails:
                print(f"    - {x}")
            print()
            print("  Не запускай інструмент на бойових даних, поки це не")
            print("  з'ясовано. Найчастіша причина — інша версія ffmpeg.")
        else:
            print("  УСІ ПЕРЕВІРКИ ПРОЙДЕНО")
            print()
            print("  Інструмент на цій машині ловить: обрив файлу, повне і")
            print("  часткове шифрування, підміну вмісту, записки, порожні")
            print("  файли, зниклі при копіюванні та биті байти в середині.")
        print("=" * 62)

        if a.keep:
            print(f"\n  Дерево лишилось: {work}")
        return 1 if fails else 0
    finally:
        if not a.keep:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[!] перервано")
        sys.exit(130)
