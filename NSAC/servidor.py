"""Servidor local: python servidor.py [--geotiff RUTA] [--puerto 8000]."""
import argparse
import json
import logging
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import BoundedSemaphore, Timer
from urllib.parse import urlsplit
import webbrowser

from analizador import ErrorAnalisis, analizar, metadatos, vista_previa

ROOT = Path(__file__).resolve().parent
GEOTIFF_LOCAL = ROOT / 'paraguay_2023_combinado.tif'
ESTATICOS = {'/': ('index.html', 'text/html'), '/index.html': ('index.html', 'text/html'),
             '/app.js': ('app.js', 'text/javascript'),
             '/style.css': ('style.css', 'text/css')}


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, geotiff, max_pixeles, **kwargs):
        self.geotiff, self.max_pixeles = geotiff, max_pixeles
        super().__init__(*args, **kwargs)

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def responder(self, estado, datos, tipo='application/json'):
        if tipo == 'application/json':
            cuerpo = json.dumps(datos, ensure_ascii=False, allow_nan=False).encode('utf-8')
        else:
            cuerpo = datos
        if tipo == 'application/json' or tipo.startswith('text/'):
            tipo += '; charset=utf-8'
        self.send_response(estado)
        self.send_header('Content-Type', tipo)
        self.send_header('Content-Length', str(len(cuerpo)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; object-src 'none'; frame-ancestors 'none'")
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
        ruta = urlsplit(self.path).path
        if ruta in ESTATICOS:
            nombre, tipo = ESTATICOS[ruta]
            self.responder(200, (ROOT / 'web' / nombre).read_bytes(), tipo)
        elif ruta == '/api/info':
            self.responder(200, self.server.info)
        elif ruta == '/api/vista.png':
            try:
                png = vista_previa(self.geotiff, self.server.info)
            except ErrorAnalisis as exc:
                self.responder(exc.estado, {'error': str(exc)})
            except Exception:
                logging.exception('Error al generar la vista previa')
                self.responder(500, {'error': 'No se pudo generar la vista previa del GeoTIFF.'})
            else:
                self.responder(200, png, 'image/png')
        else:
            self.responder(404, {'error': 'Ruta no encontrada.'})

    def do_POST(self):
        if not self.acceso_local():
            return
        if urlsplit(self.path).path != '/api/analizar':
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
        if not self.server.ocupado.acquire(blocking=False):
            self.responder(429, {'error': 'Hay otro análisis en curso. Intenta nuevamente al terminar.'})
            return
        try:
            self.responder(200, analizar(self.geotiff, datos, self.max_pixeles))
        except ErrorAnalisis as exc:
            self.responder(exc.estado, {'error': str(exc)})
        except Exception:
            logging.exception('Error durante el análisis')
            self.responder(500, {'error': 'No se pudo analizar el archivo. Consulta la consola del servidor.'})
        finally:
            self.server.ocupado.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--geotiff', type=Path, default=GEOTIFF_LOCAL,
                        help=f'Archivo GeoTIFF (por defecto: {GEOTIFF_LOCAL.name})')
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
