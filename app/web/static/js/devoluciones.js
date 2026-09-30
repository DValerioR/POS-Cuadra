// Pantalla de devoluciones, cancelaciones y cambios de producto.
//
// El administrador las hace al momento. El cajero no: envía una solicitud de
// devolución o cancelación (el cambio de producto es solo del administrador)
// y sigue cobrando; un administrador la autoriza desde el centro de
// notificaciones y al cajero le aparece en Vender cuánto entregar.
//
// Flujo: buscar la venta por el folio del ticket (o elegirla de las de hoy)
// -> "Devolver algunos productos", "Cambiar por otro producto" o "Cancelar
// toda la venta" -> motivo -> confirmar -> se le dice al vendedor cuánto
// dinero entregar o cobrar y por qué medio.
// En un cambio, lo que regresa el cliente es saldo a favor para lo que se
// lleva: si lo nuevo cuesta más paga la diferencia; si cuesta menos, se le
// regresa en efectivo.
// El dinero sale del turno abierto de la caja de esta computadora.

const MOTIVOS = ["Producto equivocado", "Producto dañado o caducado", "El cliente ya no lo quiere", "Error al cobrar"];

const METODOS = { efectivo: "Efectivo", tarjeta: "Tarjeta", saldo_a_favor: "Saldo a favor", transferencia: "Transferencia" };

function pantallaDevoluciones() {
  return {
    usuario: null,
    cajaId: CajaLocal.obtener(),
    cajaNombre: "",
    turno: null,
    cargando: true,
    error: "",

    // Buscar la venta
    folio: "",
    recientes: [],
    venta: null,

    // Qué se hace
    modo: null, // "devolver" | "cambiar" | "cancelar"
    piezas: {}, // renglon_id -> cantidad que regresa
    lotes: {}, // renglon_id -> lote_id de la caja devuelta ("" = no se sabe)
    motivo: "",
    motivoOtro: "",
    confirmando: false,
    procesando: false,
    resultado: null,

    // Cambio: lo que se lleva el cliente y cómo paga la diferencia
    nuevos: [], // [{ producto, cantidad }]
    cotizacion: null, // ofertas de lo nuevo: { firma, renglones } (ver venta.js)
    _cotizaTimer: null,
    buscar: "",
    encontrados: [],
    _buscado: "", // texto al que corresponde `encontrados`
    elegido: 0,
    _temporizador: null,
    _consulta: 0,
    formaPago: "efectivo", // efectivo | tarjeta | mixto
    efectivo: "",
    tarjeta: "",

    motivos: MOTIVOS,

    async init() {
      try {
        this.usuario = await API.get("/auth/yo");
        if (!this.puedeUsar) return;
        if (this.cajaId) {
          const caja = (await API.get("/cajas")).find((c) => c.id === this.cajaId);
          this.cajaNombre = caja ? caja.nombre : "";
          this.turno = caja ? await API.get(`/turnos/abierto?caja_id=${this.cajaId}`) : null;
        }
        this.$watch("firmaNuevos", () => this.programarCotizacion());
        await this.cargarRecientes();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.cargando = false;
        this.$nextTick(() => this.enfocarFolio());
      }
      window.addEventListener("keydown", (ev) => {
        if (ev.key !== "Escape") return;
        if (this.confirmando) this.confirmando = false;
        else if (this.resultado) this.otraVenta();
        else if (this.modo) this.modo = null;
        else if (this.venta) this.otraVenta();
      });
    },

    get esAdmin() {
      return this.usuario && this.usuario.rol === "admin";
    },
    // El cajero también entra, pero para pedir la devolución, no para hacerla.
    get puedeUsar() {
      return this.usuario && this.usuario.rol !== "bodega";
    },
    get pideAutorizacion() {
      return !this.esAdmin;
    },
    get textoAccion() {
      if (this.pideAutorizacion) return { cancelar: "Pedir la cancelación", devolver: "Pedir la devolución" }[this.modo];
      return { cancelar: "Cancelar la venta", cambiar: "Hacer el cambio", devolver: "Hacer la devolución" }[this.modo];
    },
    get puedeRegresarDinero() {
      return Boolean(this.turno);
    },

    enfocarFolio() {
      const campo = document.getElementById("folio");
      if (campo) campo.focus();
    },

    // --- Buscar -----------------------------------------------------------

    async cargarRecientes() {
      const hoy = new Date();
      const desde = `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, "0")}-${String(hoy.getDate()).padStart(2, "0")}`;
      this.recientes = await API.get(`/ventas?desde=${desde}&limite=40`);
    },

    async buscarFolio() {
      const folio = String(this.folio).trim();
      if (!folio) return;
      this.error = "";
      try {
        const lista = await API.get(`/ventas?folio=${encodeURIComponent(folio)}`);
        if (!lista.length) {
          this.error = `No hay ninguna venta con el folio ${folio}.`;
          return;
        }
        await this.abrir(lista[0].id);
      } catch (e) {
        this.error = e.message;
      }
    },

    async abrir(ventaId) {
      this.error = "";
      try {
        this.venta = await API.get(`/ventas/${ventaId}`);
        this.modo = null;
        this.piezas = {};
        this.lotes = {};
        this.motivo = "";
        this.motivoOtro = "";
        this.limpiarCambio();
        window.scrollTo(0, 0);
      } catch (e) {
        this.error = e.message;
      }
    },

    otraVenta() {
      this.venta = null;
      this.modo = null;
      this.resultado = null;
      this.confirmando = false;
      this.folio = "";
      this.error = "";
      this.cargarRecientes().catch(() => {});
      this.$nextTick(() => this.enfocarFolio());
    },

    // --- Datos de la venta -------------------------------------------------

    get cancelada() {
      return this.venta && this.venta.estado === "cancelada";
    },
    get yaDevuelto() {
      return this.venta ? this.venta.devoluciones.reduce((s, d) => s + centavos(d.total), 0) : 0;
    },
    // Valor de la venta que todavía se puede regresar, en centavos.
    get porRegresar() {
      return this.venta ? Math.max(0, centavos(this.venta.total) - this.yaDevuelto) : 0;
    },
    get formaDePago() {
      const metodos = [...new Set(this.venta.pagos.map((p) => METODOS[p.metodo] || p.metodo))];
      return metodos.join(" y ");
    },
    disponible(renglon) {
      return Number(renglon.cantidad) - Number(renglon.cantidad_devuelta);
    },
    // Lotes de los que aún quedan piezas por devolver (para preguntar de cuál es la caja).
    lotesPendientes(renglon) {
      return renglon.lotes.filter((l) => Number(l.cantidad) > Number(l.cantidad_devuelta));
    },
    textoLote(lote) {
      const partes = [];
      if (lote.numero_lote) partes.push(`Lote ${lote.numero_lote}`);
      if (lote.caducidad) partes.push(`Cad ${mesAnio(lote.caducidad)}`);
      return partes.join(" · ") || "Sin caducidad registrada";
    },
    get eligePiezas() {
      return this.modo === "devolver" || this.modo === "cambiar";
    },
    textoTipo(tipo) {
      return { cancelacion: "Cancelación", devolucion: "Devolución", cambio: "Cambio de producto" }[tipo] || tipo;
    },

    // --- Devolver algunas piezas --------------------------------------------

    elegirModo(modo) {
      this.modo = modo;
      this.error = "";
      if (modo === "devolver" || modo === "cambiar") {
        // Si solo se vendió una pieza de un solo producto, ya va marcada.
        const conPiezas = this.venta.renglones.filter((r) => this.disponible(r) > 0);
        if (conPiezas.length === 1 && this.disponible(conPiezas[0]) === 1) this.piezas[conPiezas[0].id] = 1;
      }
    },

    cuantas(renglon) {
      return Number(this.piezas[renglon.id] || 0);
    },
    cambiar(renglon, paso) {
      const nueva = Math.min(this.disponible(renglon), Math.max(0, this.cuantas(renglon) + paso));
      this.piezas[renglon.id] = nueva;
    },
    todas(renglon) {
      this.piezas[renglon.id] = this.disponible(renglon);
    },

    // Lo que se cobró por pieza: con oferta, su parte del descuento (igual que el servidor).
    precioPagado(r) {
      return Number(r.descuento) > 0 ? Number(r.importe) / Number(r.cantidad) : Number(r.precio_unitario);
    },

    get piezasElegidas() {
      return this.venta.renglones.filter((r) => this.cuantas(r) > 0);
    },
    // Lo que se regresa, en centavos.
    get totalARegresar() {
      if (this.modo === "cancelar") return this.porRegresar;
      const suma = this.piezasElegidas.reduce(
        (s, r) => s + Math.round(this.precioPagado(r) * 100 * this.cuantas(r)),
        0
      );
      return Math.min(suma, this.porRegresar);
    },
    // Igual que el servidor: primero a tarjeta (hasta lo que se pagó con
    // tarjeta y no se ha regresado) y el resto en efectivo.
    get reparto() {
      const pagadoTarjeta = this.venta.pagos
        .filter((p) => p.metodo === "tarjeta")
        .reduce((s, p) => s + centavos(p.monto), 0);
      const yaATarjeta = this.venta.devoluciones.reduce((s, d) => s + centavos(d.tarjeta), 0);
      const tarjeta = Math.min(this.totalARegresar, Math.max(0, pagadoTarjeta - yaATarjeta));
      return { tarjeta, efectivo: this.totalARegresar - tarjeta };
    },

    get motivoFinal() {
      return (this.motivo === "otro" ? this.motivoOtro : this.motivo).trim();
    },
    get listo() {
      if (!this.puedeRegresarDinero || !this.motivoFinal || this.procesando) return false;
      if (this.modo === "cancelar") return true;
      if (!this.piezasElegidas.length) return false;
      if (this.modo === "cambiar") {
        return this.nuevos.length > 0 && this.nuevos.every((n) => Number(n.cantidad) > 0) && this.faltaCentavos === 0;
      }
      return true;
    },

    // --- Cambio: lo que se lleva ------------------------------------------

    limpiarCambio() {
      this.nuevos = [];
      this.buscar = "";
      this.encontrados = [];
      this.formaPago = "efectivo";
      this.efectivo = "";
      this.tarjeta = "";
    },

    alBuscar() {
      clearTimeout(this._temporizador);
      const texto = this.buscar.trim();
      if (texto.length < 2) {
        this.encontrados = [];
        return;
      }
      this._temporizador = setTimeout(async () => {
        const numero = ++this._consulta;
        try {
          const lista = await API.get(`/productos?solo_activos=true&limite=20&q=${encodeURIComponent(texto)}`);
          if (numero !== this._consulta) return; // ignorar respuestas viejas
          this.encontrados = lista;
          this._buscado = texto;
          this.elegido = 0;
        } catch (e) {
          this.error = e.message;
        }
      }, 180);
    },

    // Enter: si es un código de barras exacto se agrega ese; si no, el de la lista.
    async alPresionarEnter() {
      const texto = this.buscar.trim();
      if (!texto) return;
      clearTimeout(this._temporizador);
      this.error = "";
      try {
        const porClave = await API.get(`/productos?solo_activos=true&limite=2&clave=${encodeURIComponent(texto)}`);
        if (!porClave.length && this._buscado !== texto) {
          // Se presionó Enter antes de que llegara la lista de lo que se
          // escribió: buscar ya, para no agregar algo de una búsqueda anterior.
          ++this._consulta;
          this.encontrados = await API.get(`/productos?solo_activos=true&limite=20&q=${encodeURIComponent(texto)}`);
          this._buscado = texto;
          this.elegido = 0;
        }
        const producto = porClave[0] || this.encontrados[this.elegido];
        if (producto) this.agregarNuevo(producto);
        else this.error = `No se encontró "${texto}".`;
      } catch (e) {
        this.error = e.message;
      }
    },

    moverLista(paso) {
      if (!this.encontrados.length) return;
      this.elegido = (this.elegido + paso + this.encontrados.length) % this.encontrados.length;
    },

    agregarNuevo(producto) {
      if (producto.precio_venta === null) {
        this.error = `${producto.nombre} no tiene precio de venta; captúralo primero.`;
        return;
      }
      const existente = this.nuevos.find((n) => n.producto.id === producto.id);
      if (existente) existente.cantidad = Number(existente.cantidad) + 1;
      else this.nuevos.push({ producto, cantidad: 1 });
      this.buscar = "";
      this.encontrados = [];
      this._buscado = "";
      this.error = "";
      this.$nextTick(() => document.getElementById("buscar-nuevo").focus());
    },

    cambiarNuevo(nuevo, paso) {
      nuevo.cantidad = Math.max(1, Number(nuevo.cantidad || 0) + paso);
    },
    quitarNuevo(nuevo) {
      this.nuevos = this.nuevos.filter((n) => n !== nuevo);
    },
    importeNuevo(nuevo) {
      return Math.round(centavos(nuevo.producto.precio_venta) * Number(nuevo.cantidad || 0)) - this.descuentoNuevo(nuevo);
    },
    get firmaNuevos() {
      return this.nuevos.map((n) => `${n.producto.id}:${Number(n.cantidad || 0)}`).join(",");
    },
    ofertaNuevo(nuevo) {
      const c = this.cotizacion && this.cotizacion.firma === this.firmaNuevos ? this.cotizacion : null;
      const i = this.nuevos.indexOf(nuevo);
      return c && i >= 0 && c.renglones[i] && Number(c.renglones[i].descuento) > 0 ? c.renglones[i] : null;
    },
    descuentoNuevo(nuevo) {
      const o = this.ofertaNuevo(nuevo);
      return o ? centavos(o.descuento) : 0;
    },
    programarCotizacion() {
      clearTimeout(this._cotizaTimer);
      if (!this.nuevos.length) return;
      this._cotizaTimer = setTimeout(() => this.cotizar(), 150);
    },
    async cotizar() {
      const firma = this.firmaNuevos;
      if (!this.nuevos.length || this.nuevos.some((n) => !(Number(n.cantidad) > 0))) return;
      try {
        const r = await API.post("/ventas/cotizar", {
          renglones: this.nuevos.map((n) => ({ producto_id: n.producto.id, cantidad: String(n.cantidad) })),
        });
        if (firma === this.firmaNuevos) this.cotizacion = { firma, renglones: r.renglones };
      } catch {
        // Sin cotización se muestran precios normales.
      }
    },

    // Todo en centavos.
    get totalNuevo() {
      return this.nuevos.reduce((s, n) => s + this.importeNuevo(n), 0);
    },
    get pagaCliente() {
      return Math.max(0, this.totalNuevo - this.totalARegresar);
    },
    get seLeRegresa() {
      return Math.max(0, this.totalARegresar - this.totalNuevo);
    },
    get tarjetaCentavos() {
      if (!this.pagaCliente) return 0;
      if (this.formaPago === "tarjeta") return this.pagaCliente;
      if (this.formaPago === "mixto") return Math.min(centavos(this.tarjeta), this.pagaCliente);
      return 0;
    },
    get efectivoCentavos() {
      return !this.pagaCliente || this.formaPago === "tarjeta" ? 0 : centavos(this.efectivo);
    },
    get faltaCentavos() {
      return Math.max(0, this.pagaCliente - this.tarjetaCentavos - this.efectivoCentavos);
    },
    get cambioCentavos() {
      return Math.max(0, this.efectivoCentavos - (this.pagaCliente - this.tarjetaCentavos));
    },

    elegirFormaPago(forma) {
      this.formaPago = forma;
      this.efectivo = "";
      this.tarjeta = "";
      const id = { efectivo: "cambio-efectivo", mixto: "cambio-tarjeta" }[forma];
      if (id) this.$nextTick(() => document.getElementById(id).focus());
    },
    efectivoExacto() {
      this.efectivo = ((this.pagaCliente - this.tarjetaCentavos) / 100).toFixed(2);
    },

    pedirConfirmacion() {
      if (!this.listo) return;
      this.confirmando = true;
      this.$nextTick(() => document.getElementById("boton-confirmar").focus());
    },

    async confirmar() {
      if (!this.listo) return;
      this.procesando = true;
      this.error = "";
      const reparto = this.reparto;
      try {
        let devolucion;
        if (this.pideAutorizacion) {
          const solicitud = await API.post(`/ventas/${this.venta.id}/solicitudes`, {
            caja_id: this.cajaId,
            tipo: this.modo === "cancelar" ? "cancelacion" : "devolucion",
            motivo: this.motivoFinal,
            piezas: this.modo === "cancelar" ? [] : this.piezasDevueltas(),
          });
          this.resultado = { tipo: "solicitud", folio: this.venta.folio, total: solicitud.total, cancelacion: this.modo === "cancelar" };
          this.confirmando = false;
          this.$nextTick(() => document.getElementById("boton-listo").focus());
          return;
        }
        if (this.modo === "cancelar") {
          devolucion = await API.post(`/ventas/${this.venta.id}/cancelar`, {
            caja_id: this.cajaId,
            motivo: this.motivoFinal,
          });
        } else if (this.modo === "cambiar") {
          const cambio = await API.post(`/ventas/${this.venta.id}/cambio`, {
            caja_id: this.cajaId,
            motivo: this.motivoFinal,
            devueltas: this.piezasDevueltas(),
            nuevos: this.nuevos.map((n) => ({ producto_id: n.producto.id, cantidad: String(n.cantidad) })),
            tarjeta: (this.tarjetaCentavos / 100).toFixed(2),
            // Sin diferencia que pagar no se manda efectivo (el servidor lo rechazaría).
            efectivo_recibido: ((this.tarjetaCentavos < this.pagaCliente ? this.efectivoCentavos : 0) / 100).toFixed(2),
          });
          const venta = cambio.venta;
          this.resultado = {
            tipo: "cambio",
            folio: this.venta.folio,
            folioNuevo: venta.folio,
            efectivo: (Number(cambio.se_le_regresa) + Number(venta.cambio)).toFixed(2),
            cobroTarjeta: venta.pagos.filter((p) => p.metodo === "tarjeta").reduce((s, p) => s + Number(p.monto), 0),
            avisos: venta.avisos || [],
            impresion: venta.impresion,
            ventaNuevaId: venta.id,
          };
          this.confirmando = false;
          this.$nextTick(() => document.getElementById("boton-listo").focus());
          return;
        } else {
          devolucion = await API.post(`/ventas/${this.venta.id}/devoluciones`, {
            caja_id: this.cajaId,
            motivo: this.motivoFinal,
            piezas: this.piezasDevueltas(),
          });
        }
        this.resultado = { ...devolucion, folio: this.venta.folio, estimado: reparto };
        this.confirmando = false;
        this.$nextTick(() => document.getElementById("boton-listo").focus());
      } catch (e) {
        this.error = e.message;
        this.confirmando = false;
      } finally {
        this.procesando = false;
      }
    },

    piezasDevueltas() {
      return this.piezasElegidas.map((r) => ({
        renglon_id: r.id,
        cantidad: String(this.cuantas(r)),
        lote_id: this.lotes[r.id] ? Number(this.lotes[r.id]) : null,
      }));
    },

    async reimprimir() {
      try {
        this.resultado.impresion = await API.post(`/ventas/${this.resultado.ventaNuevaId}/imprimir`, {});
      } catch (e) {
        this.resultado.impresion = { impreso: false, error: e.message };
      }
    },

    hora(fecha) {
      return new Date(fecha).toLocaleTimeString("es-MX", { hour: "numeric", minute: "2-digit" });
    },
    fechaHora(fecha) {
      return new Date(fecha).toLocaleString("es-MX", { dateStyle: "medium", timeStyle: "short" });
    },

    dinero,
    cantidad,
  };
}
