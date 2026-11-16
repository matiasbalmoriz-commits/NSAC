"""Perfil zonal de las bandas de suelo de OpenLandMap a 10 cm."""

from analizador import ErrorAnalisis, analizar


# Clases de la banda b10 de OpenLandMap SOL_TEXTURE-CLASS_USDA-TT_M/v02.
TEXTURAS = (
    'Arcilla', 'Arcilla limosa', 'Arcilla arenosa', 'Franco arcilloso',
    'Franco arcillo-limoso', 'Franco arcillo-arenoso', 'Franco',
    'Franco limoso', 'Franco arenoso', 'Limo', 'Arena franca', 'Arena',
)


def ejecutar(ruta, datos, max_pixeles):
    bandas = {banda['nombre']: banda for banda in analizar(ruta, datos, max_pixeles)['bandas']}
    ph = bandas.get('soil_ph_10cm', {})
    textura = bandas.get('soil_texture_10cm', {})
    indicadores = []
    notas = [
        'Fuente de las bandas de suelo: OpenLandMap a 10 cm.',
        'Los resultados resumen celdas con datos válidos. Las proporciones de textura se calculan '
        'sobre las celdas que tienen una clase registrada.',
        'La cartografía describe el suelo superficial a escala regional. El muestreo local permite '
        'examinar la variación dentro del predio y a mayor profundidad.',
    ]

    if ph.get('unidad') == 'pH' and ph.get('media') is not None:
        for nombre, clave in (('pH medio', 'media'), ('pH mínimo', 'minimo'), ('pH máximo', 'maximo')):
            indicadores.append(dict(nombre=nombre, valor=round(ph[clave], 2), unidad='pH'))
        indicadores.append(dict(nombre='Cobertura de datos de pH', valor=round(ph['cobertura_pct'], 1), unidad='%'))
    else:
        notas.append('La selección no tiene valores utilizables de pH a 10 cm.')

    clases = sorted(textura.get('clases', ()), key=lambda clase: (-clase['pixeles'], clase['valor']))
    if textura.get('unidad') == 'clase USDA' and clases:
        indicadores.append(dict(nombre='Cobertura de datos de textura', valor=round(textura['cobertura_pct'], 1), unidad='%'))
        for clase in clases:
            codigo = clase['valor']
            nombre = TEXTURAS[int(codigo) - 1] if codigo in range(1, len(TEXTURAS) + 1) else f'Clase {codigo:g}'
            indicadores.append(dict(nombre=nombre, valor=round(clase['porcentaje'], 1), unidad='%'))
    else:
        notas.append('La selección no tiene clases utilizables de textura a 10 cm.')

    if not indicadores:
        raise ErrorAnalisis('No hay datos compatibles de pH o textura en la selección.', 422)
    return dict(titulo='Perfil de suelo',
                resumen='Acidez y distribución de texturas del suelo superficial del área seleccionada.',
                indicadores=indicadores, notas=notas)
