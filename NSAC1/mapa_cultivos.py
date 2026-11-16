"""Capa de cultivos candidatos a partir del suelo y la lluvia del área."""

from base64 import b64encode

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import Window

from analizador import (ASSET_MAPBIOMAS_C2, ErrorAnalisis, centros_en_rectangulo,
                        mascara_productiva, rectangulo, valores_ventana, ventana)
from catalogo_cultivos import CULTIVOS


def _distancia_relativa(valores, intervalo):
    minimo, maximo = intervalo
    return np.abs((valores - minimo) * (2 / (maximo - minimo)) - 1)


def _clasificar_bloque(productivas, ph, lluvia, temperatura, candidatos, aceptar_condicionados=False):
    resultado = np.zeros(productivas.shape, dtype='uint8')
    puntaje = np.full(productivas.shape, np.inf)
    for codigo, ficha in candidatos:
        if ficha['lluvia_mm'] is None or ficha.get('riego_inundado'):
            continue
        criterios = [(ph, ficha['ph']), (lluvia, ficha['lluvia_mm'])]
        if ficha.get('temperatura_anual'):
            if temperatura is None:
                continue
            criterios.append((temperatura, ficha['temperatura_c']))
        distancias = [_distancia_relativa(valores, intervalo) for valores, intervalo in criterios]
        dentro_del_rango = np.logical_and.reduce([(valores >= minimo) & (valores <= maximo)
                                                for valores, (minimo, maximo) in criterios])
        total = sum(distancias) / len(distancias)
        if aceptar_condicionados:
            # Una coincidencia siempre gana. Fuera del rango se prioriza la menor desviación de sus límites.
            exceso = sum(np.maximum(distancia - 1, 0) for distancia in distancias) / len(distancias)
            total = np.where(dentro_del_rango, total, 2 + exceso)
        else:
            total = np.where(dentro_del_rango, total, np.inf)
        # Ante un empate, se conserva el orden de candidatos del análisis.
        mejora = productivas & (total < puntaje)
        resultado[mejora] = codigo
        puntaje[mejora] = total[mejora]
    return resultado, (resultado != 0) & (puntaje >= 2)


def _clasificar_grupos(productivas, ph, lluvia, temperatura, candidatos):
    """Calcula un cultivo por grupo 2 × 2 y lo asigna a sus celdas productivas con datos."""
    validas = productivas & np.isfinite(ph) & np.isfinite(lluvia)
    alto, ancho = validas.shape
    filas = np.arange(0, alto, 2)
    columnas = np.arange(0, ancho, 2)

    def sumar_grupo(valores):
        return np.add.reduceat(np.add.reduceat(valores, filas, axis=0), columnas, axis=1)

    def media_grupo(valores, mascara, conteo):
        suma = sumar_grupo(np.where(mascara, valores, 0))
        return np.divide(suma, conteo, out=np.full(suma.shape, np.nan), where=conteo > 0)

    conteo = sumar_grupo(validas)
    temperatura_grupo = None
    if temperatura is not None:
        temp_validas = validas & np.isfinite(temperatura)
        temperatura_grupo = media_grupo(temperatura, temp_validas, sumar_grupo(temp_validas))
    grupos, condicionados = _clasificar_bloque(conteo > 0, media_grupo(ph, validas, conteo),
                                               media_grupo(lluvia, validas, conteo), temperatura_grupo,
                                               candidatos, aceptar_condicionados=True)
    # Los índices de colores 1..N son coincidencias y N+1..2N son aproximaciones fuera de rango.
    grupos[condicionados] += len(candidatos)
    celdas = np.repeat(np.repeat(grupos, 2, axis=0), 2, axis=1)[:alto, :ancho]
    celdas[~validas] = 0
    return celdas, grupos


def _exportar_png(src, win, clases, colores):
    transformacion = src.window_transform(win)
    ancho, alto = int(win.width), int(win.height)
    xs, ys = zip(*(transformacion * p for p in ((0, 0), (ancho, 0), (0, alto), (ancho, alto))))
    limites = transform_bounds(src.crs, 'EPSG:4326', min(xs), min(ys), max(xs), max(ys), densify_pts=41)
    escala = min(1, 2048 / max(ancho, alto))
    ancho, alto = max(1, round(ancho * escala)), max(1, round(alto * escala))
    grilla = from_bounds(*limites, ancho, alto)
    proyectadas = np.zeros((alto, ancho), dtype='uint8')
    reproject(clases, proyectadas, src_transform=transformacion, src_crs=src.crs,
              src_nodata=0, dst_transform=grilla, dst_crs='EPSG:4326', dst_nodata=0)
    with MemoryFile(ext='.png') as archivo:
        with archivo.open(driver='PNG', width=ancho, height=alto, count=4, dtype='uint8',
                          crs='EPSG:4326', transform=grilla) as png:
            png.write(colores[proyectadas].transpose(2, 0, 1))
        return list(limites), b64encode(archivo.read()).decode('ascii')


def mapa_cultivos(ruta, peticion, max_pixeles, aptos, modo):
    seleccion = rectangulo(peticion)
    nombres = list(dict.fromkeys(item['cultivo'] for item in aptos))
    fichas = [CULTIVOS[nombre] for nombre in nombres]
    candidatos = list(enumerate(fichas, start=1))
    agrupado = modo == 'monocultivo'
    usar_temperatura = any(ficha.get('temperatura_anual') and ficha['lluvia_mm'] is not None
                           for ficha in fichas)
    cantidad_colores = 1 + len(fichas) * (2 if agrupado else 1)
    colores = np.zeros((cantidad_colores, 4), dtype='uint8')
    for codigo, ficha in candidatos:
        rgb = tuple(bytes.fromhex(ficha['color'][1:]))
        colores[codigo] = (*rgb, 255)
        if agrupado:
            colores[codigo + len(fichas)] = (*rgb, 255)
    conteo_grupos = np.zeros(cantidad_colores, dtype='int64')

    with rasterio.open(ruta) as src:
        indices = {nombre: i for i, nombre in enumerate(src.descriptions, start=1) if nombre}
        requeridas = ('land_cover', 'soil_ph_10cm', 'era_precip_mm')
        if (any(nombre not in indices for nombre in requeridas)
                or src.tags(indices['land_cover']).get('asset') != ASSET_MAPBIOMAS_C2):
            raise ErrorAnalisis('El mapa de cultivos requiere MapBiomas Paraguay, pH y clima anual.', 422)
        x0, y0, x1, y1 = ventana(src, seleccion)
        if (x1 - x0) * (y1 - y0) > max_pixeles:
            raise ErrorAnalisis('La ventana del mapa de cultivos supera el límite de píxeles.', 413)
        if agrupado:
            # Una malla anclada al GeoTIFF mantiene los grupos al mover la selección.
            x0, y0 = x0 - x0 % 2, y0 - y0 % 2
        clases = np.zeros((y1 - y0, x1 - x0), dtype='uint8')
        productivas_totales = 0
        for fila in range(y0, y1, 256):
            for columna in range(x0, x1, 256):
                alto, ancho = min(256, y1 - fila), min(256, x1 - columna)
                win = Window(columna, fila, ancho, alto)
                dentro = centros_en_rectangulo(src, win, seleccion)
                productivas, _ = mascara_productiva(src, indices, win, dentro)
                if not productivas.any():
                    continue
                productivas_totales += int(np.count_nonzero(productivas))
                ph, lluvia = (valores_ventana(src, indices[banda], win) for banda in requeridas[1:])
                temperatura = (valores_ventana(src, indices['era_t2m_c'], win)
                               if usar_temperatura and 'era_t2m_c' in indices else None)
                if agrupado:
                    bloque, grupos = _clasificar_grupos(productivas, ph, lluvia, temperatura, candidatos)
                    conteo_grupos += np.bincount(grupos.ravel(), minlength=cantidad_colores)
                else:
                    bloque, _ = _clasificar_bloque(productivas, ph, lluvia, temperatura, candidatos)
                clases[fila - y0:fila - y0 + alto, columna - x0:columna - x0 + ancho] = bloque
        limites, imagen = _exportar_png(src, Window(x0, y0, x1 - x0, y1 - y0), clases, colores)

    celdas = np.bincount(clases.ravel(), minlength=cantidad_colores)
    leyenda = []
    for (codigo, ficha), nombre in zip(candidatos, nombres):
        entrada = dict(cultivo=nombre, color=ficha['color'], celdas=int(celdas[codigo]))
        if agrupado:
            condicionado = codigo + len(fichas)
            entrada['celdas'] += int(celdas[condicionado])
            entrada['grupos'] = int(conteo_grupos[codigo] + conteo_grupos[condicionado])
            entrada['grupos_condicionados'] = int(conteo_grupos[condicionado])
        if entrada['celdas']:
            leyenda.append(entrada)
    total = int(np.count_nonzero(clases))
    nota_modo = ('El mapa usa el promedio de las celdas productivas con datos de cada grupo de hasta 2 × 2 y '
                 'colorea esas celdas con el mejor candidato del análisis. La leyenda cuenta como condicionados '
                 'los grupos donde el candidato más cercano queda fuera de algún rango.'
                 if agrupado else 'Cada color señala un cultivo candidato para iniciar la rotación en esa celda.')
    notas = [
        nota_modo,
        'El mapa compara el pH superficial y la lluvia anual con los rangos del cultivo. '
        'Entre las coincidencias, prioriza la cercanía al centro de los rangos. '
        'La temperatura media anual no se usa como temperatura de campaña.',
        'Los pastizales naturales e inundables se incluyen en el resumen de cobertura. '
        'El mapa asigna cultivos solo a agricultura y pasturas sembradas.',
        'La lluvia proviene de celdas de unos 11 km. Antes de sembrar, comprueba la textura, '
        'el drenaje y las condiciones de la campaña en el predio.',
    ]
    if any(ficha.get('riego_inundado') for ficha in fichas):
        notas.append('El arroz inundado requiere confirmar el manejo y la disponibilidad de agua en el predio.')
    if any(ficha['lluvia_mm'] is None for ficha in fichas):
        notas.append('El mapa usa intervalos de lluvia comprobables. Los cultivos con un valor aproximado quedan en el ranking.')
    sin_color = productivas_totales - total
    if sin_color:
        notas.append(f'{sin_color} celdas agrícolas o de pastura quedaron sin color por datos '
                     'insuficientes o falta de coincidencia con estos candidatos.')
    resultado = dict(imagen=imagen, limites=limites, leyenda=leyenda, total_celdas=total, notas=notas, opaca=True)
    if agrupado:
        resultado.update(tamano_grupo=[2, 2], total_grupos=int(conteo_grupos[1:].sum()),
                         total_grupos_condicionados=int(conteo_grupos[len(fichas) + 1:].sum()))
    return resultado
