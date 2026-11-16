'use strict';

(() => {
  const panel = document.getElementById('plugins-panel');
  if (!panel) return;
  const lista = document.getElementById('plugins-lista');
  const estadoPanel = document.getElementById('plugins-estado');
  const tarjetas = new Map();
  const numero = new Intl.NumberFormat('es-PY', {maximumFractionDigits: 2});
  let area = null;
  let cargando = false;
  let cargado = false;

  function elemento(padre, etiqueta, contenido = '', clase = '') {
    const nodo = document.createElement(etiqueta);
    nodo.textContent = contenido;
    if (clase) nodo.className = clase;
    padre.append(nodo);
    return nodo;
  }

  function estado(nodo, contenido, error = false) {
    nodo.textContent = contenido;
    nodo.classList.toggle('error', error);
  }

  async function solicitar(url, cuerpo, signal) {
    const opciones = cuerpo === undefined ? {} : {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(cuerpo),
    };
    const respuesta = await fetch(url, {...opciones, signal});
    const datos = await respuesta.json().catch(() => null);
    if (!respuesta.ok || !datos) throw new Error(datos?.error || 'No se pudo cargar la herramienta.');
    return datos;
  }

  function actualizar(tarjeta) {
    const {plugin, habilitar, ejecutar, informe, alternando, consulta} = tarjeta;
    habilitar.checked = plugin.habilitado;
    habilitar.disabled = alternando || (!plugin.disponible && !plugin.habilitado);
    ejecutar.disabled = !area || !plugin.disponible || !plugin.habilitado || alternando || !!consulta;
    informe.hidden = !plugin.habilitado || !informe.childElementCount;
  }

  function limpiarInforme(tarjeta) {
    tarjeta.consulta?.abort();
    tarjeta.consulta = null;
    tarjeta.informe.replaceChildren();
  }

  function mensajeInicial(tarjeta) {
    const {plugin} = tarjeta;
    if (!plugin.disponible) return 'Herramienta no disponible.';
    if (!plugin.habilitado) return 'Herramienta desactivada.';
    return area ? '' : 'Selecciona una zona y pulsa Analizar área.';
  }

  function mostrarInforme(contenedor, datos) {
    contenedor.replaceChildren();
    elemento(contenedor, 'h4', datos.titulo);
    elemento(contenedor, 'p', datos.resumen);
    if (datos.indicadores?.length) {
      const indicadores = elemento(contenedor, 'ul');
      for (const {nombre, valor, unidad} of datos.indicadores) {
        const valorTexto = typeof valor === 'number' ? numero.format(valor) : (valor ?? 'Sin datos');
        elemento(indicadores, 'li', [nombre, [valorTexto, unidad].filter(Boolean).join(' ')].join(' · '));
      }
    }
    if (datos.notas?.length) {
      const notas = elemento(contenedor, 'ul', '', 'caption');
      for (const nota of datos.notas) elemento(notas, 'li', nota);
    }
  }

  function agregarTarjeta(plugin) {
    const ruta = '/api/plugins/' + encodeURIComponent(plugin.id);
    const seccion = elemento(lista, 'section', '', 'plugin');
    elemento(seccion, 'h3', plugin.nombre);
    elemento(seccion, 'p', plugin.descripcion, 'caption');
    const acciones = elemento(seccion, 'div', '', 'form-actions');
    const etiqueta = elemento(acciones, 'label', '', 'interruptor');
    const habilitar = elemento(etiqueta, 'input');
    habilitar.type = 'checkbox';
    etiqueta.append(' Activar');
    habilitar.setAttribute('aria-label', 'Activar ' + plugin.nombre);
    const ejecutar = elemento(acciones, 'button', 'Generar informe', 'secundario');
    ejecutar.type = 'button';
    ejecutar.setAttribute('aria-label', 'Generar informe de ' + plugin.nombre);
    const mensaje = elemento(seccion, 'p', '', 'caption plugin-estado');
    mensaje.setAttribute('role', 'status');
    const informe = elemento(seccion, 'div', '', 'plugin-informe');
    const tarjeta = {plugin, habilitar, ejecutar, mensaje, informe, alternando: false, consulta: null};
    tarjetas.set(plugin.id, tarjeta);
    estado(mensaje, mensajeInicial(tarjeta));
    actualizar(tarjeta);

    habilitar.addEventListener('change', async () => {
      const habilitado = habilitar.checked;
      tarjeta.alternando = true;
      if (!habilitado) limpiarInforme(tarjeta);
      actualizar(tarjeta);
      try {
        tarjeta.plugin = await solicitar(ruta + '/estado', {habilitado});
        estado(mensaje, mensajeInicial(tarjeta));
      } catch (error) {
        estado(mensaje, error.message, true);
      } finally {
        tarjeta.alternando = false;
        actualizar(tarjeta);
      }
    });

    ejecutar.addEventListener('click', async () => {
      const consulta = new AbortController();
      tarjeta.consulta = consulta;
      informe.replaceChildren();
      actualizar(tarjeta);
      estado(mensaje, 'Generando informe…');
      try {
        const datos = await solicitar(ruta, area, consulta.signal);
        if (consulta.signal.aborted) return;
        mostrarInforme(informe, datos);
        estado(mensaje, 'Informe listo.');
      } catch (error) {
        if (consulta.signal.aborted) return;
        informe.replaceChildren();
        estado(mensaje, error.message, true);
      } finally {
        if (tarjeta.consulta === consulta) {
          tarjeta.consulta = null;
          actualizar(tarjeta);
        }
      }
    });
  }

  async function cargar() {
    if (!panel.open || cargando || cargado) return;
    cargando = true;
    estado(estadoPanel, 'Cargando herramientas…');
    try {
      const datos = await solicitar('/api/plugins');
      for (const plugin of datos.plugins) agregarTarjeta(plugin);
      cargado = true;
      estado(estadoPanel, datos.plugins.length ? '' : 'No hay herramientas disponibles.');
    } catch {
      estado(estadoPanel, 'Las herramientas opcionales no están disponibles en esta instancia.', true);
    } finally {
      cargando = false;
    }
  }

  document.addEventListener('geovision:area', evento => {
    area = evento.detail;
    for (const tarjeta of tarjetas.values()) {
      limpiarInforme(tarjeta);
      estado(tarjeta.mensaje, mensajeInicial(tarjeta));
      actualizar(tarjeta);
    }
  });
  panel.addEventListener('toggle', cargar);
  cargar();
})();
