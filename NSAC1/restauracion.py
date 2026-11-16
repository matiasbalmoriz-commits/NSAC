"""Detecta candidatas a restauración ribereña y conexión de bosque en el ráster nacional."""

from base64 import b64encode

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import Window
from scipy.ndimage import binary_dilation, generate_binary_structure, grey_dilation, label

from analizador import ErrorAnalisis, centros_en_rectangulo, rectangulo, ventana
from mapa import ASSET_MAPBIOMAS_C2


VECINOS = ((-1, 0), (0, -1), (1, 0), (0, 1))
LADOS = generate_binary_structure(2, 1)
LADOS_Y_ESQUINAS = generate_binary_structure(2, 2)
MAX_CELDAS_CORREDOR = 8
BANDAS = ('land_cover', 'presencia_rio', 'presencia_lago', 'dentro_paraguay_fao')
COLORES = np.array([(0, 0, 0, 0), (111, 188, 96, 215), (21, 122, 70, 215), (0, 83, 51, 230)], dtype='uint8')


def _encuentros(origen, pasos):
    """Devuelve enlaces posibles entre frentes vecinos y el largo de cada brecha."""
    ancho = origen.shape[1]
    enlaces = []
    vistas = (
        (origen[:, :-1], origen[:, 1:], pasos[:, :-1], pasos[:, 1:], 1),
        (origen[:-1, :], origen[1:, :], pasos[:-1, :], pasos[1:, :], ancho),
    )
    for a, b, d_a, d_b, salto in vistas:
        largo = d_a + d_b
        fila, col = np.nonzero((a != 0) & (b != 0) & (a != b) & (largo <= MAX_CELDAS_CORREDOR))
        p = fila * ancho + col
        enlaces.append(np.column_stack((largo[fila, col], p, p + salto)))
    return np.concatenate(enlaces)


def _corredores(bosque, candidatas):
    origen, fragmentos = label(bosque, structure=LADOS_Y_ESQUINAS)
    resultado = np.zeros_like(bosque)
    if fragmentos < 2 or not candidatas.any():
        return resultado

    # Cada celda conserva el fragmento al que llegó primero. La distancia es el
    # número de celdas agrícolas o de pastura a restaurar para llegar al bosque.
    pasos = np.zeros(origen.shape, dtype='uint8')
    disponibles = candidatas.copy()
    for largo in range(1, MAX_CELDAS_CORREDOR + 1):
        vecinos = grey_dilation(origen, footprint=LADOS, mode='constant', cval=0)
        nuevas = disponibles & (vecinos != 0)
        origen[nuevas] = vecinos[nuevas]
        pasos[nuevas] = largo
        disponibles[nuevas] = False
        if not nuevas.any():
            break

    enlaces = _encuentros(origen, pasos)
    raiz = list(range(fragmentos + 1))

    def componente(n):
        while raiz[n] != n:
            raiz[n] = raiz[raiz[n]]
            n = raiz[n]
        return n

    alto, ancho = origen.shape
    for idx in np.argsort(enlaces[:, 0], kind='stable'):
        _, a, b = enlaces[idx]
        c_a, c_b = componente(origen.flat[a]), componente(origen.flat[b])
        if c_a == c_b:
            continue
        raiz[c_b] = c_a
        for extremo in (a, b):
            fila, col = divmod(int(extremo), ancho)
            id_origen = origen[fila, col]
            for largo in range(int(pasos[fila, col]), 0, -1):
                resultado[fila, col] = True
                for dy, dx in VECINOS:
                    y, x = fila + dy, col + dx
                    if (0 <= y < alto and 0 <= x < ancho and origen[y, x] == id_origen
                            and pasos[y, x] == largo - 1):
                        fila, col = y, x
                        break
    return resultado


def _imagen(src, win, clases):
    transformacion = src.window_transform(win)
    limites = transform_bounds(src.crs, 'EPSG:4326', *src.window_bounds(win), densify_pts=41)
    escala = min(1, 2048 / max(clases.shape))
    alto, ancho = (max(1, round(n * escala)) for n in clases.shape)
    grilla = from_bounds(*limites, ancho, alto)
    reproyectado = np.zeros((alto, ancho), dtype='uint8')
    reproject(clases, reproyectado, src_transform=transformacion, src_crs=src.crs,
              src_nodata=0, dst_transform=grilla, dst_crs='EPSG:4326', dst_nodata=0)
    with MemoryFile(ext='.png') as archivo:
        with archivo.open(driver='PNG', width=ancho, height=alto, count=4, dtype='uint8',
                          crs='EPSG:4326', transform=grilla) as png:
            png.write(COLORES[reproyectado].transpose(2, 0, 1))
        return list(limites), b64encode(archivo.read()).decode('ascii')


def restaurar(ruta, peticion, max_pixeles=5_000_000):
    limites = rectangulo(peticion)
    with rasterio.open(ruta) as src:
        try:
            indices = tuple(src.descriptions.index(banda) + 1 for banda in BANDAS)
        except ValueError as exc:
            raise ErrorAnalisis('La restauración requiere MapBiomas, ríos, lagos y el límite FAO.', 422) from exc
        if src.tags(indices[0]).get('asset') != ASSET_MAPBIOMAS_C2:
            raise ErrorAnalisis('La restauración requiere la colección 2 de MapBiomas Paraguay.', 422)
        if not src.crs or src.crs.to_epsg() != 6933 or src.transform.b or src.transform.d:
            raise ErrorAnalisis('La restauración requiere el ráster nacional en la cuadrícula EPSG:6933.', 422)

        x0, y0, x1, y1 = ventana(src, limites)
        ancho, alto = x1 - x0, y1 - y0
        if ancho * alto > min(max_pixeles, 5_000_000):
            raise ErrorAnalisis('La ventana de restauración supera el límite de píxeles.', 413)
        win = Window(x0, y0, ancho, alto)
        dentro = np.zeros((alto, ancho), dtype=bool)
        for fila in range(0, alto, 128):
            bloque = Window(x0, y0 + fila, ancho, min(128, alto - fila))
            dentro[fila:fila + 128, :] = centros_en_rectangulo(src, bloque, limites)
        if not dentro.any():
            raise ErrorAnalisis('No hay centros de píxel dentro del rectángulo. Amplía la selección.', 422)

        margen = MAX_CELDAS_CORREDOR + 1
        izq, sup = max(0, x0 - margen), max(0, y0 - margen)
        der, inf = min(src.width, x1 + margen), min(src.height, y1 + margen)
        contexto = Window(izq, sup, der - izq, inf - sup)
        cobertura, rio, lago, paraguay = src.read(indices, window=contexto, masked=True, out_dtype='float32').filled(np.nan)
        pais = paraguay == 1
        agua = (rio == 1) | (lago == 1) | (cobertura == 26)
        candidatas = pais & np.isin(cobertura, (15, 18)) & ~agua
        bosque = pais & np.isin(cobertura, (3, 4)) & ~agua
        ribera = candidatas & binary_dilation(agua, structure=LADOS)
        corredor = _corredores(bosque, candidatas)
        recorte = np.s_[y0 - sup:y1 - sup, x0 - izq:x1 - izq]
        ribera = ribera[recorte] & dentro
        corredor = corredor[recorte] & dentro
        clases = ribera.astype('uint8') + 2 * corredor.astype('uint8')
        limites_mapa, imagen = _imagen(src, win, clases)
        total = int(np.count_nonzero(clases))
        hectareas = abs(src.transform.determinant) / 10_000

    return dict(limites=limites_mapa, imagen=imagen, ribera_celdas=int(ribera.sum()),
                corredor_celdas=int(corredor.sum()), total_celdas=total, hectareas_por_celda=hectareas,
                total_hectareas=total * hectareas, notas=[
                    'Celdas candidatas de agricultura o pastura. Se excluyen los cuerpos de agua, los humedales y la vegetación natural.',
                    'Ribera indica que la celda comparte un lado con agua cartografiada. Validar en campo el cauce y el ancho de la franja.',
                    'El corredor conecta fragmentos de vegetación leñosa abierta o cerrada por rutas cortas de hasta ocho celdas candidatas. El cálculo incluye el entorno de la selección.',
                    'Validar conectividad, ecosistema de referencia y uso del predio antes de intervenir. Los dos criterios pueden coincidir en una celda.',
                ])
