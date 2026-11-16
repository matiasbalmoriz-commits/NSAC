import json
import sys
import tempfile
import threading
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
import rasterio
from rasterio.transform import Affine, from_origin
from rasterio.warp import transform

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analizador import CATALOGO, ErrorAnalisis, analizar, metadatos
from servidor import Handler


class AnalizadorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ruta = Path(self.temp.name) / 'prueba.tif'
        self.peticion = dict(pos1=dict(lon=-58, lat=-26), pos2=dict(lon=-57.96, lat=-25.96))

    def crear(self, nombres=('elevation_m', 'land_cover'), datos=None, crs='EPSG:4326', affine=None, scales=None):
        if datos is None:
            datos = np.ones((len(nombres), 4, 4), dtype='float32')
        with rasterio.open(self.ruta, 'w', driver='GTiff', width=datos.shape[2], height=datos.shape[1],
                           count=len(nombres), dtype='float32', crs=crs,
                           transform=affine or from_origin(-58, -25.96, .01, .01), nodata=-9999) as dst:
            dst.write(datos.astype('float32'))
            for i, nombre in enumerate(nombres, 1):
                dst.set_band_description(i, nombre)
            if scales:
                dst.scales = scales
                dst.offsets = tuple(1 for _ in nombres)

    def test_estadisticas_nodata_clases_y_esquinas_invertidas(self):
        datos = np.array([np.arange(16).reshape(4, 4), [[0, 0, 1, 1]] * 4], dtype='float32')
        datos[0, 0, 0] = -9999
        datos[0, 0, 1] = np.nan
        datos[0, 0, 2] = np.inf
        self.crear(datos=datos)
        r = analizar(self.ruta, self.peticion)
        self.assertEqual(r['pixeles_seleccionados'], 16)
        elevacion, cobertura = r['bandas']
        self.assertEqual(elevacion['validos'], 13)
        self.assertEqual(elevacion['sin_datos'], 3)
        self.assertAlmostEqual(elevacion['media'], np.arange(3, 16).mean())
        self.assertAlmostEqual(elevacion['desviacion'], np.arange(3, 16).std())
        self.assertEqual(cobertura['clases'], [dict(valor=0., pixeles=8, porcentaje=50.), dict(valor=1., pixeles=8, porcentaje=50.)])
        self.assertIsNone(cobertura['media'])
        inversa = dict(pos1=self.peticion['pos2'], pos2=self.peticion['pos1'])
        self.assertEqual(r, analizar(self.ruta, inversa))
        json.dumps(r, allow_nan=False)

    def test_25_27_y_orden_arbitrario(self):
        for n in (25, 27):
            nombres = list(reversed(CATALOGO))
            if n == 25:
                nombres = [b for b in nombres if not b.startswith('eco_')]
            self.crear(nombres=nombres)
            info = metadatos(self.ruta)
            self.assertEqual(info['total_bandas'], n)
            self.assertEqual(info['bandas'][0]['nombre'], nombres[0])
            self.assertEqual(len(analizar(self.ruta, self.peticion)['bandas']), n)
            self.assertFalse(info['avisos'])

    def test_crs_proyectado_y_escala(self):
        x, y = transform('EPSG:4326', 'EPSG:6933', [-58], [-25.96])
        self.crear(nombres=['elevation_m'], crs='EPSG:6933',
                   affine=from_origin(x[0], y[0], 120, 120), scales=(2,))
        lon, lat = transform('EPSG:6933', 'EPSG:4326', [x[0], x[0]+480], [y[0], y[0]-480])
        p = dict(pos1=dict(lon=lon[0], lat=lat[0]), pos2=dict(lon=lon[1], lat=lat[1]))
        r = analizar(self.ruta, p)
        self.assertEqual(r['pixeles_seleccionados'], 16)
        self.assertEqual(r['bandas'][0]['media'], 3)

    def test_mascara_interna_y_nodata(self):
        datos = np.ones((1, 4, 4), dtype='float32')
        datos[0, 0, 0] = -9999
        self.crear(nombres=['elevation_m'], datos=datos)
        with rasterio.open(self.ruta, 'r+') as dst:
            mascara = np.full((4, 4), 255, dtype='uint8')
            mascara[1, 1] = 0
            dst.write_mask(mascara)
        self.assertEqual(analizar(self.ruta, self.peticion)['bandas'][0]['validos'], 14)

    def test_combinacion_estadisticas_varios_bloques(self):
        datos = np.arange(300 * 300, dtype='float32').reshape(1, 300, 300)
        self.crear(nombres=['elevation_m'], datos=datos, affine=from_origin(-58, -25, .001, .001))
        p = dict(pos1=dict(lon=-58, lat=-25), pos2=dict(lon=-57.7, lat=-25.3))
        b = analizar(self.ruta, p)['bandas'][0]
        self.assertEqual(b['validos'], 90000)
        self.assertAlmostEqual(b['media'], datos.astype('float64').mean())
        self.assertAlmostEqual(b['desviacion'], datos.astype('float64').std())

    def test_rotacion_seleccion_por_centros(self):
        affine = Affine.translation(-58, -25.96) * Affine.rotation(18) * Affine.scale(.01, -.01)
        self.crear(nombres=['elevation_m'], affine=affine)
        esperado = sum(-58 <= (affine * (c+.5, f+.5))[0] <= -57.96
                       and -26 <= (affine * (c+.5, f+.5))[1] <= -25.96
                       for f in range(4) for c in range(4))
        self.assertEqual(analizar(self.ruta, self.peticion)['pixeles_seleccionados'], esperado)

    def test_sin_datos_y_banda_desconocida(self):
        self.crear(nombres=['desconocida'], datos=np.full((1, 4, 4), -9999))
        b = analizar(self.ruta, self.peticion)['bandas'][0]
        self.assertEqual(b['validos'], 0)
        self.assertIsNone(b['media'])
        self.assertFalse(b['identificada'])
        self.assertTrue(metadatos(self.ruta)['avisos'])

    def test_validacion_y_limites(self):
        self.crear()
        for p in ({}, [], dict(pos1=dict(lon=True, lat=1), pos2=dict(lon=2, lat=3)),
                  dict(pos1=dict(lon=float('nan'), lat=1), pos2=dict(lon=2, lat=3)),
                  dict(pos1=dict(lon=1, lat=1), pos2=dict(lon=1, lat=2))):
            with self.assertRaises(ErrorAnalisis):
                analizar(self.ruta, p)
        with self.assertRaises(ErrorAnalisis) as err:
            analizar(self.ruta, self.peticion, max_pixeles=1)
        self.assertEqual(err.exception.estado, 413)
        for p in (dict(pos1=dict(lon=0, lat=0), pos2=dict(lon=1, lat=1)),
                  dict(pos1=dict(lon=-57.999, lat=-25.961), pos2=dict(lon=-57.998, lat=-25.962))):
            with self.assertRaises(ErrorAnalisis) as err:
                analizar(self.ruta, p)
            self.assertEqual(err.exception.estado, 422)

    def test_api_http_y_estaticos(self):
        self.crear()
        servidor = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, geotiff=self.ruta, max_pixeles=5000000))
        servidor.info = metadatos(self.ruta)
        servidor.ocupado = threading.BoundedSemaphore(1)
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        self.addCleanup(servidor.server_close)
        self.addCleanup(hilo.join, 3)
        self.addCleanup(servidor.shutdown)
        base = f'http://127.0.0.1:{servidor.server_port}'
        for ruta, fragmento in (('/', b'<title>GeoVision'), ('/app.js', b'api/analizar'), ('/style.css', b':root'), ('/api/info', b'total_bandas')):
            with urlopen(base + ruta) as response:
                self.assertIn(fragmento, response.read())
        def post(cuerpo, headers=None):
            return urlopen(Request(base + '/api/analizar', data=cuerpo,
                                   headers=headers or {'Content-Type': 'application/json'}))
        with post(json.dumps(self.peticion).encode()) as response:
            self.assertEqual(json.load(response)['pixeles_seleccionados'], 16)
        for cuerpo, cabeceras, codigo in ((b'{', None, 400), (b'{}', None, 400),
                                         (b'{}', {'Content-Type': 'text/plain'}, 415),
                                         (b'{}', {'Content-Type': 'application/json', 'Origin': 'https://example.com'}, 403)):
            with self.assertRaises(HTTPError) as err:
                post(cuerpo, cabeceras)
            self.assertEqual(err.exception.code, codigo)
            err.exception.close()
        servidor.ocupado.acquire()
        try:
            with self.assertRaises(HTTPError) as err:
                post(json.dumps(self.peticion).encode())
            self.assertEqual(err.exception.code, 429)
            err.exception.close()
        finally:
            servidor.ocupado.release()


if __name__ == '__main__':
    unittest.main()
