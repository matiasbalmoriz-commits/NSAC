# Field Shift Paraguay

## 1. Preparar Python en VS Code

Abre la carpeta que contiene los dos scripts en VS Code. En la terminal PowerShell, con CPython 3.14 estándar para Windows x64 instalado, ejecuta:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: earthengine-api numpy rasterio==1.5.0 shapely==2.1.2 pyogrio==0.12.1 scikit-image==0.26.0
```

En la paleta de VS Code, usa **Python: Select Interpreter** y selecciona `.venv\Scripts\python.exe`. Los comandos de esta guía llaman al intérprete directamente y funcionan sin activar el entorno.

Activa la API de Earth Engine en un proyecto de Google Cloud, registra ese proyecto para Earth Engine y usa una cuenta con acceso. En los ejemplos, reemplaza `mi-proyecto-gee` por el **ID** de tu proyecto. [Configuración y autenticación de Earth Engine](https://developers.google.com/earth-engine/guides/auth)

## 2. Exportar un área de prueba

```powershell
.\.venv\Scripts\python.exe .\exportar_field_shift.py --project mi-proyecto-gee --authenticate --year 2023 --bbox -56.70 -25.62 -56.45 -25.40 --tile 128 --ecostress --output .\datos\piloto.tif
```

`--bbox` recibe oeste, sur, este y norte en grados WGS 84 y se intersecta con Paraguay. El ejemplo cubre parte de Caaguazú. Quita `--authenticate` en corridas posteriores si ya hay credenciales. Quita `--ecostress` para omitir esa colección. El año predeterminado es 2023 y el intervalo configurado es 2013–2023 por el cruce de Landsat y MapBiomas Colección 2. Las fechas de inicio están incluidas y las del año siguiente están excluidas.

El resultado incluye `piloto.tif`, `piloto.bands.json` y una caché de teselas `piloto.tiles`. El JSON contiene el orden de bandas, fuentes, unidades, fórmulas, transformaciones nativas de imágenes de referencia y conteos de píxeles válidos. Los factores se aplican durante el cálculo. El TIFF usa Float32 con `-9999` como NoData, incluso para las bandas categóricas, cuyos códigos siguen siendo enteros. Comprueba `valid_pixels` antes de interpretar una banda. Las cuentas de escenas indican observaciones válidas por celda y pueden ser cero.

Para todo Paraguay ejecuta el mismo comando sin `--bbox`, con otro nombre de salida y, como punto de partida, teselas de 256. Las solicitudes se ejecutan en secuencia y las teselas se guardan en disco. Si la exportación se interrumpe, repite el mismo comando con los mismos parámetros para reaprovechar las teselas completas. Si una solicitud supera los límites de cálculo de Earth Engine, prueba `--tile 128` o `64` con un nombre nuevo. La caché nacional puede ocupar varios GB. Ejecuta una sola instancia por nombre de salida. [Solicitudes por cuadrícula con computePixels](https://developers.google.com/earth-engine/apidocs/ee-data-computepixels)

### Fuentes, unidades y agregación

Cuadrícula común en **EPSG:6933**, proyección de igual área con origen global (0, 0) y paso de 120 m en ambos ejes. Cada píxel completo representa 1,44 ha. Las capas finas se agregan por solape espacial. Las capas gruesas se proyectan por vecino más cercano y conservan su soporte espacial original, aunque sus valores se repitan en muchos píxeles de salida. [Agregación y remuestreo en Earth Engine](https://developers.google.com/earth-engine/guides/resample)

| Bandas | Fuente y píxel nominal | Conversión y máscaras |
| --- | --- | --- |
| `elevation_m` | SRTM, 30 m | Elevación en m. Media espacial de los valores válidos. |
| `land_cover` | MapBiomas Paraguay Colección 2, 30 m | `classification_AÑO`, moda ponderada por solape. Código 0 excluido. Se conservan los códigos de MapBiomas. |
| `ls_red`, `ls_nir`, `ls_swir1`, `ndvi`, `ndmi`, `ls_valid_scenes` | Landsat 8/9 C2 L2 T1, 30 m | SR = DN × 0,0000275 − 0,2. Se excluyen relleno, nubes, cirros, sombras, nieve y QA_RADSAT distinto de cero. NDVI usa NIR y rojo. NDMI usa NIR y SWIR1. Ambos usan diferencia dividida por suma, con suma positiva y resultado en [−1, 1]. Media espacial por escena y mediana temporal por banda. |
| `soil_ph_10cm`, `soil_texture_10cm` | OpenLandMap, 250 m | `b10` representa 10 cm. pH en agua = DN / 10. Textura USDA 1–12. |
| `era_t2m_c`, `era_precip_mm`, `era_soil_water` | ERA5-Land mensual, ~11,1 km | Temperatura a 2 m en °C (K − 273,15) y humedad del suelo de 0–7 cm en m³/m³, ponderadas por días. Precipitación en mm/año, suma de acumulados mensuales × 1000 con valores negativos truncados a cero. Se requieren los 12 meses válidos por celda. |
| `pml_et_mm_d`, `pml_ec_mm_d`, `pml_es_mm_d`, `pml_ei_mm_d`, `pml_ew_mm_d` | PML‑V2.2a MODIS, 500 m | DN × 0,01. Media de tasas de las composiciones de aproximadamente 8 días, en mm/día. ET es evapotranspiración, Ec transpiración, Es evaporación del suelo, Ei evaporación por intercepción y Ew evaporación de agua, nieve o hielo según el producto. Se conservan las máscaras de origen y se excluyen negativos. Las tasas pueden promediarse sobre observaciones diferentes por banda. |
| `eco_lst_c`, `eco_valid_scenes` | ECOSTRESS L2T LSTE V002, 70 m | Temperatura superficial en °C (K − 273,15) para tierra despejada con QC estricto. Media espacial por escena y mediana temporal. Las dos bandas se incluyen si la opción está activada y hay al menos un píxel de temperatura válido en el área. |

Catálogos primarios para contrastar las bandas y los IDs. [SRTM](https://developers.google.com/earth-engine/datasets/catalog/USGS_SRTMGL1_003), [MapBiomas Paraguay](https://paraguay.mapbiomas.org/mapas-de-la-coleccion/), [Landsat 8](https://developers.google.com/earth-engine/datasets/catalog/LANDSAT_LC08_C02_T1_L2), [Landsat 9](https://developers.google.com/earth-engine/datasets/catalog/LANDSAT_LC09_C02_T1_L2), [pH](https://developers.google.com/earth-engine/datasets/catalog/OpenLandMap_SOL_SOL_PH-H2O_USDA-4C1A2A_M_v02), [textura](https://developers.google.com/earth-engine/datasets/catalog/OpenLandMap_SOL_SOL_TEXTURE-CLASS_USDA-TT_M_v02), [ERA5-Land](https://developers.google.com/earth-engine/datasets/catalog/ECMWF_ERA5_LAND_MONTHLY_AGGR), [PML](https://developers.google.com/earth-engine/datasets/catalog/projects_pml_evapotranspiration_PML_OUTPUT_PML_V22a), [ECOSTRESS](https://developers.google.com/earth-engine/datasets/catalog/NASA_ECOSTRESS_L2T_LSTE_V2), [límite GAUL](https://developers.google.com/earth-engine/datasets/catalog/FAO_GAUL_2015_level0).

## 3. Crear chunks y abrirlos en QGIS

```powershell
.\.venv\Scripts\python.exe .\crear_chunks.py .\datos\piloto.tif --tile 128 --output .\datos\piloto.gpkg
```

Cada píxel recibe una firma formada por sus códigos categóricos y los tramos de las variables continuas. La intersección de las clases sucede en la cuadrícula común. Después se agrupan píxeles con firma idéntica que comparten lado, incluso entre teselas. Los vecinos diagonales forman componentes separados si carecen de un camino por lados. Los polígonos y acumulados temporales se guardan en SQLite. La fase de unión conserva en memoria la equivalencia entre bordes y la geometría del componente en curso.

De forma predeterminada, se exige `land_cover` y se usan sus clases y las de textura. Los tramos iniciales son 50 m de elevación, 0,2 de NDVI/NDMI, 0,5 de pH, 2 °C, 200 mm de lluvia anual, 0,10 m³/m³ de humedad, y 1 mm/día para Ec y Es. Los tramos de NDVI y NDMI comienzan en −1. Los demás usan origen 0. Son umbrales exploratorios. Los faltantes en las demás capas forman parte de la firma como `null`. Modifica `--require` si quieres exigir otras observaciones. Al pasar cualquier `--category` o `--bin`, se usa la selección explícita completa:

```powershell
.\.venv\Scripts\python.exe .\crear_chunks.py .\datos\piloto.tif --category land_cover --bin ndvi:0.25:-1 --bin pml_ec_mm_d:1 --require land_cover --require ndvi --output .\datos\piloto_simple.gpkg
```

En QGIS, agrega el TIFF como ráster y abre la capa vectorial `chunks` del GeoPackage. Usa **Identificar objetos espaciales** para obtener `chunk_id`, `pixels`, `area_ha`, clases, `mean_*` y `n_*`. El archivo `.chunks.json` documenta la configuración y las unidades para interpretar esos atributos desde una IA local. Para un ancho `w`, origen `o` y código `k`, el tramo comienza en `o + k × w` y termina antes de `o + (k + 1) × w`, con redondeo de la posición fraccional a seis decimales. Los `n_*` cuentan celdas válidas de la cuadrícula común. Varias celdas de 120 m pueden representar una sola observación nativa. Los IDs identifican chunks dentro de cada ejecución y pueden cambiar al variar el tamaño de tesela. `--min-pixels` descarta componentes pequeños tras unir bordes. Con el valor predeterminado de 1 se conserva cada componente.

### Límite de Paraguay y ríos en el GeoPackage

`crear_chunks.py` incluye de forma predeterminada tres capas en el mismo archivo:
`chunks`, `limite_paraguay` y `rios`. Las dos capas de referencia cubren todo
Paraguay y usan EPSG:6933, igual que los chunks. En QGIS selecciona las tres
capas al abrir el GeoPackage y coloca las de referencia por encima de los chunks.
El archivo guarda estilos predeterminados para mostrar el límite oscuro sin
relleno y los ríos en azul. No cambia las bandas del TIFF.

Para aprovechar un TIFF ya descargado sin repetir Earth Engine, usa un nombre
de salida nuevo:

```powershell
python .\crear_chunks.py .\datos\piloto.tif --tile 128 --output .\datos\piloto_con_rios.gpkg
```

Conserva `cartografia_field_shift.py` y la carpeta `cartografia` junto a
`crear_chunks.py`; los datos están incluidos y no necesitan descargas ni
autenticación. La fuente es Natural Earth 1:10 millones: ríos principales y
límite de referencia nacional, no una red completa de arroyos ni una delimitación
oficial. El piloto puede no contener ningún río de esta fuente. La procedencia
y el recorte están documentados en `cartografia/LEEME.md` y en `.chunks.json`.
Usa `--sin-cartografia` si necesitas generar solamente la capa `chunks`.

### Arroyos medianos/grandes, lagos y embalses

Para mayor detalle que Natural Earth, descarga una vez la hidrografía usando
tu proyecto autenticado de Earth Engine:

```powershell
python .\exportar_hidrografia.py --project mapbiomes-para-nsac --output .\datos\hidrografia.gpkg
python .\crear_chunks.py .\datos\piloto.tif --hidrografia .\datos\hidrografia.gpkg --tile 128 --output .\datos\piloto_hidrografia.gpkg
```

El segundo archivo incluye `chunks`, `limite_paraguay`, `rios` y `lagos`;
guarda estilos predeterminados para cauces azules y superficies de agua azules.
Selecciona las cuatro capas al abrirlo en QGIS. Las capas de referencia cubren
el país completo, aunque el TIFF sea un piloto. No se cambia el TIFF ni se
necesita repetir su exportación. Las siguientes ejecuciones pueden reutilizar
`hidrografia.gpkg` sin autenticación ni red.

La selección inicial usa caudal medio **modelado >= 1 m³/s** (HydroSHEDS Free
Flowing Rivers) como aproximación al tamaño de los cauces; no mide su ancho y
no constituye una clasificación oficial de arroyos. Incluye lagos y embalses
con **superficie >= 1 km²** (HydroLAKES v1.0). Para ajustar los umbrales usa
`--min-caudal` y `--min-lago-km2` en el exportador, con un nombre de salida nuevo.
Las geometrías lacustres que intersectan Paraguay se conservan completas,
incluidas sus partes fronterizas. Los ríos se recortan al contorno nacional
con margen de 0,02 grados. Los atributos de caudal, cuenca y superficie se
conservan en el GeoPackage. Las fuentes son históricas/modeladas y no
representan necesariamente la fecha ni el estado de agua del TIFF.

Se consultan estas colecciones (se necesita acceso a ambas desde tu cuenta):

- `WWF/HydroSHEDS/v1/FreeFlowingRivers`:
  https://developers.google.com/earth-engine/datasets/catalog/WWF_HydroSHEDS_v1_FreeFlowingRivers
- `projects/sat-io/open-datasets/HydroLakes/lake_poly_v10` (catálogo comunitario):
  https://gee-community-catalog.org/projects/hydrolakes/

El archivo `.hidrografia.json` guarda fuentes, umbrales y conteos. Si falla
el acceso a una colección o no hay elementos, el exportador informa el error
y no publica un GeoPackage incompleto. No sustituye silenciosamente los datos
detallados por Natural Earth. Revisa las condiciones y atribuciones de las
fuentes antes de redistribuir los datos descargados.

## Verificación realizada

Se contrastaron las fuentes con los catálogos publicados. El exportador consulta bandas, proyección y cantidad de escenas al iniciar, y verifica dimensiones y bandas al recibir cada tesela. Se comprobó la lógica de chunks con datos sintéticos, cuatro tamaños de tesela, GDAL y escritura real a GeoPackage. La prueba local usó Python 3.12 de QGIS con adaptadores para lectura, etiquetado y poligonización. Queda por ejecutar el piloto completo con las dependencias de Python 3.14 y un proyecto de Earth Engine autenticado.
