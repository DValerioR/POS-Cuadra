// Pantalla de venta en mostrador.
//
// Flujo: buscar (o escanear) -> agregar al carrito -> indicar el lote real si
// se entregó otro -> cobrar (efectivo, tarjeta o mixto) -> ticket.
// Atajos: F2 buscar, F12 cobrar, Esc cerrar/limpiar, flechas + Enter en la lista.

function pantallaVenta() {
  return {
    usuario: null,
    cajas: [],
    cajaId: CajaLocal.obtener(),
    turno: null,
    cargando: true,
    error: "",

    // Abrir turno
    nuevoTurno: { tipo: new Date().getHours() < 14 ? "manana" : "tarde", fondo: "" },

    // Búsqueda
    busqueda: "",
    resultados: [],
    elegido: 0,
    _temporizador: null,
    _consulta: 0,

    // Carrito y cobro
    carrito: [],
    efectivo: "",
    tarjeta: "",
    cobrando: false,
    ultimaVenta: null,

    async init() {
      try {
        this.usuario = await API.get("/auth/yo");
        this.cajas = (await API.get("/cajas")).filter((c) => c.activa);
        if (this.cajaId && !this.cajas.some((c) => c.id === this.cajaId)) this.cajaId = null;
        if (this.cajaId) await this.cargarTurno();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.cargando = false;
      }
      window.addEventListener("keydown", (ev) => this.atajo(ev));
      this.$nextTick(() => this.enfocarBusqueda());
    },

    get puedeVender() {
      return this.usuario && this.usuario.rol !== "bodega";
    },
    get cajaNombre() {
      const caja = this.cajas.find((c) => c.id === this.cajaId);
      return caja ? caja.nombre : "";
    },

    // --- Caja y turno ---------------------------------------------------

    async elegirCaja(id) {
      this.cajaId = Number(id);
      CajaLocal.guardar(this.cajaId);
      await this.cargarTurno();
    },

    async cargarTurno() {
      this.turno = await API.get(`/turnos/abierto?caja_id=${this.cajaId}`);
    },

    async abrirTurno() {
      this.error = "";
      try {
        this.turno = await API.post("/turnos", {
          caja_id: this.cajaId,
          tipo: this.nuevoTurno.tipo,
          fondo_inicial: this.nuevoTurno.fondo || "0",
        });
        this.$nextTick(() => this.enfocarBusqueda());
      } catch (e) {
        this.error = e.message;
      }
    },

    // --- Búsqueda -------------------------------------------------------

    enfocarBusqueda() {
      const campo = document.getElementById("busqueda");
      if (campo) campo.focus();
    },

    async consultar(texto) {
      const numero = ++this._consulta;
      const lista = await API.get(`/productos?solo_activos=true&limite=30&q=${encodeURIComponent(texto)}`);
      return numero === this._consulta ? lista : null; // ignorar respuestas viejas
    },

    alEscribir() {
      clearTimeout(this._temporizador);
      const texto = this.busqueda.trim();
      if (texto.length < 2) {
        this.resultados = [];
        return;
      }
      this._temporizador = setTimeout(async () => {
        try {
          const lista = await this.consultar(texto);
          if (lista) {
            this.resultados = lista;
            this.elegido = 0;
          }
        } catch (e) {
          this.error = e.message;
        }
      }, 180);
    },

    // Enter: el escáner escribe el código y manda Enter muy rápido, así que se
    // busca en ese momento sin esperar a la búsqueda mientras se escribe.
    async alPresionarEnter() {
      const texto = this.busqueda.trim();
      if (!texto) return;
      clearTimeout(this._temporizador);
      let lista = this.resultados;
      try {
        const nueva = await this.consultar(texto);
        if (nueva) lista = nueva;
      } catch (e) {
        this.error = e.message;
        return;
      }
      const porClave = lista.find((p) => p.clave && p.clave.replace(/^0+/, "") === texto.replace(/^0+/, ""));
      const producto = porClave || (lista.length === 1 ? lista[0] : lista[this.elegido]);
      if (producto) {
        await this.agregar(producto);
      } else {
        this.error = `No se encontró "${texto}"`;
        this.resultados = [];
      }
    },

    mover(paso) {
      if (!this.resultados.length) return;
      this.elegido = (this.elegido + paso + this.resultados.length) % this.resultados.length;
    },

    limpiarBusqueda() {
      this.busqueda = "";
      this.resultados = [];
      this.enfocarBusqueda();
    },

    // --- Carrito --------------------------------------------------------

    async agregar(producto) {
      this.error = "";
      if (producto.precio_venta === null) {
        this.error = `${producto.nombre} no tiene precio de venta; pide al administrador que lo capture.`;
        return;
      }
      const existente = this.carrito.find((r) => r.producto.id === producto.id && !r.loteId);
      if (existente) {
        existente.cantidad = Number(existente.cantidad) + 1;
      } else {
        try {
          const existencia = await API.get(`/inventario/productos/${producto.id}`);
          this.carrito.push({
            clave: crypto.randomUUID ? crypto.randomUUID() : String(Date.now() + Math.random()),
            producto,
            existencia,
            cantidad: 1,
            loteId: "",
            caducidadMes: "",
            numeroLote: "",
          });
        } catch (e) {
          this.error = e.message;
          return;
        }
      }
      this.limpiarBusqueda();
    },

    quitar(renglon) {
      this.carrito = this.carrito.filter((r) => r !== renglon);
      this.enfocarBusqueda();
    },

    importe(renglon) {
      return Math.round(centavos(renglon.producto.precio_venta) * Number(renglon.cantidad || 0)) / 100;
    },

    // Lote que se sugiere entregar (FEFO) o el que eligió el vendedor.
    loteAEntregar(renglon) {
      const lotes = renglon.existencia.lotes;
      if (renglon.loteId) return lotes.find((l) => l.id === Number(renglon.loteId));
      return lotes[0];
    },

    textoLote(lote) {
      if (!lote) return "";
      if (!lote.caducidad && !lote.numero_lote) return "Sin caducidad registrada";
      const partes = [];
      if (lote.numero_lote) partes.push(`Lote ${lote.numero_lote}`);
      if (lote.caducidad) partes.push(`Cad ${mesAnio(lote.caducidad)}`);
      return partes.join(" · ");
    },

    // Capturar caducidad solo tiene sentido si hay piezas sin caducidad y no se eligió lote.
    puedeCapturarCaducidad(renglon) {
      return !renglon.loteId && renglon.existencia.controla_lote && Number(renglon.existencia.sin_caducidad) > 0;
    },

    faltaExistencia(renglon) {
      const disponible = renglon.loteId
        ? Number((this.loteAEntregar(renglon) || {}).cantidad || 0)
        : Number(renglon.existencia.existencia);
      return Number(renglon.cantidad) > disponible ? disponible : null;
    },

    // --- Cobro ----------------------------------------------------------

    get totalCentavos() {
      return this.carrito.reduce((suma, r) => suma + Math.round(this.importe(r) * 100), 0);
    },
    get efectivoNecesarioCentavos() {
      return Math.max(0, this.totalCentavos - centavos(this.tarjeta));
    },
    get faltaCentavos() {
      return Math.max(0, this.efectivoNecesarioCentavos - centavos(this.efectivo));
    },
    get cambioCentavos() {
      return Math.max(0, centavos(this.efectivo) - this.efectivoNecesarioCentavos);
    },
    get listoParaCobrar() {
      return (
        this.carrito.length > 0 &&
        !this.cobrando &&
        this.faltaCentavos === 0 &&
        centavos(this.tarjeta) <= this.totalCentavos &&
        this.carrito.every((r) => Number(r.cantidad) > 0)
      );
    },

    efectivoExacto() {
      this.efectivo = (this.efectivoNecesarioCentavos / 100).toFixed(2);
    },
    todoConTarjeta() {
      this.tarjeta = (this.totalCentavos / 100).toFixed(2);
      this.efectivo = "";
    },

    // "2027-03" -> "2027-03-31": las cajas traen mes/año; se toma el último día.
    ultimoDiaDelMes(mes) {
      const [anio, m] = mes.split("-").map(Number);
      const dia = new Date(anio, m, 0).getDate();
      return `${mes}-${String(dia).padStart(2, "0")}`;
    },

    async cobrar() {
      if (!this.listoParaCobrar) return;
      this.cobrando = true;
      this.error = "";
      try {
        const venta = await API.post("/ventas", {
          caja_id: this.cajaId,
          renglones: this.carrito.map((r) => ({
            producto_id: r.producto.id,
            cantidad: String(r.cantidad),
            lote_id: r.loteId ? Number(r.loteId) : null,
            caducidad: !r.loteId && r.caducidadMes ? this.ultimoDiaDelMes(r.caducidadMes) : null,
            numero_lote: !r.loteId && r.caducidadMes && r.numeroLote ? r.numeroLote : null,
          })),
          tarjeta: this.tarjeta || "0",
          efectivo_recibido: this.efectivo || "0",
        });
        this.ultimaVenta = venta;
      } catch (e) {
        this.error = e.message;
      } finally {
        this.cobrando = false;
      }
    },

    async reimprimir() {
      try {
        const r = await API.post(`/ventas/${this.ultimaVenta.id}/imprimir`, {});
        this.ultimaVenta.impresion = r;
      } catch (e) {
        this.ultimaVenta.impresion = { impreso: false, error: e.message };
      }
    },

    nuevaVenta() {
      this.ultimaVenta = null;
      this.carrito = [];
      this.efectivo = "";
      this.tarjeta = "";
      this.error = "";
      this.limpiarBusqueda();
    },

    // --- Teclado --------------------------------------------------------

    atajo(ev) {
      if (this.ultimaVenta) {
        if (ev.key === "Enter" || ev.key === "Escape") {
          ev.preventDefault();
          this.nuevaVenta();
        }
        return;
      }
      if (ev.key === "F2") {
        ev.preventDefault();
        this.enfocarBusqueda();
      } else if (ev.key === "F12") {
        ev.preventDefault();
        this.cobrar();
      } else if (ev.key === "Escape") {
        if (this.resultados.length) this.resultados = [];
        else this.limpiarBusqueda();
      }
    },

    dinero,
    cantidad,
    mesAnio,
  };
}
