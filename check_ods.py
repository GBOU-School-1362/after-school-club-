#!/usr/bin/env python3
"""
Проверяет, что таблица очищена от служебных листов.

    python3 check_ods.py data/catalog.ods

Только стандартная библиотека — чтобы работать в git-хуке без окружения.
Белый список берётся из config.json, поэтому новый служебный лист тоже
будет пойман, а не только известные СВОД и «Занятость залов».

Код возврата: 0 — чисто, 1 — есть лишние листы.
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent
NAME_RE = re.compile(rb'table:name="([^"]*)"')


def sheets(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as z:
        content = z.read("content.xml")
    seen, out = set(), []
    for raw in NAME_RE.findall(content):
        name = raw.decode("utf-8")
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print("Укажите путь к .ods", file=sys.stderr)
        return 2

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Файл не найден: {path}", file=sys.stderr)
        return 2

    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    allowed = set(cfg["sheets"]["courses"])

    found = sheets(path)
    extra = [s for s in found if s not in allowed]

    if extra:
        print(f"В {path} остались служебные листы: {', '.join(extra)}")
        print("Публиковать такой файл нельзя — там внутренние данные.")
        print(f"Запустите:  uv run sanitize.py <исходник>")
        return 1

    print(f"{path}: чисто ({', '.join(found)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
