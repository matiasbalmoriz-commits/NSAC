"""Diagnostica píxeles o la primera tesela sin modificar la caché del exportador."""
import argparse
import math

import ee
from rasterio.transform import Affine
from rasterio.warp import transform
from rasterio.windows import Window, bounds

import exportar_field_shift as exportador


def comprobar(nombre, operacion):
    print(f"PRUEBA: {nombre}", flush=True)
    try:
        operacion()
    except (ee.EEException, ValueError) as error:
        print(f"FALLO: {nombre}: {error}", flush=True)
        return False
    print(f"OK: {nombre}", flush=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--year", type=int, default=2023)
    parser.add_argument("--first-tile", action="store_true",
                        help="Reproduce la primera tesela del exportador, con filtros y recorte")
    parser.add_argument("--tile", type=int, default=128)
    parser.add_argument("--bbox", type=float, nargs=4,
                        default=[-56.70, -25.62, -56.45, -25.40])
    args = parser.parse_args()
    if not 32 <= args.tile <= 512:
        parser.error("--tile debe estar en 32–512")
    ee.Initialize(project=args.project)
    ee.data.setDeadline(120000)
    west, south, east, north = args.bbox
    xs, ys = transform("EPSG:4326", exportador.CRS,
                       [(west + east) / 2], [(south + north) / 2])
    step = exportador.STEP
    grid = Affine(step, 0, math.floor(xs[0] / step) * step,
                  0, -step, math.ceil(ys[0] / step) * step)
    width = height = 1
    area = ee.Geometry.Rectangle(args.bbox, geodesic=False)
    tile_area = None
    if args.first_tile:
        print("MODO: primera tesela, con límite de Paraguay y filtro espacial", flush=True)
        area = ee.FeatureCollection(exportador.ASSETS["boundary"]).filter(
            ee.Filter.eq("ADM0_NAME", "Paraguay")).geometry(30).intersection(area, 30)
        ring = area.bounds(30, ee.Projection(exportador.EE_CRS)).coordinates().getInfo()[0]
        left = math.floor(min(x for x, _ in ring) / step) * step
        right = math.ceil(max(x for x, _ in ring) / step) * step
        bottom = math.floor(min(y for _, y in ring) / step) * step
        top = math.ceil(max(y for _, y in ring) / step) * step
        grid = Affine(step, 0, left, 0, -step, top)
        width = min(args.tile, (right - left) // step)
        height = min(args.tile, (top - bottom) // step)
        tile_area = ee.Geometry.Rectangle(
            list(bounds(Window(0, 0, width, height), grid)),
            ee.Projection(exportador.EE_CRS), False).buffer(360, 30)
        if not comprobar("geometría de la tesela con margen", lambda: tile_area.getInfo()):
            return 1

    def pixel(image, names):
        return exportador.compute_tile(image, names, grid, width, height)

    comprobar("definición WKT", lambda: ee.Projection(exportador.EE_CRS).getInfo())
    constant = ee.Image.constant(1).rename("prueba")
    if not comprobar("computePixels constante (solo cuadrícula de salida)",
                     lambda: pixel(constant, ["prueba"])):
        print("DETENIDO: falla la cuadrícula incluso sin capas de datos.")
        return 1
    if not comprobar("computePixels constante reproyectada",
                     lambda: pixel(exportador.coarse(constant), ["prueba"])):
        print("DETENIDO: falla la reproyección explícita incluso sin fuentes.")
        return 1

    if args.first_tile and not comprobar(
            "recorte al límite de Paraguay", lambda: pixel(constant.clip(area), ["prueba"])):
        return 1
    static, other, landsat, eco, counts, _ = exportador.prepare(args.year, area, True)
    if tile_area is not None:
        landsat = landsat.filterBounds(tile_area)
        eco = eco.filterBounds(tile_area)
    optical = exportador.temporal_optical(
        landsat, exportador.landsat_scene, exportador.OPTICAL,
        "ls_red", "ls_valid_scenes")
    groups = [("relieve/cobertura", static, ["elevation_m", "land_cover"]),
              ("suelo/clima/PML", other,
               [r["name"] for r in exportador.band_records(args.year, False)][8:]),
              ("Landsat", optical, exportador.OPTICAL + ["ls_valid_scenes"])]
    if counts["eco"]:
        thermal = exportador.temporal_optical(
            eco, exportador.eco_scene, ["eco_lst_c"], "eco_lst_c", "eco_valid_scenes")
        groups.append(("ECOSTRESS", thermal, ["eco_lst_c", "eco_valid_scenes"]))
    failures = 0
    for label, image, names in groups:
        if args.first_tile:
            image = image.clip(area)
        if not comprobar(label, lambda: pixel(image, names)):
            failures += 1
            for name in names:
                comprobar(name, lambda: pixel(image, [name]))
    if not failures:
        stack = groups[0][1]
        names = list(groups[0][2])
        for _, image, band_names in groups[1:]:
            stack = stack.addBands(image)
            names.extend(band_names)
        if not comprobar("todas las capas combinadas y recortadas",
                         lambda: pixel(stack.clip(area), names)):
            failures += 1
    print(f"FIN: {failures} grupos fallidos. No se descargó el piloto ni se modificó su caché.")
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())
