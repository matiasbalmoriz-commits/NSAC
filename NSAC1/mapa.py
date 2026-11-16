"""Vista de cobertura, consulta de celdas y exportación del área seleccionada."""
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.warp import reproject, transform, transform_bounds
from rasterio.windows import Window

from analizador import ASSET_MAPBIOMAS_C2, ErrorAnalisis, bandas, centros_en_rectangulo, rectangulo, ventana


# Códigos de la leyenda de MapBiomas Paraguay, colección 2 (CC BY 4.0).
FUENTE_LEYENDA = 'https://paraguay.stg.mapbiomas.org/wp-content/uploads/sites/9/2026/09/2.Cod_Leyenda-ES-PRY.pdf'
MAPA_URBANO = Path(__file__).resolve().parent / 'ghs_smod_paraguay_2020.tif'
LEYENDA_URBANA = dict(codigo='urbano_ghsl', nombre='Zonas urbanizadas', color='#d4271e',
                     fuente='https://human-settlement.emergency.copernicus.eu/ghs_smod2023.php',
                     atribucion='GHS-SMOD 2020 · Comisión Europea (JRC) · CC BY 4.0')
CLASES_URBANAS = (21, 22, 23, 30)
CLASES = {
    1: ('Vegetación leñosa natural', '#1f8d49'), 3: ('Leñosas cerradas', '#1f8d49'),
    4: ('Leñosas abiertas', '#7dc975'), 6: ('Leñosas inundables', '#007785'),
    9: ('Forestaciones', '#ffefc3'), 10: ('Vegetación herbácea natural', '#d6bc74'),
    11: ('Pastizales inundables', '#519799'), 12: ('Pastizal', '#d6bc74'),
    14: ('Agropecuario', '#ffefc3'), 15: ('Pastura', '#edde8e'), 18: ('Agricultura', '#e974ed'),
    22: ('Área sin vegetación', '#d4271e'), 26: ('Cuerpo de agua', '#2532e4'),
    27: ('No observado', '#ffffff'),
}


@lru_cache(maxsize=2)
def cobertura(ruta, version):
    with rasterio.open(ruta) as src:
        if 'land_cover' not in src.descriptions:
            return None, None
        index = src.descriptions.index('land_cover') + 1
        mayor = max(src.width, src.height, 1)
        w, h = (max(1, round(dim * min(1, 2048/mayor))) for dim in (src.width, src.height))
        limites = transform_bounds(src.crs, 'EPSG:4326', *src.bounds, densify_pts=41)
        grid = from_bounds(*limites, w, h)
        data = np.full((h, w), np.nan, dtype='float32')
        reproject(rasterio.band(src, index), data, dst_crs='EPSG:4326',
                  dst_transform=grid, dst_nodata=np.nan)
        data = data.astype('float64') * src.scales[index - 1] + src.offsets[index - 1]
        tags = src.tags(index)
        oficial = tags.get('asset') == ASSET_MAPBIOMAS_C2
        rgba = np.zeros((4, h, w), dtype='uint8')
        leyenda = []
        urbano = None
        if oficial and MAPA_URBANO.is_file():
            clases_asentamiento = np.zeros((h, w), dtype='int16')
            with rasterio.open(MAPA_URBANO) as asentamiento:
                reproject(rasterio.band(asentamiento, 1), clases_asentamiento, dst_crs='EPSG:4326',
                          dst_transform=grid, dst_nodata=0)
            # Sombrea el dominio urbano de GHSL dentro de la cobertura de Paraguay, conservando el agua de MapBiomas.
            urbano = np.isin(clases_asentamiento, CLASES_URBANAS) & np.isfinite(data) & (data != 26)
        alternos = ('#5f836d', '#9f7caf', '#d5ac6e', '#2a8294', '#a55a61')
        for i, codigo in enumerate(np.unique(data[np.isfinite(data)])):
            nombre, color = (CLASES.get(codigo) if oficial else None) or (f'Código {codigo:g}', alternos[i % len(alternos)])
            clase = dict(codigo=float(codigo), nombre=nombre, color=color)
            leyenda.append(clase)
            if urbano is not None and codigo == 22:
                clase['visible'] = False
                # El código se conserva para identificar el dato original en celdas y estadísticas.
                color = '#e1e4df'
                clase['color'] = color
            rgb = tuple(bytes.fromhex(color[1:]))
            rgba[:, data == codigo] = np.asarray((*rgb, 255))[:, None]
        if urbano is not None and urbano.any():
            rgb = tuple(bytes.fromhex(LEYENDA_URBANA['color'][1:]))
            rgba[:, urbano] = np.asarray((*rgb, 255))[:, None]
            leyenda.append(LEYENDA_URBANA)
        with MemoryFile(ext='.png') as mem:
            with mem.open(driver='PNG', width=w, height=h, count=4, dtype='uint8',
                          transform=grid, crs='EPSG:4326') as png:
                png.write(rgba)
            imagen = mem.read()
        return imagen, dict(limites=limites, leyenda=leyenda, fuente=FUENTE_LEYENDA if oficial else None,
                            anio=tags.get('original', '').removeprefix('classification_'))


def consultar_celda(ruta, lon, lat):
    if not math.isfinite(lon) or not math.isfinite(lat) or abs(lon) > 180 or abs(lat) >= 90:
        raise ErrorAnalisis('Indica longitud y latitud válidas en grados.')
    with rasterio.open(ruta) as src:
        x, y = transform('EPSG:4326', src.crs, [lon], [lat])
        if not all(math.isfinite(value) for value in (*x, *y)):
            raise ErrorAnalisis('El punto no se puede proyectar al GeoTIFF.', 422)
        fila, columna = src.index(x[0], y[0])
        if not (0 <= fila < src.height and 0 <= columna < src.width):
            raise ErrorAnalisis('El punto está fuera del GeoTIFF.', 422)
        win = Window(columna, fila, 1, 1)
        datos = src.read(window=win, masked=True)[:, 0, 0]
        valores = []
        for b, dato, nodata in zip(bandas(src), datos, src.nodatavals):
            valor = None
            if not np.ma.is_masked(dato) and dato != nodata:
                escalado = float(dato) * b['escala'] + b['offset']
                valor = escalado if math.isfinite(escalado) else None
            valores.append(dict(b, valor=valor))
        esquinas = [src.window_transform(win) * p for p in ((0, 0), (1, 0), (1, 1), (0, 1))]
        lons, lats = transform(src.crs, 'EPSG:4326', *zip(*esquinas))
        return dict(lon=lon, lat=lat, fila=int(fila), columna=int(columna),
                    esquinas=list(zip(lons, lats)), bandas=valores)


def exportar_recorte(ruta, destino, peticion, max_pixeles):
    limites = rectangulo(peticion)
    with rasterio.open(ruta) as src:
        x0, y0, x1, y1 = ventana(src, limites)
        w, h = x1 - x0, y1 - y0
        if w * h > max_pixeles:
            raise ErrorAnalisis('La selección supera el límite de píxeles.', 413)
        formato = dict(driver='GTiff', width=w, height=h, count=src.count, dtype=src.dtypes[0],
                       crs=src.crs, transform=src.window_transform(Window(x0, y0, w, h)),
                       nodata=src.nodata, compress='deflate', tiled=True)
        seleccionados = 0
        with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True), rasterio.open(destino, 'w', **formato) as out:
            out.update_tags(**src.tags())
            out.descriptions, out.units, out.scales, out.offsets = src.descriptions, src.units, src.scales, src.offsets
            for i in src.indexes:
                out.update_tags(i, **src.tags(i))
            for _, local in out.block_windows(1):
                original = Window(x0 + local.col_off, y0 + local.row_off, local.width, local.height)
                dentro = centros_en_rectangulo(src, original, limites)
                seleccionados += int(dentro.sum())
                datos = src.read(window=original, masked=True)
                if src.nodata is not None:
                    datos.mask = np.ma.getmaskarray(datos) | ~dentro
                    out.write(datos.filled(src.nodata), window=local)
                else:
                    out.write(datos.data, window=local)
                    dentro = dentro & ~np.all(np.ma.getmaskarray(datos), axis=0)
                    out.write_mask(dentro, window=local)
        if not seleccionados:
            raise ErrorAnalisis('No hay centros de píxel dentro del rectángulo.', 422)
