'use strict';

const $ = id => document.getElementById(id);
const campos = ['lon1', 'lat1', 'lon2', 'lat2'];
const formato = new Intl.NumberFormat('es-PY', {maximumFractionDigits: 2});
const numero = valor => valor == null ? '—' : formato.format(valor);
const clasesMapa = new Map();
const coloresCultivos = new Map();
const coberturasAgricolas = new Set([18, 15, 12, 11]);
const nombresSistema = {monocultivo: 'Monocultivo', rotacion: 'Rotación'};
const evaluaciones = new Map();
let info, resultado, ocupado = false, consultaCelda = 0, consultaArea = 0;
let configuracionNemotron, actualizandoClave = false, probandoConexion = false;

function texto(parent, tag, contenido, clase) {
  const node = document.createElement(tag);
  node.textContent = contenido;
  if (clase) node.className = clase;
  parent.append(node);
  return node;
}

function estado(id, mensaje, error = false) {
  $(id).textContent = mensaje;
  $(id).classList.toggle('error', error);
}

function leerSeleccion() {
  const puntos = campos.map(id => $(id).valueAsNumber);
  if (!puntos.every(Number.isFinite)) return null;
  const [lon1, lat1, lon2, lat2] = puntos;
  return [[lon1, lat1], [lon2, lat2]];
}

function peticion([[lon1, lat1], [lon2, lat2]]) {
  return {pos1: {lon: lon1, lat: lat1}, pos2: {lon: lon2, lat: lat2}};
}

function avisarAreaAnalizada(seleccion = null) {
  document.dispatchEvent(new CustomEvent('geovision:area', {
    detail: seleccion ? peticion(seleccion) : null,
  }));
}

function sistemaCultivo() {
  return $('sistema-cultivo').querySelector('input:checked').value;
}

function actualizarSeleccion() {
  mapa.seleccion = leerSeleccion();
  consultaArea += 1;
  resultado = null;
  avisarAreaAnalizada();
  limpiarEvaluaciones();
  $('resultados').hidden = true;
  $('limpiar').disabled = !campos.some(id => $(id).value);
  $('analizar').disabled = ocupado || !info || !mapa.seleccion;
  $('area-instruccion').textContent = mapa.seleccion
    ? 'Rectángulo listo. Puedes dibujarlo de nuevo o ajustar sus coordenadas.'
    : 'Dibuja un rectángulo en el mapa o introduce las coordenadas.';
  if (!ocupado) estado('estado', '');
}

function modo(nombre) {
  mapa.cambiarModo(nombre);
  $('explorar').setAttribute('aria-pressed', nombre === 'explorar');
  $('dibujar').setAttribute('aria-pressed', nombre === 'dibujar');
  $('ayuda-mapa').textContent = nombre === 'dibujar'
    ? 'Arrastra entre dos esquinas para definir el área. También puedes introducir coordenadas.'
    : 'Arrastra para desplazarte y haz clic para consultar una celda. Usa +, − y las flechas con el teclado.';
}

const mapa = new MapaCobertura($('vista'), {
  seleccionar(puntos) {
    puntos.flat().forEach((valor, indice) => { $(campos[indice]).value = valor.toFixed(7); });
    actualizarSeleccion();
    modo('explorar');
  },
  consultar: consultarPunto,
  posicion(punto) {
    $('coordenada').textContent = punto ? punto.map(v => v.toFixed(4)).join(', ') : '';
  },
});

async function solicitar(url, opciones) {
  const respuesta = await fetch(url, opciones);
  if (!respuesta.ok) {
    const error = await respuesta.json().catch(() => ({}));
    const fallo = new Error(error.error || 'No se pudo completar la solicitud.');
    fallo.estado = respuesta.status;
    throw fallo;
  }
  return respuesta;
}

function necesitaClaveNemotron() {
  return configuracionNemotron?.editable && !configuracionNemotron.configurada;
}

function actualizarControlesNemotron() {
  const editable = configuracionNemotron?.editable !== false;
  const desdeInterfaz = configuracionNemotron?.origen === 'interfaz';
  const campo = $('nemotron-clave');
  $('nemotron-formulario').hidden = !editable;
  campo.disabled = !editable || actualizandoClave || probandoConexion;
  $('nemotron-guardar').disabled = campo.disabled || !campo.value.trim();
  $('nemotron-guardar').textContent = desdeInterfaz ? 'Reemplazar clave' : 'Guardar clave';
  $('nemotron-borrar').hidden = !editable || !desdeInterfaz;
  $('nemotron-borrar').disabled = actualizandoClave || probandoConexion;
  $('nemotron-probar').disabled = actualizandoClave || probandoConexion || evaluaciones.has('cultivos');
  const ranking = $('ejecutar-cultivos');
  ranking.disabled = actualizandoClave || probandoConexion || evaluaciones.has('cultivos');
  ranking.textContent = necesitaClaveNemotron() ? 'Configurar clave para analizar' : 'Analizar cultivos';
}

async function consultarConfiguracionNemotron(opciones) {
  if (actualizandoClave) return;
  actualizandoClave = true;
  actualizarControlesNemotron();
  if (opciones) {
    estado('nemotron-estado', 'Actualizando la clave…');
    estado('nemotron-conexion', '');
  }
  try {
    const datos = await (await solicitar('/api/nemotron/config', opciones)).json();
    configuracionNemotron = datos;
    let mensaje = 'Añade tu clave de NVIDIA para analizar los cultivos.';
    if (datos.origen === 'interfaz') mensaje = 'Clave configurada para esta sesión del servidor.';
    if (datos.origen === 'entorno') mensaje = 'Clave configurada en el entorno del servidor.';
    if (datos.origen === 'local') mensaje = 'Proveedor local configurado.';
    if (!datos.editable) {
      mensaje = datos.configurada
        ? 'Nemotron está configurado en el entorno del servidor.'
        : 'Revisa la configuración de Nemotron en el entorno del servidor.';
    }
    estado('nemotron-estado', mensaje);
  } catch (error) {
    const mensaje = opciones
      ? 'No se pudo actualizar la clave. Comprueba que esté completa e inténtalo de nuevo.'
      : 'No se pudo consultar la configuración de Nemotron.';
    estado('nemotron-estado', mensaje, true);
  } finally {
    actualizandoClave = false;
    actualizarControlesNemotron();
  }
}

$('nemotron-probar').addEventListener('click', async () => {
  if (probandoConexion || actualizandoClave) return;
  if ($('nemotron-clave').value.trim()) {
    estado('nemotron-conexion', 'Guarda la clave que acabas de escribir y vuelve a probar.', true);
    return;
  }
  probandoConexion = true;
  actualizarControlesNemotron();
  estado('nemotron-conexion', 'Comprobando conexión con la API…');
  try {
    const datos = await (await solicitar('/api/nemotron/probar', {
      ...solicitudJson({}), signal: AbortSignal.timeout(35000),
    })).json();
    const tiempo = numero(datos.latencia_ms / 1000);
    const http = datos.http ? ` · HTTP ${datos.http}` : '';
    estado('nemotron-conexion', `${datos.mensaje} Modelo: ${datos.modelo}. ${tiempo} s${http}`, !datos.funcional);
  } catch (error) {
    estado('nemotron-conexion', error.name === 'TimeoutError'
      ? 'El servidor local no completó la prueba en 35 segundos. Vuelve a intentarlo.'
      : `No se pudo completar la prueba. ${error.message}`, true);
  } finally {
    probandoConexion = false;
    actualizarControlesNemotron();
  }
});

function etiqueta(codigo) {
  return clasesMapa.get(codigo)?.nombre || `Código ${numero(codigo)}`;
}

function muestra(parent, codigo) {
  muestraColor(parent, clasesMapa.get(codigo)?.color);
}

function muestraColor(parent, color) {
  if (!color) return;
  const item = texto(parent, 'span', '', 'muestra');
  item.style.backgroundColor = color;
  item.setAttribute('aria-hidden', 'true');
}

async function consultarPunto([lon, lat]) {
  const solicitud = ++consultaCelda;
  mapa.celda = null;
  mapa.dibujar();
  $('celda').hidden = true;
  estado('celda-estado', 'Consultando la celda…');
  try {
    const url = '/api/celda?' + new URLSearchParams({lon, lat});
    const celda = await (await solicitar(url)).json();
    if (solicitud !== consultaCelda) return;
    mapa.celda = celda;
    mapa.dibujar();
    const cover = celda.bandas.find(banda => banda.nombre === 'land_cover');
    $('celda-clase').textContent = cover?.valor == null ? 'Cobertura sin datos' : etiqueta(cover.valor);
    const valores = $('celda-valores');
    valores.replaceChildren();
    for (const banda of celda.bandas) {
      texto(valores, 'dt', banda.titulo);
      const valor = banda.valor == null ? 'Sin datos'
        : banda.nombre === 'land_cover' ? etiqueta(banda.valor)
        : [numero(banda.valor), banda.unidad === '1' ? '' : banda.unidad].filter(Boolean).join(' ');
      texto(valores, 'dd', valor);
    }
    $('celda').hidden = false;
    estado('celda-estado', `Lon ${lon.toFixed(5)}°, lat ${lat.toFixed(5)}°`);
  } catch (error) {
    if (solicitud === consultaCelda) estado('celda-estado', error.message, true);
  }
}

function mostrar(data) {
  $('resultados').hidden = false;
  $('analisis-avanzados').hidden = false;
  const superficie = data.hectareas_por_celda
    ? ` · ${numero(data.pixeles_seleccionados * data.hectareas_por_celda)} ha representadas` : '';
  $('resumen').textContent = `${numero(data.pixeles_seleccionados)} celdas · ${data.total_bandas} bandas${superficie}`;
  $('exportacion-estado').textContent = '';
  $('notas').replaceChildren();
  data.avisos.filter(aviso => !clasesMapa.size || !aviso.includes('leyenda')).forEach(aviso =>
    texto($('notas'), 'p', aviso, 'caption'));
  $('bandas').replaceChildren();
  $('clases').replaceChildren();
  const cover = data.bandas.find(banda => banda.nombre === 'land_cover');
  $('cobertura-resumen').hidden = !cover;
  $('distribucion').replaceChildren();
  if (cover) {
    $('cobertura-valida').textContent = `${numero(cover.cobertura_pct)} % de las celdas seleccionadas tienen cobertura clasificada.`;
    for (const clase of [...cover.clases].sort((a, b) => b.pixeles - a.pixeles)) {
      const item = document.createElement('li');
      const nombre = texto(item, 'span', '', 'clase');
      muestra(nombre, clase.valor);
      texto(nombre, 'span', etiqueta(clase.valor));
      const barra = document.createElement('progress');
      barra.max = 100;
      barra.value = clase.porcentaje;
      barra.setAttribute('aria-label', `Porcentaje de ${etiqueta(clase.valor)}`);
      item.append(barra);
      const area = data.hectareas_por_celda ? ` · ${numero(clase.pixeles * data.hectareas_por_celda)} ha` : '';
      texto(item, 'span', `${numero(clase.porcentaje)} %${area}`);
      $('distribucion').append(item);
    }
  }
  for (const b of data.bandas) {
    const fila = document.createElement('tr');
    const nombre = texto(fila, 'td', `${b.indice}. ${b.titulo}`);
    texto(nombre, 'small', b.fuente);
    [b.unidad || '—', numero(b.validos), numero(b.sin_datos), numero(b.cobertura_pct) + ' %',
     numero(b.minimo), numero(b.media), numero(b.maximo), numero(b.desviacion)].forEach(v => texto(fila, 'td', v));
    $('bandas').append(fila);
    if (b.tipo !== 'category') continue;
    const card = texto($('clases'), 'div', '', 'class-card');
    texto(card, 'h4', b.titulo);
    if (!b.clases.length) texto(card, 'p', b.aviso || 'Sin celdas válidas.', 'caption');
    for (const c of b.clases) {
      const filaClase = texto(card, 'div', '', 'class-row');
      texto(filaClase, 'span', b.nombre === 'land_cover' ? etiqueta(c.valor) : `Código ${numero(c.valor)}`);
      texto(filaClase, 'span', `${numero(c.pixeles)} celdas · ${numero(c.porcentaje)} %`);
    }
  }
}

function limpiarEvaluaciones() {
  limpiarCultivos();
  evaluaciones.get('restauracion')?.abort();
  evaluaciones.delete('restauracion');
  $('analisis-avanzados').hidden = true;
  $('restauracion-leyenda').hidden = true;
  $('ejecutar-restauracion').disabled = false;
  estado('restauracion-estado', '');
  mapa.restauracion = null;
  mapa.dibujar();
}

function limpiarCultivos() {
  evaluaciones.get('cultivos')?.abort();
  evaluaciones.delete('cultivos');
  for (const id of ['cultivos', 'ver-cultivos', 'ver-mapa-cultivos', 'cultivos-leyenda']) $(id).hidden = true;
  if (resultado) delete resultado.datos.cultivos;
  mapa.cultivos = null;
  estado('cultivos-estado', '');
  actualizarControlesNemotron();
}

function completarLista(id, elementos) {
  const lista = $(id);
  lista.replaceChildren();
  for (const elemento of elementos) texto(lista, 'li', elemento);
}

function mostrarPaletaCultivos(paleta) {
  const lista = $('paleta-cultivos');
  lista.replaceChildren();
  coloresCultivos.clear();
  for (const {cultivo, color} of paleta) {
    coloresCultivos.set(cultivo, color);
    const item = texto(lista, 'li', '');
    muestraColor(item, color);
    texto(item, 'span', cultivo);
  }
  $('catalogo-colores').hidden = !paleta.length;
}

function mostrarReferencia(cultivo, ficha) {
  const rango = valores => valores.map(numero).join('–');
  const referencia = texto(cultivo, 'details', '', 'referencia-cultivo');
  texto(referencia, 'summary', 'Rangos de referencia');
  const lluvia = ficha.lluvia_mm ? rango(ficha.lluvia_mm) : `alrededor de ${numero(ficha.lluvia_objetivo_mm)}`;
  texto(referencia, 'p', `Temperatura ${rango(ficha.temperatura_c)} °C · Lluvia anual ${lluvia} mm · pH ${rango(ficha.ph)}`);
  texto(referencia, 'p', ficha.suelo);
  if (ficha.notas) texto(referencia, 'p', ficha.notas);
  for (const [nombre, url] of Object.entries(ficha.fuentes || {})) {
    if (!url.startsWith('https://')) continue;
    const enlace = texto(referencia, 'a', nombre);
    enlace.href = url;
    enlace.target = '_blank';
    enlace.rel = 'noopener';
  }
}

function ordenarMonocultivos(datos) {
  const grupos = new Map((datos.mapa_cultivos?.leyenda || []).map(clase => [clase.cultivo, clase]));
  const aptos = [...datos.aptos].sort((a, b) => {
    const primero = grupos.get(a.cultivo);
    const segundo = grupos.get(b.cultivo);
    return (segundo?.grupos || 0) - (primero?.grupos || 0)
      || (primero?.grupos_condicionados || 0) - (segundo?.grupos_condicionados || 0);
  });
  // Nemotron devuelve los cinco menos aptos en orden de menor a mayor limitación.
  return {...datos, aptos, no_aptos: [...datos.no_aptos].reverse()};
}

function mostrarMonocultivo(datos) {
  const grupos = new Map((datos.mapa_cultivos?.leyenda || []).map(clase => [clase.cultivo, clase]));
  for (const [id, cultivos] of [['cultivos-aptos', datos.aptos], ['cultivos-no-aptos', datos.no_aptos]]) {
    const lista = $(id);
    lista.replaceChildren();
    for (const cultivo of cultivos) {
      const ficha = texto(lista, 'li', '', 'cultivo-ficha');
      const titulo = texto(ficha, 'h5', '', 'cultivo-nombre');
      muestraColor(titulo, coloresCultivos.get(cultivo.cultivo) || datos.fichas?.[cultivo.cultivo]?.color);
      texto(titulo, 'span', cultivo.cultivo);
      if (id === 'cultivos-aptos' && Number.isInteger(datos.mapa_cultivos?.total_grupos)) {
        const clase = grupos.get(cultivo.cultivo);
        const cantidad = clase?.grupos || 0;
        const condicionados = clase?.grupos_condicionados || 0;
        const detalle = condicionados ? ` · ${numero(condicionados)} condicionados` : '';
        texto(ficha, 'p', `${numero(cantidad)} grupos asignados en el mapa${detalle}`, 'caption');
      }
      if (cultivo.abono_verde) {
        const abono = cultivo.abono_verde;
        const recomendacion = texto(ficha, 'div', '', 'abono-verde');
        texto(recomendacion, 'p', 'Abono verde recomendado', 'cultivo-etiqueta');
        texto(recomendacion, 'strong', abono.especie);
        texto(recomendacion, 'p', abono.epoca);
        texto(recomendacion, 'p', abono.motivo);
      }
      texto(ficha, 'p', 'Motivos', 'cultivo-etiqueta');
      const motivos = texto(ficha, 'ul', '');
      cultivo.motivos.forEach(motivo => texto(motivos, 'li', motivo));
      texto(ficha, 'p', 'Medidas posibles', 'cultivo-etiqueta');
      const medidas = texto(ficha, 'ul', '');
      cultivo.medidas.forEach(medida => texto(medidas, 'li', medida));
      const referencia = datos.fichas?.[cultivo.cultivo];
      if (referencia) mostrarReferencia(ficha, referencia);
    }
  }
}

function mostrarRotacion(datos) {
  const rotacion = $('cultivos-rotacion');
  rotacion.replaceChildren();
  for (const paso of datos.rotacion || []) {
    const item = texto(rotacion, 'li', '');
    muestraColor(item, coloresCultivos.get(paso.cultivo) || datos.fichas?.[paso.cultivo]?.color);
    texto(item, 'strong', paso.cultivo);
    texto(item, 'span', paso.epoca, 'rotacion-epoca');
    texto(item, 'p', paso.motivo);
  }
}

function volverOpaca(imagen) {
  // Compatibilidad con servidores en ejecución que aún devuelven colores translúcidos.
  const canvas = document.createElement('canvas');
  canvas.width = imagen.naturalWidth;
  canvas.height = imagen.naturalHeight;
  const ctx = canvas.getContext('2d', {willReadFrequently: true});
  ctx.drawImage(imagen, 0, 0);
  const pixeles = ctx.getImageData(0, 0, canvas.width, canvas.height);
  for (let i = 3; i < pixeles.data.length; i += 4) {
    if (pixeles.data[i] !== 0) pixeles.data[i] = 255;
  }
  ctx.putImageData(pixeles, 0, 0);
  return canvas;
}

async function mostrarCultivos(datos, signal) {
  const capa = datos.mapa_cultivos;
  let imagen = null;
  if (capa?.imagen && capa.total_celdas > 0) {
    imagen = new Image();
    imagen.src = `data:image/png;base64,${capa.imagen}`;
    await imagen.decode();
    if (signal.aborted) return;
    if (!capa.opaca) imagen = volverOpaca(imagen);
  }
  if (signal.aborted) return;
  const sistema = datos.modo || sistemaCultivo();
  const esRotacion = sistema === 'rotacion';
  $('cultivos-titulo').textContent = `Análisis de cultivos · ${nombresSistema[sistema]}`;
  $('cultivos-alcance').textContent = datos.alcance;
  $('ranking-monocultivo').hidden = esRotacion;
  $('manejo-rotacion').hidden = !esRotacion;
  if (esRotacion) mostrarRotacion(datos);
  else mostrarMonocultivo(datos);
  completarLista('cultivos-faltantes', datos.datos_faltantes);
  $('cultivos').hidden = false;
  $('ver-cultivos').hidden = false;
  $('ver-mapa-cultivos').hidden = !imagen;
  if (capa) mostrarMapaCultivos(capa, imagen, sistema);
}

function mostrarMapaCultivos(capa, imagen, sistema) {
  const agrupado = sistema === 'monocultivo' && Number.isInteger(capa.total_grupos);
  $('cultivos-leyenda-titulo').textContent = sistema === 'rotacion'
    ? 'Cultivo inicial de la rotación por zona' : 'Monocultivo recomendado por grupo';
  mapa.cultivos = imagen ? {imagen, limites: capa.limites, visible: true} : null;
  $('mostrar-cultivos').checked = !!imagen;
  $('mostrar-cultivos').disabled = !imagen;
  $('acercar-cultivos').disabled = !imagen;
  if (imagen && agrupado) {
    $('cultivos-mapa-resumen').textContent = `${numero(capa.total_grupos)} grupos de hasta cuatro celdas · ${numero(capa.total_celdas)} celdas coloreadas.`;
  } else {
    $('cultivos-mapa-resumen').textContent = imagen
      ? `${numero(capa.total_celdas)} celdas con un cultivo sugerido.`
      : 'No se identificaron celdas para mostrar cultivos en esta selección.';
  }
  const lista = $('cultivos-colores');
  lista.replaceChildren();
  const clases = [...capa.leyenda];
  if (agrupado) clases.sort((a, b) => b.grupos - a.grupos);
  const predominante = $('cultivos-mapa-predominante');
  predominante.hidden = !imagen || !agrupado || !clases.length;
  predominante.replaceChildren();
  if (!predominante.hidden) {
    const lideres = clases.filter(clase => clase.grupos === clases[0].grupos);
    texto(predominante, 'strong', lideres.length === 1 ? 'Cultivo con más grupos en el mapa' : 'Cultivos empatados con más grupos');
    texto(predominante, 'span', ' · ' + lideres.map(clase => {
      const condicionados = clase.grupos_condicionados || 0;
      return `${clase.cultivo}, ${numero(clase.grupos)} de ${numero(capa.total_grupos)} (${numero(condicionados)} condicionados)`;
    }).join(' · '));
  }
  for (const clase of clases) {
    const item = texto(lista, 'li', '');
    muestraColor(item, clase.color);
    const cantidad = agrupado ? `${numero(clase.grupos)} grupos` : `${numero(clase.celdas)} celdas`;
    const condicionados = clase.grupos_condicionados
      ? ` (${numero(clase.grupos_condicionados)} condicionados)` : '';
    texto(item, 'span', `${clase.cultivo} · ${cantidad}${condicionados}`);
  }
  const notas = capa.notas || [];
  const textoCondicionados = 'La leyenda cuenta como condicionados los grupos donde el candidato más cercano queda fuera de algún rango.';
  completarLista('cultivos-mapa-notas', agrupado && !capa.opaca ? [textoCondicionados, ...notas.slice(1)] : notas);
  $('cultivos-leyenda').hidden = false;
  if (imagen && agrupado) mapa.encuadrar(capa.limites);
  else mapa.dibujar();
}

async function mostrarRestauracion(datos, signal) {
  const imagen = new Image();
  imagen.src = `data:image/png;base64,${datos.imagen}`;
  await imagen.decode();
  if (signal.aborted) return;
  const visible = datos.total_celdas > 0;
  mapa.restauracion = {imagen, limites: datos.limites, visible};
  $('mostrar-restauracion').checked = visible;
  $('mostrar-restauracion').disabled = !visible;
  $('restauracion-leyenda').hidden = false;
  $('restauracion-resumen').textContent = visible
    ? `${numero(datos.total_celdas)} celdas candidatas${datos.total_hectareas == null ? '' : ` · ${numero(datos.total_hectareas)} ha representadas`}. Junto al agua: ${numero(datos.ribera_celdas)}. En corredores: ${numero(datos.corredor_celdas)}.`
    : 'No se identificaron celdas candidatas en esta selección.';
  completarLista('restauracion-notas', datos.notas);
  mapa.dibujar();
}

async function evaluar(nombre, enCurso, mostrarEvaluacion) {
  if (!resultado || evaluaciones.has(nombre)) return;
  const boton = $(`ejecutar-${nombre}`);
  const controlador = new AbortController();
  const {signal} = controlador;
  evaluaciones.set(nombre, controlador);
  boton.disabled = true;
  if (nombre === 'cultivos') actualizarControlesNemotron();
  estado(`${nombre}-estado`, enCurso);
  try {
    const entrada = peticion(resultado.seleccion);
    if (nombre === 'cultivos') entrada.modo = sistemaCultivo();
    const opciones = {...solicitudJson(entrada), signal};
    const respuesta = await (await solicitar(`/api/${nombre}`, opciones)).json();
    const datos = nombre === 'cultivos' && entrada.modo === 'monocultivo'
      ? ordenarMonocultivos(respuesta) : respuesta;
    if (signal.aborted) return;
    await mostrarEvaluacion(datos, signal);
    if (signal.aborted) return;
    if (nombre === 'cultivos') {
      const {mapa_cultivos, ...ranking} = datos;
      if (mapa_cultivos) {
        const {imagen, ...resumen} = mapa_cultivos;
        ranking.mapa_cultivos = resumen;
      }
      if (ranking.modo === 'rotacion') {
        const {aptos, no_aptos, fichas, ...rotacion} = ranking;
        rotacion.fichas = Object.fromEntries(ranking.rotacion.map(paso => [paso.cultivo, fichas[paso.cultivo]]));
        resultado.datos.cultivos = rotacion;
      } else {
        resultado.datos.cultivos = ranking;
      }
    } else {
      const {imagen, ...resumen} = datos;
      resultado.datos.restauracion = resumen;
    }
    estado(`${nombre}-estado`, nombre === 'cultivos' ? 'Análisis de cultivos listo.' : 'Restauración evaluada.');
  } catch (error) {
    if (signal.aborted) return;
    const mensaje = nombre === 'cultivos' && error.estado === 503
      ? `No se pudo completar el análisis de cultivos. ${error.message}`
      : error.message;
    estado(`${nombre}-estado`, mensaje, true);
  } finally {
    if (evaluaciones.get(nombre) === controlador) {
      evaluaciones.delete(nombre);
      boton.disabled = false;
      if (nombre === 'cultivos') actualizarControlesNemotron();
    }
  }
}

function solicitudJson(datos) {
  return {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(datos)};
}

function descargar(blob, nombre) {
  const url = URL.createObjectURL(blob);
  const enlace = document.createElement('a');
  enlace.href = url;
  enlace.download = nombre;
  enlace.click();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

$('explorar').addEventListener('click', () => modo('explorar'));
$('dibujar').addEventListener('click', () => modo('dibujar'));
$('acercar').addEventListener('click', () => mapa.escalar(1.5));
$('alejar').addEventListener('click', () => mapa.escalar(1/1.5));
$('restablecer').addEventListener('click', () => mapa.restablecer());
$('nemotron-clave').addEventListener('input', actualizarControlesNemotron);
$('nemotron-formulario').addEventListener('submit', event => {
  event.preventDefault();
  const campo = $('nemotron-clave');
  const clave = campo.value.trim();
  if (!clave || actualizandoClave || configuracionNemotron?.editable === false) return;
  campo.value = '';
  consultarConfiguracionNemotron(solicitudJson({clave}));
});
$('nemotron-borrar').addEventListener('click', async () => {
  if (configuracionNemotron?.origen !== 'interfaz') return;
  $('nemotron-clave').value = '';
  await consultarConfiguracionNemotron(solicitudJson({clave: ''}));
  if (!configuracionNemotron?.configurada) $('nemotron-clave').focus();
});
$('sistema-cultivo').addEventListener('change', () => {
  limpiarCultivos();
  mapa.dibujar();
});
const ayudaRotacion = $('ayuda-rotacion');
$('porque-rotacion').addEventListener('click', () => {
  const abierta = ayudaRotacion.classList.toggle('abierta');
  ayudaRotacion.classList.toggle('cerrada', !abierta);
});
ayudaRotacion.addEventListener('pointerleave', () => ayudaRotacion.classList.remove('cerrada'));
ayudaRotacion.addEventListener('focusout', () => ayudaRotacion.classList.remove('abierta', 'cerrada'));
document.addEventListener('pointerdown', event => {
  if (!ayudaRotacion.contains(event.target)) ayudaRotacion.classList.remove('abierta');
});
document.addEventListener('keydown', event => {
  if (event.key !== 'Escape' || !ayudaRotacion.matches(':hover, :focus-within, .abierta')) return;
  ayudaRotacion.classList.remove('abierta');
  ayudaRotacion.classList.add('cerrada');
});
$('ejecutar-cultivos').addEventListener('click', async () => {
  const area = resultado;
  const sistema = sistemaCultivo();
  if (necesitaClaveNemotron()) {
    await consultarConfiguracionNemotron();
    if (resultado !== area || sistemaCultivo() !== sistema) return;
    if (necesitaClaveNemotron()) {
      $('nemotron-clave').focus();
      return;
    }
  }
  evaluar('cultivos', 'Evaluando cultivos…', mostrarCultivos);
});
$('ejecutar-restauracion').addEventListener('click', () => evaluar('restauracion', 'Buscando riberas y corredores…', mostrarRestauracion));
$('mostrar-cultivos').addEventListener('change', event => {
  if (!mapa.cultivos) return;
  mapa.cultivos.visible = event.target.checked;
  mapa.dibujar();
});
$('acercar-cultivos').addEventListener('click', () => {
  if (mapa.cultivos) mapa.encuadrar(mapa.cultivos.limites);
});
$('mostrar-restauracion').addEventListener('change', event => {
  if (!mapa.restauracion) return;
  mapa.restauracion.visible = event.target.checked;
  mapa.dibujar();
});
$('limpiar').addEventListener('click', () => {
  campos.forEach(id => { $(id).value = ''; });
  actualizarSeleccion();
});
campos.forEach(id => $(id).addEventListener('input', actualizarSeleccion));

$('formulario').addEventListener('submit', async event => {
  event.preventDefault();
  const seleccion = leerSeleccion();
  if (!seleccion || ocupado) return;
  const solicitud = ++consultaArea;
  ocupado = true;
  resultado = null;
  avisarAreaAnalizada();
  limpiarEvaluaciones();
  $('analizar').disabled = true;
  $('resultados').hidden = true;
  estado('estado', 'Analizando el área…');
  try {
    const datos = await (await solicitar('/api/analizar', solicitudJson(peticion(seleccion)))).json();
    if (consultaArea !== solicitud) return;
    resultado = {datos, seleccion};
    mostrar(datos);
    avisarAreaAnalizada(seleccion);
    estado('estado', 'Análisis completado.');
  } catch (error) {
    if (consultaArea === solicitud) estado('estado', error.message, true);
  } finally {
    ocupado = false;
    $('analizar').disabled = !leerSeleccion();
    if (consultaArea !== solicitud) estado('estado', '');
  }
});

$('descargar').addEventListener('click', () => {
  if (!resultado) return;
  descargar(new Blob([JSON.stringify(resultado.datos, null, 2)], {type: 'application/json'}), 'analisis_paraguay.json');
});

$('descargar-tiff').addEventListener('click', async () => {
  if (!resultado) return;
  $('descargar-tiff').disabled = true;
  estado('exportacion-estado', 'Preparando el GeoTIFF…');
  try {
    const respuesta = await solicitar('/api/recorte', solicitudJson(peticion(resultado.seleccion)));
    descargar(await respuesta.blob(), 'recorte_paraguay.tif');
    estado('exportacion-estado', 'Recorte listo.');
  } catch (error) {
    estado('exportacion-estado', error.message, true);
  } finally {
    $('descargar-tiff').disabled = false;
  }
});

async function iniciar() {
  try {
    info = await (await solicitar('/api/info')).json();
    mostrarPaletaCultivos(info.paleta_cultivos || []);
    $('archivo').textContent = `${info.archivo} · ${info.total_bandas} bandas · ${numero(info.ancho)} × ${numero(info.alto)} píxeles`;
    info.avisos.forEach(aviso => texto($('avisos'), 'p', aviso, 'caption warning'));
    if (info.mapa) {
      for (const clase of info.mapa.leyenda) {
        clasesMapa.set(clase.codigo, clase);
        if (clase.visible === false) continue;
        const item = document.createElement('li');
        muestra(item, clase.codigo);
        texto(item, 'span', clase.nombre);
        const agricola = info.mapa.fuente && coberturasAgricolas.has(clase.codigo);
        $(agricola ? 'leyenda-coberturas-agricolas' : 'leyenda').append(item);
        if (agricola) $('leyenda-agricultura').hidden = false;
        if (clase.fuente?.startsWith('https://') && clase.atribucion) {
          const enlace = texto($('leyenda-fuentes'), 'a', clase.atribucion);
          enlace.href = clase.fuente;
          enlace.target = '_blank';
          enlace.rel = 'noopener';
        }
      }
      $('anio-mapa').textContent = info.mapa.anio;
      if (info.mapa.fuente) {
        $('fuente').href = info.mapa.fuente;
        $('fuente').hidden = false;
      }
      $('leyenda-panel').hidden = false;
    }
    actualizarSeleccion();
    await mapa.cargar(info.mapa?.limites || info.limites_wgs84, info.mapa ? '/api/cobertura.png' : null);
    if (!info.mapa) estado('estado', 'El archivo conectado carece de una banda de cobertura del suelo.');
  } catch (error) {
    estado('estado', error.message, true);
    if (!info) $('archivo').textContent = 'GeoTIFF no disponible.';
  }
}
consultarConfiguracionNemotron();
iniciar();
