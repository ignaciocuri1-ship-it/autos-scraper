"""Helper de autorización OAuth para MercadoLibre.

Hace el flujo authorization_code: abrís el navegador, autorizás, pegás la URL
de callback, y guarda los tokens en data/_cache/tokens.json para uso futuro.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import webbrowser
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
TOKENS_FILE = ROOT / "data" / "_cache" / "tokens.json"


def main() -> int:
    load_dotenv(ROOT / ".env")
    cid = os.getenv("ML_CLIENT_ID")
    cs = os.getenv("ML_CLIENT_SECRET")
    if not cid or not cs:
        print("ERROR: faltan ML_CLIENT_ID y ML_CLIENT_SECRET en .env")
        return 1

    redirect = "https://example.com/callback"
    auth_url = (
        "https://auth.mercadolibre.com.ar/authorization"
        f"?response_type=code&client_id={cid}"
        f"&redirect_uri={urllib.parse.quote(redirect, safe='')}"
    )

    print("=" * 70)
    print("AUTORIZACIÓN MERCADO LIBRE")
    print("=" * 70)
    print()
    print("Voy a abrir el navegador. Pasos:")
    print("  1. Loguéate con tu cuenta de ML (si te lo pide)")
    print("  2. Click en 'Permitir'")
    print("  3. El navegador va a redirigir a una página que NO carga")
    print("     (algo tipo: https://localhost.local/callback?code=TG-XXXXXXX)")
    print("  4. Copiá la URL ENTERA de la barra de direcciones y pegala acá.")
    print()
    print("Si no se abre el navegador automático, pegá esta URL manualmente:")
    print(auth_url)
    print()

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    callback_url = input("Pegá acá la URL completa del callback: ").strip()
    if "code=" not in callback_url:
        print("ERROR: no veo 'code=' en la URL pegada")
        return 1

    code = urllib.parse.parse_qs(urllib.parse.urlparse(callback_url).query).get("code", [None])[0]
    if not code:
        print("ERROR: no pude extraer el code")
        return 1

    print(f"\nIntercambiando code por access_token...")
    r = requests.post(
        "https://api.mercadolibre.com/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": cid,
            "client_secret": cs,
            "code": code,
            "redirect_uri": redirect,
        },
        timeout=30,
    )
    if r.status_code != 200:
        print(f"ERROR: {r.status_code} {r.text}")
        return 1
    tokens = r.json()
    print(f"\n✓ Token OK (expira en {tokens.get('expires_in')}s)")

    TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKENS_FILE.write_text(json.dumps(tokens, indent=2))
    print(f"✓ Guardado en {TOKENS_FILE}")
    print("\nYa podés correr 2-scrapear-toyota.bat")
    return 0


if __name__ == "__main__":
    sys.exit(main())
