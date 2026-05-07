# Autos Scraper — MercadoLibre → Power BI

Scraper modular para publicaciones de autos usados en MercadoLibre Argentina.
Output: CSVs listos para Power BI.

## Estructura

```
Autos/
├── scraper/
│   ├── config.yaml         # marcas/modelos/años a scrapear
│   ├── ml_api.py           # cliente API MercadoLibre
│   ├── storage.py          # CSV UPSERT + histórico
│   ├── scraper.py          # orquestador
│   └── requirements.txt
├── data/
│   └── toyota_yaris/
│       ├── publicaciones.csv   # estado actual (UPSERT por item_id)
│       └── historico.csv       # 1 row por item por día (evolución precios)
└── .github/workflows/scrape.yml  # cron diario
```

## Uso local

```bash
cd scraper
pip install -r requirements.txt
python scraper.py                          # corre config completo
python scraper.py --marca Toyota --modelo Yaris   # solo un modelo
```

## Escalar

- **Sumar modelos de Toyota:** descomentar líneas en `config.yaml > marcas.Toyota.modelos`.
- **Sumar otras marcas:** agregar bloque `Ford: {modelos: [...]}`.
- **Cambiar frecuencia:** editar cron en `.github/workflows/scrape.yml` (`"0 9 * * 1"` = semanal lunes).
- **Migrar a Postgres/Supabase:** reemplazar `storage.py` (mantener firmas `save_publicaciones` / `append_historico`).

## Por qué segmentación por año

La API de ML tope ofsets a 1000 resultados por query. Iterando año por año
(1995→2026) el scraper puede capturar miles de publicaciones sin perderse ninguna.
Al dedupar por `item_id`, no importa si un año solapa con otro.

## Conectar a Power BI

1. Subir la carpeta `data/` a **OneDrive** (o usar el repo de GitHub vía raw URL).
2. Power BI Desktop → **Obtener datos** → **Carpeta** → apuntar a `data/`.
3. Combinar todos los `publicaciones.csv` en una tabla.
4. Hacer lo mismo con `historico.csv` para la tabla de hechos de precios.
5. Publicar al servicio y configurar refresh diario.

### Modelo sugerido

- **fact_publicaciones** (estado actual): `publicaciones.csv` unidos.
- **fact_historico** (precios diarios): `historico.csv` unidos.
- **dim_calendario**: tabla calendario generada en Power Query/DAX.
- Relación: `fact_historico[item_id]` → `fact_publicaciones[item_id]`.

### Medidas DAX útiles

```dax
Precio Promedio = AVERAGE(fact_publicaciones[precio])
Listings Activos = DISTINCTCOUNT(fact_publicaciones[item_id])
Variación Precio 7d =
    VAR precio_hoy = CALCULATE(AVERAGE(fact_historico[precio]), LASTDATE(dim_calendario[fecha]))
    VAR precio_7d  = CALCULATE(AVERAGE(fact_historico[precio]), DATEADD(dim_calendario[fecha], -7, DAY))
    RETURN DIVIDE(precio_hoy - precio_7d, precio_7d)
```

## Roadmap sugerido

1. ✅ Toyota Yaris diario
2. Sumar resto de modelos Toyota (descomentar config)
3. Sumar más marcas (Ford, VW, Chevrolet, Fiat, Renault…)
4. Pasar cron a **semanal** cuando el volumen justifique
5. Migrar CSV → Supabase Postgres (conexión nativa Power BI)
6. Dashboard público con snapshot semanal

## Notas API

- Endpoint base: `https://api.mercadolibre.com`
- No requiere autenticación para búsquedas públicas
- Rate limit aprox. 10-20 req/seg anónimo (config: `request_delay`, `max_workers`)
- Campos de atributos: `VEHICLE_YEAR`, `KILOMETERS`, `TRANSMISSION`, `FUEL_TYPE`, etc.
