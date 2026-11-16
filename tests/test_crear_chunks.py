import json, sqlite3, subprocess, sys, tempfile
from contextlib import closing
from xml.etree import ElementTree
import unittest
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import Affine
import pyogrio, shapely
class ChunkCliTest(unittest.TestCase):
    def test_cli_writes_outputs_and_closes_database(self):
        with tempfile.TemporaryDirectory(prefix='nsac-smoke-') as d:
            d=Path(d)
            a=np.ones((6,6),dtype='float32'); a[:,3:]=2; a[0,0]=-9999
            with rasterio.open(d/'input.tif','w',driver='GTiff',width=6,height=6,count=2,dtype='float32',crs='EPSG:6933',transform=Affine(120,0,0,0,-120,720),nodata=-9999) as f:
                f.write(a,1); f.write(np.full((6,6),.5,dtype='float32'),2)
                f.set_band_description(1,'land_cover'); f.set_band_description(2,'ndvi')
            for tile in (1,2,4,6):
                out=d/f'chunks{tile}.gpkg'
                result = subprocess.run(
                    [sys.executable, str(Path(__file__).resolve().parents[1] / 'crear_chunks.py'),
                     str(d/'input.tif'), '--category', 'land_cover', '--bin', 'ndvi:0.2:-1',
                     '--tile', str(tile), '--output', str(out)],
                    capture_output=True, text=True)
                assert result.returncode == 0, result.stdout + result.stderr
                assert json.loads(out.with_suffix('.chunks.json').read_text())['chunks'] == 2
                assert not list(d.glob('field_shift_*')), 'Temporary database directory leaked'
                meta,fids,geom,data=pyogrio.raw.read(out,layer='chunks')
                cols=dict(zip(meta['fields'],data))
                assert sorted(cols['pixels'])==[17,18], cols
                assert np.allclose(sorted(cols['area_ha']),[24.48,25.92])
                assert np.allclose(cols['mean_ndvi'],.5)
                assert np.all(shapely.is_valid(shapely.from_wkb(geom)))
                assert np.isclose(shapely.area(shapely.from_wkb(geom)).sum(),35*14400)
                layers = {name for name, _ in pyogrio.list_layers(out)}
                assert {'chunks', 'limite_paraguay', 'rios'} <= layers
                for layer, expected in [('limite_paraguay', 1), ('rios', 8)]:
                    info = pyogrio.read_info(out, layer=layer)
                    assert info['features'] == expected
                    assert info['crs'] == 'EPSG:6933'
                    _, _, geometry, _ = pyogrio.raw.read(out, layer=layer)
                    assert np.all(shapely.is_valid(shapely.from_wkb(geometry)))
                with closing(sqlite3.connect(out)) as db:
                    styles = dict(db.execute(
                        'SELECT f_table_name, styleQML FROM layer_styles WHERE useAsDefault=1'))
                river_style = ElementTree.fromstring(styles['rios'])
                assert river_style.find(".//Option[@name='line_color']").get('value') == '0,102,255,255'
                border_style = ElementTree.fromstring(styles['limite_paraguay'])
                assert border_style.find(".//Option[@name='style']").get('value') == 'no'
                metadata = json.loads(out.with_suffix('.chunks.json').read_text())
                assert metadata['cartografia']['layers'] == ['limite_paraguay', 'rios']
            # La opción explícita conserva la salida anterior de solo chunks.
            simple = d / 'sin_cartografia.gpkg'
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve().parents[1] / 'crear_chunks.py'),
                 str(d/'input.tif'), '--category', 'land_cover', '--bin', 'ndvi:0.2:-1',
                 '--sin-cartografia', '--output', str(simple)], capture_output=True, text=True)
            assert result.returncode == 0, result.stdout + result.stderr
            assert [name for name, _ in pyogrio.list_layers(simple)] == ['chunks']
            assert json.loads(simple.with_suffix('.chunks.json').read_text())['cartografia'] is None

if __name__ == "__main__":
    unittest.main()
