// Vista para la tableta: consultar precio y existencia escaneando con la
// cámara (o buscando), capturar caducidades, marcar "No caduca", contar y
// ver lo que está por caducar. Pensada para el dedo: todo grande.
//
// La cámara necesita HTTPS (ver app/scripts/certificado_local.py). El código
// se lee con BarcodeDetector de Chrome; si el navegador no lo tiene, se
// escribe a mano.

const FORMATOS_CODIGO = ["ean_13", "ean_8", "upc_a", "upc_e", "code_128", "code_39", "itf", "codabar"];

function pantallaTableta() {
  return {
    usuario: null,
    negocio: "",
    cargando: true,
    pestana: "buscar", // buscar | caducar
    aviso: "",
    error: "",

    // Buscar
    buscar: "",
    resultados: [],
    buscando: false,
    producto: null, // {..datos de /productos, existencia: {...} de /inventario}

    // Cámara
    camara: false,
    errorCamara: "",
    _flujo: null,
    _lector: null,
    _timer: null,

    // Hojas (capturar | contar)
    hoja: null,
    captura: { mes: "", cantidad: "", lote: "" },
    conteo: "",
    guardando: false,
    errorHoja: "",

    // Por caducar
    meses: 3,
    porCaducar: [],

    async init() {
      try {
        const [usuario, negocio] = await Promise.all([API.get("/auth/yo"), API.get("/negocio")]);
        this.usuario = usuario;
        this.negocio = negocio.nombre;
        ponerLogo(this.$refs.logo, negocio.marca_url);
      } catch {
        return; // sin sesión: API manda al login
      } finally {
        this.cargando = false;
      }
    },
    get puedeAjustar() {
      return this.usuario && (this.usuario.rol === "admin" || this.usuario.rol === "bodega");
    },
    get puedeCamara() {
      return window.isSecureContext && !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
    },
    async salir() {
      try {
        await API.post("/auth/logout");
      } finally {
        location.href = "/login?volver=/tableta";
      }
    },

    // --- Buscar -----------------------------------------------------------
    async alBuscar() {
      const q = this.buscar.trim();
      if (q.length < 2) return (this.resultados = []);
      this.buscando = true;
      try {
        const lista = await API.get(`/productos?q=${encodeURIComponent(q)}&solo_activos=true&limite=20`);
        if (q === this.buscar.trim()) this.resultados = lista;
      } catch (e) {
        this.error = e.message;
      } finally {
        this.buscando = false;
      }
    },
    async porCodigo(codigo) {
      this.error = "";
      try {
        const lista = await API.get(`/productos?clave=${encodeURIComponent(codigo)}&limite=2`);
        if (!lista.length) {
          this.buscar = codigo;
          this.resultados = [];
          this.producto = null;
          return (this.error = `No hay ningún producto con el código ${codigo}.`);
        }
        await this.abrir(lista[0]);
      } catch (e) {
        this.error = e.message;
      }
    },
    async enterBuscar() {
      const q = this.buscar.trim();
      if (!q) return;
      if (/^\d{6,}$/.test(q)) return this.porCodigo(q); // parece código de barras
      await this.alBuscar();
      if (this.resultados.length === 1) this.abrir(this.resultados[0]);
    },
    async abrir(p) {
      this.error = "";
      try {
        const existencia = await API.get(`/inventario/productos/${p.id}`);
        this.producto = { ...p, existencia };
        this.resultados = [];
        this.buscar = "";
        window.scrollTo(0, 0);
      } catch (e) {
        this.error = e.message;
      }
    },
    async abrirPorId(id) {
      this.pestana = "buscar";
      try {
        await this.abrir(await API.get(`/productos/${id}`));
      } catch (e) {
        this.error = e.message;
      }
    },
    async recargar() {
      const p = await API.get(`/productos/${this.producto.id}`);
      await this.abrir(p);
    },
    cerrarProducto() {
      this.producto = null;
    },
    get sinCaducidad() {
      return this.producto ? Number(this.producto.existencia.sin_caducidad) : 0;
    },
    get puedeCapturar() {
      return this.producto && this.producto.existencia.controla_lote && this.sinCaducidad > 0;
    },

    // --- Cámara -----------------------------------------------------------
    async abrirCamara() {
      this.errorCamara = "";
      this.error = "";
      if (!this.puedeCamara) {
        return (this.error = "La cámara solo funciona entrando por https:// (pide al administrador la dirección segura). Mientras, escribe el código o el nombre.");
      }
      if (!("BarcodeDetector" in window)) {
        return (this.error = "Este navegador no puede leer códigos con la cámara. Usa Chrome actualizado o escribe el código.");
      }
      try {
        const soportados = await BarcodeDetector.getSupportedFormats();
        this._lector = new BarcodeDetector({ formats: FORMATOS_CODIGO.filter((f) => soportados.includes(f)) });
        this._flujo = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false,
        });
      } catch (e) {
        this.cerrarCamara();
        return (this.error = e && e.name === "NotAllowedError"
          ? "No se dio permiso para usar la cámara. Actívalo en el candado de la barra de direcciones."
          : "No se pudo abrir la cámara.");
      }
      this.camara = true;
      await this.$nextTick();
      const video = this.$refs.video;
      video.srcObject = this._flujo;
      await video.play().catch(() => {});
      this._timer = setInterval(() => this.leerCuadro(), 250);
    },
    async leerCuadro() {
      const video = this.$refs.video;
      if (!this._lector || !video || video.readyState < 2) return;
      try {
        const codigos = await this._lector.detect(video);
        if (codigos.length && this.camara) {
          const codigo = codigos[0].rawValue.trim();
          if (navigator.vibrate) navigator.vibrate(80);
          this.cerrarCamara();
          await this.porCodigo(codigo);
        }
      } catch {
        /* cuadro sin código: se intenta con el siguiente */
      }
    },
    cerrarCamara() {
      clearInterval(this._timer);
      this._timer = null;
      if (this._flujo) this._flujo.getTracks().forEach((t) => t.stop());
      this._flujo = null;
      this.camara = false;
    },

    // --- Capturar, No caduca, Contar ----------------------------------------
    abrirHoja(tipo) {
      this.errorHoja = "";
      this.hoja = tipo;
      if (tipo === "capturar") this.captura = { mes: "", cantidad: String(this.sinCaducidad), lote: "" };
      if (tipo === "contar") this.conteo = "";
    },
    cerrarHoja() {
      this.hoja = null;
    },
    ultimoDiaDelMes(mes) {
      const [anio, m] = mes.split("-").map(Number);
      return `${mes}-${String(new Date(anio, m, 0).getDate()).padStart(2, "0")}`;
    },
    async guardar(accion) {
      this.guardando = true;
      this.errorHoja = "";
      try {
        const texto = await accion();
        this.hoja = null;
        await this.recargar();
        this.avisar(texto);
      } catch (e) {
        this.errorHoja = e.message;
        this.error = this.hoja ? "" : e.message;
      } finally {
        this.guardando = false;
      }
    },
    guardarCaptura() {
      const c = this.captura;
      if (!c.mes) return (this.errorHoja = "Elige el mes y año de caducidad que trae la caja.");
      if (!(Number(c.cantidad) > 0)) return (this.errorHoja = "¿Cuántas piezas son de esa caducidad?");
      return this.guardar(async () => {
        await API.post("/inventario/captura-caducidad", {
          producto_id: this.producto.id, caducidad: this.ultimoDiaDelMes(c.mes),
          cantidad: String(c.cantidad), numero_lote: c.lote.trim() || null,
        });
        return `Listo: ${cantidad(c.cantidad)} piezas con caducidad ${mesAnio(this.ultimoDiaDelMes(c.mes))}.`;
      });
    },
    marcarNoCaduca(valor) {
      return this.guardar(async () => {
        await API.put(`/inventario/productos/${this.producto.id}/no-caduca`, { no_caduca: valor });
        return valor ? "Listo: quedó como no caduca." : "Listo: se le vuelve a pedir caducidad.";
      });
    },
    guardarConteo() {
      if (this.conteo === "" || Number(this.conteo) < 0) return (this.errorHoja = "Escribe cuántas piezas hay en total.");
      return this.guardar(async () => {
        await API.post("/inventario/conteo", { producto_id: this.producto.id, conteo: String(this.conteo) });
        return `Listo: la existencia quedó en ${cantidad(this.conteo)}.`;
      });
    },

    // --- Por caducar --------------------------------------------------------
    async verPorCaducar(meses) {
      this.pestana = "caducar";
      this.meses = meses;
      this.cerrarCamara();
      try {
        this.porCaducar = await API.get(`/inventario/por-caducar?meses=${meses}`);
      } catch (e) {
        this.error = e.message;
      }
    },
    nivel(dias) {
      if (dias < 0) return "caducado";
      if (dias <= 90) return "pronto";
      return "";
    },
    textoDias(dias) {
      if (dias < 0) return dias === -1 ? "caducó ayer" : `caducó hace ${-dias} días`;
      if (dias === 0) return "caduca hoy";
      if (dias < 60) return `en ${dias} días`;
      return `en ${Math.round(dias / 30)} meses`;
    },

    textoLote(l) {
      if (!l.caducidad && !l.numero_lote) return this.producto && this.producto.existencia.no_caduca ? "No caduca" : "Sin caducidad registrada";
      return l.numero_lote ? `Lote ${l.numero_lote}` : "Sin número de lote";
    },
    avisar(texto) {
      this.aviso = texto;
      clearTimeout(this._aviso);
      this._aviso = setTimeout(() => (this.aviso = ""), 3500);
    },
    dinero,
    cantidad,
    mesAnio,
  };
}
