// Catálogo y precios (solo administradores).
//
// Pestaña Productos: búsqueda, filtros (para revisar, sin precio, sin
// categoría, desactivados, por categoría), lista de 50 en 50 con casillas
// para cambios en grupo (categoría, IVA, "ya revisado") y el editor de cada
// producto con precio sugerido por margen e historial de precios.
// Pestaña Categorías: nombre, margen y si maneja caducidad.
//
// El precio de venta incluye impuestos: IEPS sobre el precio sin impuestos e
// IVA sobre ese + IEPS, con el redondeo del negocio (igual que el servidor).

const FILTROS = [
  { id: "todos", texto: "Todos", params: {} },
  { id: "revisar", texto: "Para revisar", params: { solo_revision: true } },
  { id: "sin-precio", texto: "Sin precio", params: { sin_precio: true } },
  { id: "sin-categoria", texto: "Sin categoría", params: { sin_categoria: true } },
  { id: "inactivos", texto: "Desactivados", params: { solo_inactivos: true } },
];
const POR_PAGINA = 50;

function pantallaCatalogo() {
  return {
    usuario: null,
    negocio: null,
    cargando: true,
    error: "",
    aviso: "",
    _avisoTimer: null,
    pestana: "productos",

    // Lista
    filtros: FILTROS,
    filtro: "todos",
    categoriaFiltro: "",
    buscar: "",
    _temporizador: null,
    productos: [],
    total: 0,
    conteos: {},
    pagina: 0,
    cargandoLista: false,
    seleccion: [], // ids

    // Categorías
    categorias: [],
    edicionCategorias: {}, // id -> {nombre, margen, controla_lote}
    nuevaCategoria: "",

    // Editor
    editor: null, // copia editable del producto (id null = nuevo)
    original: null,
    historial: [],
    proveedoresDelProducto: [],
    margenEscrito: null, // lo que se está tecleando en Margen (mientras tiene el foco)
    guardando: false,
    errorEditor: "",

    // Cambios en grupo
    grupo: null, // "categoria" | "iva"
    ivaGrupo: null,
    aplicando: false,

    async init() {
      try {
        this.usuario = await API.get("/auth/yo");
        if (!this.esAdmin) return;
        this.negocio = await API.get("/negocio");
        await Promise.all([this.cargarCategorias(), this.cargarLista(), this.cargarConteos()]);
      } catch (e) {
        this.error = e.message;
      } finally {
        this.cargando = false;
      }
      window.addEventListener("keydown", (ev) => {
        if (ev.key !== "Escape") return;
        if (this.grupo) this.grupo = null;
        else if (this.editor) this.cerrarEditor();
      });
    },

    get esAdmin() {
      return this.usuario && this.usuario.rol === "admin";
    },

    avisar(texto) {
      this.aviso = texto;
      clearTimeout(this._avisoTimer);
      this._avisoTimer = setTimeout(() => (this.aviso = ""), 3500);
    },

    // --- Lista de productos ------------------------------------------------

    parametros(extra = {}) {
      const f = FILTROS.find((x) => x.id === this.filtro);
      const p = { ...f.params, ...extra };
      if (this.categoriaFiltro) p.categoria_id = this.categoriaFiltro;
      if (this.buscar.trim()) p.q = this.buscar.trim();
      return new URLSearchParams(p).toString();
    },

    async cargarLista() {
      this.cargandoLista = true;
      try {
        const [lista, conteo] = await Promise.all([
          API.get(`/productos?${this.parametros({ limite: POR_PAGINA, desplazamiento: this.pagina * POR_PAGINA })}`),
          API.get(`/productos/contar?${this.parametros()}`),
        ]);
        this.productos = lista;
        this.total = conteo.total;
        this.error = "";
      } catch (e) {
        this.error = e.message;
      } finally {
        this.cargandoLista = false;
      }
    },

    // Cuántos hay en cada filtro (los números de los botones).
    async cargarConteos() {
      const pares = await Promise.all(
        FILTROS.map(async (f) => [f.id, (await API.get(`/productos/contar?${new URLSearchParams(f.params)}`)).total])
      );
      this.conteos = Object.fromEntries(pares);
    },

    elegirFiltro(id) {
      this.filtro = id;
      this.pagina = 0;
      this.seleccion = [];
      this.cargarLista();
    },
    elegirCategoriaFiltro() {
      this.pagina = 0;
      this.seleccion = [];
      this.cargarLista();
    },
    alBuscar() {
      clearTimeout(this._temporizador);
      this._temporizador = setTimeout(() => {
        this.pagina = 0;
        this.cargarLista();
      }, 250);
    },
    irPagina(paso) {
      this.pagina = Math.max(0, this.pagina + paso);
      this.cargarLista();
      window.scrollTo(0, 0);
    },
    get paginas() {
      return Math.max(1, Math.ceil(this.total / POR_PAGINA));
    },
    get rango() {
      if (!this.total) return "0";
      const desde = this.pagina * POR_PAGINA + 1;
      return `${desde.toLocaleString("es-MX")}–${Math.min(this.total, desde + POR_PAGINA - 1).toLocaleString("es-MX")} de ${this.total.toLocaleString("es-MX")}`;
    },

    nombreCategoria(id) {
      const c = this.categorias.find((x) => x.id === id);
      return c ? c.nombre : "";
    },

    // --- Selección y cambios en grupo ----------------------------------------

    seleccionado(p) {
      return this.seleccion.includes(p.id);
    },
    alternar(p) {
      this.seleccion = this.seleccionado(p) ? this.seleccion.filter((id) => id !== p.id) : [...this.seleccion, p.id];
    },
    get todaLaPagina() {
      return this.productos.length > 0 && this.productos.every((p) => this.seleccionado(p));
    },
    alternarPagina() {
      const ids = this.productos.map((p) => p.id);
      this.seleccion = this.todaLaPagina
        ? this.seleccion.filter((id) => !ids.includes(id))
        : [...new Set([...this.seleccion, ...ids])];
    },

    abrirGrupo(tipo, iva = null) {
      this.grupo = tipo;
      this.ivaGrupo = iva;
    },

    // Ejemplo para la pregunta del IVA: el primer seleccionado con precio.
    get ejemploIva() {
      const p = this.productos.find((x) => this.seleccionado(x) && x.precio_venta !== null && Number(x.iva_porcentaje) !== this.ivaGrupo);
      if (!p) return null;
      const base = Number(p.precio_venta) / ((1 + Number(p.ieps_porcentaje) / 100) * (1 + Number(p.iva_porcentaje) / 100));
      const nuevo = redondearPrecio(
        Math.round(base * (1 + Number(p.ieps_porcentaje) / 100) * (1 + this.ivaGrupo / 100) * 100) / 100,
        this.paso, p.precio_maximo_publico ? Number(p.precio_maximo_publico) : null,
      );
      return { nombre: p.nombre, antes: Number(p.precio_venta), ajustado: nuevo };
    },

    async aplicarGrupo(cambio) {
      this.aplicando = true;
      this.error = "";
      try {
        const r = await API.post("/productos/en-grupo", { ids: this.seleccion, ...cambio });
        this.avisar(`Listo: se cambiaron ${r.productos} productos.`);
        this.seleccion = [];
        this.grupo = null;
        await Promise.all([this.cargarLista(), this.cargarConteos(), this.cargarCategorias()]);
      } catch (e) {
        this.error = e.message;
        this.grupo = null;
      } finally {
        this.aplicando = false;
      }
    },

    // --- Editor de producto ---------------------------------------------------

    get paso() {
      return this.negocio && this.negocio.redondeo_precio_venta ? Number(this.negocio.redondeo_precio_venta) : null;
    },

    async abrirEditor(p) {
      this.errorEditor = "";
      this.historial = [];
      this.proveedoresDelProducto = [];
      this.margenEscrito = null;
      const vacio = {
        id: null, nombre: "", clave: "", categoria_id: null, laboratorio: "", requiere_receta: false, no_caduca: false,
        costo: "", precio_venta: "", precio_maximo_publico: "", iva_porcentaje: 0, ieps_porcentaje: 0,
        minimo: "", maximo: "", requiere_revision: false, motivo_revision: null, activo: true,
      };
      const base = p ? { ...vacio, ...p } : vacio;
      // Números como texto para los campos; vacío = sin dato.
      for (const k of ["costo", "precio_venta", "precio_maximo_publico", "minimo", "maximo"]) {
        base[k] = base[k] === null || base[k] === undefined ? "" : String(Number(base[k]));
      }
      base.iva_porcentaje = Number(base.iva_porcentaje);
      base.ieps_porcentaje = Number(base.ieps_porcentaje);
      base.clave = base.clave || "";
      base.laboratorio = base.laboratorio || "";
      base.revisado = false;
      this.editor = base;
      this.original = { ...base };
      this.$nextTick(() => document.getElementById("editor-nombre").focus());
      if (p) {
        try {
          [this.historial, this.proveedoresDelProducto] = await Promise.all([
            API.get(`/productos/${p.id}/precios`),
            API.get(`/productos/${p.id}/proveedores`),
          ]);
        } catch {
          /* sin historial */
        }
      }
    },

    cerrarEditor() {
      this.editor = null;
    },

    // Margen de la categoría para el costo del editor (puede depender del costo).
    get margenCategoria() {
      const c = this.categorias.find((x) => x.id === this.editor.categoria_id);
      return margenPara(c, this.editor.costo === "" ? null : Number(this.editor.costo));
    },
    precioCon(base) {
      const e = this.editor;
      const bruto = Math.round(base * (1 + e.ieps_porcentaje / 100) * (1 + e.iva_porcentaje / 100) * 100) / 100;
      return redondearPrecio(bruto, this.paso, e.precio_maximo_publico ? Number(e.precio_maximo_publico) : null);
    },
    // Costo + margen de la categoría + impuestos, redondeado.
    get sugerido() {
      const e = this.editor;
      if (!e || e.costo === "" || this.margenCategoria === null) return null;
      return this.precioCon(Number(e.costo) * (1 + this.margenCategoria / 100));
    },
    // Si cambió el IVA/IEPS: el precio que deja igual el precio sin impuestos.
    get precioMismoSinImpuestos() {
      const e = this.editor;
      const o = this.original;
      if (!e || e.precio_venta === "" || !o || o.precio_venta === "") return null;
      if (e.iva_porcentaje === o.iva_porcentaje && e.ieps_porcentaje === o.ieps_porcentaje) return null;
      const base = Number(o.precio_venta) / ((1 + o.ieps_porcentaje / 100) * (1 + o.iva_porcentaje / 100));
      const nuevo = this.precioCon(base);
      return nuevo === Number(e.precio_venta) ? null : nuevo;
    },
    get pasaDelMaximo() {
      const e = this.editor;
      return e && e.precio_venta !== "" && e.precio_maximo_publico !== "" && Number(e.precio_venta) > Number(e.precio_maximo_publico);
    },
    // Margen puesto a mano: calcula el precio de venta con costo + margen + impuestos.
    ponerMargen(valor) {
      this.margenEscrito = valor;
      const costo = Number(this.editor.costo);
      if (valor === "" || !costo) return;
      this.editor.precio_venta = String(this.precioCon(costo * (1 + Number(valor) / 100)));
    },
    get margenReal() {
      const e = this.editor;
      if (!e || e.costo === "" || !Number(e.costo) || e.precio_venta === "") return null;
      const base = Number(e.precio_venta) / ((1 + e.ieps_porcentaje / 100) * (1 + e.iva_porcentaje / 100));
      return Math.round((base / Number(e.costo) - 1) * 1000) / 10;
    },

    async guardarProducto() {
      const e = this.editor;
      if (!e.nombre.trim()) return (this.errorEditor = "El producto necesita un nombre.");
      const num = (v) => (v === "" || v === null ? null : String(v));
      const datos = {
        nombre: e.nombre.trim(),
        clave: e.clave.trim() || null,
        categoria_id: e.categoria_id,
        laboratorio: e.laboratorio.trim() || null,
        requiere_receta: e.requiere_receta,
        no_caduca: e.no_caduca,
        costo: num(e.costo),
        precio_venta: num(e.precio_venta),
        precio_maximo_publico: num(e.precio_maximo_publico),
        iva_porcentaje: String(e.iva_porcentaje),
        ieps_porcentaje: String(e.ieps_porcentaje),
        minimo: num(e.minimo),
        maximo: num(e.maximo),
      };
      if (e.revisado) {
        datos.requiere_revision = false;
        datos.motivo_revision = null;
      }
      this.guardando = true;
      this.errorEditor = "";
      try {
        const r = e.id ? await API.put(`/productos/${e.id}`, datos) : await API.post("/productos", datos);
        this.avisar(`Listo: se guardó ${r.nombre}${r.precio_venta !== null ? ` a ${dinero(r.precio_venta)}` : ""}.`);
        this.editor = null;
        await Promise.all([this.cargarLista(), this.cargarConteos(), this.cargarCategorias()]);
      } catch (err) {
        this.errorEditor = err.message;
      } finally {
        this.guardando = false;
      }
    },

    async alternarActivo() {
      const e = this.editor;
      this.guardando = true;
      try {
        if (e.activo) await API.borrar(`/productos/${e.id}`);
        else await API.put(`/productos/${e.id}`, { activo: true });
        this.avisar(e.activo ? `${e.nombre} quedó desactivado: ya no se puede vender.` : `${e.nombre} está activo otra vez.`);
        this.editor = null;
        await Promise.all([this.cargarLista(), this.cargarConteos(), this.cargarCategorias()]);
      } catch (err) {
        this.errorEditor = err.message;
      } finally {
        this.guardando = false;
      }
    },

    // --- Categorías -----------------------------------------------------------

    async cargarCategorias() {
      this.categorias = await API.get("/categorias");
      this.edicionCategorias = Object.fromEntries(this.categorias.map((c) => [c.id, {
        nombre: c.nombre,
        margen: c.margen_porcentaje === null ? "" : String(Number(c.margen_porcentaje)),
        limite: c.limite_costo === null ? "" : String(Number(c.limite_costo)),
        margen_arriba: c.margen_arriba_limite === null ? "" : String(Number(c.margen_arriba_limite)),
        controla_lote: c.controla_lote,
      }]));
    },
    cambioCategoria(c) {
      const e = this.edicionCategorias[c.id];
      if (!e) return false;
      const texto = (v) => (v === null ? "" : String(Number(v)));
      return e.nombre.trim() !== c.nombre || e.margen !== texto(c.margen_porcentaje) || e.controla_lote !== c.controla_lote ||
        e.limite !== texto(c.limite_costo) || e.margen_arriba !== texto(c.margen_arriba_limite);
    },
    async guardarCategoria(c) {
      const e = this.edicionCategorias[c.id];
      if (!e.nombre.trim()) return (this.error = "La categoría necesita un nombre.");
      if ((e.limite === "") !== (e.margen_arriba === "")) {
        return (this.error = "Para el margen de costo alto pon las dos cosas: desde qué costo y qué margen, o deja las dos vacías.");
      }
      try {
        await API.put(`/categorias/${c.id}`, {
          nombre: e.nombre.trim(),
          margen_porcentaje: e.margen === "" ? null : String(e.margen),
          limite_costo: e.limite === "" ? null : String(e.limite),
          margen_arriba_limite: e.margen_arriba === "" ? null : String(e.margen_arriba),
          controla_lote: e.controla_lote,
        });
        this.avisar(`Listo: se guardó la categoría ${e.nombre.trim()}.`);
        this.error = "";
        await this.cargarCategorias();
      } catch (err) {
        this.error = err.message;
      }
    },
    async crearCategoria() {
      const nombre = this.nuevaCategoria.trim();
      if (!nombre) return;
      try {
        await API.post("/categorias", { nombre });
        this.nuevaCategoria = "";
        this.avisar(`Listo: se creó la categoría ${nombre}.`);
        await this.cargarCategorias();
      } catch (err) {
        this.error = err.message;
      }
    },
    verProductosDe(c) {
      this.pestana = "productos";
      this.filtro = "todos";
      this.categoriaFiltro = String(c.id);
      this.buscar = "";
      this.pagina = 0;
      this.cargarLista();
    },

    fechaHora(fecha) {
      return new Date(fecha).toLocaleString("es-MX", { dateStyle: "medium", timeStyle: "short" });
    },

    dinero,
    cantidad,
  };
}
