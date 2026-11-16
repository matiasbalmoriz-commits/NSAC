'use strict';

class MapaCobertura {
  constructor(canvas, controles) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.controles = controles;
    this.modo = 'explorar';
    this.seleccion = null;
    this.celda = null;
    this.zoom = 1;
    new ResizeObserver(() => this.dibujar()).observe(canvas);
    canvas.addEventListener('pointerdown', event => this.iniciar(event));
    canvas.addEventListener('pointermove', event => this.mover(event));
    canvas.addEventListener('pointerup', event => this.terminar(event));
    canvas.addEventListener('pointercancel', () => this.cancelar());
    canvas.addEventListener('lostpointercapture', () => this.cancelar());
    canvas.addEventListener('pointerleave', () => controles.posicion(null));
    canvas.addEventListener('wheel', event => {
      if (!this.limites) return;
      event.preventDefault();
      this.escalar(event.deltaY < 0 ? 1.25 : .8, this.puntoPantalla(event));
    }, {passive: false});
    canvas.addEventListener('keydown', event => this.teclado(event));
  }

  cargar(limites, url) {
    this.limites = limites;
    this.restablecer();
    if (!url) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const imagen = new Image();
      imagen.onload = () => {
        this.imagen = imagen;
        this.dibujar();
        resolve();
      };
      imagen.onerror = () => reject(new Error('No se pudo cargar la imagen de cobertura.'));
      imagen.src = url;
    });
  }

  restablecer() {
    if (!this.limites) return;
    const [oeste, sur, este, norte] = this.limites;
    this.centro = [(oeste + este) / 2, (sur + norte) / 2];
    this.aspecto = Math.max(.1, Math.cos(this.centro[1] * Math.PI / 180));
    this.zoom = 1;
    this.dibujar();
  }

  escala() {
    const [oeste, sur, este, norte] = this.limites;
    return this.zoom * Math.min(
      this.canvas.clientWidth * .88 / ((este - oeste) * this.aspecto),
      this.canvas.clientHeight * .88 / (norte - sur)
    );
  }

  pantalla([lon, lat]) {
    const escala = this.escala();
    return [
      this.canvas.clientWidth / 2 + (lon - this.centro[0]) * escala * this.aspecto,
      this.canvas.clientHeight / 2 - (lat - this.centro[1]) * escala
    ];
  }

  mundo([x, y]) {
    const escala = this.escala();
    return [
      this.centro[0] + (x - this.canvas.clientWidth / 2) / (escala * this.aspecto),
      this.centro[1] - (y - this.canvas.clientHeight / 2) / escala
    ];
  }

  puntoPantalla(event) {
    const rect = this.canvas.getBoundingClientRect();
    return [event.clientX - rect.left, event.clientY - rect.top];
  }

  limitar([lon, lat]) {
    const [oeste, sur, este, norte] = this.limites;
    return [Math.max(oeste, Math.min(este, lon)), Math.max(sur, Math.min(norte, lat))];
  }

  escalar(factor, ancla = [this.canvas.clientWidth / 2, this.canvas.clientHeight / 2]) {
    if (!this.limites) return;
    const antes = this.mundo(ancla);
    this.zoom = Math.max(1, Math.min(48, this.zoom * factor));
    const despues = this.mundo(ancla);
    this.centro = this.limitar(this.centro.map((coord, i) => coord + antes[i] - despues[i]));
    if (this.zoom === 1) this.restablecer();
    else this.dibujar();
  }

  encuadrar([oeste, sur, este, norte]) {
    const {clientWidth: ancho, clientHeight: alto} = this.canvas;
    if (!this.limites || !ancho || !alto || este <= oeste || norte <= sur) return;
    const escalaBase = this.escala() / this.zoom;
    const escalaZona = Math.min(ancho * .82 / ((este - oeste) * this.aspecto), alto * .82 / (norte - sur));
    this.zoom = Math.max(1, Math.min(48, escalaZona / escalaBase));
    this.centro = this.limitar([(oeste + este) / 2, (sur + norte) / 2]);
    this.dibujar();
  }

  cambiarModo(modo) {
    this.modo = modo;
    this.canvas.classList.toggle('seleccionando', modo === 'dibujar');
  }

  iniciar(event) {
    if (!this.limites || event.button !== 0 || this.gesto) return;
    const punto = this.puntoPantalla(event);
    this.gesto = {id: event.pointerId, inicio: punto, centro: this.centro.slice()};
    this.canvas.setPointerCapture(event.pointerId);
    this.canvas.focus({preventScroll: true});
  }

  mover(event) {
    if (!this.limites) return;
    const punto = this.puntoPantalla(event);
    const coordenadas = this.mundo(punto);
    this.controles.posicion(coordenadas);
    if (this.gesto?.id !== event.pointerId) return;
    const [dx, dy] = punto.map((v, i) => v - this.gesto.inicio[i]);
    this.gesto.movido ||= Math.hypot(dx, dy) >= 4;
    if (!this.gesto.movido) return;
    if (this.modo === 'dibujar') {
      this.borrador = [this.gesto.inicio, punto].map(p => this.limitar(this.mundo(p)));
    } else {
      this.canvas.classList.add('arrastrando');
      const escala = this.escala();
      this.centro = this.limitar([this.gesto.centro[0] - dx / (escala * this.aspecto),
                                  this.gesto.centro[1] + dy / escala]);
    }
    this.dibujar();
  }

  terminar(event) {
    if (this.gesto?.id !== event.pointerId) return;
    const {movido} = this.gesto;
    const seleccion = this.borrador;
    this.cancelar();
    if (this.modo === 'dibujar' && seleccion) this.controles.seleccionar(seleccion);
    else if (this.modo === 'explorar' && !movido) this.controles.consultar(this.mundo(this.puntoPantalla(event)));
  }

  cancelar() {
    this.gesto = null;
    this.borrador = null;
    this.canvas.classList.remove('arrastrando');
    this.dibujar();
  }

  teclado(event) {
    if (!this.limites) return;
    const movimientos = {ArrowLeft: [-55, 0], ArrowRight: [55, 0], ArrowUp: [0, -55], ArrowDown: [0, 55]};
    if (event.key in movimientos) {
      const [dx, dy] = movimientos[event.key];
      this.centro = this.limitar(this.mundo([this.canvas.clientWidth / 2 + dx, this.canvas.clientHeight / 2 + dy]));
      this.dibujar();
    } else if (event.key === '+' || event.key === '=') this.escalar(1.5);
    else if (event.key === '-') this.escalar(1/1.5);
    else if (event.key === 'Enter' && this.modo === 'explorar') this.controles.consultar(this.centro);
    else return;
    event.preventDefault();
  }

  dibujar() {
    const {canvas, ctx} = this;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (canvas.width !== Math.round(w*dpr) || canvas.height !== Math.round(h*dpr)) {
      canvas.width = Math.round(w*dpr);
      canvas.height = Math.round(h*dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = '#eef3ed';
    ctx.fillRect(0, 0, w, h);
    if (!this.limites) return;
    const [oeste, sur, este, norte] = this.limites;
    const paso = this.zoom < 3 ? 2 : this.zoom < 8 ? 1 : this.zoom < 18 ? .5 : .25;
    ctx.strokeStyle = '#cbd8ce';
    ctx.fillStyle = '#506457';
    ctx.font = '11px system-ui';
    ctx.lineWidth = 1;
    for (let lon = Math.ceil(oeste/paso)*paso; lon <= este; lon += paso) {
      const [x] = this.pantalla([lon, 0]);
      if (x < 20 || x > w - 20) continue;
      ctx.beginPath(); ctx.moveTo(x, 22); ctx.lineTo(x, h); ctx.stroke();
      ctx.fillText(`${Math.abs(lon)}° O`, x + 3, 16);
    }
    for (let lat = Math.ceil(sur/paso)*paso; lat <= norte; lat += paso) {
      const [, y] = this.pantalla([0, lat]);
      if (y < 28 || y > h - 12) continue;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
      ctx.fillText(`${Math.abs(lat)}° S`, 7, y - 4);
    }
    if (this.imagen) this.dibujarImagen(this.imagen, this.limites);
    if (this.cultivos?.visible) this.dibujarImagen(this.cultivos.imagen, this.cultivos.limites);
    if (this.restauracion?.visible) this.dibujarImagen(this.restauracion.imagen, this.restauracion.limites);
    const seleccion = this.borrador || this.seleccion;
    if (seleccion) {
      const [[x, y], [a, b]] = seleccion.map(p => this.pantalla(p));
      if (this.borrador || !this.cultivos?.visible) {
        ctx.fillStyle = '#fff3';
        ctx.fillRect(x, y, a - x, b - y);
      }
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 4;
      ctx.strokeRect(x, y, a - x, b - y);
      ctx.strokeStyle = '#183a2a';
      ctx.lineWidth = 2;
      ctx.strokeRect(x, y, a - x, b - y);
    }
    if (this.celda) {
      const [x, y] = this.pantalla([this.celda.lon, this.celda.lat]);
      ctx.beginPath();
      ctx.arc(x, y, 5, 0, 2*Math.PI);
      ctx.fillStyle = '#183a2a';
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = '#fff';
      ctx.stroke();
      ctx.beginPath();
      this.celda.esquinas.map(p => this.pantalla(p)).forEach(([px, py], i) => {
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      });
      ctx.closePath();
      ctx.strokeStyle = '#183a2a';
      ctx.lineWidth = 1;
      ctx.stroke();
    }
  }

  dibujarImagen(imagen, [oeste, sur, este, norte]) {
    const [x0, y0] = this.pantalla([oeste, norte]);
    const [x1, y1] = this.pantalla([este, sur]);
    this.ctx.imageSmoothingEnabled = false;
    this.ctx.drawImage(imagen, x0, y0, x1 - x0, y1 - y0);
  }
}
