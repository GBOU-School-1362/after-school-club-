#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["odfpy"]
# ///
"""
Готовит таблицу к коммиту в публичный репозиторий.

    uv run sanitize.py "~/Рабочий стол/Внебюджет 26-27.ods"

Оставляет только листы с кружками, вырезает служебные: финансовый свод,
занятость залов и прочее, что перечислено в config.json -> sheets.ignore.
Остальное содержимое не трогает — работа идёт на уровне XML, а не через
пересборку, поэтому форматирование и даты остаются как были.

Результат: data/catalog.ods — его и коммитим. Исходник в git не попадает.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from odf.opendocument import load
from odf.table import Table

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "catalog.ods"


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("Укажите путь к исходной таблице:\n  uv run sanitize.py '~/Загрузки/Внебюджет 26-27.ods'")

    src = Path(sys.argv[1]).expanduser()
    if not src.exists():
        sys.exit(f"Файл не найден: {src}")

    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    keep = set(cfg["sheets"]["courses"])

    doc = load(str(src))
    tables = doc.spreadsheet.getElementsByType(Table)
    if not tables:
        sys.exit("В файле нет листов — проверьте, что это .ods")

    kept, removed = [], []
    for table in list(tables):
        name = table.getAttribute("name")
        if name in keep:
            kept.append(name)
        else:
            table.parentNode.removeChild(table)
            removed.append(name)

    missing = keep - set(kept)
    if missing:
        sys.exit(f"В файле нет ожидаемых листов: {', '.join(sorted(missing))}\n"
                 f"Проверьте config.json -> sheets.courses")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        shutil.copy2(OUT, OUT.with_suffix(".ods.bak"))
    doc.save(str(OUT))

    print(f"Оставлено ({len(kept)}): {', '.join(kept)}")
    print(f"Вырезано  ({len(removed)}): {', '.join(removed) or '—'}")
    print(f"\n{OUT} — этот файл коммитим.")
    print(f"Размер: {src.stat().st_size // 1024} КБ -> {OUT.stat().st_size // 1024} КБ")
    print("\nДальше:  uv run build_catalog.py data/catalog.ods --strict")


if __name__ == "__main__":
    main()
