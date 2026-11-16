"""Vectoriza clases multibanda contiguas y une componentes entre teselas."""
import argparse
import json
import sqlite3
import sys
from contextlib import closing
from itertools import groupby
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pyogrio
import rasterio
import shapely
from rasterio.features import shapes
from rasterio.windows import Window
from shapely.geometry import MultiPolygon, shape
from skimage.measure import label

from cartografia_field_shift import agregar_cartografia

CATEGORY_DEFAULTS = ["land_cover", "soil_texture_10cm"]
BIN_DEFAULTS = {
    "elevation_m": (50, 0),
    "ndvi": (0.2, -1),
    "ndmi": (0.2, -1),
    "soil_ph_10cm": (0.5, 0),
    "era_t2m_c": (2, 0),
    "era_precip_mm": (200, 0),
    "era_soil_water": (0.10, 0),
    "pml_ec_mm_d": (1, 0),
    "pml_es_mm_d": (1, 0),
}
MISSING = np.iinfo("int32").min


def specifications(args, names):
    if args.category is None and args.bin is None:
        categories = CATEGORY_DEFAULTS
        bins = dict(BIN_DEFAULTS)
    else:
        categories = args.category or []
        bins = {}
        for spec in args.bin or []:
            name, width, *origin = spec.split(":")
            if len(origin) > 1 or name in bins:
                raise ValueError(f"Tramo duplicado o inválido: {spec}")
            width, origin = float(width), float(origin[0]) if origin else 0.0
            if not np.isfinite([width, origin]).all() or width <= 0:
                raise ValueError(f"Ancho u origen inválido: {spec}")
            bins[name] = (width, origin)
    selected = categories + list(bins)
    if not selected or len(selected) != len(set(selected)) or set(selected) - set(names):
        raise ValueError(f"Comprueba las bandas de clasificación {selected}. Disponibles: {names}")
    return categories, bins


def classify(data, names, categories, bins, required):
    valid = np.ones(data.shape[1:], dtype=bool)
    for name in required:
        valid &= np.isfinite(data[names.index(name)])
    if not valid.any():
        return np.zeros(valid.shape, dtype="int32"), np.empty((0, len(categories) + len(bins)), dtype="int32")
    keys = []
    for name in categories + list(bins):
        values = data[names.index(name)][valid]
        finite = np.isfinite(values)
        code = np.full(len(values), MISSING, dtype="int32")
        raw = values[finite].astype("float64")
        if name in bins:
            step, origin = bins[name]
            raw = np.floor(np.round((raw - origin) / step, decimals=6))
        elif np.any(raw != np.rint(raw)):
            raise ValueError(f"La banda categórica {name} contiene valores no enteros.")
        if np.any((raw <= MISSING) | (raw > np.iinfo("int32").max)):
            raise ValueError(f"Códigos fuera de rango en {name}.")
        code[finite] = raw.astype("int32")
        keys.append(code)
    signatures, index = np.unique(np.column_stack(keys), axis=0, return_inverse=True)
    classified = np.zeros(valid.shape, dtype="int32")
    classified[valid] = index.reshape(-1) + 1
    return classified, signatures


def connect(classes_a, ids_a, classes_b, ids_b, parent, signatures):
    for a, b in zip(ids_a[(classes_a > 0) & (classes_b > 0)],
                    ids_b[(classes_a > 0) & (classes_b > 0)]):
        a, b = int(a), int(b)
        if signatures[a] == signatures[b]:
            ra, rb = root(parent, a), root(parent, b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)


def root(parent, item):
    node = item
    while node in parent:
        node = parent[node]
    while item in parent and parent[item] != node:
        next_item = parent[item]
        parent[item] = node
        item = next_item
    return node


def polygonal(geom):
    if not geom.is_valid:
        geom = shapely.make_valid(geom)
    if geom.geom_type == "Polygon":
        return MultiPolygon([geom])
    if geom.geom_type == "MultiPolygon":
        return geom
    polygons = []
    for part in getattr(geom, "geoms", ()):
        if part.geom_type in ("Polygon", "MultiPolygon", "GeometryCollection"):
            polygons.extend(polygonal(part).geoms)
    if not polygons:
        raise ValueError("La geometría no contiene superficie poligonal.")
    return MultiPolygon(polygons)


def process_raster(src, db, tile, names, categories, bins, required):
    db.execute("CREATE TABLE pieces(id INTEGER PRIMARY KEY, chunk INTEGER, signature TEXT, "
               "pixels INTEGER, totals BLOB, counts BLOB, geom BLOB)")
    parent = {}
    previous_bottom = {}
    offset = 0
    for row in range(0, src.height, tile):
        current_bottom = {}
        previous_right = None
        for col in range(0, src.width, tile):
            window = Window(col, row, min(tile, src.width-col), min(tile, src.height-row))
            masked = src.read(window=window, masked=True, out_dtype="float64")
            data = masked.filled(np.nan)
            classes, keys = classify(data, names, categories, bins, required)
            local = label(classes, background=0, connectivity=1).astype("int32")
            number = int(local.max())
            codes = np.zeros(number + 1, dtype="int32")
            codes[local.ravel()] = classes.ravel()
            global_ids = np.where(local, local.astype("int64") + offset, 0)
            # Comparar firmas globales porque el índice del mismo vector cambia entre teselas.
            edges = {int(idx) for edge in (local[0], local[-1], local[:, 0], local[:, -1])
                     for idx in np.unique(edge) if idx}
            signature_map = {offset + idx: tuple(keys[codes[idx] - 1].tolist()) for idx in edges}
            bottom = (classes[-1].copy(), global_ids[-1].copy())
            right = (classes[:, -1].copy(), global_ids[:, -1].copy())
            if col in previous_bottom:
                old_classes, old_ids, old_keys = previous_bottom[col]
                connect(old_classes, old_ids, classes[0], global_ids[0], parent,
                        old_keys | signature_map)
            if previous_right is not None:
                old_classes, old_ids, old_keys = previous_right
                connect(old_classes, old_ids, classes[:, 0], global_ids[:, 0], parent,
                        old_keys | signature_map)
            current_bottom[col] = (*bottom, signature_map)
            previous_right = (*right, signature_map)

            if number:
                pixels = np.bincount(local.ravel(), minlength=number + 1)
                totals = np.empty((number + 1, len(names)), dtype="<f8")
                counts = np.empty((number + 1, len(names)), dtype="<i8")
                for i, values in enumerate(data):
                    good = np.isfinite(values) & (local != 0)
                    ids = local[good]
                    counts[:, i] = np.bincount(ids, minlength=number + 1)
                    totals[:, i] = np.bincount(ids, weights=values[good], minlength=number + 1)

                def pieces():
                    for geom, idx in shapes(local, mask=local != 0, connectivity=4,
                                            transform=src.window_transform(window)):
                        idx = int(idx)
                        item = offset + idx
                        sig = json.dumps(keys[codes[idx] - 1].tolist(), separators=(",", ":"))
                        yield (item, item, sig, int(pixels[idx]), totals[idx].tobytes(),
                               counts[idx].tobytes(), polygonal(shape(geom)).wkb)

                db.executemany("INSERT INTO pieces VALUES (?,?,?,?,?,?,?)", pieces())
                db.commit()
            offset += number
        previous_bottom = current_bottom
        print(f"Filas procesadas: {min(row + tile, src.height)}/{src.height}", flush=True)

    if not offset:
        raise ValueError("Ningún píxel cumple los requisitos de datos válidos.")
    db.executemany("UPDATE pieces SET chunk=? WHERE id=?",
                   ((root(parent, item), item) for item in parent))
    db.execute("CREATE INDEX pieces_chunk ON pieces(chunk)")
    db.commit()


def export_chunks(db, path, crs, names, categories, bins, min_pixels):
    selected = categories + list(bins)
    batch, geometries = [], []
    written = 0

    def flush():
        nonlocal written
        if not batch:
            return
        fields = list(batch[0])
        columns, masks = [], []
        for field in fields:
            values = [attrs[field] for attrs in batch]
            if field.startswith("class_"):
                masks.append(np.array([value is None for value in values], dtype=bool))
                columns.append(np.array([0 if value is None else value for value in values],
                                        dtype="int64"))
            else:
                masks.append(None)
                columns.append(np.array(values, dtype=object if field == "classes_json" else None))
        pyogrio.raw.write(path, np.asarray(geometries, dtype=object),
                          columns, fields, field_mask=masks, layer="chunks", driver="GPKG",
                          geometry_type="MultiPolygon", crs=crs, append=written > 0)
        written += len(batch)
        batch.clear()
        geometries.clear()

    continuous = [i for i, name in enumerate(names) if name not in categories
                  and name not in CATEGORY_DEFAULTS]
    query = ("SELECT p.chunk, p.signature, p.totals, p.counts, p.geom, s.pixels "
             "FROM pieces AS p JOIN (SELECT chunk, SUM(pixels) AS pixels FROM pieces "
             "GROUP BY chunk HAVING SUM(pixels) >= ?) AS s USING (chunk) ORDER BY p.chunk, p.id")
    for chunk, rows in groupby(db.execute(query, (min_pixels,)), key=lambda row: row[0]):
        total = np.zeros(len(names), dtype="float64")
        valid = np.zeros(len(names), dtype="int64")
        parts = []
        for _, signature, sums, counts, geom, pixels in rows:
            total += np.frombuffer(sums, dtype="<f8")
            valid += np.frombuffer(counts, dtype="<i8")
            parts.append(shapely.from_wkb(geom))
            if len(parts) == 128:
                parts[:] = [shapely.union_all(parts, grid_size=120)]
        geom = polygonal(parts[0] if len(parts) == 1 else shapely.union_all(parts, grid_size=120))
        area = int(pixels) * 120 * 120
        if not np.isclose(geom.area, area, rtol=0, atol=0.1):
            raise ValueError(f"El área del chunk {chunk} difiere de la de sus píxeles.")
        codes = dict(zip(selected, [None if v == MISSING else v for v in json.loads(signature)]))
        attrs = dict(chunk_id=int(chunk), pixels=int(pixels), area_ha=area / 10000,
                     classes_json=json.dumps(codes, separators=(",", ":")))
        for name in categories:
            attrs[f"class_{name}"] = codes[name]
        for i in continuous:
            attrs[f"mean_{names[i]}"] = float(total[i] / valid[i]) if valid[i] else np.nan
            attrs[f"n_{names[i]}"] = int(valid[i])
        batch.append(attrs)
        geometries.append(geom.wkb)
        if len(batch) == 500:
            flush()
    flush()
    if not written:
        raise ValueError("Ningún chunk supera el umbral --min-pixels.")
    return written


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="GeoTIFF de 120 m con nombres de bandas")
    parser.add_argument("--output", type=Path, default=Path("field_shift_chunks.gpkg"))
    parser.add_argument("--tile", type=int, default=256)
    parser.add_argument("--min-pixels", type=int, default=1)
    parser.add_argument("--category", action="append", help="Banda entera, repetible")
    parser.add_argument("--bin", action="append", help="banda:ancho[:origen], repetible")
    parser.add_argument("--require", action="append", help="Banda obligatoria, repetible")
    parser.add_argument("--sin-cartografia", action="store_true",
                        help="Omite el límite de Paraguay y los ríos de referencia")
    parser.add_argument("--hidrografia", type=Path,
                        help="GeoPackage detallado de exportar_hidrografia.py (incluye lagos)")
    args = parser.parse_args()
    if args.sin_cartografia and args.hidrografia:
        parser.error("--hidrografia no se puede combinar con --sin-cartografia.")
    output = args.output
    if output.suffix.lower() != ".gpkg" or output.exists() or output.with_suffix(".chunks.json").exists():
        parser.error("Usa un nombre .gpkg nuevo y comprueba que no exista su .chunks.json.")
    if not 1 <= args.tile <= 1024 or args.min_pixels < 1:
        parser.error("--tile debe estar en 1–1024 y --min-pixels debe ser positivo.")

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="field_shift_", dir=output.parent) as scratch, rasterio.open(args.input) as src:
        tmp = Path(scratch)
        transform = src.transform
        if (src.crs is None or src.crs.to_epsg() != 6933
                or (transform.a, transform.b, transform.d, transform.e) != (120, 0, 0, -120)
                or transform.c % 120 or transform.f % 120):
            raise ValueError("Se requiere la cuadrícula EPSG:6933 de 120 m del exportador.")
        names = list(src.descriptions)
        if any(not name or not name.isascii() or not name.replace("_", "").isalnum()
               for name in names) or len(set(name.lower() for name in names)) != len(names):
            raise ValueError("Cada banda necesita un nombre ASCII único (letras, números y _).")
        categories, bins = specifications(args, names)
        required = args.require or (["land_cover"] if "land_cover" in names else categories + list(bins))
        if set(required) - set(names):
            raise ValueError(f"Bandas obligatorias no encontradas: {set(required) - set(names)}")
        with closing(sqlite3.connect(tmp / "pieces.sqlite")) as db, db:
            db.execute("PRAGMA temp_store=FILE")
            process_raster(src, db, args.tile, names, categories, bins, required)
            count = export_chunks(db, tmp / output.name, src.crs.to_wkt(), names,
                                  categories, bins, args.min_pixels)
        cartografia = None if args.sin_cartografia else agregar_cartografia(
            tmp / output.name, src.crs.to_wkt(), args.hidrografia)
        sidecar = output.with_suffix(".chunks.json")
        (tmp / sidecar.name).write_text(json.dumps({
            "input": str(args.input.resolve()), "crs": "EPSG:6933", "connectivity": 4,
            "chunks": count, "min_pixels": args.min_pixels, "required_valid": required,
            "categories": categories, "bins": {name: dict(width=w, origin=o) for name, (w, o) in bins.items()},
            "band_units": dict(zip(names, src.units)),
            "cartografia": cartografia,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        (tmp / output.name).replace(output)
        (tmp / sidecar.name).replace(sidecar)
    print(f"{count} chunks: {output}")
    if cartografia:
        print("Capas adicionales: " + ", ".join(cartografia['layers']) + " (estilos para QGIS)")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, sqlite3.Error) as error:
        sys.exit(f"Error: {error}")
