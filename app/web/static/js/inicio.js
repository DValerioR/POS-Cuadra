// Pantalla de inicio ("núcleo"): desde aquí se entra a todas las funciones.
//
// Arriba, los menús por tema (como los de PVWin); abajo de ellos, los accesos
// rápidos de uso diario; al centro, la imagen del negocio; y hasta abajo, la
// barra de estado. Menús y accesos salen de SECCIONES (api.js), filtrados por
// el rol: a cada quien solo le aparece lo que puede usar.
//
// Teclado:
//  - Alt (solo, sin otra tecla) o F10 abren y cierran los menús; flechas para
//    moverse, Enter abre la opción, Esc cierra.
//  - F1 a F4 abren los accesos rápidos.

function pantallaInicio() {
  return {
    usuario: null,
    negocio: null,
    cajaId: CajaLocal.obtener(),
    cajaNombre: "",
    turno: null,
    conectado: true,
    fechaHora: "",
    entradaDirecta: EntradaDirecta.activa(),

    menuAbierto: null, // índice del grupo abierto
    opcionElegida: 0,
    altSolo: false,

    ventana: null, // "imagen" | "teclas" | "acerca"
    archivo: null,
    vistaPrevia: null,
    guardando: false,
    error: "",
    aviso: "",
    avisoTimer: null,

    ROLES,

    async init() {
      this.actualizarReloj();
      setInterval(() => this.actualizarReloj(), 15000);
      setInterval(() => this.revisarConexion(), 15000);
      window.addEventListener("keydown", (ev) => this.teclaAbajo(ev));
      window.addEventListener("keyup", (ev) => this.teclaArriba(ev));
      try {
        [this.usuario, this.negocio] = await Promise.all([API.get("/auth/yo"), API.get("/negocio")]);
        document.title = `Inicio · ${this.negocio.nombre}`;
        if (this.usuario.rol === "admin") vigilarSolicitudes(document.querySelector(".barra-menus .campana"));
      } catch {
        return; // sin sesión: API ya manda al login
      }
      this.cargarCajaYTurno();
    },

    async cargarCajaYTurno() {
      if (!this.cajaId) return;
      try {
        const cajas = await API.get("/cajas");
        const caja = cajas.find((c) => c.id === this.cajaId);
        this.cajaNombre = caja ? caja.nombre : "";
        if (caja) this.turno = await API.get(`/turnos/abierto?caja_id=${this.cajaId}`);
      } catch {
        /* la barra de estado se queda sin esos datos */
      }
    },

    // --- Lo que ve este rol ----------------------------------------------

    get grupos() {
      if (!this.usuario) return [];
      const mias = seccionesDe(this.usuario.rol);
      return GRUPOS.map((nombre) => ({ nombre, secciones: mias.filter((s) => s.grupo === nombre) })).filter(
        (g) => g.secciones.length
      );
    },
    get rapidos() {
      if (!this.usuario) return [];
      return seccionesDe(this.usuario.rol).filter((s) => s.tecla);
    },

    usar(s) {
      this.cerrarMenu();
      if (!s.existe) {
        this.avisar(`"${s.texto}" todavía no está lista. Pronto se podrá usar.`);
      } else if (s.ruta) {
        location.href = s.ruta;
      } else if (s.accion === "entradaDirecta") {
        this.entradaDirecta = !this.entradaDirecta;
        EntradaDirecta.cambiar(this.entradaDirecta);
        this.avisar(
          this.entradaDirecta
            ? "Listo: al iniciar sesión en esta computadora se entrará directo a Vender."
            : "Listo: al iniciar sesión en esta computadora se entrará a esta pantalla de inicio."
        );
      } else if (s.accion === "imagen") {
        this.archivo = null;
        this.vistaPrevia = null;
        this.error = "";
        this.ventana = "imagen";
      } else {
        this.ventana = s.accion; // "teclas" | "acerca"
      }
    },

    avisar(texto) {
      this.aviso = texto;
      clearTimeout(this.avisoTimer);
      this.avisoTimer = setTimeout(() => (this.aviso = ""), 3500);
    },

    // --- Menús -----------------------------------------------------------

    abrirMenu(i) {
      this.menuAbierto = i;
      this.opcionElegida = 0;
    },
    alternarMenu(i) {
      if (this.menuAbierto === i) this.cerrarMenu();
      else this.abrirMenu(i);
    },
    cerrarMenu() {
      this.menuAbierto = null;
    },
    cerrarMenuSiAfuera(ev) {
      if (this.menuAbierto !== null && !ev.target.closest(".menu")) this.cerrarMenu();
    },

    moverMenu(paso) {
      const total = this.grupos.length;
      this.abrirMenu((this.menuAbierto + paso + total) % total);
    },
    moverOpcion(paso) {
      const total = this.grupos[this.menuAbierto].secciones.length;
      this.opcionElegida = (this.opcionElegida + paso + total) % total;
    },

    // --- Teclado ---------------------------------------------------------

    teclaAbajo(ev) {
      // Alt suelto abre los menús; si se usa con otra tecla (Alt+Tab), no.
      if (ev.key === "Alt") {
        ev.preventDefault();
        this.altSolo = !ev.repeat;
        return;
      }
      this.altSolo = false;

      if (this.ventana) {
        if (ev.key === "Escape") {
          ev.preventDefault();
          this.cerrarVentana();
        }
        return;
      }

      if (ev.key === "F10") {
        ev.preventDefault();
        this.alternarConTeclado();
        return;
      }

      if (this.menuAbierto !== null) {
        const acciones = {
          ArrowLeft: () => this.moverMenu(-1),
          ArrowRight: () => this.moverMenu(1),
          ArrowUp: () => this.moverOpcion(-1),
          ArrowDown: () => this.moverOpcion(1),
          Enter: () => this.usar(this.grupos[this.menuAbierto].secciones[this.opcionElegida]),
          Escape: () => this.cerrarMenu(),
        };
        if (acciones[ev.key]) {
          ev.preventDefault();
          acciones[ev.key]();
        }
        return;
      }

      if (/^F[1-9]$/.test(ev.key)) {
        ev.preventDefault(); // F1 abriría la ayuda de Chrome
        const s = this.rapidos.find((r) => r.tecla === ev.key);
        if (s) this.usar(s);
      }
    },

    teclaArriba(ev) {
      if (ev.key !== "Alt") return;
      ev.preventDefault();
      if (this.altSolo && !this.ventana) this.alternarConTeclado();
      this.altSolo = false;
    },

    alternarConTeclado() {
      if (this.menuAbierto !== null) this.cerrarMenu();
      else if (this.grupos.length) this.abrirMenu(0);
    },

    // --- Barra de estado -------------------------------------------------

    get textoCaja() {
      if (!this.cajaId) return "Esta computadora no tiene caja";
      return this.cajaNombre || "Caja";
    },
    get textoTurno() {
      if (!this.turno) return "Sin turno abierto";
      const hora = new Date(this.turno.abierto_en).toLocaleTimeString("es-MX", { hour: "numeric", minute: "2-digit" });
      return `Turno de la ${this.turno.tipo === "manana" ? "mañana" : "tarde"}, desde las ${hora}`;
    },

    actualizarReloj() {
      const ahora = new Date();
      const fecha = ahora.toLocaleDateString("es-MX", { weekday: "long", day: "numeric", month: "long" });
      const hora = ahora.toLocaleTimeString("es-MX", { hour: "numeric", minute: "2-digit" });
      this.fechaHora = `${fecha.charAt(0).toUpperCase()}${fecha.slice(1)} · ${hora}`;
    },

    async revisarConexion() {
      const control = new AbortController();
      const limite = setTimeout(() => control.abort(), 5000);
      try {
        const r = await fetch("/health", { signal: control.signal, cache: "no-store" });
        this.conectado = r.ok;
      } catch {
        this.conectado = false;
      } finally {
        clearTimeout(limite);
      }
    },

    // --- Imagen de inicio (administrador) ----------------------------------

    elegirArchivo(ev) {
      const archivo = ev.target.files[0];
      ev.target.value = ""; // para poder elegir el mismo archivo otra vez
      if (!archivo) return;
      this.error = "";
      if (!["image/png", "image/jpeg", "image/gif", "image/webp"].includes(archivo.type)) {
        this.error = "Ese archivo no es una imagen PNG, JPG, GIF o WEBP.";
        return;
      }
      if (archivo.size > 5 * 1024 * 1024) {
        this.error = "La imagen es muy pesada; el máximo es 5 MB.";
        return;
      }
      if (this.vistaPrevia) URL.revokeObjectURL(this.vistaPrevia);
      this.archivo = archivo;
      this.vistaPrevia = URL.createObjectURL(archivo);
    },

    async guardarImagen() {
      this.guardando = true;
      this.error = "";
      try {
        this.negocio = await API.put("/negocio/logo", this.archivo);
        this.cerrarVentana();
        this.avisar("Listo: se cambió la imagen de inicio.");
      } catch (e) {
        this.error = e.message;
      } finally {
        this.guardando = false;
      }
    },

    async quitarImagen() {
      if (!confirm("¿Quitar la imagen de inicio? Se mostrará el nombre del negocio.")) return;
      this.error = "";
      try {
        this.negocio = await API.borrar("/negocio/logo");
        this.cerrarVentana();
      } catch (e) {
        this.error = e.message;
      }
    },

    cerrarVentana() {
      if (this.vistaPrevia) URL.revokeObjectURL(this.vistaPrevia);
      this.vistaPrevia = null;
      this.archivo = null;
      this.ventana = null;
    },
  };
}
