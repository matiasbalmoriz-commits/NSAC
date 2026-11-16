"""Referencias de aptitud entregadas para los cultivos y coberturas de Paraguay."""

ECOCROP = 'https://ecocrop.apps.fao.org/ecocrop/srv/en/dataSheet?id='
GUIA_ABONOS_VERDES = ('https://www.fao.org/fileadmin/user_upload/fsn/docs/Smallholders/'
                     'LIBRO_Expereincias_AC_Forestal_Paraguay.pdf')


def _ficha(temperatura_c, lluvia_mm, ph, suelo, especie, familia, ciclo, color, id_fao=None, *, fuentes=None,
           **condiciones):
    referencias = {'FAO EcoCrop': f'{ECOCROP}{id_fao}'} if id_fao is not None else {}
    referencias.update(fuentes or {})
    return dict(temperatura_c=temperatura_c, lluvia_mm=lluvia_mm, ph=ph, suelo=suelo,
                especie=especie, familia=familia, ciclo=ciclo, color=color, fuentes=referencias, **condiciones)


# Los intervalos son los de la tabla de trabajo. Se interpretan como referencias favorables de cribado.
CULTIVOS = {
    'Soja': _ficha([20, 33], [600, 1500], [5.5, 6.5], 'Textura media y buen drenaje.',
                   'Glycine max', 'Fabaceae', 'anual', '#762a83', 1150),
    'Maíz': _ficha([18, 33], [600, 1200], [5.0, 7.0], 'Textura media y buen drenaje.',
                   'Zea mays', 'Poaceae', 'anual', '#e08214', 238663),
    'Trigo': _ficha([15, 23], [750, 900], [6.0, 7.0], 'Textura media y buen drenaje.',
                    'Triticum aestivum', 'Poaceae', 'anual', '#a6761d', 2114,
                    estacion='Invierno', notas='Evalúa la temperatura durante el ciclo de invierno.'),
    'Arroz': _ficha([20, 30], [1500, 2000], [5.5, 7.0],
                    'En arroz inundado se requiere suelo que retenga agua y manejo hídrico.',
                    'Oryza sativa', 'Poaceae', 'anual', '#146c94', 1574, riego_inundado=True,
                    notas='El arroz inundado requiere verificar la disponibilidad y el control del agua. '
                          'Evalúa biotipos de secano con datos y referencias propios.'),
    'Mandioca': _ficha([20, 29], [1000, 1500], [5.5, 8.0], 'Textura media a ligera y buen drenaje.',
                       'Manihot esculenta', 'Euphorbiaceae', 'ciclo largo', '#a63603', 1420,
                       notas='Para incluirla en una rotación, considera el tiempo entre plantación y cosecha.'),
    'Caña de azúcar': _ficha([24, 37], [1500, 2000], [5.0, 8.0], 'Suelo profundo y fértil.',
                             'Saccharum officinarum', 'Poaceae', 'perenne', '#04a6a6', 1884, rotacion_estacional=False,
                             notas='Considera sus varios ciclos de corte al proponer secuencias multianuales.'),
    'Poroto tipo caupí': _ficha([20, 35], [600, 1500], [5.5, 7.5], 'Textura media y buen drenaje.',
                                'Vigna unguiculata', 'Fabaceae', 'anual', '#008837', 10835,
                                notas='Rangos específicos de caupí.'),
    'Maní': _ficha([22, 32], [600, 1500], [5.5, 6.5], 'Suelo bien drenado que permita el desarrollo de vainas.',
                   'Arachis hypogaea', 'Fabaceae', 'anual', '#8856a7', 2199),
    'Sésamo': _ficha([20, 30], [500, 1000], [5.5, 7.5], 'Textura media y buen drenaje.',
                     'Sesamum indicum', 'Pedaliaceae', 'anual', '#ef8a62', 1937),
    'Canola': _ficha([15, 25], [500, 1000], [6.5, 7.6], 'Textura media a ligera y buen drenaje.',
                     'Brassica napus', 'Brassicaceae', 'anual', '#fcce22', 549,
                     estacion='Estación fresca', notas='Evalúa el clima durante la campaña y la variedad.'),
    'Girasol': _ficha([17, 34], [600, 1000], [6.0, 7.5], 'Textura media a ligera y buen drenaje.',
                      'Helianthus annuus', 'Asteraceae', 'anual', '#d9ab00', 1191),
    'Sorgo': _ficha([22, 35], [400, 600], [5.5, 7.5], 'Textura media a pesada y buen drenaje.',
                    'Sorghum bicolor', 'Poaceae', 'anual', '#654100', 48747),
    'Algodón': _ficha([22, 36], [750, 1200], [6.0, 7.5], 'Suelo profundo, textura media a pesada y buen drenaje.',
                      'Gossypium hirsutum', 'Malvaceae', 'anual', '#3288bd', 1160),
    'Yerba mate': _ficha([20, 23], None, [4.5, 5.5], 'Suelo profundo, permeable y sin estancamiento.',
                         'Ilex paraguariensis', 'Aquifoliaceae', 'perenne', '#547713',
                         temperatura_anual=True, lluvia_objetivo_mm=1500, rotacion_estacional=False,
                         notas='Alrededor de 1.500 mm anuales, bien distribuidos. '
                               'Los 20 a 23 °C se refieren a la temperatura media anual.',
                         fuentes={'Guía de Paraguay, FCA/UNA y JICA': 'https://www.jica.go.jp/Resource/paraguay/'
                                  'espanol/office/others/c8h0vm0000ad5gke-att/gt_07.pdf'}),
    'Tabaco': _ficha([20, 27], [500, 1250], [5.5, 6.5], 'Buen drenaje. Evita lluvias fuertes durante la maduración.',
                     'Nicotiana tabacum', 'Solanaceae', 'anual', '#53535f',
                     notas='La temperatura se refiere al periodo del cultivo. Confirma la distribución de lluvias '
                           'durante el ciclo y el tipo de tabaco.',
                     fuentes={'TNAU': 'https://agritech.tnau.ac.in/agriculture/othercrops.html',
                              'ICAR': 'https://nirca.icar.gov.in/farmers.php?page=soils-climate',
                              'Guía del Departamento de Agricultura de Sudáfrica': 'https://old.dalrrd.gov.za/'
                              'Portals/0/Brochures%20and%20Production%20guidelines/'
                              'tobacco%20production%20guideline%20publication.pdf'}),
    'Banana': _ficha([23, 33], [1200, 3600], [5.5, 7.5], 'Suelo profundo, fértil y bien drenado.',
                     'Musa acuminata', 'Musaceae', 'perenne', '#66bd63', 7848, rotacion_estacional=False,
                     notas='Rangos de la ficha de Musa acuminata. Confirma el cultivar.'),
    'Piña / ananá': _ficha([21, 30], [800, 2500], [4.5, 5.5], 'Textura media a ligera y buen drenaje.',
                           'Ananas comosus', 'Bromeliaceae', 'ciclo largo', '#01665e', 402, rotacion_estacional=False,
                           notas='El pH de referencia de 4,5 a 5,5 sigue la guía de la Universidad de Hawái.',
                           fuentes={'Universidad de Hawái': 'https://www3.ctahr.hawaii.edu/tpss/'
                                    'research_extension/rxsoil/pineapple.htm'}),
    'Batata': _ficha([18, 28], [750, 2000], [5.0, 7.0], 'Confirma textura y drenaje con una guía local.',
                     'Ipomoea batatas', 'Convolvulaceae', 'anual', '#d53e4f', 1265),
    'Tomate': _ficha([20, 27], [600, 1300], [5.5, 6.8], 'Textura media y buen drenaje.',
                     'Solanum lycopersicum', 'Solanaceae', 'anual', '#b2182b', 1379),
    'Locote / pimiento': _ficha([17, 30], [600, 1250], [5.5, 6.8], 'Textura media y buen drenaje.',
                                'Capsicum annuum', 'Solanaceae', 'anual', '#081d58', 618),
}


def paleta_cultivos():
    """Devuelve los colores fijos del mapa en el orden del catálogo."""
    return [{'cultivo': cultivo, 'color': ficha['color']} for cultivo, ficha in CULTIVOS.items()]


# Estos códigos describen coberturas de partida, separadas de las especies del ranking.
COBERTURAS_DISPONIBLES = {
    18: dict(nombre='Agricultura', criterio='Cobertura agrícola cartografiada. Verifica el uso actual.'),
    15: dict(nombre='Pastura', criterio='Pastura sembrada. Las condiciones dependen de la especie sembrada.',
             ejemplo=dict(nombre='Brizantha', especie='Urochloa brizantha', temperatura_c=[25, 35],
                          lluvia_mm=[750, 2500], ph=[5.0, 6.0], suelo='Distintas texturas con buen drenaje.',
                          fuente=f'{ECOCROP}536')),
    12: dict(nombre='Pastizal', criterio='Pastizal natural. Valora las especies, la ecorregión, '
                                        'el suelo, el agua y el estado de conservación. NDVI y NDMI aportan contexto.'),
    11: dict(nombre='Pastizales inundables', criterio='Cobertura herbácea que puede estar sujeta a anegamiento. '
             'Comprueba profundidad de la napa, frecuencia, duración y profundidad de inundación. '
             'Usa la elevación, la humedad y el agua cartografiada como contexto. '
             'La lluvia anual por sí sola no permite evaluar su aptitud.'),
}


# Experiencias de abonos verdes en la Región Oriental (MAG, GIZ y KfW).
ABONOS_VERDES = {
    'Avena negra': dict(familia='Poaceae', estacion='fresca', uso='Protege el suelo con cobertura y rastrojo.'),
    'Nabo forrajero': dict(familia='Brassicaceae', estacion='fresca',
                          uso='Aporta cobertura y captura nutrientes con su sistema radicular.'),
    'Lupino': dict(familia='Fabaceae', estacion='fresca',
                   uso='Puede aportar nitrógeno mediante fijación biológica si se establece y nodula bien.'),
    'Mucuna': dict(familia='Fabaceae', estacion='cálida',
                   uso='Cubre el suelo y compite con malezas. Considera su hábito de crecimiento.'),
    'Crotalaria': dict(familia='Fabaceae', estacion='cálida',
                       uso='Aporta biomasa y puede fijar nitrógeno. Verifica la especie y el manejo.'),
    'Canavalia': dict(familia='Fabaceae', estacion='cálida',
                      uso='Aporta cobertura y biomasa en la entrecampaña.'),
    "Guandú (kumanda yvyra'i)": dict(familia='Fabaceae', estacion='cálida',
                                   uso='Genera biomasa. Ajusta el manejo para evitar competencia por luz.'),
}
