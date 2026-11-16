# Analizador local de GeoTIFF

Servidor Python con interfaz HTML, CSS y JavaScript. Analiza un rectángulo definido por dos esquinas sobre un GeoTIFF de **1 a 27 bandas**. El conjunto completo de este proyecto contiene 27 bandas, o 25 si falta ECOSTRESS.

## Ejecutar en PowerShell

Desde la carpeta que contiene `servidor.py` y `paraguay_2023_combinado.tif`. La primera vez, si aún no existe el entorno virtual:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Para iniciar el servidor y abrir la interfaz:

```powershell
.\.venv\Scripts\python.exe servidor.py --abrir
```

El servidor abre el TIFF de esta carpeta de forma predeterminada. Para usar otro archivo, añade `--geotiff 'C:\ruta\archivo.tif'`. Si ya tienes NumPy y Rasterio en tu instalación de Python, puedes ejecutar `python servidor.py --abrir`.

Abre [la interfaz local](http://127.0.0.1:8000) mientras esté activo el servidor. Arrastra sobre la vista previa de elevación o escribe ambas posiciones y pulsa **Analizar rectángulo**. Si el TIFF no incluye elevación, se muestra su primera banda. La tabla muestra las estadísticas de todas las bandas y, debajo, la distribución de las clases. Usa **Descargar JSON** para guardar el resultado y `Ctrl+C` en PowerShell para detener el servidor.

Opciones adicionales: `--puerto 8001`, `--max-pixeles 10000000`. El servidor escucha únicamente en `127.0.0.1`, atiende un análisis a la vez y abre el archivo en modo de lectura.

## API

- `GET /api/info`: archivo, CRS, tamaño, extensión WGS84, catálogo de bandas y advertencias.
- `GET /api/vista.png`: vista previa en PNG alineada con la extensión WGS84 de `/api/info`. `banda_vista` indica el índice de la banda mostrada.
- `POST /api/analizar`: analiza las dos posiciones y devuelve JSON al terminar.

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
