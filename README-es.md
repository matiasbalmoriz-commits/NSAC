# GeoVision: análisis geoespacial local de Paraguay

GeoVision es una aplicación web local creada para explorar y analizar información geoespacial de Paraguay. El proyecto recibe un GeoTIFF multibanda, procesa únicamente el área seleccionada por el usuario y presenta los resultados mediante una interfaz interactiva en el navegador. Su utilidad principal consiste en conectar un conjunto raster complejo con herramientas visuales y analíticas prácticas, sin exigir que el usuario trabaje directamente con un programa GIS ni que cargue todo el dataset en memoria.

La aplicación está organizada alrededor de un backend Python, un frontend web y varios módulos de análisis. El backend lee el raster con Rasterio y realiza cálculos numéricos con NumPy y SciPy. El frontend muestra el mapa, permite seleccionar un área, solicita estadísticas al servidor y presenta los resultados mediante capas, leyendas, informes y descargas. El proyecto también incorpora funciones opcionales para análisis de cultivos, priorización de restauración e informes de suelo y agua.

## Propósito y funcionamiento general

El proyecto está pensado como una herramienta local de apoyo a decisiones. No intenta reemplazar el trabajo de campo, un sistema completo de manejo de fincas ni una plataforma GIS profesional. Su función es ofrecer una forma clara de inspeccionar la información que ya está almacenada en un GeoTIFF y comparar las condiciones existentes dentro de un área elegida.

El flujo principal es el siguiente:

1. El usuario inicia el servidor local y abre la interfaz web.
2. GeoVision lee los metadatos del GeoTIFF e identifica las bandas disponibles.
3. El usuario explora el mapa o selecciona dos puntos geográficos para definir un rectángulo.
4. El servidor transforma el rectángulo al sistema de coordenadas del raster y analiza los píxeles cuyos centros caen dentro de él.
5. La interfaz muestra estadísticas, mapas, informes opcionales y botones de descarga.

El proyecto utiliza el archivo nacional `NSAC1/paraguay_2023_combinado.tif`, aunque el servidor puede recibir otro GeoTIFF compatible mediante el argumento `--geotiff`. La instalación y ejecución estándar son:

```powershell
cd NSAC1
python -m pip install -r requirements.txt
python servidor.py --geotiff ".\paraguay_2023_combinado.tif" --abrir
```

La aplicación se abre en `http://127.0.0.1:8000/`. También se puede usar otro puerto con `--puerto` y limitar el tamaño máximo del área analizada con `--max-pixeles`.

## Arquitectura

[`servidor.py`](NSAC1/servidor.py) es el punto de entrada. Crea un `ThreadingHTTPServer` local, sirve los archivos web, valida las peticiones y conecta cada ruta de la API con la función de análisis correspondiente. También controla la concurrencia, limita el tamaño de las solicitudes, gestiona errores y mantiene en memoria la clave opcional de Nemotron.

[`analizador.py`](NSAC1/analizador.py) es la capa central de procesamiento raster. Valida que el archivo sea un GeoTIFF compatible, lee las descripciones y los metadatos de las bandas, convierte los valores crudos usando escala y offset, ignora NoData y valores inválidos, y calcula estadísticas en ventanas pequeñas. Este enfoque evita cargar todo el raster nacional en memoria. Las bandas continuas producen mínimos, máximos, medias y desviaciones estándar. Las bandas categóricas producen cantidades y porcentajes por clase.

[`mapa.py`](NSAC1/mapa.py) genera la imagen de cobertura, consulta una celda individual y exporta recortes GeoTIFF. El mapa se reproyecta a WGS84 para poder mostrarlo en el navegador, mientras que el análisis continúa utilizando el sistema de coordenadas nativo del raster.

El cliente web se encuentra en [`NSAC1/web/`](NSAC1/web). Sus archivos JavaScript gestionan el mapa, la selección de áreas, las peticiones a la API, las leyendas, las capas de cultivos, los plugins y las descargas. El navegador no lee directamente el GeoTIFF: todos los datos pasan por el servidor local.

## Capacidades principales

GeoVision reúne varias funciones relacionadas:

- **Exploración del mapa:** permite ver la cobertura del suelo, acercarse, desplazarse y consultar celdas individuales.
- **Análisis de áreas:** calcula estadísticas de todas las bandas disponibles dentro de un rectángulo.
- **Evaluación preliminar de cultivos:** compara los datos del área con un catálogo de referencia y muestra una capa de candidatos. Es una ayuda analítica, no una recomendación agronómica definitiva.
- **Priorización de restauración:** identifica áreas candidatas cercanas a agua cartografiada o corredores ecológicos mediante reglas raster locales.
- **Informes opcionales:** carga indicadores de suelo y agua mediante plugins aislados.
- **Exportación:** permite descargar estadísticas en JSON y recortes GeoTIFF para continuar el trabajo.

La capa de cultivos implementada en [`mapa_cultivos.py`](NSAC1/mapa_cultivos.py) es solo uno de los componentes del sistema completo. Utiliza los resultados del análisis raster y produce una imagen coloreada con límites geográficos y leyenda. El proyecto presenta este resultado como una comparación preliminar e incluye límites para evitar que la evidencia raster se confunda con un diagnóstico completo del terreno.

## API y flujo de datos

El servidor ofrece rutas como `/api/info`, `/api/cobertura.png`, `/api/celda`, `/api/analizar`, `/api/cultivos`, `/api/restauracion` y `/api/recorte`. También existen rutas para configurar Nemotron y administrar los plugins. Las peticiones JSON deben indicar `Content-Type: application/json`.

Cuando llega una petición, el servidor valida su origen, interpreta las coordenadas, comprueba el límite de píxeles, abre el raster y ejecuta el módulo correspondiente. Los errores se devuelven como JSON junto con un código HTTP. El servidor acepta únicamente peticiones locales y permite un análisis principal a la vez para mantener controlado el consumo de memoria y procesamiento.

Las explicaciones opcionales de cultivos se generan mediante un servicio compatible con Chat Completions. La API key se puede cargar desde la interfaz o proporcionar mediante variables de entorno. La clave no se escribe en los archivos del proyecto y el ejecutor de plugins elimina las variables de API key antes de iniciar herramientas opcionales.

## Dependencias y límites

Las dependencias de [`NSAC1/requirements.txt`](NSAC1/requirements.txt) son NumPy, Rasterio y SciPy. NumPy trabaja con arrays y estadísticas, Rasterio permite leer GeoTIFF y reproyectar datos, y SciPy aporta operaciones espaciales utilizadas por algunos análisis opcionales.

El proyecto informa lo que existe en el raster; no inventa mediciones faltantes. Los resultados se basan en centros de píxel, no se ponderan automáticamente por superficie geográfica y pueden tener cobertura parcial o datos ausentes. Las variables climáticas anuales sirven como contexto, no como garantía sobre una campaña específica. Cualquier decisión agrícola o de restauración debe contrastarse con observaciones actuales de campo y asesoría local competente.

Las pruebas pueden ejecutarse con:

```powershell
python -m unittest discover -s NSAC1/tests -v
```
