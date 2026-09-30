// Entradas de mercancía (administrador y bodega).
//
// Tres formas de empezar, que terminan en la misma revisión:
//  - Manual: se escanea o busca cada producto.
//  - Subir XML: el CFDI se lee exacto, sin IA.
//  - PDF o foto con IA: la IA propone los datos; lo dudoso va en amarillo.
// En la revisión se relaciona cada renglón con su producto (si ya se conoce,
// sale solo), se corrigen cantidades, piezas por unidad, costo, lote y
// caducidad, y el administrador decide si aplica el precio sugerido cuando
// cambió el costo. Nada entra al inventario hasta "Confirmar entrada".

function hoyTexto() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function pantallaEntradas() {
  return {
    usuario: null,
    negocio: null,
    ia: null,
    cargando: true,
    error: "",
    aviso: "",
    _avisoTimer: null,

    vista: "lista", // lista | nueva | revision | hecha
    recientes: [],
    pedidosAbiertos: [], // pedidos enviados del proveedor de la entrada
    pedidosDe: "", // de qué proveedor son
    proveedores: [],
    leyendo: null, // "xml" | "ia" mientras se lee el archivo
    resultado: null,

    // Borrador en revisión
    e: null,
    nuevoProveedor: null, // {nombre, rfc} mientras se da de alta
    guardando: false,

    // Buscar producto (agregar renglón o relacionar uno)
    buscador: null, // null | {renglon: índice o null para agregar}
    buscar: "",
    encontrados: [],
    elegido: 0,
    _temporizador: null,
    _consulta: 0,

    async init() {
      try {
        this.usuario = await API.get("/auth/yo");
        if (!this.puedeUsar) return;
        [this.negocio, this.ia, this.proveedores, this.recientes] = await Promise.all([
          API.get("/negocio"), API.get("/ia/estado"), API.get("/proveedores"), API.get("/entradas?limite=30"),
        ]);
      } catch (err) {
        this.error = err.message;
      } finally {
        this.cargando = false;
      }
      window.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape" && this.buscador) this.cerrarBuscador();
      });
    },

    get puedeUsar() {
      return this.usuario && (this.usuario.rol === "admin" || this.usuario.rol === "bodega");
    },
    get esAdmin() {
      return this.usuario && this.usuario.rol === "admin";
    },
    get paso() {
      return this.negocio && this.negocio.redondeo_precio_venta ? Number(this.negocio.redondeo_precio_venta) : null;
    },

    avisar(texto) {
      this.aviso = texto;
      clearTimeout(this._avisoTimer);
      this._avisoTimer = setTimeout(() => (this.aviso = ""), 4000);
    },

    // --- Empezar -------------------------------------------------------------

    nueva() {
      this.error = "";
      this.vista = "nueva";
    },

    empezarManual() {
      this.cargarBorrador({ origen: "manual", renglones: [] });
      this.$nextTick(() => this.abrirBuscador(null));
    },

    elegirArchivo(tipo) {
      this.error = "";
      const input = document.getElementById(tipo === "xml" ? "archivo-xml" : "archivo-ia");
      input.value = "";
      input.click();
    },

    async subir(tipo, ev) {
      const archivo = ev.target.files[0];
      if (!archivo) return;
      this.leyendo = tipo;
      this.error = "";
      try {
        const respuesta = await fetch(tipo === "xml" ? "/entradas/leer-xml" : "/entradas/leer-ia", {
          method: "POST",
          headers: { "Content-Type": archivo.type || "application/octet-stream", "X-Nombre-Archivo": encodeURIComponent(archivo.name) },
          body: archivo,
          credentials: "same-origin",
        });
        const datos = await respuesta.json().catch(() => null);
        if (!respuesta.ok) throw new Error(mensajeDeError(datos, respuesta.status));
        this.cargarBorrador(datos);
      } catch (err) {
        this.error = err.message;
      } finally {
        this.leyendo = null;
      }
    },

    cargarBorrador(b) {
      const aTexto = (v) => (v === null || v === undefined ? "" : String(Number(v)));
      this.pedidosDe = null; // que se vuelvan a buscar los pedidos del proveedor
      this.e = {
        origen: b.origen,
        archivo_id: b.archivo_id || null,
        archivo_nombre: b.archivo_nombre || null,
        proveedor_id: b.proveedor_id || "",
        pedido_id: "",
        proveedor_leido: b.proveedor_id ? null : (b.proveedor_nombre || b.proveedor_rfc ? { nombre: b.proveedor_nombre || "", rfc: b.proveedor_rfc || "" } : null),
        folio: b.folio || "",
        fecha_factura: b.fecha_factura || "",
        fecha_recepcion: hoyTexto(),
        subtotal_factura: b.subtotal !== null && b.subtotal !== undefined ? Number(b.subtotal) : null,
        total_factura: aTexto(b.total),
        dudas: b.dudas || [],
        renglones: (b.renglones || []).map((r) => this.renglonDesde(r)),
      };
      this.nuevoProveedor = null;
      this.vista = "revision";
      window.scrollTo(0, 0);
    },

    renglonDesde(r) {
      return {
        clave_ui: crypto.randomUUID ? crypto.randomUUID() : String(Math.random()),
        descripcion: r.descripcion || null,
        clave: r.clave || null,
        unidad: r.unidad || null,
        cantidad: r.cantidad !== null && r.cantidad !== undefined ? String(Number(r.cantidad)) : "",
        costo_unitario: r.costo_unitario !== null && r.costo_unitario !== undefined ? String(Number(r.costo_unitario)) : "",
        factor: String(Number(r.factor || 1)),
        numero_lote: r.numero_lote || "",
        caducidad_mes: r.caducidad ? r.caducidad.slice(0, 7) : "",
        iva_factura: r.iva !== null && r.iva !== undefined ? Number(r.iva) : null,
        dudoso: Boolean(r.dudoso),
        nota: r.nota || null,
        producto: r.producto || null,
        reconocido: r.reconocido || null,
        aplicar_precio: false,
      };
    },

    // --- Proveedor ---------------------------------------------------------

    abrirNuevoProveedor() {
      const leido = this.e.proveedor_leido;
      this.nuevoProveedor = { nombre: leido ? leido.nombre : "", rfc: leido ? leido.rfc : "" };
      this.$nextTick(() => document.getElementById("proveedor-nombre").focus());
    },

    // Pedidos enviados del proveedor elegido, para ligar la factura a uno
    // (se propone el más reciente). Lo llama un x-effect al cambiar de proveedor.
    async cargarPedidos(proveedorId) {
      if (String(proveedorId || "") === this.pedidosDe) return;
      this.pedidosDe = String(proveedorId || "");
      this.pedidosAbiertos = [];
      if (this.e) this.e.pedido_id = "";
      if (!proveedorId) return;
      try {
        const lista = await API.get(`/compras/pedidos?estado=enviado&proveedor_id=${proveedorId}`);
        if (this.pedidosDe !== String(proveedorId)) return;
        this.pedidosAbiertos = lista;
        if (this.e && lista.length) this.e.pedido_id = String(lista[0].id);
      } catch {
        /* sin pedidos: la entrada se registra igual */
      }
    },

    async guardarProveedor() {
      try {
        const p = await API.post("/proveedores", { nombre: this.nuevoProveedor.nombre, rfc: this.nuevoProveedor.rfc || null });
        this.proveedores = await API.get("/proveedores");
        this.e.proveedor_id = p.id;
        this.e.proveedor_leido = null;
        this.nuevoProveedor = null;
        this.avisar(`Listo: se dio de alta ${p.nombre}.`);
      } catch (err) {
        this.error = err.message;
      }
    },

    // --- Renglones -----------------------------------------------------------

    piezas(r) {
      const n = Number(r.cantidad) * Number(r.factor);
      return Number.isFinite(n) ? Math.round(n * 100) / 100 : 0;
    },
    costoPieza(r) {
      if (r.costo_unitario === "" || !(Number(r.factor) > 0)) return null;
      return Math.round((Number(r.costo_unitario) / Number(r.factor)) * 10000) / 10000;
    },
    importe(r) {
      return Math.round(Number(r.cantidad || 0) * Number(r.costo_unitario || 0) * 100) / 100;
    },
    cambioCosto(r) {
      const nuevo = this.costoPieza(r);
      if (!r.producto || nuevo === null || r.producto.costo === null) return null;
      const antes = Number(r.producto.costo);
      if (Math.abs(nuevo - antes) < 0.005) return null;
      return { antes, nuevo, porcentaje: antes ? Math.round(((nuevo - antes) / antes) * 1000) / 10 : null };
    },
    sugerido(r) {
      const p = r.producto;
      const costo = this.costoPieza(r);
      const margen = p ? margenPara({ margen_porcentaje: p.margen, limite_costo: p.limite_costo,
                                      margen_arriba_limite: p.margen_arriba_limite }, costo) : null;
      if (margen === null || costo === null) return null;
      return precioConImpuestos(costo * (1 + margen / 100), p.iva_porcentaje, p.ieps_porcentaje, this.paso,
        p.precio_maximo_publico ? Number(p.precio_maximo_publico) : null);
    },
    ivaDistinto(r) {
      return r.producto && r.iva_factura !== null && r.iva_factura !== Number(r.producto.iva_porcentaje);
    },
    sinCaducidad(r) {
      return r.producto && r.producto.controla_lote && !r.caducidad_mes;
    },
    // Marca el producto como "no caduca" (para este y los demás renglones del mismo producto).
    async marcarNoCaduca(r) {
      try {
        await API.put(`/inventario/productos/${r.producto.id}/no-caduca`, { no_caduca: true });
        for (const x of this.e.renglones) {
          if (x.producto && x.producto.id === r.producto.id) {
            x.producto.controla_lote = false;
            x.caducidad_mes = "";
          }
        }
      } catch (e) {
        this.error = e.message;
      }
    },
    quitar(i) {
      this.e.renglones.splice(i, 1);
    },

    get suma() {
      return this.e ? Math.round(this.e.renglones.reduce((s, r) => s + this.importe(r), 0) * 100) / 100 : 0;
    },
    get diferencia() {
      if (!this.e || this.e.subtotal_factura === null) return null;
      const d = Math.round((this.suma - this.e.subtotal_factura) * 100) / 100;
      return Math.abs(d) >= 1 ? d : null;
    },
    get faltantes() {
      if (!this.e) return [];
      const f = [];
      if (!this.e.proveedor_id) f.push("el proveedor");
      if (!this.e.folio.trim()) f.push("el folio");
      if (!this.e.fecha_recepcion) f.push("la fecha de recepción");
      if (!this.e.renglones.length) f.push("al menos un producto");
      const sinProducto = this.e.renglones.filter((r) => !r.producto).length;
      if (sinProducto) f.push(sinProducto === 1 ? "elegir el producto de 1 renglón" : `elegir el producto de ${sinProducto} renglones`);
      const incompletos = this.e.renglones.filter((r) => r.producto && (!(Number(r.cantidad) > 0) || r.costo_unitario === "" || !(Number(r.factor) > 0))).length;
      if (incompletos) f.push(`cantidad, piezas o costo en ${incompletos} renglón(es)`);
      return f;
    },
    get dudosos() {
      return this.e ? this.e.renglones.filter((r) => r.dudoso).length : 0;
    },

    // --- Buscar producto -------------------------------------------------------

    abrirBuscador(indice) {
      this.buscador = { renglon: indice };
      this.buscar = indice !== null && this.e.renglones[indice].descripcion ? this.e.renglones[indice].descripcion.split(" ").slice(0, 3).join(" ") : "";
      this.encontrados = [];
      this.$nextTick(() => {
        document.getElementById("buscar-producto").focus();
        if (this.buscar) this.alBuscar();
      });
    },
    cerrarBuscador() {
      this.buscador = null;
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
          if (numero !== this._consulta) return;
          this.encontrados = lista;
          this.elegido = 0;
        } catch (err) {
          this.error = err.message;
        }
      }, 180);
    },
    async alPresionarEnter() {
      const texto = this.buscar.trim();
      if (!texto) return;
      clearTimeout(this._temporizador);
      try {
        const porClave = await API.get(`/productos?solo_activos=true&limite=2&clave=${encodeURIComponent(texto)}`);
        const producto = porClave[0] || this.encontrados[this.elegido];
        if (producto) await this.elegirProducto(producto);
        else this.alBuscar();
      } catch (err) {
        this.error = err.message;
      }
    },
    moverLista(paso) {
      if (!this.encontrados.length) return;
      this.elegido = (this.elegido + paso + this.encontrados.length) % this.encontrados.length;
    },

    async elegirProducto(p) {
      try {
        const datos = await API.get(`/entradas/producto/${p.id}`);
        const indice = this.buscador.renglon;
        if (indice === null) {
          const r = this.renglonDesde({ producto: datos, factor: datos.factor_conversion, cantidad: 1,
            costo_unitario: datos.costo !== null ? Number(datos.costo) * Number(datos.factor_conversion || 1) : null });
          this.e.renglones.push(r);
          this.buscar = "";
          this.encontrados = [];
          this.$nextTick(() => document.getElementById("buscar-producto").focus());
          this.avisar(`Agregado: ${datos.nombre}. Escanea el siguiente o cierra con Esc.`);
        } else {
          const r = this.e.renglones[indice];
          r.producto = datos;
          r.reconocido = null;
          if (Number(r.factor) === 1 && Number(datos.factor_conversion) > 1) r.factor = String(Number(datos.factor_conversion));
          this.cerrarBuscador();
        }
      } catch (err) {
        this.error = err.message;
      }
    },

    // Producto que no existe: darlo de alta con lo que dice la factura
    // (solo admin), marcado para revisar categoría, IVA y precio.
    async darDeAlta(i) {
      const r = this.e.renglones[i];
      const clave = r.clave && /^\d{8,14}$/.test(r.clave) ? r.clave : null; // solo si parece código de barras
      try {
        const p = await API.post("/productos", {
          nombre: r.descripcion,
          clave,
          iva_porcentaje: String(r.iva_factura || 0),
          requiere_revision: true,
          motivo_revision: "dado de alta desde una entrada de mercancía; revisar nombre, categoría, IVA y precio",
        });
        r.producto = await API.get(`/entradas/producto/${p.id}`);
        r.reconocido = null;
        this.avisar(`Se dio de alta ${p.nombre}. Ponle categoría y precio en Productos y precios.`);
      } catch (err) {
        this.error = err.message;
      }
    },

    // --- Confirmar -------------------------------------------------------------

    ultimoDiaDelMes(mes) {
      const [anio, m] = mes.split("-").map(Number);
      return `${mes}-${String(new Date(anio, m, 0).getDate()).padStart(2, "0")}`;
    },

    async confirmar() {
      if (this.faltantes.length || this.guardando) return;
      this.guardando = true;
      this.error = "";
      const e = this.e;
      try {
        this.resultado = await API.post("/entradas", {
          proveedor_id: Number(e.proveedor_id),
          folio: e.folio,
          fecha_recepcion: e.fecha_recepcion,
          fecha_factura: e.fecha_factura || null,
          origen: e.origen,
          total_factura: e.total_factura === "" ? null : String(e.total_factura),
          archivo_id: e.archivo_id,
          pedido_id: e.pedido_id ? Number(e.pedido_id) : null,
          renglones: e.renglones.map((r) => ({
            producto_id: r.producto.id,
            cantidad: String(r.cantidad),
            factor: String(r.factor),
            costo_unitario: String(r.costo_unitario),
            numero_lote: r.numero_lote.trim() || null,
            caducidad: r.caducidad_mes ? this.ultimoDiaDelMes(r.caducidad_mes) : null,
            descripcion_proveedor: r.descripcion,
            clave_proveedor: r.clave,
            aplicar_precio: this.esAdmin && r.aplicar_precio && this.sugerido(r) !== null,
          })),
        });
        this.vista = "hecha";
        this.recientes = await API.get("/entradas?limite=30");
        window.scrollTo(0, 0);
      } catch (err) {
        this.error = err.message;
        window.scrollTo(0, 0);
      } finally {
        this.guardando = false;
      }
    },

    volverALista() {
      this.e = null;
      this.resultado = null;
      this.vista = "lista";
    },

    textoOrigen(o) {
      return { manual: "Manual", xml: "XML", ia: "Leída con IA" }[o] || o;
    },
    fecha(f) {
      if (!f) return "";
      const [a, m, d] = f.split("-");
      return `${d}/${m}/${a}`;
    },

    dinero,
    cantidad,
  };
}
