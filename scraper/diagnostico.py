"""Diagnóstico: prueba qué endpoints permite ML a esta app."""
import os, sys, json
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from ml_api import MLClient

cid = os.getenv("ML_CLIENT_ID")
cs = os.getenv("ML_CLIENT_SECRET")
client = MLClient(client_id=cid, client_secret=cs)


def test(label, url, params=None):
    print(f"\n--- {label} ---")
    print(f"URL: {url}  params={params}")
    try:
        d = client._get(url, params=params)
        if isinstance(d, dict):
            paging = d.get("paging", {})
            results = d.get("results", [])
            print(f"OK total={paging.get('total')} primary={paging.get('primary_results')} returned={len(results)}")
            if results:
                r0 = results[0]
                print(f"  Primer item: {r0.get('id')} - {r0.get('title')}")
        else:
            print("OK (no dict)")
    except Exception as e:
        print(f"FAIL: {e}")


BASE = "https://api.mercadolibre.com"

print("=" * 60)
print("Diagnóstico de endpoints ML")
print("=" * 60)

# 1) Token check
test("1. /users/me (auth)", f"{BASE}/users/me")

# 2) Site info (público)
test("2. /sites/MLA", f"{BASE}/sites/MLA")

# 3) Search seller_id (público)
test("3. search seller_id", f"{BASE}/sites/MLA/search",
     {"seller_id": "151853634", "limit": 5})

# 4) Search by category solo
test("4. search solo category", f"{BASE}/sites/MLA/search",
     {"category": "MLA1744", "limit": 5})

# 5) Search category + condition
test("5. search category + USED", f"{BASE}/sites/MLA/search",
     {"category": "MLA1744", "ITEM_CONDITION": "2230581", "limit": 5})

# 6) Items search via products
test("6. /products/search", f"{BASE}/products/search",
     {"site_id": "MLA", "status": "active", "q": "Toyota Yaris", "limit": 5})

# 7) Categoría y atributos
test("7. /categories/MLA1744", f"{BASE}/categories/MLA1744")
