'use strict';
const $ = id => document.getElementById(id);
const campos = ['lon1','lat1','lon2','lat2'];
const canvas = $('vista'), ctx = canvas.getContext('2d');
let info, vista, resultado, inicio;
const numero = valor => valor == null ? '—' : new Intl.NumberFormat('es-PY',{maximumFractionDigits:4}).format(valor);
function estado(texto, error=false) { $('estado').textContent=texto; $('estado').classList.toggle('error',error); }
function agregar(parent, tag, texto, clase) { const nodo=document.createElement(tag); nodo.textContent=texto; if(clase)nodo.className=clase; parent.append(nodo); return nodo; }
function seleccion() { return campos.map(id => $(id).value === '' ? NaN : Number($(id).value)); }
function dibujar() {
  const w=canvas.width,h=canvas.height;
  ctx.fillStyle='#edf3ec';ctx.fillRect(0,0,w,h);
  ctx.strokeStyle='#d7e3d5';ctx.lineWidth=1;
  for(let x=0;x<w;x+=60){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke();}
  for(let y=0;y<h;y+=60){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();}
  if (vista) ctx.drawImage(vista, 0, 0, w, h);
  if(!info)return;
  ctx.fillStyle='#456958';ctx.font='15px system-ui';ctx.fillText('N ↑',18,28);
  const [o,s,e,n]=info.limites_wgs84;
  const p=seleccion();
  if(p.every(Number.isFinite)) {
    const x1=(p[0]-o)/(e-o)*w,y1=(n-p[1])/(n-s)*h;
    const x2=(p[2]-o)/(e-o)*w,y2=(n-p[3])/(n-s)*h;
    ctx.fillStyle='#1b806635';ctx.fillRect(x1,y1,x2-x1,y2-y1);
    ctx.strokeStyle='#fff';ctx.lineWidth=5;ctx.strokeRect(x1,y1,x2-x1,y2-y1);
    ctx.strokeStyle='#17624e';ctx.lineWidth=3;ctx.strokeRect(x1,y1,x2-x1,y2-y1);
    for(const [x,y,t] of [[x1,y1,'1'],[x2,y2,'2']]){
      ctx.beginPath();ctx.arc(x,y,10,0,2*Math.PI);ctx.fillStyle='#17624e';ctx.fill();
      ctx.fillStyle='#fff';ctx.font='12px system-ui';ctx.fillText(t,x-3,y+4);
    }
  }
}
function coordenada(event) {
  const rect=canvas.getBoundingClientRect(), [o,s,e,n]=info.limites_wgs84;
  const x=Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width));
  const y=Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height));
  return [o+x*(e-o),n-y*(n-s)];
}
function escribir(p1,p2) { [p1[0],p1[1],p2[0],p2[1]].forEach((v,i)=>$(campos[i]).value=v.toFixed(7)); dibujar(); }
canvas.addEventListener('pointerdown', event=>{
  if(!info)return; inicio=coordenada(event);canvas.setPointerCapture(event.pointerId);escribir(inicio,inicio);
});
canvas.addEventListener('pointermove',event=>{if(inicio)escribir(inicio,coordenada(event));});
canvas.addEventListener('pointerup',event=>{if(inicio)escribir(inicio,coordenada(event));inicio=null;});
canvas.addEventListener('pointercancel',()=>{inicio=null;});
campos.forEach(id=>$(id).addEventListener('input',dibujar));

function mostrar(data) {
  resultado=data; $('resultados').hidden=false;
  $('resumen').textContent=`${numero(data.pixeles_seleccionados)} píxeles seleccionados · ${data.total_bandas} bandas · ${data.archivo}`;
  const r=data.rectangulo;
  $('consulta').textContent=`Consulta WGS84: oeste ${r.oeste}, sur ${r.sur}, este ${r.este}, norte ${r.norte}.`;
  $('notas').replaceChildren();data.avisos.forEach(aviso=>agregar($('notas'),'p',aviso,'caption'));
  $('bandas').replaceChildren();$('clases').replaceChildren();
  for(const b of data.bandas) {
    const fila=document.createElement('tr');
    const nombre=agregar(fila,'td',`${b.indice}. ${b.titulo}`);agregar(nombre,'small',`${b.fuente} · ${b.nombre}`);
    [b.unidad || '—',numero(b.validos),numero(b.sin_datos),numero(b.cobertura_pct)+' %',numero(b.minimo),numero(b.media),numero(b.maximo),numero(b.desviacion)].forEach(v=>agregar(fila,'td',v));
    $('bandas').append(fila);
    if(b.tipo==='category') {
      const card=agregar($('clases'),'div','','class-card');agregar(card,'h4',b.titulo);
      if(b.aviso)agregar(card,'p',b.aviso,'warning');
      else if(!b.clases.length)agregar(card,'p','Sin píxeles válidos.');
      for(const c of b.clases) {
        const row=agregar(card,'div','','class-row');agregar(row,'span',`Código ${numero(c.valor)}`);
        agregar(row,'span',`${numero(c.pixeles)} px · ${numero(c.porcentaje)} %`);
      }
    }
  }
}
async function pedirJSON(ruta, mensaje, opciones) {
  const respuesta = await fetch(ruta, opciones).catch(() => { throw new Error(mensaje); });
  if (!respuesta.headers.get('Content-Type')?.includes('application/json')) throw new Error(mensaje);
  const datos = await respuesta.json();
  if (!respuesta.ok) throw new Error(datos.error || mensaje);
  return datos;
}

$('formulario').addEventListener('submit',async event=>{
  event.preventDefault();
  if (!info || $('analizar').disabled) return;
  const p=seleccion();
  if(!p.every(Number.isFinite)){estado('Completa las cuatro coordenadas.',true);return;}
  $('analizar').disabled=true;$('resultados').hidden=true;resultado=null;
  estado('Analizando las bandas… La duración depende del área y del archivo.');
  try {
    const datos = await pedirJSON('/api/analizar', 'No se pudo completar el análisis. Verifica que el servidor siga activo.', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({pos1: {lon: p[0], lat: p[1]}, pos2: {lon: p[2], lat: p[3]}})
    });
    mostrar(datos);estado('Análisis completado.');
  } catch(error) {estado(error.message,true);} finally {$('analizar').disabled=false;}
});
$('descargar').addEventListener('click',()=>{
  if(!resultado)return;
  const url=URL.createObjectURL(new Blob([JSON.stringify(resultado,null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download='analisis_geotiff.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
function cargarVista() {
  const leyenda = $('vista-estado');
  const banda = info.bandas[info.banda_vista - 1];
  const imagen = new Image();
  leyenda.textContent = 'Cargando la vista previa del GeoTIFF…';
  imagen.onload = () => {
    vista = imagen;
    canvas.width = imagen.naturalWidth;
    canvas.height = imagen.naturalHeight;
    leyenda.textContent = `Vista previa · ${banda.titulo} · WGS84`;
    dibujar();
  };
  imagen.onerror = () => {
    leyenda.textContent = 'No se pudo mostrar la imagen. Puedes seleccionar un área en la cuadrícula o escribir las coordenadas.';
  };
  imagen.src = '/api/vista.png';
}

async function iniciar() {
  dibujar();
  if (location.protocol === 'file:') {
    $('archivo').textContent = 'Esta página necesita el servidor local.';
    estado('Ejecuta servidor.py desde la carpeta del proyecto y abre http://127.0.0.1:8000 en el navegador.', true);
    return;
  }
  try {
    info = await pedirJSON('/api/info', 'No se pudo conectar con el servidor del GeoTIFF.');
    $('archivo').textContent=`${info.archivo} · ${info.total_bandas} bandas · ${numero(info.ancho)} × ${numero(info.alto)} píxeles · ${info.crs}`;
    info.avisos.forEach(aviso=>agregar($('avisos'),'p',aviso,'warning'));
    const [o,s,e,n]=info.limites_wgs84;
    $('extension').textContent=`Extensión WGS84: oeste ${numero(o)} · sur ${numero(s)} · este ${numero(e)} · norte ${numero(n)}`;
    $('analizar').disabled=false;estado(`Selecciona un área. Límite: ${numero(info.max_pixeles)} píxeles por ventana.`);dibujar();
    cargarVista();
  } catch(error) {$('archivo').textContent='Sin conexión con el archivo.';estado(error.message,true);}
}
iniciar();
