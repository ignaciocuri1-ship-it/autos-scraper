"""Scraper MercadoLibre — autos usados (sostenible y resumible).

Estrategia en 2 fases:
- FASE 1 (rápida): scrape de listados → metadata + IDs.
- FASE 2 (lenta): solo descripciones de items NUEVOS (cache global).

Ventajas:
- Cada item se "describe" UNA sola vez en su vida.
- Si ML bloquea, las descripciones pendientes se completan al día siguiente.
- Snapshots diarios siempre actualizados con metadata fresca + descripción cacheada.

Uso:
    python scraper.py
    python scraper.py --marca Toyota --modelo Yaris
    python scraper.py --skip-descriptions    # solo metadata
"""
from __future__ import annotations

import argparse
import logging
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

from ml_api import MLClient
from storage import (
    save_publicaciones, append_historico,
    load_descripciones_cache, save_descripciones_cache,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scraper")

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "_cache"
DESC_CACHE_FILE = CACHE_DIR / "descripciones.csv"


def _row_from(card: dict, description: str, marca: str, modelo: str) -> dict:
    return {
        "item_id": card.get("id"),
        "marca": marca,
        "modelo": modelo,
        "titulo": card.get("title"),
        "precio": card.get("price"),
        "moneda": card.get("currency_id"),
        "año": card.get("year"),
        "km": card.get("km"),
        "version": card.get("version"),
        "transmision": card.get("transmision"),
        "combustible": card.get("combustible"),
        "color": card.get("color"),
        "condicion": card.get("condition"),
        "permalink": card.get("permalink"),
        "thumbnail": card.get("thumbnail"),
        "provincia": card.get("state"),
        "ciudad": card.get("city"),
        "vendedor_id": card.get("seller_id"),
        "vendedor_tipo": None,
        "vendedor_reputacion": card.get("seller_name"),
        "fecha_publicacion": None,
        "fecha_update": None,
        "descripcion": description,
        "fecha_scrape": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


def fase1_listado(client: MLClient, marca: str, modelo: str,
                  year_from: int, year_to: int) -> dict[str, dict]:
    """Trae todos los items (metadata) de un modelo. Sin descripciones."""
    log.info("=== FASE 1: %s %s ===", marca, modelo)
    cards: dict[str, dict] = {}

    for c in client.search(marca=marca, modelo=modelo, condition="usado"):
        cards.setdefault(c["id"], c)
    log.info("  pase general: %d items", len(cards))

    # Solo segmentar por año si llegamos al cap (>1900 listings)
    if len(cards) >= 1900:
        log.info("  cap de paginación alcanzado, segmentando por año...")
        for year in range(year_to, year_from - 1, -1):
            before = len(cards)
            for c in client.search(marca=marca, modelo=modelo, year=year, condition="usado"):
                cards.setdefault(c["id"], c)
            if len(cards) > before:
                log.info("  año %s: +%d (acum %d)", year, len(cards) - before, len(cards))

    log.info("  total únicos %s %s: %d", marca, modelo, len(cards))
    return cards


def fase2_descripciones(client: MLClient, items_pendientes: list[dict],
                        cache: dict[str, str], cap: int, max_workers: int) -> int:
    """Trae descripciones de items que NO están en el cache. Cap por corrida."""
    nuevos = [it for it in items_pendientes if it["id"] not in cache]
    if not nuevos:
        log.info("FASE 2: 0 items pendientes (todo cacheado)")
        return 0
    if cap > 0 and len(nuevos) > cap:
        log.info("FASE 2: %d pendientes, corro %d esta vez (resto al próximo run)", len(nuevos), cap)
        nuevos = nuevos[:cap]
    else:
        log.info("FASE 2: %d descripciones a traer", len(nuevos))

    fetched = 0

    def _fetch(it):
        try:
            return it["id"], client.item_description(it["permalink"])
        except Exception as e:
            log.warning("desc %s fail: %s", it.get("id"), e)
            return it["id"], ""

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(_fetch, it) for it in nuevos]
        for i, fut in enumerate(as_completed(futs), 1):
            iid, desc = fut.result()
            cache[iid] = desc
            fetched += 1
            if i % 25 == 0:
                log.info("  desc %d/%d", i, len(nuevos))
    return fetched


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(Path(__file__).with_name("config.yaml")))
    ap.add_argument("--marca")
    ap.add_argument("--modelo")
    ap.add_argument("--year-from", type=int)
    ap.add_argument("--year-to", type=int)
    ap.add_argument("--skip-descriptions", action="store_true")
    ap.add_argument("--out", default=str(DATA_DIR))
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Cargar credenciales desde .env (en raíz del proyecto)
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_path)
    client_id = os.getenv("ML_CLIENT_ID")
    client_secret = os.getenv("ML_CLIENT_SECRET")

    client = MLClient(
        client_id=client_id,
        client_secret=client_secret,
        site=cfg.get("site", "MLA"),
        delay=cfg.get("request_delay", 0.1),
    )

    marcas = cfg.get("marcas", {})
    if args.marca:
        marcas = {args.marca: marcas.get(args.marca, {"modelos": [args.modelo] if args.modelo else []})}

    year_from = args.year_from or cfg.get("year_from", 1995)
    year_to = args.year_to or cfg.get("year_to", 2026)
    inter_delay = cfg.get("inter_model_delay", 30)
    desc_cap = cfg.get("max_descriptions_per_run", 400)
    max_workers = cfg.get("max_workers", 3)

    # FASE 1: scrape de todos los modelos (rápido, solo metadata)
    todo_cards: dict[tuple[str, str], dict[str, dict]] = {}
    modelos_lista = []
    for marca, conf in marcas.items():
        modelos = [args.modelo] if args.modelo else conf.get("modelos", [])
        for modelo in modelos:
            modelos_lista.append((marca, modelo))

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    for i, (marca, modelo) in enumerate(modelos_lista):
        cards = fase1_listado(client, marca, modelo, year_from, year_to)
        todo_cards[(marca, modelo)] = cards
        if i < len(modelos_lista) - 1:
            sleep_t = inter_delay + random.uniform(0, 10)
            log.info("Pausa entre modelos: %.0fs", sleep_t)
            time.sleep(sleep_t)

    # FASE 2: traer descripciones nuevas (con cache global)
    cache = load_descripciones_cache(DESC_CACHE_FILE)
    log.info("Cache descripciones: %d items previos", len(cache))

    if not args.skip_descriptions and not cfg.get("skip_descriptions", False):
        all_items = [c for cards in todo_cards.values() for c in cards.values()]
        # priorizar items nuevos (no en cache)
        random.shuffle(all_items)
        fetched = fase2_descripciones(client, all_items, cache, desc_cap, max_workers)
        log.info("Descripciones nuevas: %d", fetched)
        save_descripciones_cache(cache, DESC_CACHE_FILE)

    # FASE 3: escribir snapshots diarios por modelo
    total = 0
    for (marca, modelo), cards in todo_cards.items():
        rows = [_row_from(c, cache.get(c["id"], ""), marca, modelo) for c in cards.values()]
        sub = out_dir / marca / modelo
        pub_file = sub / f"{today}publicaciones.csv"
        hist_file = sub / "historico.csv"
        n = save_publicaciones(rows, pub_file)
        h = append_historico(rows, hist_file)
        log.info("[%s/%s] %d filas → %s | +%d hist", marca, modelo, n, pub_file.name, h)
        total += n

    log.info("DONE. Total: %d items procesados", total)
    try:
        client.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
