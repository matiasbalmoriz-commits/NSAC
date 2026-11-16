"""Análisis zonal exacto por centros de píxel, sin cargar el GeoTIFF completo."""
import math
from collections import Counter
from pathlib import Path

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.warp import reproject, transform, transform_bounds
from rasterio.windows import Window


# Los nombres proceden de los exportadores del proyecto; nunca se infieren por índice.
CATALOGO = {
    'elevation_m': ('SRTM', 'Elevación', 'm', 'continuous'),
    'land_cover': ('MapBiomas', 'Cobertura y uso del suelo', 'clase', 'category'),
    'ls_red': ('Landsat 8/9', 'Reflectancia roja', '1', 'continuous'),
    'ls_nir': ('Landsat 8/9', 'Reflectancia infrarroja cercana', '1', 'continuous'),
    'ls_swir1': ('Landsat 8/9', 'Reflectancia SWIR1', '1', 'continuous'),
    'ndvi': ('Landsat 8/9', 'NDVI', '1', 'continuous'),
    'ndmi': ('Landsat 8/9', 'NDMI', '1', 'continuous'),
    'ls_valid_scenes': ('Landsat 8/9', 'Escenas válidas', 'escenas', 'count'),
    'soil_ph_10cm': ('OpenLandMap', 'pH a 10 cm', 'pH', 'continuous'),
    'soil_texture_10cm': ('OpenLandMap', 'Textura a 10 cm', 'clase USDA', 'category'),
    'era_t2m_c': ('ERA5-Land', 'Temperatura del aire', '°C', 'continuous'),
    'era_precip_mm': ('ERA5-Land', 'Precipitación anual', 'mm/año', 'continuous'),
    'era_soil_water': ('ERA5-Land', 'Humedad del suelo', 'm3/m3', 'continuous'),
    'eco_lst_c': ('ECOSTRESS', 'Temperatura superficial', '°C', 'continuous'),
    'eco_valid_scenes': ('ECOSTRESS', 'Escenas válidas', 'escenas', 'count'),
    'dentro_paraguay_fao': ('FAO', 'Dentro de Paraguay', '1', 'category'),
    'dentro_paraguay_natural_earth': ('Natural Earth', 'Dentro de Paraguay', '1', 'category'),
    'presencia_rio': ('HydroSHEDS', 'Presencia de río', '1', 'category'),
    'caudal_m3_s': ('HydroSHEDS', 'Caudal', 'm3/s', 'continuous'),
    'cuenca_aguas_arriba_km2': ('HydroSHEDS', 'Cuenca aguas arriba', 'km2', 'continuous'),
    'presencia_lago': ('HydroLAKES', 'Presencia de lago', '1', 'category'),
    'area_lago_km2': ('HydroLAKES', 'Superficie del lago', 'km2', 'continuous'),
}
for componente in ('et', 'ec', 'es', 'ei', 'ew'):
    CATALOGO[f'pml_{componente}_mm_d'] = ('PML', f'Evapotranspiración {componente.upper()}', 'mm/día', 'continuous')


class ErrorAnalisis(ValueError):
    def __init__(self, mensaje, estado=400):
        super().__init__(mensaje)
        self.estado = estado


def validar_dataset(src):
    if src.driver != 'GTiff' or not 1 <= src.count <= 27:
        raise ErrorAnalisis('Se requiere un GeoTIFF de 1 a 27 bandas.')
    if not src.crs or abs(src.transform.determinant) == 0:
        raise ErrorAnalisis('El GeoTIFF necesita CRS y una transformación geográfica válida.')
    if any(np.issubdtype(np.dtype(tipo), np.complexfloating) for tipo in src.dtypes):
        raise ErrorAnalisis('Las bandas complejas no están admitidas.')


def bandas(src):
    resultado = []
    for i in src.indexes:
        nombre = src.descriptions[i - 1] or f'banda_{i}'
        tags = src.tags(i)
        fuente, titulo, unidad, tipo = CATALOGO.get(nombre, ('Sin identificar', nombre, '', 'continuous'))
        resultado.append(dict(indice=i, nombre=nombre, titulo=titulo, fuente=fuente,
                              unidad=src.units[i - 1] or tags.get('unit') or unidad,
                              tipo=tags.get('kind', tipo), identificada=nombre in CATALOGO,
                              escala=src.scales[i - 1], offset=src.offsets[i - 1]))
    return resultado


def metadatos(ruta):
    with rasterio.open(ruta) as src:
        validar_dataset(src)
        listado = bandas(src)
        avisos = []
        if src.count not in (25, 27):
            avisos.append(f'Archivo parcial: {src.count} bandas; el conjunto esperado contiene 25 o 27.')
        if any(not b['identificada'] for b in listado):
            avisos.append('Hay bandas sin nombre reconocido. No se asignan fuentes por su posición.')
        banda_vista = next((b['indice'] for b in listado if b['nombre'] == 'elevation_m'), 1)
        return dict(archivo=Path(ruta).name, crs=src.crs.to_string(), ancho=src.width,
                    alto=src.height, total_bandas=src.count, bandas=listado, banda_vista=banda_vista,
                    limites_wgs84=list(transform_bounds(src.crs, 'EPSG:4326', *src.bounds, densify_pts=41)),
                    avisos=avisos)


def vista_previa(ruta, info):
    """Genera una imagen WGS84 alineada con las coordenadas de selección."""
    limites = info['limites_wgs84']
    oeste, sur, este, norte = limites
    dx, dy = este - oeste, norte - sur
    if not all(map(math.isfinite, limites)) or dx <= 0 or dy <= 0:
        raise ErrorAnalisis('No se puede mostrar la extensión geográfica del GeoTIFF.', 422)
    proporcion = 900 / max(dx, dy)
    ancho, alto = max(1, round(dx * proporcion)), max(1, round(dy * proporcion))
    transformacion = from_bounds(*limites, ancho, alto)
    valores = np.empty((alto, ancho), dtype='float64')
    banda = info['bandas'][info['banda_vista'] - 1]
    with rasterio.open(ruta) as src:
        factor = min(1, 1800 / max(src.width, src.height))
        columnas = max(1, round(src.width * factor))
        filas = max(1, round(src.height * factor))
        muestra = src.read(banda['indice'], out_shape=(filas, columnas), masked=True, out_dtype='float64')
        nodata = src.nodatavals[banda['indice'] - 1]
        if nodata is not None:
            muestra = np.ma.masked_equal(muestra, nodata, copy=False)
        origen = src.transform * src.transform.scale(src.width / columnas, src.height / filas)
        reproject(muestra.filled(np.nan), valores, src_crs=src.crs, src_transform=origen, src_nodata=np.nan,
                  dst_crs='EPSG:4326', dst_transform=transformacion, dst_nodata=np.nan)
    valores = valores * banda['escala'] + banda['offset']
    validos = np.isfinite(valores)
    rgba = np.zeros((4, alto, ancho), dtype='uint8')
    if validos.any():
        datos = valores[validos]
        minimo, maximo = np.percentile(datos, [2, 98])
        if minimo == maximo:
            minimo, maximo = datos.min(), datos.max()
        if minimo == maximo:
            tonos = np.full(datos.shape, .5)
        else:
            tonos = np.clip((datos - minimo) / (maximo - minimo), 0, 1)
        colores = ((56, 128, 103), (155, 180, 113), (242, 226, 175))
        for i, canal in enumerate(zip(*colores)):
            rgba[i, validos] = np.interp(tonos, [0, .5, 1], canal)
        rgba[3, validos] = 255
    with MemoryFile(ext='.png') as memoria:
        with memoria.open(driver='PNG', width=ancho, height=alto, count=4, dtype='uint8',
                          crs='EPSG:4326', transform=transformacion) as png:
            png.write(rgba)
        return memoria.read()


def rectangulo(peticion):
    if not isinstance(peticion, dict):
        raise ErrorAnalisis('El cuerpo debe ser un objeto JSON.')
    puntos = []
    for nombre in ('pos1', 'pos2'):
        p = peticion.get(nombre)
        if not isinstance(p, dict):
            raise ErrorAnalisis(f'{nombre} debe contener lon y lat.')
        coords = []
        for clave, limite in (('lon', 180), ('lat', 90)):
            valor = p.get(clave)
            if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor) or abs(valor) > limite:
                raise ErrorAnalisis(f'{nombre}.{clave} debe ser un número finito entre {-limite} y {limite}.')
            coords.append(float(valor))
        puntos.append(coords)
    oeste, este = sorted(p[0] for p in puntos)
    sur, norte = sorted(p[1] for p in puntos)
    if oeste == este or sur == norte:
        raise ErrorAnalisis('El rectángulo debe tener ancho y alto mayores que cero.')
    if este - oeste > 180 or sur <= -90 or norte >= 90:
        raise ErrorAnalisis('No se admiten rectángulos que crucen el antimeridiano o toquen los polos.')
    return oeste, sur, este, norte


def ventana(src, limites):
    # Densificar antes de calcular la envolvente en el CRS nativo.
    izquierda, abajo, derecha, arriba = transform_bounds('EPSG:4326', src.crs, *limites, densify_pts=101)
    if not all(math.isfinite(v) for v in (izquierda, abajo, derecha, arriba)):
        raise ErrorAnalisis('El rectángulo no se puede transformar al CRS del archivo.')
    inv = ~src.transform
    puntos = [inv * (x, y) for x in (izquierda, derecha) for y in (abajo, arriba)]
    x0 = max(0, math.floor(min(p[0] for p in puntos)) - 1)
    y0 = max(0, math.floor(min(p[1] for p in puntos)) - 1)
    x1 = min(src.width, math.ceil(max(p[0] for p in puntos)) + 1)
    y1 = min(src.height, math.ceil(max(p[1] for p in puntos)) + 1)
    if x0 >= x1 or y0 >= y1:
        raise ErrorAnalisis('El rectángulo no intersecta el GeoTIFF.', 422)
    return x0, y0, x1, y1


def analizar(ruta, peticion, max_pixeles=5_000_000):
    limites = rectangulo(peticion)
    oeste, sur, este, norte = limites
    with rasterio.open(ruta) as src:
        validar_dataset(src)
        x0, y0, x1, y1 = ventana(src, limites)
        if (x1 - x0) * (y1 - y0) > max_pixeles:
            raise ErrorAnalisis(f'La ventana supera {max_pixeles:,} píxeles. Reduce el rectángulo.', 413)
        listado = bandas(src)
        acumulados = [dict(n=0, media=0., m2=0., minimo=math.inf, maximo=-math.inf,
                           clases=Counter() if b['tipo'] == 'category' else None) for b in listado]
        seleccionados = 0
        for fila in range(y0, y1, 256):
            for columna in range(x0, x1, 256):
                h, w = min(256, y1 - fila), min(256, x1 - columna)
                filas, columnas = np.mgrid[fila:fila+h, columna:columna+w].astype('float64')
                xs, ys = src.transform * (columnas + .5, filas + .5)
                lon, lat = transform(src.crs, 'EPSG:4326', xs.ravel(), ys.ravel())
                lon, lat = np.asarray(lon).reshape(h, w), np.asarray(lat).reshape(h, w)
                dentro = (lon >= oeste) & (lon <= este) & (lat >= sur) & (lat <= norte)
                seleccionados += int(dentro.sum())
                if not dentro.any():
                    continue
                win = Window(columna, fila, w, h)
                for b, acc in zip(listado, acumulados):
                    raw = src.read(b['indice'], window=win, masked=True)
                    validos = dentro & ~np.ma.getmaskarray(raw) & np.isfinite(raw.data)
                    # Comprobar también NoData: una máscara interna puede tener prioridad sobre él.
                    nodata = src.nodatavals[b['indice'] - 1]
                    if nodata is not None:
                        validos &= raw.data != nodata
                    valores = raw.data[validos].astype('float64') * b['escala'] + b['offset']
                    valores = valores[np.isfinite(valores)]
                    n = int(valores.size)
                    if not n:
                        continue
                    media = float(valores.mean())
                    delta = media - acc['media']
                    total = acc['n'] + n
                    acc['m2'] += float(np.sum((valores - media) ** 2)) + delta ** 2 * acc['n'] * n / total
                    acc['media'] += delta * n / total
                    acc['n'] = total
                    acc['minimo'] = min(acc['minimo'], float(valores.min()))
                    acc['maximo'] = max(acc['maximo'], float(valores.max()))
                    if acc['clases'] is not None:
                        unicos, conteos = np.unique(valores, return_counts=True)
                        acc['clases'].update(dict(zip(map(float, unicos), map(int, conteos))))
                        if len(acc['clases']) > 256:
                            acc['clases'] = None
        if not seleccionados:
            raise ErrorAnalisis('No hay centros de píxel dentro del rectángulo. Amplía la selección.', 422)
        salida = []
        for b, acc in zip(listado, acumulados):
            n = acc['n']
            dato = dict(b, validos=n, sin_datos=seleccionados-n,
                        cobertura_pct=100*n/seleccionados, minimo=acc['minimo'] if n else None,
                        maximo=acc['maximo'] if n else None,
                        media=acc['media'] if n and b['tipo'] != 'category' else None,
                        desviacion=math.sqrt(max(0, acc['m2']/n)) if n and b['tipo'] != 'category' else None)
            if b['tipo'] == 'category':
                dato['clases'] = [dict(valor=k, pixeles=v, porcentaje=100*v/n)
                                  for k, v in sorted((acc['clases'] or {}).items())] if n else []
                if acc['clases'] is None:
                    dato['aviso'] = 'Histograma omitido: más de 256 clases distintas.'
            salida.append(dato)
        return dict(archivo=Path(ruta).name, crs_entrada='EPSG:4326',
                    rectangulo=dict(oeste=oeste, sur=sur, este=este, norte=norte),
                    pixeles_seleccionados=seleccionados, total_bandas=src.count,
                    bandas=salida, avisos=[
                        'Estadísticas sobre centros de píxel dentro de la intersección; sin ponderar por superficie.',
                        'Los valores de caudal, cuenca y superficie de lago pueden repetirse entre píxeles; no se suman.',
                        'Los códigos de clases se conservan sin asignar una leyenda no verificada.'
                    ])
