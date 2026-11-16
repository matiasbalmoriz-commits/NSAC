"""Ejecutar desde el editor de la consola Python de QGIS (no desde PowerShell)."""
from pathlib import Path

from qgis.PyQt.QtWidgets import QFileDialog
from qgis.core import QgsFillSymbol, QgsLineSymbol, QgsProject, QgsVectorLayer
from qgis.utils import iface


def agregar_cartografia():
    archivo, _ = QFileDialog.getOpenFileName(
        iface.mainWindow(), "Selecciona limite_paraguay.geojson de la carpeta extraída",
        "", "GeoJSON (*.geojson)")
    if not archivo:
        return
    carpeta = Path(archivo).parent
    especificaciones = (
        ("limite_paraguay.geojson", "Límite de Paraguay", QgsFillSymbol.createSimple({
            "style": "no", "outline_style": "solid", "outline_color": "35,35,35,255",
            "outline_width": "0.6", "outline_width_unit": "MM"})),
        ("rios_paraguay.geojson", "Ríos principales", QgsLineSymbol.createSimple({
            "line_color": "0,102,255,255", "line_width": "0.45", "line_width_unit": "MM"})),
    )
    capas = []
    for nombre, titulo, simbolo in especificaciones:
        capa = QgsVectorLayer(str(carpeta / nombre), titulo, "ogr")
        if not capa.isValid():
            raise RuntimeError(f"No se pudo cargar {nombre}. Extrae primero todo el ZIP.")
        capa.renderer().setSymbol(simbolo)
        capa.setAbstract("Natural Earth. Cartografía generalizada de referencia; "
                         "no es una delimitación oficial ni una red completa de arroyos.")
        capa.setCustomProperty("NSAC/cartografia", nombre)
        capas.append(capa)
    proyecto = QgsProject.instance()
    # Permite repetir la carga sin duplicar nuestras capas.
    nombres = {nombre for nombre, _, _ in especificaciones}
    anteriores = [c.id() for c in proyecto.mapLayers().values()
                  if c.customProperty("NSAC/cartografia", "") in nombres]
    proyecto.addMapLayers(capas)
    proyecto.removeMapLayers(anteriores)
    # Mantiene la vista actual para conservar el encuadre del área piloto.
    iface.mapCanvas().refresh()
    iface.messageBar().pushSuccess("NSAC", "Límite de Paraguay y ríos azules añadidos. Guarda tu proyecto.")


agregar_cartografia()
