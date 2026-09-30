// Pantalla de inventario (administrador y bodega).
//
// Arriba se busca el producto (escanear o escribir el nombre; F2 lleva al
// buscador). Sin producto elegido se ven dos pestañas:
//  - Avance: cuántas piezas ya tienen caducidad capturada y cuáles faltan
//    (las de más piezas primero).
//  - Por caducar: lotes ya caducados y los que caducan pronto, para moverlos
//    o devolverlos al proveedor, o darlos de baja como merma.
// Con un producto elegido se ve su ficha: lotes, y las acciones Capturar
// caducidad, Contar y Merma, más el historial de movimientos.

const MOTIVOS_MERMA = ["Caducado", "Dañado", "Extravío"];
const TIPOS_MOVIMIENTO = {
  importacion: "Importación",
  ajuste: "Ajuste",
  merma: "Merma",
  captura_caducidad: "Captura de caducidad",
};

function pantallaInventario() {
  return {
    usuario: null,
    cargando: true,
    error: "",
    aviso: "",
    _avisoTimer: null,

    // Búsqueda
    buscar: "",
    encontrados: [],
    elegido: 0,
    _buscado: "",
    _temporizador: null,
    _consulta: 0,

    // Sin producto: pestañas
    pestana: new URLSearchParams(location.search).get("vista") === "por-caducar" ? "caducar" : "avance",
    avance: null,
    pendientes: [],
    cargandoMas: false,
    meses: 6,
    porCaducar: [],

    // Ficha del producto
    producto: null, // respuesta de /inventario/productos/{id}
    movimientos: [],

    // Ventanas: "capturar" | "contar" | "merma"
    ventana: null,
    guardando: false,
    errorVentana: "",
    captura: { mes: "", lote: "", cantidad: 1 },
    conteo: "",
    merma: { loteId: null, cantidad: 1, motivo: "", otro: "" },
    motivosMerma: MOTIVOS_MERMA,

    async init() {
      try {
        this.usuario = await API.get("/auth/yo");
        if (this.puedeUsar) await Promise.all([this.cargarAvance(), this.cargarPorCaducar()]);
      } catch (e) {
        this.error = e.message;
      } finally {
        this.cargando = false;
        this.$nextTick(() => this.enfocarBuscador());
      }
      window.addEventListener("keydown", (ev) => this.atajo(ev));
    },

    get puedeUsar() {
      return this.usuario && (this.usuario.rol === "admin" || this.usuario.rol === "bodega");
    },

    atajo(ev) {
      if (ev.key === "F2") {
        ev.preventDefault();
        this.enfocarBuscador();
      } else if (ev.key === "Escape") {
        if (this.ventana) this.cerrarVentana();
        else if (this.encontrados.length) this.encontrados = [];
        else if (this.producto) this.cerrarProducto();
      }
    },

    enfocarBuscador() {
      const campo = document.getElementById("buscar-producto");
      if (campo) campo.focus();
    },

    avisar(texto) {
      this.aviso = texto;
      clearTimeout(this._avisoTimer);
      this._avisoTimer = setTimeout(() => (this.aviso = ""), 3500);
    },

    // --- Buscar ----------------------------------------------------------

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
          const lista = await API.get(`/productos?limite=20&q=${encodeURIComponent(texto)}`);
          if (numero !== this._consulta) return;
          this.encontrados = lista;
          this._buscado = texto;
          this.elegido = 0;
        } catch (e) {
          this.error = e.message;
        }
      }, 180);
    },

    // Enter: código de barras exacto, o el elegido de la lista.
    async alPresionarEnter() {
      const texto = this.buscar.trim();
      if (!texto) return;
      clearTimeout(this._temporizador);
      this.error = "";
      try {
        const porClave = await API.get(`/productos?limite=2&clave=${encodeURIComponent(texto)}`);
        if (!porClave.length && this._buscado !== texto) {
          ++this._consulta;
          this.encontrados = await API.get(`/productos?limite=20&q=${encodeURIComponent(texto)}`);
          this._buscado = texto;
          this.elegido = 0;
        }
        const producto = porClave[0] || this.encontrados[this.elegido];
        if (producto) await this.abrir(producto.id);
        else this.error = `No se encontró "${texto}".`;
      } catch (e) {
        this.error = e.message;
      }
    },

    moverLista(paso) {
      if (!this.encontrados.length) return;
      this.elegido = (this.elegido + paso + this.encontrados.length) % this.encontrados.length;
    },

    // --- Avance y por caducar ----------------------------------------------

    async cargarAvance() {
      this.avance = await API.get("/inventario/avance-caducidades?limite=50");
      this.pendientes = this.avance.productos;
    },

    async cargarMas() {
      this.cargandoMas = true;
      try {
        const mas = await API.get(`/inventario/avance-caducidades?limite=50&desplazamiento=${this.pendientes.length}`);
        this.pendientes = this.pendientes.concat(mas.productos);
      } catch (e) {
        this.error = e.message;
      } finally {
        this.cargandoMas = false;
      }
    },

    async cargarPorCaducar() {
      this.porCaducar = await API.get(`/inventario/por-caducar?meses=${this.meses}`);
    },

    async cambiarMeses(meses) {
      this.meses = meses;
      try {
        await this.cargarPorCaducar();
      } catch (e) {
        this.error = e.message;
      }
    },

    // Lo urgente: caducado o que caduca en menos de 3 meses (el número rojo de la pestaña).
    get urgentesPorCaducar() {
      return this.porCaducar.filter((l) => l.dias < 90).length;
    },

    get gruposPorCaducar() {
      const grupos = [
        { id: "caducado", titulo: "Ya caducaron", lotes: [] },
        { id: "pronto", titulo: "Caducan en menos de 3 meses", lotes: [] },
        { id: "despues", titulo: "Caducan en 3 meses o más", lotes: [] },
      ];
      for (const l of this.porCaducar) grupos[this.nivelCaducidad(l.dias) === "caducado" ? 0 : l.dias < 90 ? 1 : 2].lotes.push(l);
      return grupos.filter((g) => g.lotes.length);
    },

    // Color según qué tan cerca está: caducado, menos de 3 meses, menos de 6.
    nivelCaducidad(dias) {
      if (dias === null || dias === undefined) return "";
      if (dias < 0) return "caducado";
      if (dias < 90) return "pronto";
      if (dias < 180) return "medio";
      return "";
    },
    diasDe(caducidad) {
      if (!caducidad) return null;
      const hoy = new Date();
      hoy.setHours(0, 0, 0, 0);
      return Math.round((new Date(`${caducidad}T00:00:00`) - hoy) / 86400000);
    },
    textoDias(dias) {
      if (dias < 0) return dias === -1 ? "caducó ayer" : `caducó hace ${-dias} días`;
      if (dias === 0) return "caduca hoy";
      if (dias < 60) return `en ${dias} días`;
      return `en ${Math.round(dias / 30)} meses`;
    },

    // --- Ficha del producto ------------------------------------------------

    async abrir(productoId) {
      this.error = "";
      try {
        const [producto, movimientos] = await Promise.all([
          API.get(`/inventario/productos/${productoId}`),
          API.get(`/inventario/productos/${productoId}/movimientos`),
        ]);
        this.producto = producto;
        this.movimientos = movimientos;
        this.buscar = "";
        this.encontrados = [];
        window.scrollTo(0, 0);
      } catch (e) {
        this.error = e.message;
      }
    },

    async recargarProducto() {
      await this.abrir(this.producto.producto_id);
      // El avance y la lista de por caducar cambian con cada movimiento.
      Promise.all([this.cargarAvance(), this.cargarPorCaducar()]).catch(() => {});
    },

    cerrarProducto() {
      this.producto = null;
      this.movimientos = [];
      this.$nextTick(() => this.enfocarBuscador());
    },

    get negativa() {
      return this.producto && Number(this.producto.existencia_registrada) < 0;
    },
    get puedeCapturar() {
      return this.producto && this.producto.controla_lote && Number(this.producto.sin_caducidad) > 0;
    },
    textoLote(l) {
      if (!l.caducidad && !l.numero_lote) return this.producto && this.producto.no_caduca ? "No caduca" : "Sin caducidad registrada";
      return l.numero_lote ? `Lote ${l.numero_lote}` : "Sin número de lote";
    },
    textoTipo(tipo) {
      return TIPOS_MOVIMIENTO[tipo] || tipo;
    },
    fechaHora(fecha) {
      return new Date(fecha).toLocaleString("es-MX", { dateStyle: "medium", timeStyle: "short" });
    },
    piezas(n) {
      return Number(n) === 1 ? "1 pieza" : `${cantidad(n)} piezas`;
    },
    conSigno(valor) {
      const n = Number(valor);
      return (n > 0 ? "+" : "") + cantidad(n);
    },

    // --- Ventanas -----------------------------------------------------------

    abrirVentana(tipo, lote = null) {
      this.errorVentana = "";
      this.ventana = tipo;
      if (tipo === "capturar") {
        this.captura = { mes: "", lote: "", cantidad: Math.min(1, Number(this.producto.sin_caducidad)) || 1 };
      } else if (tipo === "contar") {
        this.conteo = "";
      } else if (tipo === "merma") {
        const lotes = this.producto.lotes;
        const elegido = lote || (lotes.length === 1 ? lotes[0] : null);
        const caducado = elegido && elegido.caducidad && this.diasDe(elegido.caducidad) < 0;
        this.merma = {
          loteId: elegido ? elegido.id : null,
          cantidad: elegido && caducado ? Number(elegido.cantidad) : 1,
          motivo: caducado ? "Caducado" : "",
          otro: "",
        };
      }
      const foco = { capturar: "captura-mes", contar: "conteo-total", merma: "merma-cantidad" }[tipo];
      this.$nextTick(() => document.getElementById(foco) && document.getElementById(foco).focus());
    },

    cerrarVentana() {
      this.ventana = null;
    },

    // Desde "Por caducar": abre la ficha y la merma de ese lote.
    async bajaDeLote(l) {
      await this.abrir(l.producto_id);
      const lote = this.producto && this.producto.lotes.find((x) => x.id === l.lote_id);
      if (lote) this.abrirVentana("merma", lote);
    },

    // "2027-03" -> "2027-03-31": las cajas traen mes y año.
    ultimoDiaDelMes(mes) {
      const [anio, m] = mes.split("-").map(Number);
      return `${mes}-${String(new Date(anio, m, 0).getDate()).padStart(2, "0")}`;
    },

    async guardarCaptura() {
      const c = this.captura;
      if (!c.mes) return (this.errorVentana = "Escribe el mes y año de caducidad que trae la caja.");
      if (!(Number(c.cantidad) > 0)) return (this.errorVentana = "¿Cuántas piezas son de esa caducidad?");
      await this.guardar(async () => {
        await API.post("/inventario/captura-caducidad", {
          producto_id: this.producto.producto_id,
          caducidad: this.ultimoDiaDelMes(c.mes),
          cantidad: String(c.cantidad),
          numero_lote: c.lote.trim() || null,
        });
        return `Listo: ${cantidad(c.cantidad)} piezas con caducidad ${mesAnio(this.ultimoDiaDelMes(c.mes))}.`;
      });
    },

    // "No caduca": ya no se le pide caducidad y sale del avance.
    async marcarNoCaduca(valor) {
      await this.guardar(async () => {
        await API.put(`/inventario/productos/${this.producto.producto_id}/no-caduca`, { no_caduca: valor });
        return valor ? "Listo: quedó como no caduca y ya no cuenta en el avance." : "Listo: se le vuelve a pedir caducidad.";
      });
    },

    async guardarConteo() {
      if (this.conteo === "" || Number(this.conteo) < 0) return (this.errorVentana = "Escribe cuántas piezas hay en total.");
      await this.guardar(async () => {
        await API.post("/inventario/conteo", { producto_id: this.producto.producto_id, conteo: String(this.conteo) });
        return `Listo: la existencia quedó en ${cantidad(this.conteo)}.`;
      });
    },

    get loteMerma() {
      return this.producto ? this.producto.lotes.find((l) => l.id === this.merma.loteId) : null;
    },
    get motivoMerma() {
      return (this.merma.motivo === "otro" ? this.merma.otro : this.merma.motivo).trim();
    },

    async guardarMerma() {
      const m = this.merma;
      if (!this.loteMerma) return (this.errorVentana = "Elige de qué lote son las piezas.");
      if (!(Number(m.cantidad) > 0)) return (this.errorVentana = "¿Cuántas piezas salen?");
      if (Number(m.cantidad) > Number(this.loteMerma.cantidad)) {
        return (this.errorVentana = `Ese lote solo tiene ${cantidad(this.loteMerma.cantidad)} piezas.`);
      }
      if (!this.motivoMerma) return (this.errorVentana = "Elige el motivo.");
      await this.guardar(async () => {
        await API.post("/inventario/ajustes", {
          producto_id: this.producto.producto_id,
          tipo: "merma",
          cantidad: String(-Number(m.cantidad)),
          motivo: this.motivoMerma,
          lote_id: m.loteId,
        });
        return `Listo: salieron ${cantidad(m.cantidad)} piezas como merma (${this.motivoMerma.toLowerCase()}).`;
      });
    },

    async guardar(accion) {
      this.guardando = true;
      this.errorVentana = "";
      try {
        const texto = await accion();
        this.ventana = null;
        await this.recargarProducto();
        this.avisar(texto);
      } catch (e) {
        this.errorVentana = e.message;
      } finally {
        this.guardando = false;
      }
    },

    dinero,
    cantidad,
    mesAnio,
  };
}
