"""Almacenamiento CSV (Power BI friendly).

Dos archivos por marca/modelo:
- publicaciones.csv  → estado actual (UPSERT por item_id, se pisa)
- historico.csv      → append por cada scrape (item_id + fecha + precio)
"""
from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd


PUB_COLS = [
    "item_id", "marca", "modelo", "titulo", "precio", "moneda",
    "año", "km", "version", "transmision", "combustible", "color",
    "condicion", "permalink", "thumbnail",
    "provincia", "ciudad",
    "vendedor_id", "vendedor_tipo", "vendedor_reputacion",
    "fecha_publicacion", "fecha_update",
    "descripcion",
    "fecha_scrape",
]

HIST_COLS = ["fecha_scrape", "item_id", "precio", "moneda", "activo"]

DESC_COLS = ["item_id", "descripcion", "fecha_fetched"]


def load_descripciones_cache(cache_path: str | Path) -> dict[str, str]:
    """Carga {item_id: descripcion} de un cache persistente."""
    p = Path(cache_path)
    if not p.exists():
        return {}
    df = pd.read_csv(p, dtype=str)
    return dict(zip(df["item_id"], df["descripcion"].fillna("")))


def save_descripciones_cache(cache: dict[str, str], cache_path: str | Path) -> None:
    p = _ensure_dir(cache_path)
    from datetime import datetime
    today = datetime.utcnow().strftime("%Y-%m-%d")
    rows = [{"item_id": k, "descripcion": _clean_text(v), "fecha_fetched": today}
            for k, v in cache.items()]
    df = pd.DataFrame(rows, columns=DESC_COLS)
    df.to_csv(p, index=False, encoding="utf-8-sig",
              quoting=csv.QUOTE_ALL, lineterminator="\r\n")


def _ensure_dir(p: str | Path) -> Path:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _clean_text(v):
    """Reemplaza saltos de línea y tabs en celdas para que Excel no rompa filas."""
    if v is None:
        return v
    if not isinstance(v, str):
        return v
    return v.replace("\r\n", " | ").replace("\n", " | ").replace("\r", " | ").replace("\t", " ").strip()


def save_publicaciones(rows: Iterable[dict], out_path: str | Path) -> int:
    """Snapshot diario: escribe TODAS las filas del día (overwrite si ya existe)."""
    out = _ensure_dir(out_path)
    rows = [{k: _clean_text(v) for k, v in r.items()} for r in rows]
    df = pd.DataFrame(rows, columns=PUB_COLS)
    if df.empty:
        return 0
    df.to_csv(out, index=False, encoding="utf-8-sig",
              quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    return len(df)


def append_historico(rows: Iterable[dict], out_path: str | Path) -> int:
    """Append diario: un row por item para mirar evolución de precios."""
    out = _ensure_dir(out_path)
    fecha = datetime.utcnow().strftime("%Y-%m-%d")
    hist_rows = [
        {
            "fecha_scrape": fecha,
            "item_id": r["item_id"],
            "precio": r["precio"],
            "moneda": r["moneda"],
            "activo": 1,
        }
        for r in rows
    ]
    if not hist_rows:
        return 0

    df = pd.DataFrame(hist_rows, columns=HIST_COLS)
    header = not out.exists()
    df.to_csv(out, mode="a", header=header, index=False, encoding="utf-8-sig")
    return len(hist_rows)
