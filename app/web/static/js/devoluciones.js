// Pantalla de devoluciones y cancelaciones (solo administrador).
//
// Flujo: buscar la venta por el folio del ticket (o elegirla de las de hoy)
// -> "Devolver algunos productos" o "Cancelar toda la venta" -> motivo ->
// confirmar -> se le dice al vendedor cuánto dinero entregar y por qué medio.
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
    modo: null, // "devolver" | "cancelar"
    piezas: {}, // renglon_id -> cantidad que regresa
    lotes: {}, // renglon_id -> lote_id de la caja devuelta ("" = no se sabe)
    motivo: "",
    motivoOtro: "",
    confirmando: false,
    procesando: false,
    resultado: null,

    motivos: MOTIVOS,

    async init() {
      try {
        this.usuario = await API.get("/auth/yo");
        if (!this.esAdmin) return;
        if (this.cajaId) {
          const caja = (await API.get("/cajas")).find((c) => c.id === this.cajaId);
          this.cajaNombre = caja ? caja.nombre : "";
          this.turno = caja ? await API.get(`/turnos/abierto?caja_id=${this.cajaId}`) : null;
        }
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
    textoTipo(tipo) {
      return { cancelacion: "Cancelación", devolucion: "Devolución", cambio: "Cambio de producto" }[tipo] || tipo;
    },

    // --- Devolver algunas piezas --------------------------------------------

    elegirModo(modo) {
      this.modo = modo;
      this.error = "";
      if (modo === "devolver") {
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

    get piezasElegidas() {
      return this.venta.renglones.filter((r) => this.cuantas(r) > 0);
    },
    // Lo que se regresa, en centavos.
    get totalARegresar() {
      if (this.modo === "cancelar") return this.porRegresar;
      const suma = this.piezasElegidas.reduce(
        (s, r) => s + Math.round(centavos(r.precio_unitario) * this.cuantas(r)),
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
      return this.modo === "cancelar" || this.piezasElegidas.length > 0;
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
        if (this.modo === "cancelar") {
          devolucion = await API.post(`/ventas/${this.venta.id}/cancelar`, {
            caja_id: this.cajaId,
            motivo: this.motivoFinal,
          });
        } else {
          devolucion = await API.post(`/ventas/${this.venta.id}/devoluciones`, {
            caja_id: this.cajaId,
            motivo: this.motivoFinal,
            piezas: this.piezasElegidas.map((r) => ({
              renglon_id: r.id,
              cantidad: String(this.cuantas(r)),
              lote_id: this.lotes[r.id] ? Number(this.lotes[r.id]) : null,
            })),
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
