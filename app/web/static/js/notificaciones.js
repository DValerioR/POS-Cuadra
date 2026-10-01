// Centro de notificaciones (solo administradores):
//  - Devoluciones y cancelaciones que pidieron los cajeros. Se autorizan o
//    rechazan desde cualquier computadora; al autorizar, la devolución se hace
//    en la caja que la pidió y al cajero le aparece en Vender cuánto entregar.
//  - Ventas sin existencia registrada: se vendió más de lo que el sistema
//    tenía. Se cuenta lo que hay en anaquel y la existencia se ajusta a eso.
// La lista se actualiza sola cada 15 segundos.

function pantallaNotificaciones() {
  return {
    usuario: null,
    cargando: true,
    error: "",
    pendientes: [],
    respondidas: [],
    avisos: [], // ventas sin existencia pendientes
    avisosRevisados: [],
    respaldo: null, // estado de /respaldos; se avisa si falló o está atrasado
    encargosPorPedir: 0,
    whatsappPendientes: 0, // clientes de WhatsApp que esperan a una persona
    actualizacionFallo: false, // la última actualización automática falló
    conteos: {}, // producto_id -> lo que se escribió en "¿Cuántas hay?"
    rechazando: null, // id de la solicitud a la que se le escribe el motivo del rechazo
    respuesta: "",
    procesando: null, // id de la solicitud que se está guardando
    aviso: "",
    _avisoTimer: null,

    async init() {
      try {
        this.usuario = await API.get("/auth/yo");
        if (this.esAdmin) await this.cargar();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.cargando = false;
      }
      setInterval(() => this.esAdmin && !this.ocupado && this.cargar(), 15000);
      document.addEventListener("solicitudes-pendientes", (ev) => {
        if (ev.detail !== this.pendientes.length + this.avisos.length + (this.alertaRespaldo ? 1 : 0) + this.encargosPorPedir + this.whatsappPendientes + (this.actualizacionFallo ? 1 : 0) && !this.ocupado) this.cargar();
      });
      window.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape" && this.rechazando) this.rechazando = null;
      });
    },

    get alertaRespaldo() {
      return Boolean(this.respaldo && this.respaldo.automaticos && this.respaldo.necesita_atencion);
    },
    textoRespaldo() {
      const r = this.respaldo;
      if (!r) return "";
      if (r.error) return `El último respaldo falló: ${r.error}`;
      if (!r.ultimo_ok) return "Todavía no se ha hecho ningún respaldo de la base de datos.";
      return `El último respaldo es del ${new Date(r.ultimo_ok).toLocaleString("es-MX", { dateStyle: "long", timeStyle: "short" })}: hace más de un día.`;
    },

    get esAdmin() {
      return this.usuario && this.usuario.rol === "admin";
    },

    async cargar() {
      try {
        const hoy = new Date();
        hoy.setHours(0, 0, 0, 0);
        const desde = encodeURIComponent(hoy.toISOString());
        const [pendientes, hechas, avisos, avisosHoy, respaldo, encargosAbiertos] = await Promise.all([
          API.get("/solicitudes?estado=pendiente&limite=100"),
          API.get(`/solicitudes?desde=${desde}&limite=50`),
          API.get("/avisos-inventario?estado=pendiente&limite=200"),
          API.get(`/avisos-inventario?desde=${desde}&limite=100`),
          API.get("/respaldos/estado"),
          API.get("/encargos/lista"),
        ]);
        this.respaldo = respaldo;
        this.encargosPorPedir = encargosAbiertos.filter((e) => e.estado === "por_pedir").length;
        const cuenta = await API.get("/notificaciones/pendientes");
        this.whatsappPendientes = cuenta.whatsapp || 0;
        this.actualizacionFallo = Boolean(cuenta.actualizacion);
        this.pendientes = pendientes;
        this.respondidas = hechas.filter((s) => s.estado !== "pendiente");
        this.avisos = avisos;
        this.avisosRevisados = avisosHoy.filter((a) => a.estado === "revisado");
        this.error = "";
      } catch (e) {
        this.error = e.message;
      }
    },

    async autorizar(s) {
      this.procesando = s.id;
      this.error = "";
      try {
        const r = await API.post(`/solicitudes/${s.id}/autorizar`);
        this.avisar(`Autorizada. En ${r.caja} le aparecerá al cajero que entregue ${this.textoDinero(r)}.`);
      } catch (e) {
        this.error = `Folio ${s.folio}: ${e.message}`;
      } finally {
        this.procesando = null;
        await this.cargar();
        if (window.revisarCampana) window.revisarCampana();
      }
    },

    empezarRechazo(s) {
      this.rechazando = s.id;
      this.respuesta = "";
      this.$nextTick(() => document.getElementById(`respuesta-${s.id}`).focus());
    },

    async rechazar(s) {
      this.procesando = s.id;
      this.error = "";
      try {
        await API.post(`/solicitudes/${s.id}/rechazar`, { respuesta: this.respuesta.trim() || null });
        this.rechazando = null;
        this.avisar(`Rechazada. Al cajero de ${s.caja} le aparecerá que no se hace.`);
      } catch (e) {
        this.error = `Folio ${s.folio}: ${e.message}`;
      } finally {
        this.procesando = null;
        await this.cargar();
        if (window.revisarCampana) window.revisarCampana();
      }
    },

    // Mientras se escribe un rechazo o un conteo no se recarga la lista.
    get ocupado() {
      return Boolean(this.rechazando) || Object.values(this.conteos).some((c) => c !== "" && c !== undefined);
    },

    // --- Ventas sin existencia registrada --------------------------------

    // Un grupo por producto: contar una vez cierra todos sus avisos.
    get productosSinExistencia() {
      const grupos = new Map();
      for (const a of this.avisos) {
        if (!grupos.has(a.producto_id)) grupos.set(a.producto_id, { ...a, ventas: [] });
        grupos.get(a.producto_id).ventas.push(a);
      }
      return [...grupos.values()];
    },

    async contar(g) {
      const conteo = this.conteos[g.producto_id];
      if (conteo === undefined || conteo === "" || Number(conteo) < 0) {
        this.error = `${g.producto}: escribe cuántas piezas hay en anaquel.`;
        return;
      }
      this.procesando = `p${g.producto_id}`;
      this.error = "";
      try {
        await API.post(`/avisos-inventario/${g.ventas[0].id}/conteo`, { conteo: String(conteo) });
        delete this.conteos[g.producto_id];
        this.avisar(`Listo: ${g.producto} queda con ${cantidad(conteo)} en existencia.`);
      } catch (e) {
        this.error = `${g.producto}: ${e.message}`;
      } finally {
        this.procesando = null;
        await this.cargar();
        if (window.revisarCampana) window.revisarCampana();
      }
    },

    async yaRevisado(g) {
      this.procesando = `p${g.producto_id}`;
      this.error = "";
      try {
        await API.post(`/avisos-inventario/${g.ventas[0].id}/revisado`);
        delete this.conteos[g.producto_id];
        this.avisar(`${g.producto}: marcado como revisado, sin cambiar la existencia.`);
      } catch (e) {
        this.error = `${g.producto}: ${e.message}`;
      } finally {
        this.procesando = null;
        await this.cargar();
        if (window.revisarCampana) window.revisarCampana();
      }
    },

    // "$232.00 en efectivo", "$116.00 a su tarjeta" o las dos.
    textoDinero(s) {
      const partes = [];
      if (Number(s.efectivo) > 0) partes.push(`${dinero(s.efectivo)} en efectivo`);
      if (Number(s.tarjeta) > 0) partes.push(`${dinero(s.tarjeta)} a su tarjeta`);
      return partes.join(" y ") || dinero(0);
    },
    textoTipo(s) {
      return s.tipo === "cancelacion" ? "Cancelar toda la venta" : "Devolución";
    },
    hace(fecha) {
      const minutos = Math.round((Date.now() - new Date(fecha)) / 60000);
      if (minutos < 1) return "hace un momento";
      if (minutos < 60) return `hace ${minutos} min`;
      return `a las ${this.hora(fecha)}`;
    },
    hora(fecha) {
      return new Date(fecha).toLocaleTimeString("es-MX", { hour: "numeric", minute: "2-digit" });
    },
    fecha(fecha) {
      return new Date(fecha).toLocaleString("es-MX", { dateStyle: "medium", timeStyle: "short" });
    },

    avisar(texto) {
      this.aviso = texto;
      clearTimeout(this._avisoTimer);
      this._avisoTimer = setTimeout(() => (this.aviso = ""), 4500);
    },

    dinero,
    cantidad,
  };
}
