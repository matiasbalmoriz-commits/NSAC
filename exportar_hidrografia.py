"""Exporta cauces medianos/grandes y lagos de Paraguay desde Earth Engine."""
import argparse
import json
import math
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import ee
import numpy as np
import pyogrio
from shapely import make_valid
from shapely.geometry import shape

from cartografia_field_shift import DATA_DIR, agregar_estilos

RIVERS_ASSET = 'WWF/HydroSHEDS/v1/FreeFlowingRivers'
LAKES_ASSET = 'projects/sat-io/open-datasets/HydroLakes/lake_poly_v10'


def descargar(collection):
    """Pagina computeFeatures sin los límites de tamaño de getInfo/toList."""
    token = None
    while True:
        request = {'expression': collection, 'pageSize': 500}
        if token:
            request['pageToken'] = token
        page = ee.data.computeFeatures(request)
        yield from page.get('features', [])
        token = page.get('nextPageToken')
        if not token:
            break


def guardar_capa(path, layer, features, fields, kind, clip=None):
    geometries, rows = [], []
    for feature in features:
        geom = make_valid(shape(feature['geometry']))
        if clip is not None:
            geom = geom.intersection(clip)
        parts = []
        def collect(part):
            if part.geom_type == kind:
                parts.append(part)
            elif hasattr(part, 'geoms'):
                for child in part.geoms:
                    collect(child)
        collect(geom)
        if not parts:
            continue
        from shapely.ops import unary_union
        geom = unary_union(parts)
        props = feature['properties']
        rows.append([props.get(source, '') if dtype == 'object' else props[source]
                     for _, source, dtype in fields])
        geometries.append(geom.wkb)
    if not geometries:
        raise ValueError(f'Sin elementos en {layer}; revisa umbrales y permisos de la colección.')
    columns = [np.array([row[i] for row in rows], dtype=dtype)
               for i, (_, _, dtype) in enumerate(fields)]
    pyogrio.raw.write(path, np.array(geometries, dtype=object), columns,
                      [name for name, _, _ in fields], layer=layer, driver='GPKG',
                      geometry_type='Multi' + kind, promote_to_multi=True, crs='EPSG:4326')
    return len(geometries)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--authenticate', action='store_true')
    parser.add_argument('--min-caudal', type=float, default=1.0, help='Caudal medio mínimo en m³/s')
    parser.add_argument('--min-lago-km2', type=float, default=1.0, help='Área mínima del lago en km²')
    parser.add_argument('--output', type=Path, default=Path('datos/hidrografia.gpkg'))
    args = parser.parse_args()
    if any(not math.isfinite(v) or v <= 0 for v in [args.min_caudal, args.min_lago_km2]):
        parser.error('Los umbrales deben ser positivos y finitos.')
    output = args.output
    metadata = output.with_suffix('.hidrografia.json')
    if output.suffix.lower() != '.gpkg' or output.exists() or metadata.exists():
        parser.error('Usa un nombre .gpkg nuevo sin .hidrografia.json existente.')
    if args.authenticate:
        ee.Authenticate()
    ee.Initialize(project=args.project)
    ee.data.setDeadline(300000)
    boundary = json.loads((DATA_DIR / 'limite_paraguay.geojson').read_text(encoding='utf-8'))
    country = shape(boundary['features'][0]['geometry'])
    area = ee.Geometry(boundary['features'][0]['geometry'])
    rivers = ee.FeatureCollection(RIVERS_ASSET).filterBounds(area.buffer(2000)).filter(
        ee.Filter.gte('DIS_AV_CMS', args.min_caudal)).select(['NOID', 'DIS_AV_CMS', 'UPLAND_SKM'])
    lakes = ee.FeatureCollection(LAKES_ASSET).filterBounds(area).filter(
        ee.Filter.gte('Lake_area', args.min_lago_km2)).select(['Hylak_id', 'Lake_name', 'Lake_area', 'Lake_type'])
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='hidrografia_', dir=output.parent) as scratch:
        partial = Path(scratch) / output.name
        counts = {}
        counts['limite_paraguay'] = guardar_capa(partial, 'limite_paraguay', boundary['features'],
            [('nombre', 'nombre', 'object')], 'Polygon')
        print('Descargando cauces de HydroSHEDS…', flush=True)
        counts['rios'] = guardar_capa(partial, 'rios', descargar(rivers), [
            ('id_cauce', 'NOID', 'int64'), ('caudal_m3_s', 'DIS_AV_CMS', 'float64'),
            ('cuenca_km2', 'UPLAND_SKM', 'float64')], 'LineString', country.buffer(.02))
        print('Descargando lagos y embalses de HydroLAKES…', flush=True)
        counts['lagos'] = guardar_capa(partial, 'lagos', descargar(lakes), [
            ('id_lago', 'Hylak_id', 'int64'), ('nombre', 'Lake_name', 'object'),
            ('area_km2', 'Lake_area', 'float64'), ('tipo', 'Lake_type', 'int32')], 'Polygon')
        agregar_estilos(partial, incluir_lagos=True)
        info = {'source': 'HydroSHEDS Free Flowing Rivers; HydroLAKES v1.0; Natural Earth (límite)',
                'rivers_asset': RIVERS_ASSET, 'lakes_asset': LAKES_ASSET,
                'min_caudal_m3_s': args.min_caudal, 'min_lago_km2': args.min_lago_km2,
                'counts': counts, 'crs': 'EPSG:4326',
                'note': 'Tamaño de cauce aproximado por caudal modelado, no por ancho observado. '
                        'Lagos y embalses completos que intersectan Paraguay. No representa la fecha del TIFF.'}
        (Path(scratch) / metadata.name).write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
        partial.replace(output)
        (Path(scratch) / metadata.name).replace(metadata)
    print(f'Hidrografía: {output}\nElementos: {counts}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (ee.EEException, OSError, ValueError) as error:
        sys.exit(f'Error: {error}')
