#!/usr/bin/env python3
"""Build the offline barcode packs from bulk dumps (run on the Mac, once per data refresh).

Outputs (Ubermensch/Resources/):
- barcodes-usda.sqlite — USDA FoodData Central Branded Foods (CC0 / public domain).
- barcodes-off-<n>.sqlite — Open Food Facts subset (ODbL 1.0): products sold in the
  markets below that are NOT already in the USDA pack, split into gtin-ordered
  shards of <= 1.3M rows (GitHub rejects files over 100 MiB). Kept apart from the
  USDA file so the two form a collective database and ODbL share-alike stays on
  the OFF part.

Schema (both files):
  meta(key TEXT PRIMARY KEY, value TEXT)
  brand(id INTEGER PRIMARY KEY, name TEXT NOT NULL)
  product(gtin INTEGER PRIMARY KEY, name TEXT NOT NULL, brand INTEGER,
          kcal INTEGER NOT NULL, protein INTEGER, fat INTEGER, carbs INTEGER,
          fiber INTEGER, sugar INTEGER, sodium INTEGER, caffeine INTEGER)
  Values per 100 g (or 100 ml for drinks): kcal as is; protein/fat/carbs/fiber/sugar
  in tenths of a gram; sodium and caffeine in mg. NULL = unknown.
  gtin = the barcode digits as one integer, so 8/12/13/14-digit paddings of the
  same code collapse to one key.

Inputs (~/projects/ubermensch-data/barcodes/, not in git):
- fdc_products.tsv  — from fdc_extract.py over FoodData_Central_branded_food_json_<date>.zip
- off_cols.parquet  — code, product_name, brands, nutriments, countries_tags pulled
                      from huggingface.co/datasets/openfoodfacts/product-database (off_pull.py)

Usage:
  python3 scripts/make_barcode_packs.py [--data DIR] [--mini]
  --mini writes UbermenschTests/Fixtures/barcode-mini.sqlite (a few known rows) instead.
"""
import argparse
import csv
import math
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RES = REPO / "Ubermensch" / "Resources"
OFF_COUNTRIES = ["en:" + c for c in [
    "united-states", "canada", "united-kingdom", "ireland", "ukraine", "switzerland", "norway",
    "austria", "belgium", "bulgaria", "croatia", "cyprus", "czech-republic", "denmark", "estonia",
    "finland", "france", "germany", "greece", "hungary", "italy", "latvia", "lithuania", "luxembourg",
    "malta", "netherlands", "poland", "portugal", "romania", "slovakia", "slovenia", "spain", "sweden",
]]
SHARD = 1_300_000
SMALL = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with"}


def nice_case(s: str) -> str:
    """USDA descriptions are ALL CAPS; title-case them, keep small words low."""
    s = re.sub(r"\s+", " ", s.strip().strip('"'))
    if not s or any(c.islower() for c in s):
        return s
    words = s.lower().split(" ")
    out = []
    for i, w in enumerate(words):
        out.append(w if (i and w in SMALL) else re.sub(r"(^|[-/(&])([a-z])", lambda m: m[1] + m[2].upper(), w))
    return " ".join(out)


def valid_key(code: str):
    digits = "".join(c for c in code if c.isdigit())
    if not (8 <= len(digits) <= 14) or set(digits) == {"0"}:
        return None
    padded = digits.zfill(13)[-13:] if len(digits) <= 13 else digits
    # GS1 restricted-circulation prefixes (in-store / variable-weight): not unique.
    if len(digits) <= 13 and (padded.startswith("2") or padded.startswith("02")) and len(digits) > 8:
        return None
    return int(digits)


def num(v, cap):
    """A finite, non-negative value within a physical ceiling per 100 g, else unknown."""
    if v is None or v == "":
        return None
    f = float(v)
    return f if math.isfinite(f) and 0 <= f <= cap else None


def tenth(v, cap=100):
    f = num(v, cap)
    return None if f is None else round(f * 10)


def whole(v, cap=100_000):
    f = num(v, cap)
    return None if f is None else round(f)


NA_MAX_MG = 39_340  # sodium share of pure salt, per 100 g


def sodium_mg(sodium_g, salt_g):
    """OFF sodium is grams per 100 g, but contributors often type milligrams into
    the gram field (Red Bull: 40). Salt is entered more reliably and sodium =
    salt / 2.5, so salt wins when the two disagree; anything above pure salt is unknown."""
    na = num(sodium_g, 1e9)
    salt = num(salt_g, 100)
    if salt is not None and (na is None or abs(na * 2.5 - salt) > max(0.5 * salt, 0.01)):
        na = salt / 2.5
    return whole(None if na is None else na * 1000, NA_MAX_MG)


def caffeine_mg(caffeine_g, kcal):
    """Caffeine per 100 g in grams tops out near 4 (instant coffee); a larger number
    is milligrams typed into the gram field (energy drinks: 32). Drinks (low kcal)
    stay under espresso's ~210 mg/100 ml."""
    c = num(caffeine_g, 1e9)
    if c is None:
        return None
    mg = c if c > 5 else c * 1000
    return whole(mg, 300 if (kcal or 0) < 80 else 5000)


def create(path: Path, meta: dict):
    path.unlink(missing_ok=True)
    db = sqlite3.connect(path)
    db.executescript("""
        PRAGMA page_size=4096;
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE brand(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE product(gtin INTEGER PRIMARY KEY, name TEXT NOT NULL, brand INTEGER,
            kcal INTEGER NOT NULL, protein INTEGER, fat INTEGER, carbs INTEGER,
            fiber INTEGER, sugar INTEGER, sodium INTEGER, caffeine INTEGER);
    """)
    db.executemany("INSERT INTO meta VALUES (?, ?)", meta.items())
    return db


def finish(db, brands: dict, path: Path, count: int):
    db.executemany("INSERT INTO brand VALUES (?, ?)", ((i, n) for n, i in brands.items()))
    db.execute("INSERT OR REPLACE INTO meta VALUES ('count', ?)", (str(count),))
    db.commit()
    db.execute("VACUUM")
    db.close()
    print(f"{path.name}: {count} products, {len(brands)} brands, {path.stat().st_size / 1e6:.1f} MB")


def brand_id(brands: dict, name: str):
    name = (name or "").split(",")[0].strip()
    if not name:
        return None
    return brands.setdefault(name, len(brands) + 1)


def sane(kcal) -> bool:
    return kcal is not None and 0 <= kcal <= 900


def build_usda(data: Path) -> set:
    path = RES / "barcodes-usda.sqlite"
    db = create(path, {"source": "USDA FoodData Central — Branded Foods", "release": "2026-04-30",
                       "license": "CC0 1.0 (public domain)", "url": "https://fdc.nal.usda.gov"})
    brands, keys, rows = {}, set(), []
    with open(data / "fdc_products.tsv", newline="") as f:
        for r in csv.reader(f, delimiter="\t"):
            key = valid_key(r[0])
            kcal = whole(r[3])
            if key is None or key in keys or not sane(kcal) or not r[1].strip():
                continue
            keys.add(key)
            rows.append((key, nice_case(r[1]), brand_id(brands, nice_case(r[2])), kcal,
                         tenth(r[4]), tenth(r[5]), tenth(r[6]), tenth(r[7]), tenth(r[8]),
                         whole(r[9], NA_MAX_MG), whole(r[10], 300 if kcal < 80 else 5000)))
    rows.sort()
    db.executemany("INSERT INTO product VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    finish(db, brands, path, len(rows))
    return keys


def pick_name(names):
    by = {n["lang"]: (n["text"] or "").strip() for n in (names or []) if n and n.get("text")}
    for lang in ("main", "en", "ru", "uk"):
        if by.get(lang):
            return by[lang]
    return next(iter(by.values()), "")


def build_off(data: Path, skip: set):
    import duckdb
    path = RES / "barcodes-off.sqlite"
    meta = {"source": "Open Food Facts", "snapshot": "2026-09-30",
                       "license": "ODbL 1.0 (database), DbCL 1.0 (contents)",
                       "url": "https://openfoodfacts.org",
                       "attribution": "Contains data from Open Food Facts, available under the Open Database License"}
    db = create(path, meta)
    con = duckdb.connect()
    countries = "[" + ",".join(f"'{c}'" for c in OFF_COUNTRIES) + "]"
    cur = con.execute(f"""
        SELECT code, product_name, brands,
               list_filter(nutriments, n -> n.name IN ('energy-kcal','energy','energy-kj','proteins','fat',
                   'carbohydrates','fiber','sugars','sodium','salt','caffeine')) AS nut
        FROM read_parquet('{data / "off_cols.parquet"}')
        WHERE list_has_any(countries_tags, {countries})
    """)
    brands, keys, rows = {}, set(), []
    while batch := cur.fetchmany(50000):
        for code, names, brand, nut in batch:
            key = valid_key(code or "")
            if key is None or key in skip or key in keys:
                continue
            v = {n["name"]: (n["100g"], (n["unit"] or "").lower()) for n in (nut or []) if n["100g"] is not None}
            kcal = v.get("energy-kcal", (None,))[0]
            if kcal is None:
                kj = v.get("energy-kj", (None,))[0]
                if kj is None and v.get("energy", (None, ""))[1] == "kj":
                    kj = v["energy"][0]
                kcal = kj / 4.184 if kj is not None else None
            kcal = whole(kcal)
            name = pick_name(names)
            if not sane(kcal) or not name:
                continue
            g = lambda k: v.get(k, (None,))[0]
            keys.add(key)
            rows.append((key, name[:120], brand_id(brands, brand), kcal, tenth(g("proteins")), tenth(g("fat")),
                         tenth(g("carbohydrates")), tenth(g("fiber")), tenth(g("sugars")),
                         sodium_mg(g("sodium"), g("salt")), caffeine_mg(g("caffeine"), kcal)))
    rows.sort()
    db.close()
    path.unlink()
    # GitHub rejects files over 100 MiB: split into gtin-ordered shards of <= SHARD rows.
    for i in range(0, len(rows), SHARD):
        part = rows[i:i + SHARD]
        shard = RES / f"barcodes-off-{i // SHARD + 1}.sqlite"
        sdb = create(shard, dict(meta, first=str(part[0][0]), last=str(part[-1][0])))
        used = {r[2] for r in part if r[2] is not None}
        sdb.executemany("INSERT INTO product VALUES (?,?,?,?,?,?,?,?,?,?,?)", part)
        finish(sdb, {n: b for n, b in brands.items() if b in used}, shard, len(part))


def build_mini():
    path = REPO / "UbermenschTests" / "Fixtures" / "barcode-mini.sqlite"
    db = create(path, {"source": "test fixture", "license": "CC0"})
    brands = {"Acme": 1}
    db.executemany("INSERT INTO product VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        (4006381333931, "Test Chocolate", 1, 535, 63, 300, 590, 34, 560, 24, None),   # EAN-13
        (36000291452, "Test Cola", None, 42, 0, 0, 106, None, 106, 4, 10),           # UPC-A (12 digits)
        (49000008739, "Test Small Pack", 1, 120, None, None, None, None, None, None, None),  # UPC-A of UPC-E 04987309
    ])
    finish(db, brands, path, 3)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=Path.home() / "projects/ubermensch-data/barcodes")
    ap.add_argument("--mini", action="store_true")
    ap.add_argument("--usda-only", action="store_true")
    a = ap.parse_args()
    if a.mini:
        build_mini()
        sys.exit()
    usda_keys = build_usda(a.data)
    if not a.usda_only:
        build_off(a.data, usda_keys)
