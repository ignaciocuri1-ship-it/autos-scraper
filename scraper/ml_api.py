"""Cliente híbrido MercadoLibre.

- Listados: web scraping (HTML público de listado.mercadolibre.com.ar)
- Detalles/descripciones: API oficial (api.mercadolibre.com con Bearer token)
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Iterator, Optional

import requests
from curl_cffi import requests as cffi_requests

log = logging.getLogger(__name__)

API = "https://api.mercadolibre.com"
TOKENS_FILE = Path(__file__).resolve().parent.parent / "data" / "_cache" / "tokens.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
}


def _slug(s: str) -> str:
    return s.lower().strip().replace(" ", "-")


def _extract_results_json(html: str) -> list[dict]:
    needle = '"results":[{"id":"MLA'
    idx = html.find(needle)
    if idx < 0:
        return []
    start = html.index("[", idx)
    depth, in_str, escape = 0, False, False
    end = -1
    for i in range(start, len(html)):
        c = html[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        return []
    try:
        return json.loads(html[start:end + 1])
    except json.JSONDecodeError:
        return []


def _attr_value(item: dict, *attr_ids: str) -> Optional[str]:
    for a in (item.get("attributes") or []):
        if a.get("id") in attr_ids:
            return a.get("value_name") or (a.get("values", [{}])[0].get("name") if a.get("values") else None)
    return None


def _normalize_card(item: dict) -> dict:
    iid = item.get("id") or ""
    permalink = item.get("permalink") or ""
    price_info = item.get("price") or {}
    price = price_info.get("amount") if isinstance(price_info, dict) else None
    currency = (price_info.get("currency_id") if isinstance(price_info, dict) else None) or item.get("currency_id")
    addr = item.get("location") or item.get("address") or {}
    state = (addr.get("state") or {}).get("name") if isinstance(addr.get("state"), dict) else addr.get("state_name")
    city = (addr.get("city") or {}).get("name") if isinstance(addr.get("city"), dict) else addr.get("city_name")
    seller = item.get("seller") or {}
    return {
        "id": iid,
        "permalink": permalink,
        "title": item.get("title"),
        "price": price,
        "currency_id": currency,
        "year": _attr_value(item, "VEHICLE_YEAR", "YEAR"),
        "km": _attr_value(item, "KILOMETERS"),
        "transmision": _attr_value(item, "TRANSMISSION"),
        "combustible": _attr_value(item, "FUEL_TYPE"),
        "color": _attr_value(item, "VEHICLE_COLOR", "COLOR"),
        "version": _attr_value(item, "TRIM", "VERSION"),
        "condition": _attr_value(item, "ITEM_CONDITION") or "Usado",
        "thumbnail": item.get("thumbnail"),
        "state": state,
        "city": city,
        "neighborhood": None,
        "seller_id": seller.get("id"),
        "seller_name": seller.get("nickname") or seller.get("name"),
    }


class MLClient:
    def __init__(self, client_id: str, client_secret: str, site: str = "MLA",
                 delay: float = 1.0, **_ignored):
        self.client_id = client_id
        self.client_secret = client_secret
        self.site = site
        self.delay = delay
        # Sesión cffi para web scraping
        self.web = cffi_requests.Session(impersonate="chrome124")
        self.web.headers.update(HEADERS)
        # Sesión requests normal para API
        self.api_s = requests.Session()
        self.api_s.headers.update({"User-Agent": "autos-scraper/2.0"})
        self._token: Optional[str] = None
        self._token_exp = 0.0

    # ---- AUTH (API) ----

    def _load_tokens(self) -> Optional[dict]:
        if TOKENS_FILE.exists():
            try:
                return json.loads(TOKENS_FILE.read_text())
            except Exception:
                return None
        return None

    def _save_tokens(self, t: dict):
        TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKENS_FILE.write_text(json.dumps(t, indent=2))

    def _get_token(self) -> Optional[str]:
        if self._token and time.time() < self._token_exp - 120:
            return self._token
        tokens = self._load_tokens()
        if tokens:
            issued = tokens.get("_issued_at", 0)
            exp = tokens.get("expires_in", 21600)
            if time.time() < issued + exp - 120:
                self._token = tokens["access_token"]
                self._token_exp = issued + exp
                return self._token
            refresh = tokens.get("refresh_token")
            if refresh:
                log.info("Refrescando token...")
                r = self.api_s.post(f"{API}/oauth/token", data={
                    "grant_type": "refresh_token",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": refresh,
                }, timeout=30)
                if r.status_code == 200:
                    nt = r.json()
                    nt["_issued_at"] = time.time()
                    self._save_tokens(nt)
                    self._token = nt["access_token"]
                    self._token_exp = nt["_issued_at"] + nt.get("expires_in", 21600)
                    return self._token
        return None

    # ---- WEB (listados) ----

    def _web_get(self, url: str) -> str:
        r = self.web.get(url, timeout=30)
        if self.delay:
            time.sleep(self.delay)
        if r.status_code == 404:
            return ""
        r.raise_for_status()
        if "suspicious-traffic-frontend" in r.text[:1000]:
            log.warning("Web BLOQUEADO. Esperando 60s...")
            time.sleep(60)
            r = self.web.get(url, timeout=30)
            r.raise_for_status()
            if "suspicious-traffic-frontend" in r.text[:1000]:
                return ""
        return r.text

    def search(self, marca: str, modelo: str, year: Optional[int] = None,
               condition: str = "usado", **_ignored) -> Iterator[dict]:
        slug = f"{_slug(marca)}-{_slug(modelo)}"
        if condition:
            slug = f"{slug}-{condition}"
        offset = 0
        pages = 0
        seen = set()
        while pages < 50:
            parts = []
            if offset > 0:
                parts.append(f"_Desde_{offset+1}")
            if year:
                parts.append(f"_VEHICLE*YEAR_{year}")
            url = f"https://listado.mercadolibre.com.ar/{slug}{''.join(parts)}_NoIndex_True"
            log.info("GET %s", url)
            try:
                html = self._web_get(url)
            except Exception as e:
                log.warning("web err: %s", e)
                break
            if not html:
                break
            items = _extract_results_json(html)
            if not items:
                break
            yielded = 0
            for it in items:
                row = _normalize_card(it)
                if not row["id"] or row["id"] in seen:
                    continue
                seen.add(row["id"])
                yielded += 1
                yield row
            log.info("  pag %d: %d items (acum %d)", pages + 1, yielded, len(seen))
            if yielded == 0:
                break
            offset += len(items)
            pages += 1

    # ---- API (descripciones) ----

    def item_description(self, permalink_or_id: str) -> str:
        m = re.search(r"MLA-?(\d+)", permalink_or_id or "")
        if not m:
            return ""
        iid = f"MLA{m.group(1)}"
        token = self._get_token()
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            r = self.api_s.get(f"{API}/items/{iid}/description", headers=headers, timeout=30)
            if r.status_code == 404:
                return ""
            r.raise_for_status()
            d = r.json()
            return d.get("plain_text") or d.get("text") or ""
        except Exception as e:
            log.warning("desc %s: %s", iid, e)
            return ""

    def item_detail(self, permalink_or_id: str) -> dict:
        return {"permalink": permalink_or_id, "description": self.item_description(permalink_or_id)}

    def _get(self, url: str, params: Optional[dict] = None) -> dict:
        """Helper para diagnóstico."""
        token = self._get_token()
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        r = self.api_s.get(url, params=params, headers=headers, timeout=30)
        if r.status_code >= 400:
            log.warning("HTTP %s en %s — body: %s", r.status_code, url, r.text[:500])
        r.raise_for_status()
        return r.json()

    def ping(self) -> dict:
        try:
            return self._get(f"{API}/users/me")
        except Exception as e:
            return {"error": str(e)}

    def close(self):
        try:
            self.web.close()
            self.api_s.close()
        except Exception:
            pass
