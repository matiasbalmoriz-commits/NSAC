"""Añade cartografía de referencia y estilos de QGIS al GeoPackage de chunks."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np
import pyogrio
from rasterio.warp import transform_geom
from shapely.geometry import shape, mapping
from shapely import from_wkb

DATA_DIR = Path(__file__).resolve().parent / 'cartografia'
LAYERS = (
    ('limite_paraguay', 'limite_paraguay', 'MultiPolygon'),
    ('rios_paraguay', 'rios', 'MultiLineString'),
)


def agregar_cartografia(path, crs, hidrografia=None):
    """Copia capas nacionales al CRS de los chunks, sin usar Internet."""
    layers = LAYERS + (('lagos_paraguay', 'lagos', 'MultiPolygon'),) if hidrografia else LAYERS
    if hidrografia:
        if Path(hidrografia).resolve() == Path(path).resolve():
            raise ValueError('La hidrografía y la salida deben ser archivos diferentes.')
        available = {name for name, _ in pyogrio.list_layers(hidrografia)}
        if not {'limite_paraguay', 'rios', 'lagos'} <= available:
            raise ValueError('La hidrografía debe contener limite_paraguay, rios y lagos.')
    for stem, layer, geometry_type in layers:
        if hidrografia:
            meta, _, geometries, columns = pyogrio.raw.read(hidrografia, layer=layer)
            if not meta['crs'] or len(geometries) == 0:
                raise ValueError(f'Capa {layer} vacía o sin CRS.')
            geometries = np.array([
                shape(transform_geom(meta['crs'], crs, mapping(from_wkb(wkb)))).wkb
                for wkb in geometries], dtype=object)
            pyogrio.raw.write(path, geometries, columns, list(meta['fields']), layer=layer,
                              driver='GPKG', geometry_type=geometry_type,
                              promote_to_multi=True, crs=crs)
            continue
        features = json.loads((DATA_DIR / f'{stem}.geojson').read_text(encoding='utf-8'))['features']
        geometries = np.array([
            shape(transform_geom('EPSG:4326', crs, feature['geometry'])).wkb
            for feature in features
        ], dtype=object)
        names = np.array([feature['properties'].get('nombre') or '' for feature in features], dtype=object)
        pyogrio.raw.write(
            path, geometries, [names], ['nombre'], layer=layer, driver='GPKG',
            geometry_type=geometry_type, promote_to_multi=True, crs=crs)

    agregar_estilos(path, incluir_lagos=bool(hidrografia))
    if hidrografia:
        metadata = Path(hidrografia).with_suffix('.hidrografia.json')
        return {'layers': [layer for _, layer, _ in layers],
                'source_file': str(Path(hidrografia).resolve()),
                'qgis_default_styles': True,
                'source_metadata': json.loads(metadata.read_text(encoding='utf-8')) if metadata.exists() else None}
    return {
        'layers': [layer for _, layer, _ in LAYERS],
        'source': 'Natural Earth', 'scale': '1:10 millones',
        'extent': 'Paraguay completo; ríos con margen fronterizo de 0,02 grados',
        'qgis_default_styles': True,
        'note': 'Ríos principales; no es una red exhaustiva de arroyos ni una delimitación oficial.',
    }


def agregar_estilos(path, incluir_lagos=False):
    layers = LAYERS + (('lagos_paraguay', 'lagos', 'MultiPolygon'),) if incluir_lagos else LAYERS
    # Tabla estándar que QGIS consulta para cargar estilos predeterminados del GPKG.
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('''CREATE TABLE IF NOT EXISTS layer_styles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            f_table_catalog TEXT, f_table_schema TEXT, f_table_name TEXT,
            f_geometry_column TEXT, styleName TEXT, styleQML TEXT, styleSLD TEXT,
            useAsDefault BOOLEAN, description TEXT, owner TEXT, ui TEXT,
            update_time DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        for stem, layer, _ in layers:
            geometry_column = db.execute(
                'SELECT column_name FROM gpkg_geometry_columns WHERE table_name=?', (layer,)
            ).fetchone()[0]
            qml = (DATA_DIR / f'{stem}.qml').read_text(encoding='utf-8')
            db.execute('''INSERT INTO layer_styles
                (f_table_catalog, f_table_schema, f_table_name, f_geometry_column,
                 styleName, styleQML, styleSLD, useAsDefault, description, owner, ui)
                VALUES ('', '', ?, ?, 'NSAC', ?, '', 1, ?, '', '')''',
                (layer, geometry_column, qml, 'NSAC: cartografía de referencia'))
