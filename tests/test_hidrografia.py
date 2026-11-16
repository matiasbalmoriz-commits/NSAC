import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pyogrio
import rasterio
from rasterio.transform import Affine
from shapely.geometry import Polygon, LineString, mapping
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exportar_hidrografia import descargar, guardar_capa
from cartografia_field_shift import agregar_estilos


def feature(geometry, **properties):
    return {'type': 'Feature', 'geometry': mapping(geometry), 'properties': properties}


class HidrografiaTest(unittest.TestCase):
    def test_paginacion(self):
        with patch('exportar_hidrografia.ee.data.computeFeatures', side_effect=[
            {'features': [{'id': 1}], 'nextPageToken': 'segunda'},
            {'features': [{'id': 2}]}]) as api:
            self.assertEqual(list(descargar('coleccion')), [{'id': 1}, {'id': 2}])
            self.assertNotIn('pageToken', api.call_args_list[0].args[0])
            self.assertEqual(api.call_args_list[1].args[0]['pageToken'], 'segunda')

    def test_hidrografia_integrada_en_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            hydro = tmp / 'hidrografia.gpkg'
            polygon = Polygon([(-58,-26),(-57,-26),(-57,-25),(-58,-25),(-58,-26)])
            guardar_capa(hydro, 'limite_paraguay', [feature(polygon, nombre='Paraguay')],
                         [('nombre','nombre','object')], 'Polygon')
            guardar_capa(hydro, 'rios', [feature(LineString([(-57.9,-25.9),(-57.1,-25.1)]),
                         NOID=1, DIS_AV_CMS=3.5, UPLAND_SKM=500)],
                         [('id_cauce','NOID','int64'),('caudal_m3_s','DIS_AV_CMS','float64'),
                          ('cuenca_km2','UPLAND_SKM','float64')], 'LineString', polygon)
            guardar_capa(hydro, 'lagos', [feature(polygon, Hylak_id=5, Lake_name='Lago prueba',
                         Lake_area=3.0, Lake_type=2)],
                         [('id_lago','Hylak_id','int64'),('nombre','Lake_name','object'),
                          ('area_km2','Lake_area','float64'),('tipo','Lake_type','int32')], 'Polygon')
            agregar_estilos(hydro, incluir_lagos=True)
            raster = tmp / 'input.tif'
            with rasterio.open(raster, 'w', driver='GTiff', width=2, height=2, count=1,
                               dtype='float32', crs='EPSG:6933', transform=Affine(120,0,0,0,-120,240)) as dst:
                dst.write(np.ones((1,2,2), dtype='float32'))
                dst.set_band_description(1, 'land_cover')
            output = tmp / 'output.gpkg'
            command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'crear_chunks.py'),
                       str(raster), '--category', 'land_cover', '--hidrografia', str(hydro),
                       '--output', str(output)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue({'chunks','limite_paraguay','rios','lagos'} <=
                            {name for name, _ in pyogrio.list_layers(output)})
            meta, _, _, columns = pyogrio.raw.read(output, layer='rios')
            self.assertEqual(meta['crs'], 'EPSG:6933')
            self.assertAlmostEqual(dict(zip(meta['fields'], columns))['caudal_m3_s'][0], 3.5)
            meta, _, geometries, columns = pyogrio.raw.read(output, layer='lagos')
            self.assertEqual(dict(zip(meta['fields'], columns))['nombre'][0], 'Lago prueba')
            from shapely import from_wkb
            self.assertGreater(abs(from_wkb(geometries[0]).bounds[0]), 1000000)
            with closing(sqlite3.connect(output)) as db:
                qml = db.execute("SELECT styleQML FROM layer_styles WHERE f_table_name='lagos'").fetchone()[0]
            self.assertEqual(ElementTree.fromstring(qml).find(".//Option[@name='color']").get('value'),
                             '65,155,240,200')
            metadata = json.loads(output.with_suffix('.chunks.json').read_text())
            self.assertIn('lagos', metadata['cartografia']['layers'])

    def test_sin_datos_no_crea_capa(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'vacio.gpkg'
            with self.assertRaisesRegex(ValueError, 'Sin elementos'):
                guardar_capa(target, 'rios', [], [], 'LineString')
            self.assertFalse(target.exists())
