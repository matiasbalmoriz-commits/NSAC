# Límite de Paraguay y ríos principales para QGIS

Extrae todo el ZIP. Arrastra `limite_paraguay.geojson` y `rios_paraguay.geojson`
al panel de capas de QGIS. Conserva los archivos `.qml` junto a los GeoJSON:
contienen el contorno oscuro sin relleno y los ríos azules. Sitúa ambas capas
por encima del TIFF y de los chunks. Guarda tu proyecto para conservarlas.

Para aplicar los colores explícitamente, abre Complementos > Consola de Python,
activa Mostrar editor, abre `agregar_a_qgis.py` y ejecútalo. Selecciona
`limite_paraguay.geojson` en el diálogo. El script añade ambas capas con sus
colores; conserva el encuadre del mapa y no modifica el TIFF ni los chunks.
Este script requiere el Python de QGIS; no se ejecuta en PowerShell ni en `.venv`.

Fuente: Natural Earth, dominio público, escala 1:10 millones.
https://www.naturalearthdata.com/about/terms-of-use/
Datos: https://github.com/nvkelso/natural-earth-vector
Revisión: ca96624a56bd078437bca8184e78163e5039ad19
Capas originales: ne_10m_admin_0_countries, ne_10m_rivers_lake_centerlines.

Se seleccionó Paraguay (ADM0_A3=PRY) y se recortaron los ríos a su entorno,
con un margen de 0,02 grados para conservar cauces fronterizos cuya geometría
se generalizó independientemente del límite. CRS: WGS84 / EPSG:4326.
Se conservan los nombres de la fuente, que puede agrupar varios cauces bajo
un mismo nombre. La geometría del cauce junto a Asunción está incluida.

Esta cartografía es de referencia nacional, no una delimitación oficial ni una
red exhaustiva de arroyos. El área piloto puede no contener ninguno de estos
ríos principales. Para detalle local se necesita otra fuente hidrográfica.
