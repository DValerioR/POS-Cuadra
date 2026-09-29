// Centro de notificaciones (solo administradores): devoluciones y
// cancelaciones que pidieron los cajeros. Se autorizan o rechazan desde
// cualquier computadora; al autorizar, la devolución se hace en la caja que
// la pidió y al cajero le aparece en Vender cuánto entregar.
// La lista se actualiza sola cada 15 segundos.

function pantallaNotificaciones() {
  return {
    usuario: null,
    cargando: true,
    error: "",
    pendientes: [],
    respondidas: [],
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
      setInterval(() => this.esAdmin && !this.rechazando && this.cargar(), 15000);
      document.addEventListener("solicitudes-pendientes", (ev) => {
        if (ev.detail !== this.pendientes.length && !this.rechazando) this.cargar();
      });
      window.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape" && this.rechazando) this.rechazando = null;
      });
    },

    get esAdmin() {
      return this.usuario && this.usuario.rol === "admin";
    },

    async cargar() {
      try {
        const hoy = new Date();
        hoy.setHours(0, 0, 0, 0);
        const [pendientes, hechas] = await Promise.all([
          API.get("/solicitudes?estado=pendiente&limite=100"),
          API.get(`/solicitudes?desde=${encodeURIComponent(hoy.toISOString())}&limite=50`),
        ]);
        this.pendientes = pendientes;
        this.respondidas = hechas.filter((s) => s.estado !== "pendiente");
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
