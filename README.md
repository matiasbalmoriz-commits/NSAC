# GeoVision: local geospatial analysis for Paraguay

GeoVision is a local web application created to explore and analyze geospatial information about Paraguay. The project receives a multi-band GeoTIFF, processes only the area selected by the user, and presents the results through an interactive browser interface. Its main value is that it connects a complex raster dataset with practical visual and analytical tools without requiring the user to work directly with GIS software or load the complete dataset into memory.

The application is organized around a Python backend, a browser frontend, and a collection of analysis modules. The backend reads the raster with Rasterio and performs numerical calculations with NumPy and SciPy. The frontend displays the map, lets the user select an area, requests statistics from the server, and presents the results through layers, legends, reports, and downloads. The project also includes optional integrations for crop analysis, restoration screening, soil information, and water indicators.

## Purpose and general operation

The project is designed as a local decision-support tool. It does not attempt to replace field work, a complete farm management system, or a professional GIS platform. Instead, it provides a clear way to inspect the information already stored in a GeoTIFF and to compare conditions within a chosen area.

The main workflow is simple:

1. The user starts the local server and opens the web interface.
2. GeoVision reads the GeoTIFF metadata and identifies the available bands.
3. The user explores the coverage map or selects two geographic points to define a rectangle.
4. The server transforms that rectangle to the raster's coordinate system and analyzes the pixels whose centers fall inside it.
5. The interface displays the statistics, maps, optional reports, and download buttons.

The project uses the national file `NSAC1/paraguay_2023_combinado.tif`, although the server can receive another compatible GeoTIFF through the `--geotiff` argument. The standard setup is:

```powershell
cd NSAC1
python -m pip install -r requirements.txt
python servidor.py --geotiff ".\paraguay_2023_combinado.tif" --abrir
```

The application opens at `http://127.0.0.1:8000/`. The server can use another port with `--puerto` and can limit the maximum analyzed window with `--max-pixeles`.

## Architecture

[`servidor.py`](NSAC1/servidor.py) is the entry point. It creates a local `ThreadingHTTPServer`, serves the static web files, validates requests, and connects each API route with the corresponding analysis function. It also controls concurrency, limits request sizes, handles errors, and keeps the optional Nemotron key in server memory.

[`analizador.py`](NSAC1/analizador.py) is the central raster-analysis layer. It validates that the input is a supported GeoTIFF, reads band descriptions and metadata, converts raw values using scale and offset, ignores NoData and invalid numbers, and calculates statistics in small windows. This windowed approach avoids loading the complete national raster into memory. Continuous bands produce values such as minimum, maximum, mean, and standard deviation. Categorical bands produce class counts and percentages.

[`mapa.py`](NSAC1/mapa.py) creates the coverage image, queries an individual cell, and exports a GeoTIFF clip. The map is reprojected to WGS84 so that it can be displayed in the browser. The analysis itself continues to use the source raster's native coordinate system.

The web client is in [`NSAC1/web/`](NSAC1/web). Its JavaScript files manage the map, area selection, API calls, legends, crop overlays, plugins, and downloads. The client does not read the GeoTIFF directly; all data passes through the local server.

## Main capabilities

GeoVision provides several related capabilities:

- **Map exploration:** view land-cover information, zoom, pan, and inspect individual cells.
- **Area analysis:** calculate statistics for all available bands inside a selected rectangle.
- **Crop screening:** compare the selected area's data with a reference catalogue and display a preliminary candidate layer. This is an analytical aid, not a final agronomic recommendation.
- **Restoration screening:** identify candidate areas near mapped water or ecological corridors using local raster rules.
- **Optional reports:** load soil and water indicators through isolated plugins.
- **Data export:** download JSON statistics and GeoTIFF clips for further work.

The crop layer implemented in [`mapa_cultivos.py`](NSAC1/mapa_cultivos.py) is one component of this broader system. It uses the raster analysis results and produces a colorized image with geographic bounds and a legend. The project treats this output as a preliminary comparison and includes limitations so that users do not confuse raster evidence with a complete field diagnosis.

## API and data flow

The server exposes routes such as `/api/info`, `/api/cobertura.png`, `/api/celda`, `/api/analizar`, `/api/cultivos`, `/api/restauracion`, and `/api/recorte`. There are also routes for Nemotron configuration and plugin management. JSON requests must declare `Content-Type: application/json`.

When a request arrives, the server validates its origin, parses the selected coordinates, checks the pixel limit, opens the raster, and runs the relevant module. Errors are returned as JSON with an HTTP status code. The server accepts local requests only and allows one core analysis at a time, which keeps memory and processing use predictable.

Optional crop explanations are generated through a compatible Chat Completions service. The API key can be entered in the interface or supplied through environment variables. The key is not written to the project files, and the plugin runner removes API-key variables from the environment before launching optional tools.

## Dependencies and limitations

The dependencies in [`NSAC1/requirements.txt`](NSAC1/requirements.txt) are NumPy, Rasterio, and SciPy. NumPy handles arrays and statistics, Rasterio handles GeoTIFF access and reprojection, and SciPy supports spatial operations used by optional analyses.

The project reports what is present in the raster; it does not invent missing measurements. Results are based on pixel centers, are not automatically weighted by geographic area, and may contain missing or partial coverage. Annual climate variables are context rather than a guarantee about a specific season. Any agricultural or restoration decision should be checked with current field observations and qualified local expertise.

Tests can be executed with:

```powershell
python -m unittest discover -s NSAC1/tests -v
```

