# Contexto para continuar este proyecto en otros chats

## Objetivo solicitado

Analizar un GeoTIFF multibanda de Paraguay mediante una API Python que recibe `pos1` y `pos2`, construye un rectángulo y devuelve estadísticas para una interfaz HTML/JavaScript. Todo el desarrollo nuevo está en **`este si es el bueno/`**, dentro de `nsac`. No se han cambiado los exportadores originales.

## Arquitectura

- `servidor.py`: HTTP de biblioteca estándar, escucha `127.0.0.1:8000`, sirve `web/` y expone `GET /api/info` y `POST /api/analizar`. CLI `--geotiff` obligatorio; `--puerto`, `--max-pixeles`, `--abrir` opcionales. Un análisis simultáneo, resto HTTP 429. No permite cambiar rutas de archivo desde el navegador. Comprueba Host y Origin.
- `analizador.py`: funciones reutilizables `metadatos(ruta)` y `analizar(ruta, peticion, max_pixeles=5000000)`. NumPy y Rasterio; bloques 256 × 256, máscaras y NoData, escala/offset, estadísticas acumuladas con combinación de varianza, histogramas para categorías. Centros de píxel comprobados en WGS84; envolvente transformada con densificación. Admite georreferenciación afín rotada.
- `web/index.html`, `web/style.css`, `web/app.js`: interfaz en español, coordenadas manuales o arrastre en canvas, estado, estadísticas, histogramas y descarga JSON. Sin CDN ni librerías externas. Canvas esquemático: no muestra imágenes de las bandas ni mapa base.
- `requirements.txt`: NumPy y Rasterio. `README.md`: instalación, ejecución, API, límites y pruebas.
- `tests/`: validación con archivos temporales sintéticos; ejecutar `python -m unittest discover -s tests -v` desde esta carpeta.

## Contrato

```json
{"pos1":{"lon":-57.65,"lat":-25.35},"pos2":{"lon":-57.60,"lat":-25.30}}
```

Coordenadas WGS84 (EPSG:4326). Esquinas opuestas, normalizadas sin importar orden. No admite rectángulos degenerados, polos ni cruce de antimeridiano. Respuesta: `archivo`, `crs_entrada`, `rectangulo`, `pixeles_seleccionados`, `total_bandas`, `bandas`, `avisos`. Cada banda tiene metadatos, válidos, sin datos, cobertura, mínimo, máximo y, si no es categórica, media y desviación estándar poblacional. Categorías: `clases` con `valor`, `pixeles`, `porcentaje`. Estadísticas ausentes como `null`; nunca NaN JSON. Errores: objeto `{"error":"mensaje"}` con estado HTTP apropiado.

## Fuentes esperadas (27 / 25 bandas)

| Fuente | Nombres de las bandas | Cantidad |
|---|---|---:|
| SRTM | elevation_m | 1 |
| MapBiomas Paraguay colección 2 | land_cover | 1 |
| Landsat 8/9 | ls_red, ls_nir, ls_swir1, ndvi, ndmi, ls_valid_scenes | 6 |
| OpenLandMap | soil_ph_10cm, soil_texture_10cm | 2 |
| ERA5-Land | era_t2m_c, era_precip_mm, era_soil_water | 3 |
| PML | pml_et_mm_d, pml_ec_mm_d, pml_es_mm_d, pml_ei_mm_d, pml_ew_mm_d | 5 |
| ECOSTRESS (opcional) | eco_lst_c, eco_valid_scenes | 2 |
| Límites | dentro_paraguay_fao, dentro_paraguay_natural_earth | 2 |
| HydroSHEDS | presencia_rio, caudal_m3_s, cuenca_aguas_arriba_km2 | 3 |
| HydroLAKES | presencia_lago, area_lago_km2 | 2 |

Los nombres se verificaron en `exportar_field_shift.py` y `generar_geotiffs.py`. `combinar_rasters.py` guarda descripciones, unidades, metadata, escala y offset. **No asumir índices fijos:** el orden depende de las entradas al combinador. Se admite de 1 a 27 bandas con advertencia si no son 25 o 27. Las bandas desconocidas se conservan con su nombre genérico y sin atribución de fuente.

## Decisiones importantes

Los datos originales se exportan a EPSG:6933, normalmente a 120 m; el analizador lee CRS y resolución reales. Las fuentes tienen resoluciones nativas distintas: una cuadrícula común no las convierte en observaciones independientes a 120 m. No se hacen interpretaciones agronómicas ni clasificaciones de aptitud. No se infiere la leyenda de MapBiomas. Ceros de presencia o de escenas son valores válidos. Caudal, área de cuenca y área de lago no deben sumarse por píxel. No hay áreas estimadas ni ponderación por superficie. Los porcentajes de clases usan como denominador los válidos de su banda. La cobertura excluye la parte del rectángulo exterior al archivo.

## Ejecución y próximo trabajo

Ver `README.md`. Ejemplo desde esta carpeta: `python servidor.py --geotiff "..\datos\fuentes_paraguay\paraguay_2023_combinado.tif" --abrir`. Se debe proporcionar un archivo que exista: al crear esta aplicación no había ningún GeoTIFF combinado terminado disponible en `datos/fuentes_paraguay`; la verificación se hace con TIFF sintéticos. No se inicia ni se descarga la generación completa de Paraguay automáticamente.

Posibles ampliaciones si se solicitan: mapa base con selección geográfica, vista de una banda, leyenda oficial de MapBiomas, exportación del recorte, filtros por país/escenas y trabajos asíncronos para áreas grandes. Para publicar la interfaz habrá que diseñar autenticación, política de origen y almacenamiento; la implementación actual es local.
