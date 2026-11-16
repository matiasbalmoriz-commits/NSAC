"""Registro y ejecución aislada de las extensiones incluidas con GeoVision."""

import importlib.util
import json
import logging
import os
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from threading import BoundedSemaphore, Lock


RAIZ = Path(__file__).resolve().parent
TIEMPO_LIMITE = 20
MAX_RESPUESTA = 256 * 1024
REGISTRO = {
    'suelo': ('Perfil de suelo', 'Resume el pH, la textura y la elevación de la selección.'),
    'balance_hidrico': ('Indicadores de agua', 'Resume la precipitación, la humedad y la evapotranspiración de la selección.'),
}


class ErrorPlugin(Exception):
    def __init__(self, mensaje, estado):
        super().__init__(mensaje)
        self.estado = estado


def _archivo_plugin(plugin):
    return RAIZ / 'extensiones' / f'{plugin}.py'


class GestorPlugins:
    def __init__(self):
        self._desactivados = set()
        self._candado = Lock()
        self._ocupados = {plugin: BoundedSemaphore(1) for plugin in REGISTRO}

    def _metadata(self, plugin):
        nombre, descripcion = REGISTRO[plugin]
        return dict(id=plugin, nombre=nombre, descripcion=descripcion,
                    habilitado=plugin not in self._desactivados,
                    disponible=_archivo_plugin(plugin).is_file())

    def listar(self):
        with self._candado:
            return [self._metadata(plugin) for plugin in REGISTRO]

    def cambiar_estado(self, plugin, habilitado):
        with self._candado:
            if plugin not in REGISTRO:
                raise ErrorPlugin('Plugin desconocido.', 404)
            if habilitado:
                self._desactivados.discard(plugin)
            else:
                self._desactivados.add(plugin)
            return self._metadata(plugin)

    def ejecutar(self, plugin, ruta, datos, max_pixeles):
        with self._candado:
            if plugin not in REGISTRO or not _archivo_plugin(plugin).is_file():
                raise ErrorPlugin('Plugin no disponible.', 404)
            if plugin in self._desactivados:
                raise ErrorPlugin('Este plugin está desactivado.', 409)
            ocupado = self._ocupados[plugin]
            if not ocupado.acquire(blocking=False):
                raise ErrorPlugin('Este plugin ya se está ejecutando.', 429)
        try:
            return _ejecutar_proceso(plugin, ruta, datos, max_pixeles)
        finally:
            ocupado.release()


def _ejecutar_proceso(plugin, ruta, datos, max_pixeles):
    entrada = json.dumps(datos, ensure_ascii=False).encode('utf-8')
    entorno = {k: v for k, v in os.environ.items()
               if k.upper() not in {'NVIDIA_API_KEY', 'NEMOTRON_API_KEY'}}
    try:
        proceso = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), plugin, str(ruta), str(max_pixeles)],
            input=entrada, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=entorno, timeout=TIEMPO_LIMITE,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise ErrorPlugin('El plugin superó el tiempo de espera. Puedes desactivarlo y seguir usando GeoVision.', 504) from exc
    except OSError as exc:
        raise ErrorPlugin('No se pudo iniciar el plugin.', 503) from exc
    if proceso.returncode or len(proceso.stdout) > MAX_RESPUESTA:
        logging.warning('El proceso del plugin %s no produjo un resultado válido.', plugin)
        raise ErrorPlugin('El plugin falló. Puedes desactivarlo y seguir usando GeoVision.', 503)
    try:
        respuesta = json.loads(proceso.stdout)
    except (ValueError, UnicodeError) as exc:
        raise ErrorPlugin('El plugin no devolvió datos válidos.', 503) from exc
    if 'error' in respuesta:
        raise ErrorPlugin(respuesta['error'], respuesta['estado'])
    return respuesta['resultado']


def _proceso_plugin():
    plugin, archivo, max_pixeles = sys.argv[1:]
    if plugin not in REGISTRO:
        raise ValueError('Plugin desconocido')

    dependencias = RAIZ.parent / '.deps_geotiff'
    if dependencias.is_dir():
        sys.path.append(str(dependencias))
    from analizador import ErrorAnalisis

    datos = json.load(sys.stdin.buffer)
    try:
        # Un print del plugin no debe contaminar el canal de respuesta.
        with redirect_stdout(sys.stderr):
            especificacion = importlib.util.spec_from_file_location(f'extensiones.{plugin}', _archivo_plugin(plugin))
            modulo = importlib.util.module_from_spec(especificacion)
            especificacion.loader.exec_module(modulo)
            resultado = modulo.ejecutar(Path(archivo), datos, int(max_pixeles))
        if not isinstance(resultado, dict):
            raise TypeError('El plugin debe devolver un diccionario')
        respuesta = dict(resultado=resultado)
    except ErrorAnalisis as exc:
        respuesta = dict(error=str(exc), estado=exc.estado)
    contenido = json.dumps(respuesta, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(contenido) > MAX_RESPUESTA:
        raise ValueError('Respuesta demasiado grande')
    sys.stdout.buffer.write(contenido)


gestor = GestorPlugins()


if __name__ == '__main__':
    _proceso_plugin()
