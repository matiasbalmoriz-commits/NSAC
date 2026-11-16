"""Exporta las capas Field Shift como un GeoTIFF multibanda de 120 m."""
import argparse
import json
import math
import sys
from pathlib import Path

import ee
import numpy as np
import rasterio
from rasterio.transform import Affine
from rasterio.windows import Window

CRS = "EPSG:6933"
# Earth Engine may not resolve this EPSG identifier; send its full definition.
EE_CRS = rasterio.crs.CRS.from_string(CRS).to_wkt(version="WKT1_GDAL")
STEP = 120
GRID = [STEP, 0, 0, 0, -STEP, 0]
NODATA = -9999.0
ASSETS = {
    "srtm": "USGS/SRTMGL1_003",
    "mapbiomas": "projects/mapbiomas-public/assets/paraguay/collection2/mapbiomas_paraguay_collection2_integration_v1",
    "landsat8": "LANDSAT/LC08/C02/T1_L2",
    "landsat9": "LANDSAT/LC09/C02/T1_L2",
    "ph": "OpenLandMap/SOL/SOL_PH-H2O_USDA-4C1A2A_M/v02",
    "texture": "OpenLandMap/SOL/SOL_TEXTURE-CLASS_USDA-TT_M/v02",
    "era": "ECMWF/ERA5_LAND/MONTHLY_AGGR",
    "pml": "projects/pml_evapotranspiration/PML/OUTPUT/PML_V22a",
    "eco": "NASA/ECOSTRESS/L2T_LSTE/V2",
    "boundary": "FAO/GAUL/2015/level0",
}
SR = ["SR_B4", "SR_B5", "SR_B6"]
REFLECTANCE = ["ls_red", "ls_nir", "ls_swir1"]
OPTICAL = REFLECTANCE + ["ndvi", "ndmi"]
ERA = ["temperature_2m", "total_precipitation_sum", "volumetric_soil_water_layer_1"]
PML = ["ET", "Ec", "Es", "Ei", "Ew"]


def band(name, source, original, unit, native_m, operation, kind="continuous"):
    return dict(name=name, asset=ASSETS[source], original=original, unit=unit,
                native_m=native_m, operation=operation, kind=kind)


def band_records(year, eco):
    records = [
        band("elevation_m", "srtm", "elevation", "m", 30, "media espacial"),
        band("land_cover", "mapbiomas", f"classification_{year}", "clase", 30,
             "moda ponderada por solape a 120 m; código 0 excluido", "category"),
    ]
    records.extend(band(name, "landsat8", raw, "1", 30,
                        "DN*0.0000275-0.2; media espacial por escena y mediana temporal")
                   for name, raw in zip(REFLECTANCE, SR))
    records.extend([
        band("ndvi", "landsat8", "SR_B5,SR_B4", "1", 30,
             "(NIR-rojo)/(NIR+rojo); media espacial por escena y mediana temporal"),
        band("ndmi", "landsat8", "SR_B5,SR_B6", "1", 30,
             "(NIR-SWIR1)/(NIR+SWIR1); media espacial por escena y mediana temporal"),
        band("ls_valid_scenes", "landsat8", "QA_PIXEL,QA_RADSAT", "escenas", 30,
             "número de escenas con reflectancia válida en la celda", "count"),
        band("soil_ph_10cm", "ph", "b10", "pH", 250, "DN/10; vecino más cercano"),
        band("soil_texture_10cm", "texture", "b10", "clase USDA", 250,
             "vecino más cercano; clases 1–12", "category"),
        band("era_t2m_c", "era", ERA[0], "°C", 11132,
             "K-273.15; media mensual ponderada por días; vecino más cercano"),
        band("era_precip_mm", "era", ERA[1], "mm/año", 11132,
             "suma de 12 acumulados mensuales *1000; negativos a cero; vecino más cercano"),
        band("era_soil_water", "era", ERA[2], "m3/m3", 11132,
             "media mensual ponderada por días (0–7 cm); vecino más cercano"),
    ])
    for item in records:
        if item["asset"] == ASSETS["landsat8"]:
            item["additional_asset"] = ASSETS["landsat9"]
    records.extend(band(f"pml_{raw.lower()}_mm_d", "pml", raw, "mm/día", 500,
                        "DN*0.01; media de tasas de composiciones; vecino más cercano")
                   for raw in PML)
    if eco:
        records.extend([
            band("eco_lst_c", "eco", "LST,QC,cloud,water", "°C", 70,
                 "K-273.15; media espacial por escena y mediana temporal"),
            band("eco_valid_scenes", "eco", "LST,QC,cloud,water", "escenas", 70,
                 "número de escenas válidas en la celda", "count"),
        ])
    return records


def coarse(image):
    return image.reproject(crs=EE_CRS, crsTransform=GRID)


def aggregate(image, reducer):
    return coarse(image.reduceResolution(reducer=reducer, maxPixels=256))


def validate_source(label, image, bands):
    info = image.select(bands).getInfo()
    details = [{"band": b["id"], "crs": b.get("crs"), "transform": b.get("crs_transform")}
               for b in info["bands"]]
    if len(details) != len(bands) or any(not b["crs"] or not b["transform"] for b in details):
        raise ValueError(f"Proyección o bandas incompletas: {label}")
    print(label, details[0]["crs"], details[0]["transform"], flush=True)
    return details


def landsat_scene(image):
    mask = image.select("QA_PIXEL").bitwiseAnd(63).eq(0)
    mask = mask.And(image.select("QA_RADSAT").eq(0))
    raw = image.select(SR)
    mask = mask.And(raw.reduce(ee.Reducer.min()).gt(0))
    sr = raw.multiply(0.0000275).subtract(0.2).rename(REFLECTANCE).updateMask(mask)
    nir = sr.select("ls_nir")

    def index(other, name):
        other = sr.select(other)
        total = nir.add(other)
        # Se conservan reflectancias negativas, salvo ratios fuera del intervalo físico.
        ratio = nir.subtract(other).divide(total)
        return ratio.updateMask(total.gt(0).And(ratio.abs().lte(1))).rename(name)

    return aggregate(sr.addBands(index("ls_red", "ndvi"))
                     .addBands(index("ls_swir1", "ndmi")), ee.Reducer.mean()).toFloat()


def eco_scene(image):
    kelvin = image.select("LST")
    good = image.select("QC").bitwiseAnd(255).eq(0)
    good = good.And(image.select("cloud").bitwiseAnd(1).eq(0))
    good = good.And(image.select("water").bitwiseAnd(1).eq(0)).And(kelvin.gt(0))
    return aggregate(kelvin.subtract(273.15).updateMask(good).rename("eco_lst_c"),
                     ee.Reducer.mean()).toFloat()


def temporal_optical(collection, mapper, names, count_source, count_name):
    empty = coarse(ee.Image.constant([0] * len(names)).rename(names).toFloat().selfMask())
    series = collection.map(mapper).merge(ee.ImageCollection.fromImages([empty]))
    count = series.select(count_source).count().unmask(0, False).rename(count_name)
    return coarse(series.median()).addBands(coarse(count))


def prepare(year, aoi, with_eco):
    start, end = f"{year}-01-01", f"{year + 1}-01-01"
    cover_band = f"classification_{year}"
    elevation = ee.Image(ASSETS["srtm"]).select("elevation")
    cover = ee.Image(ASSETS["mapbiomas"]).select(cover_band)
    ph = ee.Image(ASSETS["ph"]).select("b10")
    texture = ee.Image(ASSETS["texture"]).select("b10")
    era = ee.ImageCollection(ASSETS["era"]).filterDate(start, end).select(ERA)
    pml = ee.ImageCollection(ASSETS["pml"]).filterDate(start, end).select(PML)
    ls = {key: ee.ImageCollection(ASSETS[key]).filterDate(start, end).filterBounds(aoi)
          for key in ("landsat8", "landsat9")}
    eco = (ee.ImageCollection(ASSETS["eco"]).filterDate(start, end).filterBounds(aoi)
           if with_eco else None)
    sources = {"srtm": (elevation, ["elevation"]), "mapbiomas": (cover, [cover_band]),
               "ph": (ph, ["b10"]), "texture": (texture, ["b10"])}
    collections = {"era": era, "pml": pml, **ls}
    if eco is not None:
        collections["eco"] = eco
    counts = ee.Dictionary({key: value.size() for key, value in collections.items()}).getInfo()
    if counts["era"] != 12 or counts["pml"] == 0 or not (counts["landsat8"] + counts["landsat9"]):
        raise ValueError(f"Cobertura temporal insuficiente: {counts}")
    required = {"era": ERA, "pml": PML, "landsat8": SR + ["QA_PIXEL", "QA_RADSAT"],
                "landsat9": SR + ["QA_PIXEL", "QA_RADSAT"], "eco": ["LST", "QC", "cloud", "water"]}
    for key, collection in collections.items():
        if counts[key]:
            sources[key] = (ee.Image(collection.first()), required[key])
    projections = {key: validate_source(key, *value) for key, value in sources.items()}

    def era_month(image):
        date = image.date()
        days = date.advance(1, "month").difference(date, "day")
        return (image.select(ERA[0]).subtract(273.15).multiply(days).rename("era_t2m_c")
                .addBands(image.select(ERA[1]).max(0).multiply(1000).rename("era_precip_mm"))
                .addBands(image.select(ERA[2]).multiply(days).rename("era_soil_water")))

    days = ee.Date(end).difference(ee.Date(start), "day")
    era_projection = ee.Image(era.first()).select(ERA[0]).projection()
    era_sums = era.map(era_month).sum().setDefaultProjection(era_projection)
    era_count = era.count().setDefaultProjection(era_projection)
    era_sums = era_sums.updateMask(era_count.reduce(ee.Reducer.min()).eq(12))
    era_values = (era_sums.select("era_t2m_c").divide(days)
                  .addBands(era_sums.select("era_precip_mm"))
                  .addBands(era_sums.select("era_soil_water").divide(days)))
    pml_values = (pml.map(lambda img: img.updateMask(img.gte(0))).mean()
                  .setDefaultProjection(ee.Image(pml.first()).select("ET").projection())
                  .multiply(0.01).rename([f"pml_{raw.lower()}_mm_d" for raw in PML]))
    static = (aggregate(elevation, ee.Reducer.mean()).rename("elevation_m")
              .addBands(aggregate(cover.updateMask(cover.gt(0)), ee.Reducer.mode()).rename("land_cover")))
    other = (coarse(ph.updateMask(ph.gt(0).And(ph.lte(140))).divide(10)).rename("soil_ph_10cm")
             .addBands(coarse(texture.updateMask(texture.gte(1).And(texture.lte(12))))
                       .rename("soil_texture_10cm"))
             .addBands(coarse(era_values)).addBands(coarse(pml_values)))
    return static, other, ls["landsat8"].merge(ls["landsat9"]), eco, counts, projections


def compute_tile(image, names, transform, width, height):
    data = ee.data.computePixels({
        "expression": image.select(names).toFloat().unmask(NODATA, False),
        "fileFormat": "NUMPY_NDARRAY",
        "bandIds": names,
        "grid": {
            "dimensions": {"width": width, "height": height},
            "crsWkt": EE_CRS,
            "affineTransform": {
                "scaleX": STEP, "scaleY": -STEP, "shearX": 0, "shearY": 0,
                "translateX": transform.c, "translateY": transform.f,
            },
        },
    })
    if data.shape != (height, width) or set(data.dtype.names or ()) != set(names):
        raise ValueError("Earth Engine devolvió dimensiones o bandas inesperadas.")
    return np.stack([data[name].astype("float32", copy=False) for name in names])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="ID del proyecto Google Cloud")
    parser.add_argument("--year", type=int, default=2023)
    parser.add_argument("--bbox", type=float, nargs=4, metavar=("O", "S", "E", "N"))
    parser.add_argument("--tile", type=int, default=256, help="lado de tesela en píxeles (32–512)")
    parser.add_argument("--ecostress", action="store_true")
    parser.add_argument("--authenticate", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("field_shift.tif"))
    args = parser.parse_args()
    if not (2013 <= args.year <= 2023 and 32 <= args.tile <= 512):
        parser.error("Año 2013–2023 y tesela 32–512.")
    if args.bbox:
        west, south, east, north = args.bbox
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            parser.error("--bbox debe ser oeste sur este norte en EPSG:4326.")
    output = args.output
    metadata = output.with_suffix(".bands.json")
    if output.suffix.lower() != ".tif" or output.exists() or metadata.exists():
        parser.error("Usa un nombre .tif nuevo y comprueba que no exista el .bands.json correspondiente.")
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.authenticate:
        ee.Authenticate()
    ee.Initialize(project=args.project)
    ee.data.setDeadline(300000)
    area = ee.FeatureCollection(ASSETS["boundary"]).filter(
        ee.Filter.eq("ADM0_NAME", "Paraguay")).geometry(30)
    if args.bbox:
        area = area.intersection(ee.Geometry.Rectangle(args.bbox, geodesic=False), 30)
    if not area.area(30).getInfo():
        raise ValueError("El área no intersecta Paraguay.")
    ring = area.bounds(30, ee.Projection(EE_CRS)).coordinates().getInfo()[0]
    left = math.floor(min(x for x, _ in ring) / STEP) * STEP
    right = math.ceil(max(x for x, _ in ring) / STEP) * STEP
    bottom = math.floor(min(y for _, y in ring) / STEP) * STEP
    top = math.ceil(max(y for _, y in ring) / STEP) * STEP
    transform = Affine(STEP, 0, left, 0, -STEP, top)
    width, height = (right - left) // STEP, (top - bottom) // STEP
    static, other, landsat, eco, counts, projections = prepare(args.year, area, args.ecostress)
    eco_enabled = args.ecostress and counts["eco"] > 0
    records = band_records(args.year, eco_enabled)
    names = [item["name"] for item in records]
    settings = dict(version=1, project=args.project, year=args.year, bbox=args.bbox, tile=args.tile,
                    eco=args.ecostress, grid=list(transform)[:6], shape=[height, width],
                    bands=names, assets=ASSETS)
    cache = output.with_suffix(".tiles")
    cache.mkdir(exist_ok=True)
    manifest = cache / "settings.json"
    if manifest.exists() and json.loads(manifest.read_text(encoding="utf-8")) != settings:
        raise ValueError(f"Los parámetros difieren de los de {cache}. Usa otro nombre de salida.")
    manifest.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    jobs = [(Window(col, row, min(args.tile, width-col), min(args.tile, height-row)),
             cache / f"{row}_{col}.npy")
            for row in range(0, height, args.tile) for col in range(0, width, args.tile)]
    valid_counts = np.zeros(len(names), dtype="int64")
    for number, (window, path) in enumerate(jobs, 1):
        local = rasterio.windows.transform(window, transform)
        w, h = int(window.width), int(window.height)
        if path.exists():
            data = np.load(path, allow_pickle=False)
        else:
            # Margen para conservar las contribuciones cerca de bordes de escena y tesela.
            bounds = rasterio.windows.bounds(window, transform)
            tile_area = ee.Geometry.Rectangle(list(bounds), ee.Projection(EE_CRS), False).buffer(360, 30)
            ls_tile = temporal_optical(landsat.filterBounds(tile_area), landsat_scene,
                                      OPTICAL, "ls_red", "ls_valid_scenes")
            stack = static.addBands(ls_tile).addBands(other)
            if eco_enabled:
                stack = stack.addBands(temporal_optical(eco.filterBounds(tile_area), eco_scene,
                                                        ["eco_lst_c"], "eco_lst_c", "eco_valid_scenes"))
            data = compute_tile(stack.clip(area), names, local, w, h)
            data[~np.isfinite(data)] = NODATA
            with path.with_suffix(".part").open("wb") as stream:
                np.save(stream, data, allow_pickle=False)
            path.with_suffix(".part").replace(path)
        if data.shape != (len(names), h, w) or data.dtype != np.float32:
            raise ValueError(f"Tesela de caché inválida: {path}")
        valid_counts += np.count_nonzero(data != NODATA, axis=(1, 2))
        print(f"Tesela {number}/{len(jobs)}", flush=True)

    if eco_enabled and not valid_counts[names.index("eco_lst_c")]:
        records = records[:-2]
        print("ECOSTRESS omitido: ninguna observación válida en el área.", file=sys.stderr)
    elif args.ecostress and not eco_enabled:
        print("ECOSTRESS omitido: sin escenas candidatas en el área.", file=sys.stderr)
    if not valid_counts[names.index("land_cover")]:
        raise ValueError("No hay cobertura válida de MapBiomas en el área seleccionada.")
    for record, count in zip(records, valid_counts):
        record["valid_pixels"] = int(count)
        if count == 0:
            print(f"Sin píxeles válidos: {record['name']}", file=sys.stderr)
    for index, record in enumerate(records, 1):
        record["band"] = index
    partial = output.with_suffix(".part.tif")
    with rasterio.open(partial, "w", driver="GTiff", width=width, height=height, count=len(records),
                       crs=CRS, transform=transform, dtype="float32", nodata=NODATA,
                       compress="deflate", predictor=3, tiled=True, BIGTIFF="IF_SAFER") as dst:
        dst.update_tags(year=args.year, pixel_size_m=STEP)
        for item in records:
            idx = item["band"]
            dst.set_band_description(idx, item["name"])
            dst.set_band_unit(idx, item["unit"])
            dst.update_tags(idx, **{key: str(value) for key, value in item.items()})
        for window, path in jobs:
            dst.write(np.load(path, allow_pickle=False)[:len(records)], window=window)
    meta_partial = metadata.with_suffix(".part")
    meta_partial.write_text(json.dumps({
        "year": args.year, "bbox_lon_lat": args.bbox, "crs": CRS, "transform": list(transform)[:6],
        "nodata": NODATA, "shape": [height, width], "boundary_asset": ASSETS["boundary"],
        "candidate_scenes_or_periods": counts, "source_sample_projections": projections,
        "ecostress_requested": args.ecostress,
        "ecostress_exported": len(records) > 0 and records[-1]["name"] == "eco_valid_scenes",
        "bands": records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    partial.replace(output)
    meta_partial.replace(metadata)
    print(f"GeoTIFF: {output}\nBandas: {metadata}\nCaché reutilizable: {cache}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (ee.EEException, OSError, ValueError) as error:
        sys.exit(f"Error: {error}")
