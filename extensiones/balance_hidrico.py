"""Panorama zonal de lluvia, evapotranspiración y humedad."""

from analizador import ErrorAnalisis, analizar


# Las bandas se conservan en sus unidades originales para evitar extrapolar su período.
SERIES = (
    ('era_precip_mm', 'Precipitación anual media', 'mm/año', 'precipitación anual'),
    ('pml_et_mm_d', 'Evapotranspiración diaria media', 'mm/día', 'evapotranspiración diaria'),
    ('ndmi', 'NDMI medio de la composición Landsat', '1', 'NDMI'),
    ('era_soil_water', 'Humedad media del suelo (0–7 cm)', 'm3/m3', 'humedad del suelo'),
)


def ejecutar(ruta, datos, max_pixeles):
    bandas = {banda['nombre']: banda for banda in analizar(ruta, datos, max_pixeles)['bandas']}
    indicadores = []
    faltantes = []
    for identificador, nombre, unidad, nombre_corto in SERIES:
        banda = bandas.get(identificador, {})
        if banda.get('unidad') != unidad or banda.get('media') is None:
            faltantes.append(nombre_corto)
            continue
        unidad_visible = {'1': '', 'm3/m3': 'm³/m³'}.get(unidad, unidad)
        indicadores.append(dict(nombre=nombre, valor=round(banda['media'], 3), unidad=unidad_visible))
        indicadores.append(dict(nombre=f'Cobertura de datos de {nombre_corto}',
                                 valor=round(banda['cobertura_pct'], 1), unidad='%'))

    if not indicadores:
        raise ErrorAnalisis('No hay bandas hídricas con datos y unidades compatibles en la selección.', 422)
    notas = [
        'ERA5-Land aporta el acumulado de lluvia anual y la humedad superficial. PML aporta una '
        'tasa diaria media calculada con las composiciones disponibles.',
        'Los promedios se calculan por banda sobre sus celdas válidas. Cada producto tiene una resolución, '
        'una cobertura y un período propios.',
        'Se presentan lluvia y evapotranspiración lado a lado en sus unidades originales. '
        'Un balance del agua del predio requiere conocer el período común y otros flujos, como escorrentía y riego.',
        'El NDMI de Landsat aporta contexto sobre la humedad de la vegetación. La humedad de ERA5-Land '
        'corresponde a la capa superficial de 0 a 7 cm.',
    ]
    if faltantes:
        notas.append('Indicadores sin datos compatibles: ' + ', '.join(faltantes) + '.')
    return dict(titulo='Lluvia y evapotranspiración',
                resumen='Indicadores de lluvia, evapotranspiración y humedad de la selección.',
                indicadores=indicadores, notas=notas)
