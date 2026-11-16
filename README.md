# NSAC

Herramientas para exportar y analizar datos geográficos de Paraguay.

- [Analizador local de GeoTIFF](NSAC1/README.md): interfaz web y API para consultar estadísticas por rectángulo. Incluye `paraguay_2023_combinado.tif`, con 27 bandas en EPSG:6933 y píxeles de 480 m; no requiere Earth Engine para analizarlo.
- [Field Shift y cartografía](GUIA.md): exportadores de Earth Engine y creación de chunks sobre la cuadrícula de 120 m. El TIFF incluido de 480 m se utiliza con el analizador, no directamente con `crear_chunks.py`.

## Iniciar el analizador

Desde la raíz del repositorio:

```powershell
cd NSAC1
python servidor.py --geotiff ".\paraguay_2023_combinado.tif" --abrir
```

Consulta el [README de NSAC1](NSAC1/README.md) para cargar la API key, instalar las dependencias, conocer las funciones y ejecutar las pruebas.
