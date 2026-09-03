#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "odfpy"]
# ///
"""
Собирает courses.json из рабочей таблицы школы.

    uv run build_catalog.py data/Внебюджет_26-27.ods

Ключи:
    --strict     падать при нарушении порогов из config.json (режим CI)
    --out DIR    куда писать (по умолчанию текущая папка)

На выходе:
    courses.json   данные для сайта
    report.txt     список замечаний к исходной таблице

Что чинится по дороге — см. docs/DATA.md.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

# ------------------------------------------------------------------ константы

AREAS = {
    "естественнонаучная": "Естественно-научная",
    "естественнонаучнаянаправленность": "Естественно-научная",
    "естественонаучная": "Естественно-научная",
    "естественонаучнаянаправленность": "Естественно-научная",
    "социальногуманитарная": "Социально-гуманитарная",
    "социальногуманитарнаянаправленность": "Социально-гуманитарная",
    "социальногумонитарная": "Социально-гуманитарная",
    "физкультурноспортивная": "Физкультурно-спортивная",
    "физкультурноспортивнаянаправленность": "Физкультурно-спортивная",
    "художественная": "Художественная",
    "художественнаянаправленность": "Художественная",
    "техническая": "Техническая",
    "техническаянаправленность": "Техническая",
    "туристскокраеведческая": "Туристско-краеведческая",
    "туристскокраеведческаянаправленность": "Туристско-краеведческая",
    "присмотриуход": "Присмотр и уход",
}

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_BY_HEADER = {"пн": "mon", "вт": "tue", "ср": "wed",
                 "чт": "thu", "пт": "fri", "сб": "sat", "вс": "sun"}

MOS_CARD = "https://www.mos.ru/pgu2/activity/card/{}"
TIME_RE = re.compile(r"(\d{1,2})[:.,](\d{2})\s*[-–—]\s*(\d{1,2})[:.,](\d{2})")
PHONE_RE = re.compile(r"[+\d][\d\s\-()]{9,}")

problems: list[str] = []


def note(sheet: str, row: int, text: str) -> None:
    problems.append(f"{sheet}, строка {row + 1}: {text}")


# -------------------------------------------------------------- нормализация

def key(header) -> str:
    """'Стоимость 25-26' и 'Стоимость25-26' дают один ключ."""
    return re.sub(r"\s+", "", str(header)).lower()


def clean_area(value, sheet: str, row: int) -> str:
    raw = re.sub(r"\s+", " ", str(value or "")).strip()
    k = re.sub(r"[\s\-]+", "", raw).lower()
    if k in AREAS:
        return AREAS[k]
    if raw:
        note(sheet, row, f"неизвестная направленность {raw!r} — оставлена как есть")
        return raw
    note(sheet, row, "направленность не указана")
    return "Без направленности"


def clean_title(value, prefixes: list[str]) -> tuple[str, str | None]:
    text = re.sub(r"\s+", " ", str(value or "")).strip().strip('"')
    for prefix in prefixes:
        if text.startswith(prefix):
            return text[len(prefix):].strip(), prefix.strip()
    return text, None


def clean_age(value, sheet: str, row: int) -> tuple[int | None, int | None]:
    """
    '6-8' было съедено автоформатом и стало датой 2026-08-06.
    Разбираем обратно: день — нижняя граница, месяц — верхняя.
    Строками уцелели только диапазоны с числом больше 12.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        note(sheet, row, "возраст не указан")
        return None, None
    if isinstance(value, pd.Timestamp):
        low, high = value.day, value.month
        if low > high:
            note(sheet, row, f"возраст из даты перевёрнут ({low}-{high}), переставлен")
            low, high = high, low
        return low, high
    nums = [int(n) for n in re.findall(r"\d+", str(value))]
    if len(nums) >= 2:
        return min(nums[:2]), max(nums[:2])
    if len(nums) == 1:
        return nums[0], nums[0]
    note(sheet, row, f"не разобран возраст {str(value)!r}")
    return None, None


def clean_slots(value, sheet: str, row: int, day: str) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    text = str(value).strip()
    found = TIME_RE.findall(text)
    if not found:
        note(sheet, row, f"{day}: не разобрано время {text!r}")
        return []
    return [f"{int(a):02d}:{b}–{int(c):02d}:{d}" for a, b, c, d in found]


def as_int(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return int(float(str(value).replace(",", ".").split()[0]))
    except (ValueError, IndexError):
        return None


# ------------------------------------------------------------------- разбор

def read_sheet(raw: pd.DataFrame, sheet: str, cfg: dict) -> list[dict]:
    header = {key(v): i for i, v in enumerate(raw.iloc[0]) if pd.notna(v)}
    day_cols = {i: DAY_BY_HEADER[str(v).strip().lower()]
                for i, v in enumerate(raw.iloc[1])
                if pd.notna(v) and str(v).strip().lower() in DAY_BY_HEADER}

    if not day_cols:
        problems.append(f"Лист {sheet}: не найдена шапка расписания")

    def col(row, *names, default=None):
        for name in names:
            i = header.get(key(name))
            if i is not None and i in row.index and pd.notna(row[i]):
                return row[i]
        return default

    buildings = cfg["buildings"]
    no_enroll = [s.lower() for s in cfg["noEnrollment"]]
    out = []

    for idx, row in raw.iloc[2:].iterrows():
        title, club = clean_title(col(row, "Название объединения"), cfg["gluedPrefixes"])
        if not title:
            continue

        code = as_int(col(row, "Код на mos.ru"))
        building = str(col(row, "Адрес здания", default=sheet)).strip()
        if building not in buildings:
            note(sheet, idx, f"здание {building!r} отсутствует в config.json")
        info = buildings.get(building, {})

        schedule = {}
        for i, day in day_cols.items():
            slots = clean_slots(row.get(i), sheet, idx, day)
            if slots:
                schedule[day] = slots
        if not schedule:
            note(sheet, idx, f"{title!r}: нет расписания")

        teacher = str(col(row, "Фамилия И.О.педагога", default="")).strip()
        if PHONE_RE.search(teacher):
            note(sheet, idx, f"{title!r}: в поле педагога был телефон — вырезан")
            teacher = PHONE_RE.sub("", teacher).strip(" ,;—-")

        low, high = clean_age(col(row, "Возраст детей", "Возраст детей3-7"), sheet, idx)

        if any(marker in title.lower() for marker in no_enroll):
            enrollment = "school"
        elif code:
            enrollment = "mos"
        else:
            enrollment = "none"
            note(sheet, idx, f"{title!r}: нет кода mos.ru")

        start = col(row, "Дата начала")
        out.append({
            "id": f"{sheet}-{idx + 1}",
            "title": title,
            "club": club,
            "area": clean_area(col(row, "Направленность"), sheet, idx),
            "teacher": teacher or None,
            "ageFrom": low,
            "ageTo": high,
            "price": as_int(col(row, "Стоимость 26-27")),
            "pricePrev": as_int(col(row, "Стоимость 25-26")),
            "priceUnit": "месяц",
            "days": [d for d in DAYS if d in schedule],
            "schedule": schedule,
            "startDate": start.strftime("%Y-%m-%d") if isinstance(start, pd.Timestamp) else None,
            "buildingCode": building,
            "building": info.get("name"),
            "address": info.get("address"),
            "kind": info.get("kind", "school"),
            "mosCode": code,
            "enrollment": enrollment,
            "signupUrl": MOS_CARD.format(code) if code and enrollment == "mos" else None,
            "source": sheet,
        })
    return out


def apply_overrides(courses: list[dict], overrides: dict) -> None:
    """Редакторские правки поверх импорта. Ключ — код mos.ru или id."""
    index = {}
    for c in courses:
        if c["mosCode"]:
            index[str(c["mosCode"])] = c
        index[c["id"]] = c

    allowed = {"description", "image", "highlight", "titleOverride"}
    for k, patch in overrides.items():
        if k.startswith("_"):
            continue
        target = index.get(k)
        if target is None:
            problems.append(f"overrides.json: ключ {k} не найден среди кружков")
            continue
        for field, value in patch.items():
            if field not in allowed:
                problems.append(f"overrides.json: поле {field!r} не разрешено (ключ {k})")
                continue
            if field == "titleOverride":
                target["title"] = value
            else:
                target[field] = value


# ------------------------------------------------------------------- проверки

def validate(courses: list[dict], cfg: dict, strict: bool) -> list[str]:
    t = cfg["thresholds"]
    fails = []
    n = len(courses)
    if n < t["minCourses"] or n > t["maxCourses"]:
        fails.append(f"кружков {n}, ожидалось {t['minCourses']}–{t['maxCourses']}")

    missing = sum(1 for c in courses if c["enrollment"] == "none")
    if n and missing / n > t["maxMissingCodeShare"]:
        fails.append(f"без кода mos.ru {missing} из {n} — выше порога "
                     f"{t['maxMissingCodeShare']:.0%}")

    stub = sorted({c["buildingCode"] for c in courses
                   if not c["address"] or "УТОЧНИТЬ" in str(c["address"])})
    if stub:
        fails.append(f"адреса не заполнены в config.json: {', '.join(stub)}")

    leaked = [c["title"] for c in courses
              if c["teacher"] and PHONE_RE.search(c["teacher"])]
    if leaked:
        fails.append(f"телефон в поле педагога: {', '.join(leaked[:3])}")

    seen = {}
    for c in courses:
        if c["mosCode"]:
            if c["mosCode"] in seen:
                fails.append(f"код {c['mosCode']} повторяется: "
                             f"{seen[c['mosCode']]} и {c['title']}")
            seen[c["mosCode"]] = c["title"]
    return fails


# --------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", nargs="?", default="data/Внебюджет_26-27.ods")
    ap.add_argument("--out", default=".")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    root = Path(__file__).parent
    cfg = json.loads((root / "config.json").read_text(encoding="utf-8"))
    ov_path = root / "overrides.json"
    overrides = json.loads(ov_path.read_text(encoding="utf-8")) if ov_path.exists() else {}

    book = pd.read_excel(args.source, engine="odf", sheet_name=None, header=None)
    known = set(cfg["sheets"]["courses"]) | set(cfg["sheets"]["ignore"])
    for extra in sorted(set(book) - known):
        problems.append(f"Новый лист {extra!r} — не обрабатывается, добавьте в config.json")

    courses: list[dict] = []
    for sheet in cfg["sheets"]["courses"]:
        if sheet not in book:
            problems.append(f"Лист {sheet} пропал из файла")
            continue
        courses.extend(read_sheet(book[sheet], sheet, cfg))

    if not courses:
        sys.exit("Не разобрано ни одной строки — проверьте структуру файла")

    apply_overrides(courses, overrides)
    fails = validate(courses, cfg, args.strict)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "courses.json").write_text(json.dumps({
        "school": cfg["school"],
        "contact": cfg["contact"],
        "updated": pd.Timestamp.today().strftime("%Y-%m-%d"),
        "sourceFile": Path(args.source).name,
        "courses": courses,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = [
        f"Разобрано кружков: {len(courses)}",
        f"  школа / сады:    {sum(1 for c in courses if c['kind'] == 'school')} / "
        f"{sum(1 for c in courses if c['kind'] == 'kindergarten')}",
        f"  запись на mos.ru:{sum(1 for c in courses if c['enrollment'] == 'mos')}",
        f"  запись в школе:  {sum(1 for c in courses if c['enrollment'] == 'school')}",
        f"  без записи:      {sum(1 for c in courses if c['enrollment'] == 'none')}",
        f"  без расписания:  {sum(1 for c in courses if not c['days'])}",
        f"  без возраста:    {sum(1 for c in courses if c['ageFrom'] is None)}",
        "",
        f"Замечаний к таблице: {len(problems)}",
        *problems,
    ]
    (out / "report.txt").write_text("\n".join(summary), encoding="utf-8")
    print("\n".join(summary[:8]))

    if fails:
        print("\nПроверки не пройдены:")
        for f in fails:
            print("  •", f)
        if args.strict:
            sys.exit(1)
        print("\n(запуск без --strict, файлы всё равно записаны)")
    else:
        print("\nПроверки пройдены.")
    print(f"Подробности: {out / 'report.txt'}")


if __name__ == "__main__":
    main()
