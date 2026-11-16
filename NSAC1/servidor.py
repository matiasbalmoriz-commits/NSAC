"""GeoVision. Servidor local para explorar suelos y cultivos de Paraguay."""
import argparse
import json
import logging
import sys
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from shutil import copyfileobj
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore, Lock, Timer
from urllib.parse import parse_qs, urlsplit
import webbrowser

# Reutiliza las dependencias locales del generador si están instaladas.
dependencias = Path(__file__).resolve().parents[1] / '.deps_geotiff'
if dependencias.is_dir():
    sys.path.append(str(dependencias))

from analizador import ErrorAnalisis, analizar, metadatos
from catalogo_cultivos import paleta_cultivos
from mapa import cobertura, consultar_celda, exportar_recorte
from nemotron import estado_configuracion, probar_conexion, ranking_cultivos
from restauracion import restaurar

ROOT = Path(__file__).resolve().parent
GEOTIFF_PREDETERMINADO = ROOT.parent / 'datos' / 'fuentes_paraguay_480m' / 'paraguay_2023_combinado.tif'
ESTATICOS = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
             '/mapa.js': ('mapa.js', 'text/javascript'),
             '/plugins.js': ('plugins.js', 'text/javascript'),
             '/style.css': ('style.css', 'text/css')}


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, geotiff, max_pixeles, **kwargs):
        self.geotiff, self.max_pixeles = geotiff, max_pixeles
        super().__init__(*args, **kwargs)

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def responder(self, estado, datos, tipo='application/json'):
        cuerpo = json.dumps(datos, ensure_ascii=False, allow_nan=False).encode('utf-8') if tipo == 'application/json' else datos
        self.send_response(estado)
        self.send_header('Content-Type', tipo if tipo == 'image/png' else tipo + '; charset=utf-8')
        self.send_header('Content-Length', str(len(cuerpo)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        try:
            self.wfile.write(cuerpo)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def acceso_local(self):
        puerto = self.server.server_port
        permitidos = {f'127.0.0.1:{puerto}', f'localhost:{puerto}'}
        if self.headers.get('Host', '') not in permitidos:
            self.responder(403, {'error': 'Host no permitido.'})
            return False
        origin = self.headers.get('Origin')
        if origin and origin not in {f'http://{h}' for h in permitidos}:
            self.responder(403, {'error': 'Usa la interfaz del servidor local.'})
            return False
        return True

    def do_GET(self):
        if not self.acceso_local():
            return
        url = urlsplit(self.path)
        ruta = url.path
        if ruta in ESTATICOS:
            nombre, tipo = ESTATICOS[ruta]
            try:
                contenido = (ROOT / 'web' / nombre).read_bytes()
            except FileNotFoundError:
                self.responder(404, {'error': 'Archivo no disponible.'})
            else:
                self.responder(200, contenido, tipo)
        elif ruta == '/api/nemotron/config':
            self.responder(200, estado_configuracion(self.server.clave_nemotron))
        elif ruta == '/api/plugins':
            self.gestionar_plugins()
        elif ruta == '/api/info':
            _, mapa = cobertura(self.geotiff, self.geotiff.stat().st_mtime_ns)
            self.responder(200, dict(self.server.info, mapa=mapa, paleta_cultivos=paleta_cultivos()))
        elif ruta == '/api/cobertura.png':
            imagen, _ = cobertura(self.geotiff, self.geotiff.stat().st_mtime_ns)
            if imagen is None:
                self.responder(404, {'error': 'El GeoTIFF no tiene banda land_cover.'})
            else:
                self.responder(200, imagen, 'image/png')
        elif ruta == '/api/celda':
            parametros = parse_qs(url.query)
            try:
                lon, lat = (float(parametros.get(campo, ['nan'])[0]) for campo in ('lon', 'lat'))
                self.responder(200, consultar_celda(self.geotiff, lon, lat))
            except ValueError as exc:
                self.responder(exc.estado if isinstance(exc, ErrorAnalisis) else 400,
                               {'error': str(exc) if isinstance(exc, ErrorAnalisis) else 'Coordenadas inválidas.'})
        else:
            self.responder(404, {'error': 'Ruta no encontrada.'})

    def do_POST(self):
        if not self.acceso_local():
            return
        ruta = urlsplit(self.path).path
        ruta_plugin = ruta.startswith('/api/plugins/')
        if not ruta_plugin and ruta not in ('/api/analizar', '/api/recorte', '/api/cultivos', '/api/restauracion',
                                           '/api/nemotron/config', '/api/nemotron/probar'):
            self.responder(404, {'error': 'Ruta no encontrada.'})
            return
        if self.headers.get_content_type() != 'application/json':
            self.responder(415, {'error': 'Usa Content-Type: application/json.'})
            return
        try:
            largo = int(self.headers.get('Content-Length', '0'))
            if not 0 < largo <= 8192:
                raise ErrorAnalisis('El cuerpo JSON debe ocupar entre 1 y 8192 bytes.', 413)
            datos = json.loads(self.rfile.read(largo))
        except (ValueError, UnicodeError) as exc:
            self.responder(exc.estado if isinstance(exc, ErrorAnalisis) else 400,
                           {'error': str(exc) if isinstance(exc, ErrorAnalisis) else 'JSON o longitud inválidos.'})
            return
        if ruta == '/api/nemotron/config':
            self.actualizar_clave_nemotron(datos)
            return
        if ruta_plugin:
            plugin, _, accion = ruta.removeprefix('/api/plugins/').partition('/')
            self.gestionar_plugins(plugin, accion, datos)
            return
        ocupado = self.server.ocupado_nemotron if ruta in ('/api/cultivos', '/api/nemotron/probar') else self.server.ocupado
        if not ocupado.acquire(blocking=False):
            self.responder(429, {'error': 'Hay otro análisis en curso. Intenta nuevamente al terminar.'})
            return
        try:
            if ruta == '/api/nemotron/probar':
                self.responder(200, probar_conexion(self.server.clave_nemotron))
            elif ruta == '/api/analizar':
                self.responder(200, analizar(self.geotiff, datos, self.max_pixeles))
            elif ruta == '/api/cultivos':
                self.responder(200, ranking_cultivos(self.geotiff, datos, self.max_pixeles,
                                                   clave_interfaz=self.server.clave_nemotron))
            elif ruta == '/api/restauracion':
                self.responder(200, restaurar(self.geotiff, datos, self.max_pixeles))
            else:
                with TemporaryDirectory(prefix='recorte_nsac_') as carpeta:
                    destino = Path(carpeta) / 'recorte.tif'
                    exportar_recorte(self.geotiff, destino, datos, self.max_pixeles)
                    self.send_response(200)
                    self.send_header('Content-Type', 'image/tiff')
                    self.send_header('Content-Disposition', 'attachment; filename="recorte_paraguay.tif"')
                    self.send_header('Content-Length', str(destino.stat().st_size))
                    self.end_headers()
                    with destino.open('rb') as archivo:
                        try:
                            copyfileobj(archivo, self.wfile)
                        except (BrokenPipeError, ConnectionResetError):
                            pass
        except ErrorAnalisis as exc:
            self.responder(exc.estado, {'error': str(exc)})
        except Exception:
            logging.exception('Error durante el análisis')
            self.responder(500, {'error': 'No se pudo analizar el archivo. Consulta la consola del servidor.'})
        finally:
            ocupado.release()

    def gestionar_plugins(self, plugin=None, accion='', datos=None):
        # La aplicación principal inicia sin importar las extensiones ni su registro.
        try:
            from plugins_geovision import ErrorPlugin, gestor
        except Exception:
            logging.exception('No se pudo cargar el gestor de plugins')
            self.responder(503, {'error': 'Los plugins no están disponibles.'})
            return
        try:
            if plugin is None:
                resultado = {'plugins': gestor.listar()}
            elif accion == 'estado':
                habilitado = datos.get('habilitado') if isinstance(datos, dict) else None
                if not isinstance(habilitado, bool):
                    raise ErrorPlugin('Indica si el plugin está habilitado.', 400)
                resultado = gestor.cambiar_estado(plugin, habilitado)
            elif not accion:
                if not isinstance(datos, dict):
                    raise ErrorPlugin('Envía un objeto JSON para ejecutar el plugin.', 400)
                resultado = gestor.ejecutar(plugin, self.geotiff, datos, self.max_pixeles)
            else:
                raise ErrorPlugin('Ruta de plugin no encontrada.', 404)
            self.responder(200, resultado)
        except ErrorPlugin as exc:
            self.responder(exc.estado, {'error': str(exc)})
        except Exception:
            logging.exception('Error en la ruta de plugins')
            self.responder(503, {'error': 'El plugin no está disponible. Puedes seguir usando GeoVision.'})

    def actualizar_clave_nemotron(self, datos):
        clave = datos.get('clave') if isinstance(datos, dict) else None
        if not isinstance(clave, str):
            self.responder(400, {'error': 'Indica la clave como texto.'})
            return
        clave = clave.strip()
        if len(clave) > 1024 or any(not 33 <= ord(caracter) <= 126 for caracter in clave):
            self.responder(400, {'error': 'Revisa que la clave no contenga espacios ni caracteres inválidos.'})
            return
        with self.server.editar_clave_nemotron:
            if not estado_configuracion()['editable']:
                self.responder(409, {'error': 'Administra la configuración de este proveedor desde el entorno del servidor.'})
                return
            self.server.clave_nemotron = clave or None
            estado = estado_configuracion(self.server.clave_nemotron)
        self.responder(200, estado)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--geotiff', type=Path, default=GEOTIFF_PREDETERMINADO)
    parser.add_argument('--puerto', type=int, default=8000)
    parser.add_argument('--max-pixeles', type=int, default=5_000_000)
    parser.add_argument('--abrir', action='store_true', help='Abre la interfaz en el navegador')
    args = parser.parse_args()
    if args.max_pixeles <= 0 or not 1 <= args.puerto <= 65535:
        parser.error('El límite debe ser positivo y el puerto estar entre 1 y 65535.')
    ruta = args.geotiff.resolve()
    try:
        info = metadatos(ruta)
        handler = partial(Handler, geotiff=ruta, max_pixeles=args.max_pixeles)
        servidor = ThreadingHTTPServer(('127.0.0.1', args.puerto), handler)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Error: {exc}\n')
    servidor.info = dict(info, max_pixeles=args.max_pixeles)
    servidor.ocupado = BoundedSemaphore(1)
    servidor.ocupado_nemotron = BoundedSemaphore(1)
    servidor.clave_nemotron = None
    servidor.editar_clave_nemotron = Lock()
    url = f'http://127.0.0.1:{args.puerto}'
    print(f'GeoTIFF: {ruta}\nInterfaz: {url}\nDetener: Ctrl+C', flush=True)
    if args.abrir:
        Timer(.5, webbrowser.open, args=(url,)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()


if __name__ == '__main__':
    main()
