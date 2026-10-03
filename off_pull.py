import duckdb, time, sys
URL = "hf://datasets/openfoodfacts/product-database/food.parquet"
con = duckdb.connect()
con.execute("SET enable_progress_bar=false")
t = time.time()
schema = con.execute(f"DESCRIBE SELECT * FROM '{URL}'").fetchall()
print(f"schema in {time.time()-t:.0f}s", flush=True)
for name, typ, *_ in schema:
    if name in ("code","product_name","brands","nutriments","countries_tags","states_tags","lang","quantity","product_quantity"):
        print(name, "::", typ[:400], flush=True)
cols = [c for c in ("code","product_name","brands","nutriments","countries_tags") if c in {s[0] for s in schema}]
t = time.time()
con.execute(f"COPY (SELECT {', '.join(cols)} FROM '{URL}') TO 'off_cols.parquet' (FORMAT parquet, COMPRESSION zstd)")
print(f"copied {cols} in {time.time()-t:.0f}s", flush=True)
print(con.execute("SELECT count(*) FROM 'off_cols.parquet'").fetchone(), flush=True)
