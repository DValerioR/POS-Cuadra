// Pantalla de venta en mostrador.
//
// Flujo: escanear (o buscar por nombre con F2) -> agregar al carrito ->
// indicar el lote real si se entregó otro -> Esc para pasar al cobro ->
// Enter cobra -> ticket.
//
// Modos del teclado, pensados para no tener que usar el ratón:
//  - Escaneo (normal): todo lo que se teclea cae en el campo de código de
//    barras aunque no tenga el cursor; Enter agrega el producto.
//  - Búsqueda por nombre (F2): ventana con la lista; flechas + Enter agregan,
//    Esc la cierra.
//  - Cobro (Esc con productos): el cursor va a "¿Con cuánto paga?"; Enter
//    cobra, Esc regresa a escanear.
// F12 cobra desde cualquier modo.

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

    // Escaneo y búsqueda por nombre
    codigo: "",
    buscandoNombre: false,
    modoCobro: false,
    busqueda: "",
    resultados: [],
    elegido: 0,
    _temporizador: null,
    _consulta: 0,

    // Carrito y cobro
    carrito: [],
    formaPago: "efectivo", // efectivo | tarjeta | mixto
    efectivo: "",
    tarjeta: "", // solo se captura en pago mixto
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
      this.$nextTick(() => this.enfocarCodigo());
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
        this.$nextTick(() => this.enfocarCodigo());
      } catch (e) {
        this.error = e.message;
      }
    },

    // --- Escaneo por código de barras -----------------------------------

    enfocarCodigo() {
      this.modoCobro = false;
      const campo = document.getElementById("codigo");
      if (campo) campo.focus();
    },

    async escanear() {
      const texto = this.codigo.trim();
      if (!texto) return;
      this.error = "";
      try {
        const lista = await API.get(`/productos?solo_activos=true&limite=2&clave=${encodeURIComponent(texto)}`);
        if (lista.length) {
          await this.agregar(lista[0]);
        } else {
          this.error = `No hay ningún producto con el código ${texto}. Para buscarlo por nombre presiona F2.`;
        }
      } catch (e) {
        this.error = e.message;
      }
      this.codigo = "";
    },

    // --- Búsqueda por nombre (F2) ----------------------------------------

    abrirBusqueda() {
      this.modoCobro = false;
      this.buscandoNombre = true;
      this.busqueda = "";
      this.resultados = [];
      this.$nextTick(() => document.getElementById("busqueda").focus());
    },

    cerrarBusqueda() {
      this.buscandoNombre = false;
      this.busqueda = "";
      this.resultados = [];
      this.$nextTick(() => this.enfocarCodigo());
    },

    alEscribir() {
      clearTimeout(this._temporizador);
      const texto = this.busqueda.trim();
      if (texto.length < 2) {
        this.resultados = [];
        return;
      }
      this._temporizador = setTimeout(async () => {
        const numero = ++this._consulta;
        try {
          const lista = await API.get(`/productos?solo_activos=true&limite=30&q=${encodeURIComponent(texto)}`);
          if (numero !== this._consulta) return; // ignorar respuestas viejas
          this.resultados = lista;
          this.elegido = 0;
        } catch (e) {
          this.error = e.message;
        }
      }, 180);
    },

    async elegirResultado() {
      const producto = this.resultados[this.elegido];
      if (producto) await this.agregarDesdeBusqueda(producto);
    },

    async agregarDesdeBusqueda(producto) {
      if (await this.agregar(producto)) this.cerrarBusqueda();
    },

    mover(paso) {
      if (!this.resultados.length) return;
      this.elegido = (this.elegido + paso + this.resultados.length) % this.resultados.length;
      this.$nextTick(() => {
        const fila = document.querySelector(".busqueda-nombre .resultado.elegido");
        if (fila) fila.scrollIntoView({ block: "nearest" });
      });
    },

    // --- Carrito --------------------------------------------------------

    async agregar(producto) {
      this.error = "";
      if (producto.precio_venta === null) {
        this.error = `${producto.nombre} no tiene precio de venta; pide al administrador que lo capture.`;
        return false;
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
          return false;
        }
      }
      return true;
    },

    cambiarCantidad(renglon, paso) {
      renglon.cantidad = Math.max(1, Number(renglon.cantidad || 0) + paso);
    },

    quitar(renglon) {
      this.carrito = this.carrito.filter((r) => r !== renglon);
      if (!this.carrito.length) this.enfocarCodigo();
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
    get articulos() {
      return this.carrito.reduce((suma, r) => suma + Number(r.cantidad || 0), 0);
    },
    // Con "Tarjeta" todo va a tarjeta aunque el total cambie después de elegirla.
    get tarjetaCentavos() {
      if (this.formaPago === "tarjeta") return this.totalCentavos;
      if (this.formaPago === "mixto") return centavos(this.tarjeta);
      return 0;
    },
    get efectivoCentavos() {
      return this.formaPago === "tarjeta" ? 0 : centavos(this.efectivo);
    },
    get efectivoNecesarioCentavos() {
      return Math.max(0, this.totalCentavos - this.tarjetaCentavos);
    },
    get faltaCentavos() {
      return Math.max(0, this.efectivoNecesarioCentavos - this.efectivoCentavos);
    },
    get cambioCentavos() {
      return Math.max(0, this.efectivoCentavos - this.efectivoNecesarioCentavos);
    },
    get listoParaCobrar() {
      return (
        this.carrito.length > 0 &&
        !this.ultimaVenta && // ya cobrada: el Enter de "Siguiente venta" no debe cobrarla otra vez
        !this.cobrando &&
        this.faltaCentavos === 0 &&
        this.tarjetaCentavos <= this.totalCentavos &&
        this.carrito.every((r) => Number(r.cantidad) > 0)
      );
    },

    efectivoExacto() {
      this.efectivo = (this.efectivoNecesarioCentavos / 100).toFixed(2);
    },
    elegirFormaPago(forma) {
      this.formaPago = forma;
      this.efectivo = "";
      this.tarjeta = "";
      this.$nextTick(() => this.enfocarCobro());
    },

    // --- Modo cobro (Esc) -----------------------------------------------

    entrarCobro() {
      if (!this.carrito.length) return;
      this.modoCobro = true;
      // Sin esperar: el campo ya está a la vista y lo que se teclee enseguida
      // debe caer ahí, no en el código de barras.
      this.enfocarCobro();
    },

    // El cursor va a lo primero que hay que capturar según la forma de pago;
    // con tarjeta no hay nada que escribir y se enfoca el botón Cobrar.
    enfocarCobro() {
      const id = { efectivo: "campo-efectivo", mixto: "campo-tarjeta", tarjeta: "boton-cobrar" }[this.formaPago];
      const campo = document.getElementById(id);
      if (campo) campo.focus();
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
          tarjeta: (this.tarjetaCentavos / 100).toFixed(2),
          efectivo_recibido: (this.efectivoCentavos / 100).toFixed(2),
        });
        this.ultimaVenta = venta;
        // Que el cursor no se quede en "¿Con cuánto paga?": su Enter cobraría de nuevo.
        if (document.activeElement) document.activeElement.blur();
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
      this.formaPago = "efectivo";
      this.efectivo = "";
      this.tarjeta = "";
      this.error = "";
      this.codigo = "";
      this.$nextTick(() => this.enfocarCodigo());
    },

    cancelarVenta() {
      if (!confirm("¿Borrar todos los productos de esta venta?")) return;
      this.nuevaVenta();
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
      if (!this.turno) return;

      if (ev.key === "F2") {
        ev.preventDefault();
        this.abrirBusqueda();
      } else if (ev.key === "F12") {
        ev.preventDefault();
        this.cobrar();
      } else if (ev.key === "Escape") {
        ev.preventDefault();
        if (this.buscandoNombre) this.cerrarBusqueda();
        else if (this.modoCobro) this.enfocarCodigo();
        else if (this.codigo) this.codigo = "";
        else this.entrarCobro();
      } else if (this.esLetra(ev) && this.buscandoNombre && ev.target.id !== "busqueda") {
        // Se empezó a escribir antes de que la ventana de búsqueda tomara el cursor.
        ev.preventDefault();
        this.busqueda += ev.key;
        this.alEscribir();
        document.getElementById("busqueda").focus();
      } else if (this.esLetra(ev) && !this.buscandoNombre && !this.modoCobro && !this.enCampo(ev)) {
        // Se tecleó (o escaneó) sin tener el cursor en ningún campo: va al código.
        ev.preventDefault();
        this.codigo += ev.key;
        this.enfocarCodigo();
      }
    },

    esLetra(ev) {
      return ev.key.length === 1 && !ev.ctrlKey && !ev.altKey && !ev.metaKey;
    },

    enCampo(ev) {
      const destino = ev.target;
      return destino instanceof HTMLInputElement || destino instanceof HTMLTextAreaElement || destino instanceof HTMLSelectElement;
    },

    dinero,
    cantidad,
    mesAnio,
  };
}
