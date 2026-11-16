"""Análisis zonal exacto por centros de píxel, sin cargar el GeoTIFF completo."""
import math
from collections import Counter
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import transform, transform_bounds
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
ASSET_MAPBIOMAS_C2 = 'projects/mapbiomas-public/assets/paraguay/collection2/mapbiomas_paraguay_collection2_integration_v1'
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
        return dict(archivo=Path(ruta).name, crs=src.crs.to_string(), ancho=src.width,
                    alto=src.height, total_bandas=src.count, bandas=listado,
                    limites_wgs84=list(transform_bounds(src.crs, 'EPSG:4326', *src.bounds, densify_pts=41)),
                    avisos=avisos)


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


def centros_en_rectangulo(src, win, limites):
    oeste, sur, este, norte = limites
    h, w = int(win.height), int(win.width)
    filas, columnas = np.mgrid[:h, :w].astype('float64')
    xs, ys = src.window_transform(win) * (columnas + .5, filas + .5)
    lon, lat = transform(src.crs, 'EPSG:4326', xs.ravel(), ys.ravel())
    lon, lat = np.asarray(lon).reshape(h, w), np.asarray(lat).reshape(h, w)
    return (lon >= oeste) & (lon <= este) & (lat >= sur) & (lat <= norte)


def valores_ventana(src, indice, win):
    raw = src.read(indice, window=win, masked=True)
    valores = raw.data.astype('float64') * src.scales[indice - 1] + src.offsets[indice - 1]
    invalidos = np.ma.getmaskarray(raw) | ~np.isfinite(valores)
    nodata = src.nodatavals[indice - 1]
    if nodata is not None:
        invalidos |= raw.data == nodata
    valores[invalidos] = np.nan
    return valores


def mascara_productiva(src, indices, win, dentro):
    cobertura = valores_ventana(src, indices['land_cover'], win)
    contexto = dentro.copy()
    if 'dentro_paraguay_fao' in indices:
        contexto &= valores_ventana(src, indices['dentro_paraguay_fao'], win) == 1
    cobertura[~contexto] = np.nan
    productivo = np.isin(cobertura, (15, 18))
    for nombre in ('presencia_rio', 'presencia_lago'):
        if nombre in indices:
            productivo &= valores_ventana(src, indices[nombre], win) != 1
    return productivo, cobertura


def analizar(ruta, peticion, max_pixeles=5_000_000, solo_productivo=False):
    limites = rectangulo(peticion)
    oeste, sur, este, norte = limites
    with rasterio.open(ruta) as src:
        validar_dataset(src)
        x0, y0, x1, y1 = ventana(src, limites)
        if (x1 - x0) * (y1 - y0) > max_pixeles:
            raise ErrorAnalisis(f'La ventana supera {max_pixeles:,} píxeles. Reduce el rectángulo.', 413)
        listado = bandas(src)
        indices = {b['nombre']: b['indice'] for b in listado}
        original = src.tags(indices['land_cover']).get('original', '') if 'land_cover' in indices else ''
        if solo_productivo and ('land_cover' not in indices or
                                src.tags(indices['land_cover']).get('asset') != ASSET_MAPBIOMAS_C2):
            raise ErrorAnalisis('El ranking requiere la banda de MapBiomas Paraguay, colección 2.', 422)
        acumulados = [dict(n=0, media=0., m2=0., minimo=math.inf, maximo=-math.inf,
                           clases=Counter() if b['tipo'] == 'category' else None) for b in listado]
        seleccionados = total_area = 0
        conteos_agricolas = dict.fromkeys((18, 15, 12, 11), 0)
        for fila in range(y0, y1, 256):
            for columna in range(x0, x1, 256):
                h, w = min(256, y1 - fila), min(256, x1 - columna)
                win = Window(columna, fila, w, h)
                dentro = centros_en_rectangulo(src, win, limites)
                total_area += int(dentro.sum())
                if solo_productivo and dentro.any():
                    dentro, cobertura = mascara_productiva(src, indices, win, dentro)
                    for codigo in conteos_agricolas:
                        conteos_agricolas[codigo] += int(np.count_nonzero(cobertura == codigo))
                seleccionados += int(dentro.sum())
                if not dentro.any():
                    continue
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
            if total_area and solo_productivo:
                raise ErrorAnalisis('Selecciona celdas de agricultura o pastura sembrada para recomendar cultivos. '
                                    'Los pastizales naturales e inundables se consideran como contexto de conservación.', 422)
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
        detalle = {'coberturas_agricolas': conteos_agricolas} if solo_productivo else {}
        return dict(archivo=Path(ruta).name, crs_entrada='EPSG:4326',
                    rectangulo=dict(oeste=oeste, sur=sur, este=este, norte=norte),
                    anio_cobertura=int(original[-4:]) if original.startswith('classification_') and original[-4:].isdigit() else None,
                    hectareas_por_celda=abs(src.transform.determinant)/10_000 if src.crs.to_epsg() == 6933 else None,
                    pixeles_en_rectangulo=total_area,
                    pixeles_seleccionados=seleccionados, total_bandas=src.count,
                    bandas=salida, avisos=[
                        'Estadísticas sobre centros de píxel dentro de la intersección; sin ponderar por superficie.',
                        'Los valores de caudal, cuenca y superficie de lago pueden repetirse entre píxeles; no se suman.',
                        'Los códigos de clases se conservan sin asignar una leyenda no verificada.'
                    ], **detalle)
