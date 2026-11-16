# GeoVision

Explorador local de cobertura del suelo, consulta por celda y análisis por área sobre un GeoTIFF de **1 a 27 bandas**. Usa por defecto el GeoTIFF nacional de Paraguay 2023 con 27 bandas a 480 m.

## Ejecutar en PowerShell

Abre PowerShell en la raíz del repositorio y ejecuta:

```powershell
cd NSAC1
python servidor.py --geotiff ".\paraguay_2023_combinado.tif" --abrir
```

El parámetro `--abrir` abre GeoVision en [http://127.0.0.1:8000/](http://127.0.0.1:8000/). Si el navegador no se abre, entra a esa dirección manualmente. Mantén abierta la terminal mientras usas la aplicación y pulsa `Ctrl+C` para detener el servidor.

Si faltan dependencias, crea un entorno virtual dentro de `NSAC1` e instala las dependencias:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe servidor.py --geotiff ".\paraguay_2023_combinado.tif" --abrir
```

Puedes abrir otro GeoTIFF con `--geotiff 'C:\ruta\archivo.tif'`. Si el puerto 8000 ya está ocupado, usa `python servidor.py --puerto 8005 --geotiff ".\paraguay_2023_combinado.tif" --abrir`.

## Analizar cultivos en GeoVision

1. Para explorar el mapa, consultar celdas o analizar las bandas, abre GeoVision directamente. Para obtener recomendaciones de cultivos, entra a **Configurar Nemotron**, carga tu API key de NVIDIA en el campo correspondiente, pulsa **Guardar clave** y comprueba que **Probar conexión** indique que funciona. La API key es necesaria para solicitar el ranking de cultivos al modelo.
2. Elige **Dibujar área** y arrastra un rectángulo en el mapa, o introduce sus esquinas en **Coordenadas WGS84**. Pulsa **Analizar área** para obtener las estadísticas de la selección.
3. Elige **Monocultivo** o **Rotación** y pulsa **Analizar cultivos**. Consulta la paleta de los 20 cultivos y la leyenda de recomendaciones para identificar los colores de la zona. La soja, por ejemplo, conserva su color en cualquier selección en la que se recomiende. Usa **Acercar a la zona** para ver el detalle.

## Herramientas opcionales

Después de **Analizar área**, abre **Herramientas opcionales**. **Perfil de suelo** resume el pH y la textura de la selección. **Indicadores de agua** presenta lluvia, evapotranspiración y el índice NDMI cuando hay datos. Para usar cualquiera, marca **Activar** y pulsa **Generar informe**. Desmarca **Activar** para deshabilitarla durante la sesión del servidor.

GeoVision carga cada herramienta al solicitar su informe y la ejecuta en un proceso separado con un límite de tiempo. El mapa y el análisis de cultivos funcionan con los plugins desactivados. Las herramientas se registran en `plugins_geovision.py` y sus módulos se guardan en `extensiones/`. Un módulo implementa `ejecutar(ruta, datos, max_pixeles)` y devuelve un informe con `titulo`, `resumen`, `indicadores` y `notas`. Las herramientas incluidas leen el GeoTIFF local.

En **Explorar** puedes acercarte, desplazarte y consultar una celda con un clic. Los botones de descarga entregan las estadísticas en JSON y el recorte espacial en GeoTIFF.

La leyenda resalta en rojo las **Zonas urbanizadas** de la capa auxiliar [GHS-SMOD 2020](https://human-settlement.emergency.copernicus.eu/ghs_smod2023.php), con resolución de 1 km. Incluye centros urbanos y sus áreas suburbanas según esa fuente. En las estadísticas, el código 22 sigue identificando la clase original de MapBiomas.

Después de analizar un rectángulo, **Mostrar zonas de restauración** calcula en local candidatas en agricultura o pastura. Marca las celdas contiguas a ríos, lagos o agua de MapBiomas y rutas cortas que conectan fragmentos de vegetación leñosa. El corredor puede cruzar hasta ocho celdas candidatas y considera el contexto alrededor del rectángulo. El mapa sirve para revisar zonas prioritarias en campo.

**Análisis de cultivos** compara 20 fichas de referencia bajo el supuesto de secano. En **Monocultivo** muestra cinco candidatos principales y cinco menos aptos. Cada candidato principal incluye un abono verde, su época y su función. En **Rotación**, la opción recomendada, el informe muestra la secuencia de cultivos por campaña. El color de cada cultivo coincide con la paleta y se dibuja opaco sobre el mapa.

La leyenda reúne agricultura, pastura sembrada, pastizal natural y pastizal inundable con colores propios. El análisis considera los cuatro tipos de cobertura. Las recomendaciones se asignan a celdas de agricultura o pastura sembrada elegibles. En monocultivo, el mapa evalúa grupos de 2 × 2 celdas y colorea las celdas elegibles de cada grupo con su mejor candidato del ranking, según pH y lluvia. La leyenda indica los grupos con ajuste condicionado. En rotación, el color indica un posible cultivo inicial. Comprueba condiciones como drenaje y temperatura por campaña antes de decidir qué sembrar.

Puedes reemplazar o quitar la clave en **Configurar Nemotron**. La clave queda en la memoria del servidor local hasta que se reinicie. El proveedor verifica la clave cuando solicitas un ranking. [Documentación de NVIDIA Nemotron](https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3_5-bolt-e4b-infer)

El botón **Probar conexión** comprueba la API desde el servidor local. Con una clave guardada envía una consulta breve al mismo modelo y verifica que responda en JSON, mostrando el tiempo y el estado HTTP. Sin clave consulta la disponibilidad de la API y solicita guardarla para completar la comprobación. La prueba consume una pequeña consulta al proveedor.

También puedes cargar la API key al iniciar el servidor desde PowerShell 7. Esta alternativa evita escribirla en el README o en archivos del proyecto:

```powershell
$env:NVIDIA_API_KEY = Read-Host -MaskInput 'Clave de NVIDIA'
.\iniciar.ps1 --abrir
```

Para usar un servicio propio compatible con Chat Completions, configura `NEMOTRON_BASE_URL` (incluye `/v1`), `NEMOTRON_MODEL` y, si corresponde, `NEMOTRON_API_KEY`. La clave se usa en el servidor. Se envían las estadísticas seleccionadas, sin rutas locales, coordenadas ni el GeoTIFF. También se puede ejecutar `nemotron.py RUTA_GEOTIFF --bbox O S E N --modo monocultivo` con el mismo entorno de Python. Sin `--modo`, se evalúa rotación.

Opciones: `--puerto 8001`, `--max-pixeles 10000000`, `--abrir`. El servidor escucha únicamente en `127.0.0.1`, atiende un análisis a la vez y no modifica el archivo. No requiere QGIS ni Earth Engine para analizar un TIFF ya generado. No abrir `index.html` directamente: usar la URL del servidor.

## Funciones principales

- **Explorar mapa:** muestra la cobertura del suelo, permite acercar y desplazar el mapa, y consulta los valores de una celda.
- **Analizar área:** calcula estadísticas de las bandas dentro del rectángulo seleccionado, incluyendo cobertura, valores válidos, mínimos, máximos, medias y clases categóricas.
- **Analizar cultivos:** genera recomendaciones de monocultivo o rotación a partir de las condiciones de la zona. Requiere una API key válida de NVIDIA para consultar Nemotron.
- **Herramientas opcionales:** genera informes de perfil de suelo e indicadores de agua cuando se activan.
- **Zonas de restauración:** identifica áreas candidatas cercanas a agua, vegetación leñosa y corredores de conexión.
- **Descargas:** exporta las estadísticas en JSON y el recorte seleccionado como GeoTIFF.

## Dependencias

Las dependencias están definidas en [requirements.txt](requirements.txt):

- `numpy>=1.26,<3`: operaciones numéricas y manejo de matrices.
- `rasterio>=1.4,<2`: lectura de GeoTIFF, metadatos, ventanas y reproyección raster.
- `scipy>=1.11,<2`: cálculos científicos utilizados por el análisis espacial y las herramientas auxiliares.

Instálalas con:

```powershell
python -m pip install -r requirements.txt
```

## API

- `GET /api/info`: archivo, CRS, tamaño, extensión WGS84, catálogo de bandas y advertencias.
- `GET /api/cobertura.png`: capa de cobertura georreferenciada según la extensión incluida en `/api/info`.
- `GET /api/celda?lon=-57.62&lat=-25.32`: valores de las bandas en la celda consultada.
- `POST /api/analizar`: analiza las dos posiciones y devuelve JSON al terminar.
- `POST /api/cultivos`: analiza las dos posiciones con `modo` igual a `rotacion` (por defecto) o `monocultivo`. Devuelve el ranking, las sugerencias de manejo y la capa PNG de cultivos por zona.
- `GET /api/nemotron/config`: indica si Nemotron está configurado, de dónde proviene su configuración y si la interfaz permite editarla. La respuesta solo contiene el estado.
- `POST /api/nemotron/probar`: recibe `{}` y devuelve el diagnóstico de conexión, `funcional`, `api_accesible`, modelo, latencia y estado HTTP del proveedor cuando está disponible.
- `POST /api/nemotron/config`: guarda la clave de NVIDIA en memoria a partir de `{"clave":"..."}`. Una clave vacía elimina la definida en la interfaz y vuelve a la del entorno, si existe.
- `POST /api/restauracion`: devuelve la capa verde como PNG con su extensión WGS84 y los totales por criterio.
- `POST /api/recorte`: descarga un GeoTIFF con las bandas de origen para las mismas dos posiciones.

```javascript
const respuesta = await fetch('http://127.0.0.1:8000/api/analizar', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    pos1: {lon: -57.65, lat: -25.35},
    pos2: {lon: -57.60, lat: -25.30}
  })
});
const resultado = await respuesta.json();
if (!respuesta.ok) throw new Error(resultado.error);
console.log(resultado);
```

Este ejemplo JavaScript debe ejecutarse desde la interfaz servida por el mismo servidor. Las peticiones de otros orígenes se rechazan; clientes Python o PowerShell pueden consultar directamente. Para integrar una web alojada en otro dominio será necesario adaptar explícitamente el despliegue y la política de origen.

```powershell
$consulta = @{pos1=@{lon=-57.65; lat=-25.35}; pos2=@{lon=-57.60; lat=-25.30}} | ConvertTo-Json
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/analizar' -Method Post -ContentType 'application/json' -Body $consulta
```

Todas las coordenadas de entrada son **EPSG:4326**, longitud y latitud en grados. Se pueden invertir las esquinas. No se admite cruzar el antimeridiano ni tocar los polos. Cada banda devuelve índice, nombre, fuente, unidad, tipo, escala, offset, cantidad de píxeles válidos y sin datos, cobertura porcentual, mínimo y máximo. Las bandas continuas y de conteo incluyen media y desviación estándar poblacional. Las categóricas incluyen clases con cantidades y porcentaje respecto a sus píxeles válidos, sin una media de códigos.

Errores JSON con `error`: 400 entrada inválida; 403 origen o Host inválido; 404 ruta inexistente; 413 ventana demasiado grande o cuerpo excesivo; 415 formato incorrecto; 422 sin intersección o sin centros de píxel; 429 otro análisis activo; 500 error de lectura/procesamiento (detalle en consola).

## Criterios y límites

- Se leen ventanas de hasta 256 × 256, una banda a la vez, usando la resolución original, sin muestreo ni reproyección de los valores. La ventana total tiene un límite configurable de cinco millones de píxeles por defecto.
- Se transforma la envolvente del rectángulo al CRS nativo, densificando sus bordes; después se transforma cada centro de píxel a WGS84 para comprobar si está dentro del rectángulo. Admite cuadrículas afines rotadas. Destinado a los CRS de Paraguay; no es una herramienta para regiones polares o que crucen el antimeridiano.
- Se excluyen NoData, máscaras inválidas, NaN e infinitos. Se aplica `valor_crudo * escala + offset` del TIFF. Los exportadores existentes ya convierten sus valores a unidades físicas; no se repiten conversiones de Landsat, pH, PML o temperatura.
- Las estadísticas representan la intersección con el TIFF. No se añade como NoData la parte exterior al archivo. Cobertura = válidos / centros seleccionados dentro del TIFF.
- No se recorta automáticamente por límites de Paraguay ni por observaciones válidas: las bandas FAO, Natural Earth y escenas válidas se reportan como datos independientes. Un cero válido se conserva.
- Se cuentan píxeles, sin ponderar por superficie. No se informa hectáreas ni áreas geodésicas. Los valores de área de lago, caudal y cuenca pueden repetirse en muchos píxeles y no se suman; no equivalen a contar entidades únicas.
- Los histogramas categóricos admiten hasta 256 clases. Si se excede, se omite el histograma completo con una advertencia. No se asignan etiquetas de MapBiomas sin una leyenda confirmada de la colección utilizada.
- Los nombres de banda se leen de sus descripciones; el orden nunca se usa para adivinar fuentes. Si faltan, se muestra `banda_N` y una advertencia. Se admiten conjuntos parciales de 1 a 27 bandas. No hay autenticación, carga de archivos, trabajos en segundo plano ni preparación para exposición pública.

Referencias técnicas: [lectura por ventanas de Rasterio](https://rasterio.readthedocs.io/en/stable/topics/windowed-rw.html), [reproyección y envolventes](https://rasterio.readthedocs.io/en/stable/topics/reproject.html), [escala y offset en GDAL](https://gdal.org/en/stable/doxygen/classGDALRasterBand.html).

## Comprobación

```powershell
python -m unittest discover -s tests -v
```

Las pruebas generan GeoTIFF temporales; no alteran los datos del proyecto.
