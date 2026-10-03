# Übermensch — privacy, support and open data

This repository hosts the public pages of **Übermensch**, a local-first self-tracking app for iPhone, and the open data it ships with.

- Privacy policy: https://yobius.github.io/ubermensch-privacy/ (Russian: `#ru`)
- Support: https://yobius.github.io/ubermensch-privacy/support.html (Russian: `#ru`)
- Contact: chemodanclan95@gmail.com

## Offline barcode database

Übermensch looks up food barcodes on the iPhone, without a network request, in tables built into the app. The tables built from Open Food Facts are a derivative database and are published here under the same license.

| File | Source | Rows | License |
|---|---|---|---|
| `barcodes-off-1.sqlite` | Open Food Facts, snapshot of 2026-09-30 | 1,300,000 | ODbL 1.0 (database), DbCL 1.0 (contents) |
| `barcodes-off-2.sqlite` | Open Food Facts, snapshot of 2026-09-30 | 1,088,742 | ODbL 1.0 (database), DbCL 1.0 (contents) |
| `barcodes-usda.sqlite` (in the app, not republished here) | USDA FoodData Central, Branded Foods, release 2026-04-30 | 424,263 | CC0 1.0 (public domain) |

The two Open Food Facts files are attached to the release **barcodes-2026-09-30** of this repository.

**Attribution.** Contains information from Open Food Facts (https://openfoodfacts.org), made available under the Open Database License (ODbL) 1.0. Individual contents of the database are licensed under the Database Contents License (DbCL) 1.0. Nutrition data from USDA FoodData Central (https://fdc.nal.usda.gov), U.S. Department of Agriculture, Agricultural Research Service.

### What is in the Open Food Facts tables

Products from the Open Food Facts product database that are sold in the EU-27, the United Kingdom, Ireland, Switzerland, Norway, the United States, Canada or Ukraine and that are not already in the USDA table. Only the fields needed for a calorie and nutrient entry are kept.

Schema (both files):

```sql
meta(key TEXT PRIMARY KEY, value TEXT)          -- source, snapshot, license, attribution, count
brand(id INTEGER PRIMARY KEY, name TEXT NOT NULL)
product(gtin INTEGER PRIMARY KEY, name TEXT NOT NULL, brand INTEGER,
        kcal INTEGER NOT NULL, protein INTEGER, fat INTEGER, carbs INTEGER,
        fiber INTEGER, sugar INTEGER, sodium INTEGER, caffeine INTEGER)
```

Values are per 100 g (or 100 ml for drinks): `kcal` as is; `protein`, `fat`, `carbs`, `fiber` and `sugar` in tenths of a gram; `sodium` and `caffeine` in mg. NULL means unknown. `gtin` is the barcode digits read as one integer, so 8-, 12-, 13- and 14-digit forms of the same code share one key. Rows are split into two files by `gtin` order (GitHub rejects files over 100 MiB).

### How the tables are built

1. `off_pull.py` copies the columns `code, product_name, brands, nutriments, countries_tags` from the Open Food Facts dump on Hugging Face (`hf://datasets/openfoodfacts/product-database/food.parquet`, snapshot of 2026-09-30) into `off_cols.parquet` (DuckDB).
2. `make_barcode_packs.py` filters by country, drops products already in the USDA table, keeps rows with a name and a calorie value, rejects physically impossible nutrient values, and writes the SQLite files above.

Both scripts are in this repository. Running them against a newer dump gives a newer snapshot.

SHA-256:

```
36d1100ad6da4db03b91e55f0052061a21706d63d51e6b3a82dffdc08a3cf04c  barcodes-off-1.sqlite
d3c8ce6c3c0c512d541ad542f5622fbb92c13c575e2b87177d8d863df0d5eea7  barcodes-off-2.sqlite
```
