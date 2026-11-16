"""Ranking preliminar de cultivos de secano con datos de la zona y Nemotron."""
import argparse
import json
import logging
import os
import sys
from itertools import permutations
from time import perf_counter
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

dependencias = Path(__file__).resolve().parents[1] / '.deps_geotiff'
if dependencias.is_dir():
    sys.path.append(str(dependencias))

from analizador import ErrorAnalisis, analizar
from catalogo_cultivos import ABONOS_VERDES, COBERTURAS_DISPONIBLES, CULTIVOS
from mapa_cultivos import mapa_cultivos


API_NVIDIA = 'https://integrate.api.nvidia.com/v1'
MODELO_NVIDIA = 'nvidia/nemotron-3.5-bolt-e4b'
MODOS = ('monocultivo', 'rotacion')
TEXTURAS = ['arcilla', 'arcilla limosa', 'arcilla arenosa', 'franco arcilloso', 'franco arcillo-limoso',
            'franco arcillo-arenoso', 'franco', 'franco limoso', 'franco arenoso', 'limo', 'arena franca', 'arena']
DATOS_FALTANTES = [
    'Análisis de suelo de la parcela: nitrógeno disponible, fósforo, potasio, materia orgánica y salinidad.',
    'Profundidad efectiva, drenaje, pendiente del lote e historial de cultivo.',
    'Lluvia por etapa del cultivo, temperaturas extremas, heladas y disponibilidad efectiva de agua para riego.',
]
FUENTES = {
    'FAO ECOCROP': 'https://www.fao.org/geospatial/data-and-tools/data-portals/ecocrop/en',
    'Zonificación agroecológica del Paraguay (MAG)': 'https://informacionpublica.paraguay.gov.py/public/4465497-DocumentoZAEFinalPDFpdf-DocumentoZAEFinalPDF.pdf',
    'Experiencias de agricultura de conservación en Paraguay (FAO/GTZ)': 'https://www.fao.org/fileadmin/user_upload/fsn/docs/Smallholders/LIBRO_Expereincias_AC_Forestal_Paraguay.pdf',
    'Conservación y rotación de cultivos (USDA NRCS)': 'https://www.nrcs.usda.gov/resources/guides-and-instructions/conservation-crop-rotation-ac-328-conservation-practice-standard',
}
REGLAS = """Evalúa en español las 20 fichas de referencia para el área en Paraguay. Usa los rangos y condiciones
provistos para cada especie. Devuelve los cinco cultivos con mayor aptitud relativa, ordenados de mejor a peor, y
los cinco menos aptos, del más condicionado al menos favorable de ese grupo. Cada cultivo debe aparecer una sola vez.
La evaluación describe opciones para agricultura de secano, condicionadas por la disponibilidad de datos. El bloque
coberturas_agricolas incluye agricultura, pastura sembrada, pastizal natural y pastizal inundable. Las estadísticas
de suelo y clima son de agricultura y pastura sin agua cartografiada. Los pastizales naturales e inundables aportan
contexto de conservación. Si se considera una pastura sembrada, verifica viabilidad del cambio antes de proponerlo.

Da uno o dos motivos específicos y una o dos medidas factibles por cultivo. Compara pH, lluvia anual y textura con
los valores de las fichas cuando sean comparables. Distingue la media de las celdas y la variación en la selección.
La media anual del aire es contexto térmico y no sustituye temperaturas durante el ciclo ni confirma aptitud para
la estación fresca. No mezcles temperatura de superficie, temperatura del aire y temperatura por campaña. Para
arroz inundado verifica manejo hídrico, suelo y fuente de agua antes de considerarlo apto. La lluvia anual no indica
su distribución. Evita cifras inventadas y no deduzcas drenaje, fertilidad ni profundidad solamente por la textura.
El GeoTIFF carece de mediciones de N, P, K, materia orgánica, drenaje y agua de riego. No diagnostiques carencia de
nitrógeno. Propón análisis y correcciones según sus resultados, sin dosis. Lluvia anual y temperatura media del aire
a ~11 km no confirman sequía, heladas ni estrés por calor durante la floración. NDMI indica humedad de la vegetación,
ERA5 estima agua en el suelo de 0–7 cm y ECOSTRESS mide temperatura superficial. Si sugieres riego, condiciona
a un balance hídrico y una fuente disponible.

En alcance indica las limitaciones de los rangos, las mediciones que conviene comprobar y si la aptitud es limitada.
Evita sugerir expansión hacia bosque, pastizal natural, humedal o márgenes restaurables. Usa oraciones cortas.
"""
INSTRUCCIONES_MODO = {
    'monocultivo': ('Para cada uno de los cinco cultivos más aptos, escoge exactamente un abono verde del '
                   'catálogo complementario. Indica época viable y por qué lo acompaña. Para perennes, '
                   'considera cobertura entre hileras y competencia por agua. Distingue familias y '
                   'aclara que la fijación biológica depende de la especie y del manejo.'),
    'rotacion': ('En aptos, incluye cinco cultivos de rotación estacional y suficientes familias para formar '
                 'un ciclo de 3 o 4 campañas. Usa exactamente los mismos nombres del ranking aptos en rotacion, '
                 'sin repetir cultivos. Cada paso tiene cultivo, epoca y motivo. Dos pasos seguidos deben ser '
                 'de familias diferentes, incluso el último y el primero. Maíz, trigo y sorgo pertenecen a '
                 'Poaceae, por lo que no pueden quedar juntos. Considera el invierno para trigo y canola. '
                 'Señala qué verificar antes de fijar fechas.'),
}


def admite_rotacion(cultivo):
    ficha = CULTIVOS[cultivo]
    return ficha.get('rotacion_estacional', True) and not ficha.get('riego_inundado', False)


def esquema(modo):
    texto = {'type': 'string'}
    lista = {'type': 'array', 'items': texto, 'minItems': 1, 'maxItems': 3}

    def objeto(**campos):
        return dict(type='object', properties=campos, required=list(campos), additionalProperties=False)

    def ranking(cultivos, **campos):
        item = objeto(cultivo=dict(type='string', enum=cultivos), motivos=lista, medidas=lista, **campos)
        return dict(type='array', items=item, minItems=5, maxItems=5)

    extra = {}
    aptos = list(CULTIVOS)
    if modo == 'monocultivo':
        extra['abono_verde'] = objeto(especie=dict(type='string', enum=list(ABONOS_VERDES)), epoca=texto, motivo=texto)
    else:
        aptos = [cultivo for cultivo in CULTIVOS if admite_rotacion(cultivo)]
    campos = dict(aptos=ranking(aptos, **extra), no_aptos=ranking(list(CULTIVOS)), alcance=texto)
    if modo == 'rotacion':
        paso = objeto(cultivo=dict(type='string', enum=aptos), epoca=texto, motivo=texto)
        campos['rotacion'] = dict(type='array', minItems=3, maxItems=4, items=paso)
    return objeto(**campos)


def _conexion():
    base = os.environ.get('NEMOTRON_BASE_URL', API_NVIDIA).rstrip('/')
    modelo = os.environ.get('NEMOTRON_MODEL', MODELO_NVIDIA).strip()
    try:
        url = urlsplit(base)
        local = url.hostname in {'localhost', '127.0.0.1', '::1'}
    except ValueError as exc:
        raise ErrorAnalisis('La URL de Nemotron no es válida.', 503) from exc
    if not modelo or not url.hostname or (url.scheme != 'https' and not (local and url.scheme == 'http')):
        raise ErrorAnalisis('Configura un modelo Nemotron y una URL HTTPS o local.', 503)
    return base, modelo, local


def _credencial(base, clave_interfaz):
    if base == API_NVIDIA and clave_interfaz:
        return clave_interfaz, 'interfaz'
    clave = os.environ.get('NEMOTRON_API_KEY') or (os.environ.get('NVIDIA_API_KEY') if base == API_NVIDIA else None)
    return clave, 'entorno' if clave else None


def estado_configuracion(clave_interfaz=None):
    try:
        base, _, local = _conexion()
    except ErrorAnalisis:
        return dict(configurada=False, origen=None, editable=False)
    _, origen = _credencial(base, clave_interfaz)
    if local and origen is None:
        origen = 'local'
    return dict(configurada=origen is not None, origen=origen, editable=base == API_NVIDIA)


def configuracion(clave_interfaz=None):
    base, modelo, local = _conexion()
    clave, _ = _credencial(base, clave_interfaz)
    if not local and not clave:
        if base == API_NVIDIA:
            raise ErrorAnalisis('Añade tu clave en Configurar Nemotron o define NVIDIA_API_KEY en el entorno.', 503)
        raise ErrorAnalisis('Configura NEMOTRON_API_KEY para el servicio de Nemotron indicado en el entorno.', 503)
    return base, modelo, clave


def probar_conexion(clave_interfaz=None):
    inicio = perf_counter()
    base, modelo, local = _conexion()
    clave, _ = _credencial(base, clave_interfaz)
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if clave:
        headers['Authorization'] = 'Bearer ' + clave
    # Una respuesta de inferencia comprueba autenticación, modelo y JSON estructurado.
    payload = dict(model=modelo, stream=False, max_tokens=64, messages=[
        {'role': 'user', 'content': 'Prueba de conexión. Devuelve el JSON {"conexion":"ok"}.'}],
        response_format={'type': 'json_schema', 'json_schema': {'name': 'prueba_conexion', 'schema': {
            'type': 'object', 'properties': {'conexion': {'type': 'string', 'enum': ['ok']}},
            'required': ['conexion'], 'additionalProperties': False}}})
    if base == API_NVIDIA:
        payload['chat_template_kwargs'] = {'enable_thinking': False}
    puede_inferir = bool(clave) or local
    request = (Request(base + '/chat/completions', json.dumps(payload).encode(), headers)
               if puede_inferir else Request(base + '/models', headers=headers))
    resultado = dict(funcional=False, api_accesible=False, modelo=modelo, estado='sin_clave',
                     mensaje='Guarda tu clave y repite la prueba para verificar la autenticación y el modelo.')
    try:
        with urlopen(request, timeout=25) as respuesta:
            resultado.update(api_accesible=True, http=respuesta.status)
            cuerpo = json.load(respuesta)
        if puede_inferir:
            contenido = json.loads(cuerpo['choices'][0]['message']['content'])
            if contenido != {'conexion': 'ok'}:
                raise ValueError('Respuesta de prueba inesperada')
            resultado.update(funcional=True, estado='conectado',
                             mensaje='Conexión funcional. La API aceptó la clave y el modelo devolvió el JSON de prueba.')
        else:
            modelos = cuerpo.get('data')
            if not isinstance(modelos, list):
                raise ValueError('Catálogo inválido')
            existe = any(isinstance(item, dict) and item.get('id') == modelo for item in modelos)
            resultado['modelo_disponible'] = existe
            resultado['mensaje'] = ('La API responde y el modelo figura en su catálogo. Guarda tu clave para verificar la autenticación.'
                                     if existe else 'La API responde, pero el modelo configurado no figura en su catálogo. Revisa el modelo.')
    except HTTPError as exc:
        mensajes = {
            400: 'La API respondió, pero rechazó el modelo o el formato de la solicitud.',
            401: 'La API respondió, pero la clave falta, venció o fue rechazada.',
            403: 'La API respondió, pero esta clave no tiene acceso al servicio o al modelo.',
            404: 'La ruta de API o el modelo solicitado no está disponible.',
            422: 'La API respondió, pero rechazó los parámetros de la prueba.',
            429: 'La API respondió, pero se alcanzó el límite de solicitudes o de cuota.',
        }
        resultado.update(api_accesible=True, http=exc.code, estado='rechazado',
                         mensaje=mensajes.get(exc.code, f'El proveedor respondió HTTP {exc.code}. Reintenta más tarde.'))
    except (URLError, TimeoutError, OSError):
        resultado.update(estado='sin_conexion', mensaje='No se pudo conectar con la API en 25 segundos. Revisa la conexión y vuelve a probar.')
    except (ValueError, KeyError, IndexError, TypeError):
        resultado.update(estado='respuesta_invalida', mensaje='La API respondió, pero no devolvió el JSON de prueba esperado para el análisis.')
    resultado['latencia_ms'] = round((perf_counter() - inicio) * 1000)
    return resultado


def preparar_contexto(resumen, modo):
    nombres = ('elevation_m', 'land_cover', 'soil_ph_10cm', 'soil_texture_10cm', 'era_t2m_c',
               'era_precip_mm', 'era_soil_water', 'ndvi', 'ndmi', 'ls_valid_scenes',
               'pml_et_mm_d', 'pml_ec_mm_d', 'pml_es_mm_d', 'eco_lst_c', 'eco_valid_scenes')
    claves = ('unidad', 'validos', 'cobertura_pct', 'minimo', 'media', 'maximo', 'clases')
    datos = {b['nombre']: {k: b[k] for k in claves if k in b} for b in resumen['bandas'] if b['nombre'] in nombres}
    requeridas = ('soil_ph_10cm', 'soil_texture_10cm', 'era_t2m_c', 'era_precip_mm')
    if not all(datos.get(nombre, {}).get('validos') for nombre in requeridas):
        raise ErrorAnalisis('Faltan valores de suelo o clima para evaluar los cultivos en esta selección.', 422)
    coberturas = {ficha['nombre']: dict(ficha, celdas=resumen['coberturas_agricolas'][codigo])
                  for codigo, ficha in COBERTURAS_DISPONIBLES.items()}
    cultivos = {nombre: {campo: valor for campo, valor in ficha.items() if campo not in ('color', 'fuentes')}
                for nombre, ficha in CULTIVOS.items()}
    return dict(modo=modo, anio_cobertura=resumen['anio_cobertura'], hectareas_por_celda=resumen['hectareas_por_celda'],
                celdas_evaluadas=resumen['pixeles_seleccionados'],
                celdas_rectangulo=resumen['pixeles_en_rectangulo'], cultivos=cultivos, bandas=datos,
                coberturas_agricolas=coberturas, abonos_verdes=ABONOS_VERDES if modo == 'monocultivo' else {},
                clases_textura=dict(enumerate(TEXTURAS, start=1)))


def _familias_alternadas(nombres):
    familias = [CULTIVOS[nombre]['familia'] for nombre in nombres]
    return all(antes != despues for antes, despues in zip(familias, familias[1:] + familias[:1]))


def _secuencia_posible(aptos):
    nombres = [entrada['cultivo'] for entrada in aptos]
    # Prioriza tres campañas con los primeros candidatos. Cuatro permiten alternar dos familias.
    for longitud in (3, 4):
        for secuencia in permutations(nombres, longitud):
            if _familias_alternadas(secuencia):
                return secuencia
    return None


def validar_resultado(result, modo, *, validar_rotacion=True):
    def texto(valor):
        if not isinstance(valor, str) or not 1 <= len(valor.strip()) <= 800:
            raise ValueError('Texto inválido')
        return valor.strip()

    def textos(valores):
        if not isinstance(valores, list) or not 1 <= len(valores) <= 3:
            raise ValueError('Lista incompleta')
        return [texto(valor) for valor in valores]

    usados = set()
    grupos = {}
    for grupo in ('aptos', 'no_aptos'):
        items = result[grupo]
        if not isinstance(items, list) or len(items) != 5:
            raise ValueError('Se requieren cinco cultivos por grupo')
        grupos[grupo] = []
        for item in items:
            cultivo = item['cultivo']
            if cultivo not in CULTIVOS or cultivo in usados:
                raise ValueError('Cultivo desconocido o repetido')
            usados.add(cultivo)
            entrada = dict(cultivo=cultivo, motivos=textos(item['motivos']), medidas=textos(item['medidas']))
            if grupo == 'aptos':
                if modo == 'monocultivo':
                    abono = item['abono_verde']
                    if abono['especie'] not in ABONOS_VERDES:
                        raise ValueError('Abono verde desconocido')
                    entrada['abono_verde'] = dict(especie=abono['especie'], epoca=texto(abono['epoca']),
                                                  motivo=texto(abono['motivo']))
                elif not admite_rotacion(cultivo):
                    raise ValueError('Cultivo fuera de rotación estacional')
            grupos[grupo].append(entrada)

    salida = dict(grupos, alcance=texto(result['alcance']))
    if modo == 'rotacion' and validar_rotacion:
        pasos = result['rotacion']
        if not isinstance(pasos, list) or not 3 <= len(pasos) <= 4:
            raise ValueError('Secuencia incompleta')
        aptos = {item['cultivo'] for item in grupos['aptos']}
        nombres = [paso['cultivo'] for paso in pasos]
        if len(set(nombres)) != len(pasos) or not set(nombres) <= aptos:
            raise ValueError('Cada paso necesita un cultivo distinto del grupo apto')
        if not _familias_alternadas(nombres):
            raise ValueError('Las familias de pasos consecutivos deben alternar')
        salida['rotacion'] = [dict(cultivo=paso['cultivo'], epoca=texto(paso['epoca']), motivo=texto(paso['motivo']))
                              for paso in pasos]
    return salida


def _solicitar_analisis(base, datos, headers, *, timeout):
    peticion_api = Request(base + '/chat/completions', json.dumps(datos).encode('utf-8'), headers)
    with urlopen(peticion_api, timeout=timeout) as respuesta:
        opcion = json.load(respuesta)['choices'][0]
    if opcion.get('finish_reason') == 'length':
        raise ValueError('La respuesta del modelo quedó incompleta')
    return json.loads(opcion['message']['content'])


def _analisis_validado(base, datos, headers, modo):
    respuesta = None
    try:
        respuesta = _solicitar_analisis(base, datos, headers, timeout=120 if modo == 'rotacion' else 180)
        return validar_resultado(respuesta, modo)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        if modo != 'rotacion':
            raise
        logging.warning('Rotación: respuesta del modelo inválida. Se intentará una corrección (%s).', type(exc).__name__)

    # Si los rankings son válidos, propón un orden de sus propios cultivos al modelo.
    # Nemotron sigue a cargo de verificar la campaña y explicar cada paso.
    instruccion = ('La primera respuesta no pasó la validación. Devuelve nuevamente el JSON completo; '
                   'comprueba los 5 cultivos por grupo, que sean todos distintos y que rotacion use '
                   '3 o 4 cultivos de aptos con familias alternadas, incluido el cierre del ciclo.')
    formato = esquema(modo)
    try:
        grupos = validar_resultado(respuesta, modo, validar_rotacion=False)
    except (KeyError, IndexError, TypeError, ValueError):
        grupos = None
    if grupos:
        secuencia = _secuencia_posible(grupos['aptos'])
        if secuencia:
            rotacion = formato['properties']['rotacion']
            rotacion['items']['properties']['cultivo']['enum'] = list(secuencia)
            rotacion.update(minItems=len(secuencia), maxItems=len(secuencia))
            formato = dict(type='object', properties={'rotacion': rotacion}, required=['rotacion'],
                           additionalProperties=False)
            instruccion = ('El ranking ya está validado. Devuelve únicamente rotacion en este orden: ' +
                           ' → '.join(secuencia) + '. Indica la época y el motivo en cada paso. '
                           'Comprueba las limitaciones locales antes de fijar campañas.')
    mensajes = datos['messages'] + [{'role': 'user', 'content': instruccion}]
    reintento = dict(datos, messages=mensajes,
                     response_format={'type': 'json_schema', 'json_schema': {'name': 'ranking_cultivos', 'schema': formato}})
    solo_secuencia = len(formato['properties']) == 1
    if solo_secuencia:
        reintento['max_tokens'] = 1200
    correccion = _solicitar_analisis(base, reintento, headers, timeout=60)
    if solo_secuencia:
        correccion = dict(grupos, rotacion=correccion['rotacion'])
    return validar_resultado(correccion, modo)


def ranking_cultivos(ruta, peticion, max_pixeles=5_000_000, *, clave_interfaz=None):
    modo = peticion.get('modo', 'rotacion') if isinstance(peticion, dict) else None
    if modo not in MODOS:
        raise ErrorAnalisis('Elige monocultivo o rotación.')
    base, modelo, clave = configuracion(clave_interfaz)
    resumen = analizar(ruta, peticion, max_pixeles, solo_productivo=True)
    contexto = preparar_contexto(resumen, modo)
    formato = {'type': 'json_schema', 'json_schema': {'name': 'ranking_cultivos', 'schema': esquema(modo)}}
    datos = dict(model=modelo, stream=False, temperature=.2, max_tokens=5000, response_format=formato, messages=[
        {'role': 'system', 'content': REGLAS + '\n' + INSTRUCCIONES_MODO[modo]},
        {'role': 'user', 'content': json.dumps(contexto, ensure_ascii=False, allow_nan=False)},
    ])
    if base == API_NVIDIA:
        datos['chat_template_kwargs'] = {'enable_thinking': False}
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if clave:
        headers['Authorization'] = 'Bearer ' + clave
    try:
        salida = _analisis_validado(base, datos, headers, modo)
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise ErrorAnalisis('El proveedor de Nemotron rechazó la clave o el acceso al modelo.', 503) from exc
        if exc.code == 429:
            raise ErrorAnalisis('El proveedor de Nemotron alcanzó su límite de solicitudes o cuota.', 503) from exc
        raise ErrorAnalisis(f'El proveedor de Nemotron respondió HTTP {exc.code}. Revisa el modelo y su API.', 502) from exc
    except (URLError, TimeoutError) as exc:
        raise ErrorAnalisis('No se pudo conectar con Nemotron o la consulta agotó su tiempo.', 502) from exc
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        if modo == 'rotacion':
            raise ErrorAnalisis('Nemotron no pudo completar una rotación válida tras dos intentos. '
                                'Vuelve a ejecutar el análisis para pedir una nueva secuencia.', 502) from exc
        raise ErrorAnalisis('El proveedor no devolvió un análisis de cultivos válido. Intenta de nuevo.', 502) from exc
    alcance = f"Preselección de secano para {contexto['celdas_evaluadas']:,} celdas productivas. "
    salida['alcance'] = alcance + salida['alcance']
    candidatos = salida.get('rotacion', salida['aptos'])
    mapa = mapa_cultivos(ruta, peticion, max_pixeles, candidatos, modo)
    fichas = {item['cultivo']: CULTIVOS[item['cultivo']] for grupo in ('aptos', 'no_aptos') for item in salida[grupo]}
    return dict(salida, modo=modo, modelo=modelo, datos_faltantes=DATOS_FALTANTES, fuentes=FUENTES,
                mapa_cultivos=mapa, fichas=fichas, coberturas_agricolas=resumen['coberturas_agricolas'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('geotiff', type=Path)
    parser.add_argument('--bbox', nargs=4, type=float, required=True, metavar=('O', 'S', 'E', 'N'))
    parser.add_argument('--modo', choices=MODOS, default='rotacion')
    args = parser.parse_args()
    oeste, sur, este, norte = args.bbox
    try:
        ranking = ranking_cultivos(args.geotiff, dict(pos1=dict(lon=oeste, lat=sur),
                                                   pos2=dict(lon=este, lat=norte), modo=args.modo))
        print(json.dumps(ranking, ensure_ascii=False, indent=2))
    except ErrorAnalisis as exc:
        parser.exit(1, f'Error: {exc}\n')
