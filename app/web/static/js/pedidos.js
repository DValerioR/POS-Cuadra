// Pedidos a proveedores (admin y bodega).
// Lista de pedidos → nuevo pedido (proveedor → sus faltantes, con la cantidad
// sugerida o la del asistente, se ajusta a mano) → detalle: imprimir, copiar
// para WhatsApp o bajar en Excel, marcar enviado y, cuando llega la factura,
// ligarla y ver qué faltó o cambió de costo.

const ESTADOS_PEDIDO = {
  borrador: { texto: "Borrador", clase: "gris" },
  enviado: { texto: "Enviado", clase: "aviso" },
  recibido: { texto: "Recibido", clase: "verde" },
  cancelado: { texto: "Cancelado", clase: "peligro" },
};
const ESTADOS_COMPARACION = {
  no_llego: { texto: "No llegó", clase: "peligro" },
  incompleto: { texto: "Llegó incompleto", clase: "aviso" },
  de_mas: { texto: "Llegó de más", clase: "aviso" },
  no_pedido: { texto: "No se pidió", clase: "gris" },
  completo: { texto: "Completo", clase: "verde" },
};

function pantallaPedidos() {
  return {
    usuario: null,
    cargando: true,
    error: "",
    aviso: "",
    vista: "lista", // lista | proveedor | armar | detalle
    filtro: "curso", // curso | cerrados
    pedidos: [],
    proveedores: [],
    iaLista: false,

    // Armar (nuevo o editar un borrador)
    arm: null, // {pedido_id, proveedor_id, proveedor, renglones: [...], sin_proveedor: [...], notas}
    conSugerencias: false,
    preparando: false,
    guardando: false,
    buscar: "",
    resultados: [],

    // Detalle
    p: null,
    entradaElegida: "",

    async init() {
      try {
        this.usuario = await API.get("/auth/yo");
        if (!this.puedeUsar) return;
        const [proveedores, ia] = await Promise.all([API.get("/proveedores"), API.get("/ia/estado")]);
        this.proveedores = proveedores;
        this.iaLista = ia.configurada;
        const id = new URLSearchParams(location.search).get("id");
        if (id) await this.abrir(Number(id));
        else await this.cargarLista();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.cargando = false;
      }
      window.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape" && this.vista !== "lista" && !this.guardando) this.volver();
      });
    },
    get puedeUsar() {
      return this.usuario && (this.usuario.rol === "admin" || this.usuario.rol === "bodega");
    },

    // --- Lista ------------------------------------------------------------
    async cargarLista() {
      const todos = await API.get("/compras/pedidos?limite=100");
      this.pedidos = todos;
    },
    get lista() {
      const enCurso = (x) => x.estado === "borrador" || x.estado === "enviado";
      return this.pedidos.filter((x) => (this.filtro === "curso" ? enCurso(x) : !enCurso(x)));
    },
    cuantos(filtro) {
      const enCurso = (x) => x.estado === "borrador" || x.estado === "enviado";
      return this.pedidos.filter((x) => (filtro === "curso" ? enCurso(x) : !enCurso(x))).length;
    },
    estado(e) {
      return ESTADOS_PEDIDO[e] || { texto: e, clase: "" };
    },
    async volver() {
      this.vista = "lista";
      this.arm = null;
      this.p = null;
      this.error = "";
      history.replaceState(null, "", "/pedidos");
      await this.cargarLista();
    },

    // --- Nuevo pedido -----------------------------------------------------
    nuevo() {
      this.error = "";
      this.arm = null;
      this.vista = "proveedor";
    },
    async elegirProveedor(prov) {
      this.preparando = true;
      this.error = "";
      try {
        const r = await API.get(`/compras/pedidos/preparar?proveedor_id=${prov.id}&sugerencias=${this.conSugerencias && this.iaLista}`);
        this.arm = {
          pedido_id: null, proveedor_id: r.proveedor_id, proveedor: r.proveedor, notas: "",
          con_sugerencias: r.con_sugerencias,
          renglones: r.renglones.map((x) => ({ ...x, cantidad: cantidad(x.cantidad) })),
          sin_proveedor: r.sin_proveedor,
          encargos: r.encargos || [],
        };
        this.vista = "armar";
        window.scrollTo(0, 0);
      } catch (e) {
        this.error = e.message;
      } finally {
        this.preparando = false;
      }
    },
    get totalArmado() {
      if (!this.arm) return 0;
      return this.arm.renglones.reduce((s, r) => s + (Number(r.cantidad) || 0) * (Number(r.costo) || 0), 0);
    },
    get productosArmados() {
      return this.arm ? this.arm.renglones.filter((r) => Number(r.cantidad) > 0).length : 0;
    },
    agregarSinProveedor(x) {
      this.agregar({ producto_id: x.producto_id, clave: x.clave, nombre: x.nombre, existencia: x.existencia,
                     minimo: x.minimo, maximo: x.maximo, sugerido: x.sugerido, cantidad: cantidad(x.sugerido) });
      this.arm.sin_proveedor = this.arm.sin_proveedor.filter((y) => y.producto_id !== x.producto_id);
    },
    // Encargo de clientes: al enviar el pedido, sus encargos pasan solos a "pedido al proveedor".
    agregarEncargo(x) {
      this.agregar({ producto_id: x.producto_id, clave: x.clave, nombre: x.nombre, existencia: 0,
                     minimo: null, maximo: null, sugerido: x.cantidad, cantidad: cantidad(x.cantidad) });
      this.arm.encargos = this.arm.encargos.filter((y) => y.producto_id !== x.producto_id);
    },
    agregar(x) {
      if (this.arm.renglones.some((r) => r.producto_id === x.producto_id)) return;
      this.arm.renglones.push({ costo: null, ya_pedido: [], mejor_proveedor: null, sugerencia_asistente: null, ...x });
    },
    quitar(i) {
      this.arm.renglones.splice(i, 1);
    },
    async alBuscar() {
      const q = this.buscar.trim();
      if (q.length < 2) return (this.resultados = []);
      try {
        const lista = await API.get(`/productos?q=${encodeURIComponent(q)}&solo_activos=true&limite=8`);
        if (q === this.buscar.trim()) this.resultados = lista;
      } catch {
        /* se reintenta al seguir escribiendo */
      }
    },
    agregarBuscado(p) {
      this.agregar({ producto_id: p.id, clave: p.clave, nombre: p.nombre, existencia: null, minimo: p.minimo,
                     maximo: p.maximo, sugerido: null, cantidad: "1" });
      this.buscar = "";
      this.resultados = [];
    },
    async guardarArmado(enviar) {
      if (this.guardando) return;
      if (!this.productosArmados) return (this.error = "Pon la cantidad de al menos un producto.");
      this.guardando = true;
      this.error = "";
      const datos = {
        proveedor_id: this.arm.proveedor_id,
        notas: this.arm.notas,
        renglones: this.arm.renglones.filter((r) => Number(r.cantidad) > 0)
          .map((r) => ({ producto_id: r.producto_id, cantidad: String(r.cantidad) })),
      };
      try {
        let p = this.arm.pedido_id
          ? await API.put(`/compras/pedidos/${this.arm.pedido_id}`, datos)
          : await API.post("/compras/pedidos", datos);
        if (enviar) p = await API.post(`/compras/pedidos/${p.id}/enviar`);
        this.mostrar(p);
        this.avisar(enviar ? `Pedido ${p.folio} guardado y marcado como enviado.` : `Pedido ${p.folio} guardado.`);
      } catch (e) {
        this.error = e.message;
        window.scrollTo(0, 0);
      } finally {
        this.guardando = false;
      }
    },

    // --- Detalle ----------------------------------------------------------
    async abrir(id) {
      this.error = "";
      try {
        this.mostrar(await API.get(`/compras/pedidos/${id}`));
      } catch (e) {
        this.error = e.message;
      }
    },
    mostrar(p) {
      this.p = p;
      this.arm = null;
      this.entradaElegida = p.entradas_disponibles.length ? String(p.entradas_disponibles[0].id) : "";
      this.vista = "detalle";
      history.replaceState(null, "", `/pedidos?id=${p.id}`);
      window.scrollTo(0, 0);
    },
    editar() {
      const p = this.p;
      this.arm = {
        pedido_id: p.id, proveedor_id: p.proveedor_id, proveedor: p.proveedor, notas: p.notas || "",
        renglones: p.renglones.map((r) => ({ ...r, costo: r.costo_esperado, cantidad: cantidad(r.cantidad),
                                             ya_pedido: [], sugerido: null, existencia: null })),
        sin_proveedor: [],
        encargos: [],
      };
      this.vista = "armar";
    },
    async accion(ruta, texto, cuerpo) {
      if (this.guardando) return;
      this.guardando = true;
      this.error = "";
      try {
        this.p = await API.post(`/compras/pedidos/${this.p.id}/${ruta}`, cuerpo || {});
        this.entradaElegida = this.p.entradas_disponibles.length ? String(this.p.entradas_disponibles[0].id) : "";
        this.avisar(texto);
      } catch (e) {
        this.error = e.message;
      } finally {
        this.guardando = false;
      }
    },
    ligarEntrada() {
      if (!this.entradaElegida) return;
      this.accion("entradas", "Factura ligada al pedido.", { entrada_id: Number(this.entradaElegida) });
    },
    get textoWhatsApp() {
      const p = this.p;
      if (!p) return "";
      const lineas = [`*Pedido ${p.folio}* · ${document.querySelector("[data-negocio]")?.textContent || ""}`.trim(),
                      `Proveedor: ${p.proveedor}`, ""];
      for (const r of p.renglones) lineas.push(`• ${cantidad(r.cantidad)} pz  ${r.nombre}${r.clave ? `  (${r.clave})` : ""}`);
      if (p.notas) lineas.push("", p.notas);
      return lineas.join("\n");
    },
    async copiarWhatsApp() {
      try {
        await navigator.clipboard.writeText(this.textoWhatsApp);
        this.avisar("Copiado: pégalo en WhatsApp.");
      } catch {
        this.error = "No se pudo copiar; selecciona el texto del pedido y cópialo a mano.";
      }
    },
    imprimir() {
      window.print();
    },
    get resumenComparacion() {
      const c = this.p && this.p.comparacion;
      if (!c) return "";
      const partes = [];
      if (c.faltantes) partes.push(c.faltantes === 1 ? "1 producto no llegó completo" : `${c.faltantes} productos no llegaron completos`);
      if (c.cambios_de_costo) partes.push(c.cambios_de_costo === 1 ? "1 cambió de costo" : `${c.cambios_de_costo} cambiaron de costo`);
      return partes.join(" y ") + ".";
    },
    comparacionEstado(e) {
      return ESTADOS_COMPARACION[e] || { texto: e, clase: "" };
    },
    avisar(texto) {
      this.aviso = texto;
      clearTimeout(this._aviso);
      this._aviso = setTimeout(() => (this.aviso = ""), 4000);
    },
    fecha(f) {
      if (!f) return "";
      return new Date(f.length === 10 ? f + "T00:00:00" : f).toLocaleDateString("es-MX", { day: "numeric", month: "short", year: "numeric" });
    },
    dinero,
    cantidad,
  };
}
