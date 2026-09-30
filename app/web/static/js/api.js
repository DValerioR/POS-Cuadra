// Utilidades comunes de las pantallas: llamadas al API, formato y la caja
// de esta computadora.

const API = {
  // cuerpo: un objeto se manda como JSON; un archivo (Blob/File), tal cual.
  async pedir(metodo, ruta, cuerpo) {
    const archivo = cuerpo instanceof Blob;
    const respuesta = await fetch(ruta, {
      method: metodo,
      headers: cuerpo === undefined ? {} : { "Content-Type": archivo ? cuerpo.type || "application/octet-stream" : "application/json" },
      body: cuerpo === undefined || archivo ? cuerpo : JSON.stringify(cuerpo),
      credentials: "same-origin",
    });
    if (respuesta.status === 401 && ruta !== "/auth/login") {
      // En la pantalla de entrada no se recarga: borraría lo que se está escribiendo.
      if (location.pathname !== "/login") location.href = "/login?volver=" + encodeURIComponent(location.pathname);
      throw new Error("Inicia sesión");
    }
    const texto = await respuesta.text();
    let datos = null;
    try {
      datos = texto ? JSON.parse(texto) : null;
    } catch {
      datos = texto;
    }
    if (!respuesta.ok) throw new Error(mensajeDeError(datos, respuesta.status));
    return datos;
  },
  get(ruta) {
    return this.pedir("GET", ruta);
  },
  post(ruta, cuerpo = {}) {
    return this.pedir("POST", ruta, cuerpo);
  },
  put(ruta, cuerpo = {}) {
    return this.pedir("PUT", ruta, cuerpo);
  },
  borrar(ruta) {
    return this.pedir("DELETE", ruta);
  },
};

function mensajeDeError(datos, estado) {
  if (datos && typeof datos.detail === "string") return datos.detail;
  if (datos && Array.isArray(datos.detail)) {
    // Errores de validación (422): "campo: mensaje"
    return datos.detail.map((e) => `${e.loc.slice(1).join(".")}: ${e.msg}`).join("; ");
  }
  return `Error ${estado}`;
}

// Dinero con separador de miles y 2 decimales: 1234.5 -> "$1,234.50"
function dinero(valor) {
  const n = Number(valor || 0);
  return "$" + n.toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Suma exacta de importes en centavos (evita 0.1 + 0.2 = 0.30000000000000004).
function centavos(valor) {
  return Math.round(Number(valor || 0) * 100);
}

// Redondeo del precio de venta, igual que el servidor (services/precios.py):
// hacia arriba al múltiplo de `paso`, salvo que eso pase el precio máximo.
function redondearPrecio(precio, paso, maximo) {
  if (!paso) return precio;
  const arriba = Math.ceil(Math.round(precio * 100) / Math.round(paso * 100)) * paso;
  if (maximo && precio <= maximo && maximo < arriba) return Math.floor(precio / paso) * paso;
  return Math.round(arriba * 100) / 100;
}

// Margen que toca con ese costo: el normal, o el de "costo alto" si la
// categoría lo tiene y el costo pasa del límite (ej. Otros: 50% / 20% > $150).
// `c` trae margen_porcentaje, limite_costo y margen_arriba_limite.
function margenPara(c, costo) {
  if (!c || c.margen_porcentaje === null || c.margen_porcentaje === undefined) return null;
  if (c.limite_costo !== null && c.limite_costo !== undefined && c.margen_arriba_limite !== null &&
      c.margen_arriba_limite !== undefined && Number(costo) > Number(c.limite_costo)) {
    return Number(c.margen_arriba_limite);
  }
  return Number(c.margen_porcentaje);
}

// Precio con impuestos: IEPS sobre la base e IVA sobre base + IEPS.
function precioConImpuestos(base, ivaPct, iepsPct, paso, maximo) {
  const bruto = Math.round(base * (1 + Number(iepsPct) / 100) * (1 + Number(ivaPct) / 100) * 100) / 100;
  return redondearPrecio(bruto, paso, maximo);
}

// 2.00 -> "2", 1.50 -> "1.5"
function cantidad(valor) {
  return String(Number(valor));
}

// "2027-03-31" -> "03/2027" (las cajas traen mes y año)
function mesAnio(fecha) {
  if (!fecha) return "";
  const [anio, mes] = fecha.split("-");
  return `${mes}/${anio}`;
}

// Cada computadora de mostrador recuerda qué caja es (se elige una vez).
const CajaLocal = {
  obtener() {
    try {
      return Number(localStorage.getItem("pos_caja_id")) || null;
    } catch {
      return null;
    }
  },
  guardar(id) {
    try {
      localStorage.setItem("pos_caja_id", String(id));
    } catch {
      /* sin almacenamiento: se volverá a preguntar */
    }
  },
  quitar() {
    try {
      localStorage.removeItem("pos_caja_id");
    } catch {
      /* nada que quitar */
    }
  },
};

// Ajuste de esta computadora: al iniciar sesión, entrar directo a Vender en
// lugar de a la pantalla de inicio (pensado para mostrador).
const EntradaDirecta = {
  activa() {
    try {
      return localStorage.getItem("pos_entrar_a_venta") === "1";
    } catch {
      return false;
    }
  },
  cambiar(activa) {
    try {
      if (activa) localStorage.setItem("pos_entrar_a_venta", "1");
      else localStorage.removeItem("pos_entrar_a_venta");
    } catch {
      /* sin almacenamiento: se queda en la pantalla de inicio */
    }
  },
};

// Una pantalla puede impedir que se salga de ella mientras tenga algo
// pendiente (la venta, con ventas guardadas): Salida.bloquear(() => "por qué"
// o null). Lo respetan los enlaces de la barra, el botón Salir, y cerrar o
// recargar la ventana (ahí el navegador pregunta con su propio mensaje).
const Salida = {
  _revisar: null,
  bloquear(revisar) {
    this._revisar = revisar;
  },
  motivo() {
    return this._revisar ? this._revisar() : null;
  },
  // true si se puede salir; si no, avisa por qué.
  permitir() {
    const motivo = this.motivo();
    if (motivo) avisoSalida(motivo);
    return !motivo;
  },
};

window.addEventListener("beforeunload", (ev) => {
  if (Salida.motivo()) {
    ev.preventDefault();
    ev.returnValue = "";
  }
});

function avisoSalida(mensaje) {
  let velo = document.getElementById("aviso-salida");
  if (!velo) {
    velo = document.createElement("div");
    velo.id = "aviso-salida";
    velo.className = "velo";
    velo.innerHTML = `
      <div class="panel ventana" role="alertdialog" aria-labelledby="aviso-salida-titulo">
        <div class="palomita alerta">${icono("alerta", "")}</div>
        <h2 id="aviso-salida-titulo">Todavía no puedes salir</h2>
        <p data-mensaje></p>
        <button type="button" class="primario grande separado">Entendido</button>
      </div>`;
    const cerrar = () => (velo.hidden = true);
    velo.querySelector("button").addEventListener("click", cerrar);
    velo.addEventListener("click", (ev) => ev.target === velo && cerrar());
    velo.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" || ev.key === "Enter") {
        ev.preventDefault();
        ev.stopPropagation();
        cerrar();
      }
    });
    document.body.append(velo);
  }
  velo.querySelector("[data-mensaje]").textContent = mensaje;
  velo.hidden = false;
  velo.querySelector("button").focus();
}

async function cerrarSesion() {
  if (!Salida.permitir()) return;
  try {
    await API.post("/auth/logout");
  } finally {
    location.href = "/login";
  }
}

// Ícono de /static/iconos.svg como texto HTML (para x-html o innerHTML).
function icono(nombre, clase = "ico") {
  return `<svg class="${clase}"><use href="/static/iconos.svg#${nombre}"/></svg>`;
}

function escapar(texto) {
  const div = document.createElement("div");
  div.textContent = texto ?? "";
  return div.innerHTML;
}

const ROLES = { admin: "Administrador", mostrador: "Mostrador", bodega: "Bodega" };

// --- Secciones del sistema ------------------------------------------------
// La ÚNICA lista de funciones. De aquí salen los menús y los accesos rápidos
// de la pantalla de inicio y la barra superior de las demás pantallas.
//   ruta:    página que abre; sin ruta, es una acción de la pantalla de inicio
//   existe:  false = aparece como "Próximamente" y no abre nada
//   roles:   quién la ve; a los demás no les aparece
//   tecla:   acceso rápido en la pantalla de inicio (F1 a F4)
const GRUPOS = ["Ventas", "Inventario", "Reportes", "Configuración", "Ayuda"];
const TODOS = ["admin", "mostrador", "bodega"];

const SECCIONES = [
  { id: "venta", texto: "Vender", icono: "carrito", grupo: "Ventas", ruta: "/venta", existe: true, roles: ["admin", "mostrador"], tecla: "F1" },
  { id: "turno", texto: "Turno y corte", icono: "caja", grupo: "Ventas", ruta: "/turno", existe: true, roles: ["admin", "mostrador"], tecla: "F2" },
  { id: "devoluciones", texto: "Devoluciones y cambios", icono: "regresar", grupo: "Ventas", ruta: "/devoluciones", existe: true, roles: ["admin", "mostrador"] },
  { id: "notificaciones", texto: "Notificaciones", icono: "campana", grupo: "Ventas", ruta: "/notificaciones", existe: true, roles: ["admin"] },

  { id: "facturas", texto: "Facturar un ticket", icono: "ticket", grupo: "Ventas", ruta: "/facturas", existe: true, roles: ["admin", "mostrador"] },
  { id: "precio", texto: "Consultar precio", icono: "precio", grupo: "Ventas", accion: "consultarPrecio", existe: true, roles: TODOS, tecla: "F8" },
  { id: "inventario", texto: "Inventario y caducidades", icono: "paquete", grupo: "Inventario", ruta: "/inventario", existe: true, roles: ["admin", "bodega"], tecla: "F3" },
  { id: "entradas", texto: "Entradas de mercancía", icono: "camion", grupo: "Inventario", ruta: "/mercancia", existe: true, roles: ["admin", "bodega"], tecla: "F4" },
  { id: "pedidos", texto: "Pedidos a proveedores", icono: "portapapeles", grupo: "Inventario", ruta: "/pedidos", existe: true, roles: ["admin", "bodega"] },
  { id: "productos", texto: "Productos y precios", icono: "precio", grupo: "Inventario", ruta: "/catalogo", existe: true, roles: ["admin"] },
  { id: "ofertas", texto: "Ofertas", icono: "precio", grupo: "Inventario", ruta: "/ofertas", existe: true, roles: ["admin"] },

  { id: "reporte-ventas", texto: "Ventas del día", icono: "grafica", grupo: "Reportes", ruta: "/reporte-ventas", existe: true, roles: ["admin"] },
  { id: "reporte-caducidades", texto: "Productos por caducar", icono: "reloj", grupo: "Reportes", ruta: "/inventario?vista=por-caducar", existe: true, roles: ["admin", "bodega"] },
  { id: "faltantes", texto: "Faltantes por proveedor (Excel)", icono: "camion", grupo: "Reportes", ruta: "/faltantes", existe: true, roles: ["admin", "bodega"] },

  { id: "usuarios", texto: "Usuarios", icono: "usuarios", grupo: "Configuración", ruta: "/usuarios", existe: true, roles: ["admin"] },
  { id: "mi-password", texto: "Cambiar mi contraseña", icono: "candado", grupo: "Configuración", accion: "miPassword", existe: true, roles: TODOS },
  { id: "cajas", texto: "Cajas e impresoras", icono: "impresora", grupo: "Configuración", ruta: "/cajas-impresoras", existe: true, roles: ["admin"] },
  { id: "terminal", texto: "Terminal Mercado Pago", icono: "tarjeta", grupo: "Configuración", ruta: "/terminal-mp", existe: true, roles: ["admin"] },
  { id: "negocio", texto: "Datos del negocio", icono: "tienda", grupo: "Configuración", ruta: "/negocio-datos", existe: true, roles: ["admin"] },
  { id: "imagen", texto: "Imagen de inicio", icono: "imagen", grupo: "Configuración", accion: "imagen", existe: true, roles: ["admin"] },
  { id: "ia", texto: "Asistente de IA (clave de Claude)", icono: "chispa", grupo: "Configuración", accion: "ia", existe: true, roles: ["admin"] },
  { id: "entrada-directa", texto: "Entrar directo a Vender en esta computadora", icono: "rayo", grupo: "Configuración", accion: "entradaDirecta", existe: true, roles: ["admin", "mostrador"] },

  { id: "teclas", texto: "Teclas del sistema", icono: "teclado", grupo: "Ayuda", accion: "teclas", existe: true, roles: TODOS },
  { id: "acerca", texto: "Acerca del sistema", icono: "info", grupo: "Ayuda", accion: "acerca", existe: true, roles: TODOS },
];

function seccionesDe(rol) {
  return SECCIONES.filter((s) => s.roles.includes(rol));
}

// A dónde llevar al usuario al iniciar sesión.
function paginaDeEntrada(rol) {
  const vender = SECCIONES.find((s) => s.id === "venta");
  return EntradaDirecta.activa() && vender.roles.includes(rol) ? vender.ruta : "/inicio";
}

// El logo del negocio en lugar de la cruz (si ya se subió uno). Si la imagen
// no carga, se queda la cruz.
function ponerLogo(contenedor, url) {
  if (!contenedor || !url) return;
  const img = new Image();
  img.alt = "";
  img.onload = () => {
    contenedor.replaceChildren(img);
    contenedor.classList.add("con-imagen");
  };
  img.src = url;
}

// --- Barra superior de las pantallas ---------------------------------------
// <header class="barra" data-pagina="venta"></header> se dibuja sola al cargar.
// Lleva "Inicio" y las pantallas que ya existen y que el rol puede usar; en
// ventanas angostas los enlaces quedan solo con ícono, y en muy angostas se
// guardan en un botón "Menú".

async function pintarBarra() {
  const barra = document.querySelector("header.barra[data-pagina]");
  if (!barra) return;
  const actual = barra.dataset.pagina;
  barra.innerHTML = `
    <a class="marca" href="/inicio" title="Ir a la pantalla de inicio"><span class="logo">${icono("cruz", "")}</span><span data-negocio>Farmacia</span></a>
    <button type="button" class="boton-menu" aria-expanded="false">${icono("menu")}Menú</button>
    <nav></nav>
    <button type="button" class="boton-precio" title="Consultar precio (F8)" onclick="abrirConsultaPrecio()">${icono("precio")}<span>Precio</span></button>
    <a class="campana" href="/notificaciones" title="Notificaciones" hidden>${icono("campana", "")}<span class="numero"></span></a>
    <span class="usuario" data-usuario></span>
    <button type="button" class="salir" onclick="cerrarSesion()" title="Cerrar sesión">${icono("salir")}<span>Salir</span></button>`;
  const nav = barra.querySelector("nav");
  montarConsultaPrecio();
  barra.addEventListener("click", (ev) => {
    if (ev.target.closest("a[href]") && !Salida.permitir()) ev.preventDefault();
  });
  const botonMenu = barra.querySelector(".boton-menu");
  botonMenu.addEventListener("click", () => {
    const abierta = barra.classList.toggle("menu-abierto");
    botonMenu.setAttribute("aria-expanded", String(abierta));
  });
  const enlace = (ruta, texto, nombreIcono, activo) =>
    `<a href="${ruta}" class="${activo ? "activo" : ""}" title="${escapar(texto)}">${icono(nombreIcono)}<span>${escapar(texto)}</span></a>`;
  nav.innerHTML = enlace("/inicio", "Inicio", "casa", actual === "inicio");
  try {
    const [usuario, negocio] = await Promise.all([API.get("/auth/yo"), API.get("/negocio")]);
    barra.querySelector("[data-negocio]").textContent = negocio.nombre;
    ponerLogo(barra.querySelector(".marca .logo"), negocio.marca_url);
    if (usuario.rol === "admin") {
      vigilarSolicitudes(barra.querySelector(".campana"));
      montarAsistente();
    }
    nav.innerHTML += seccionesDe(usuario.rol)
      // Notificaciones va en la campana; las rutas con "?" son vistas de otra
      // pantalla, y los reportes se sacan desde Inicio.
      .filter((s) => s.ruta && s.existe && s.id !== "notificaciones" && !s.ruta.includes("?") && s.grupo !== "Reportes")
      .map((s) => enlace(s.ruta, s.texto, s.icono, s.id === actual))
      .join("");
    const nombre = usuario.nombre_completo || usuario.nombre_usuario;
    barra.querySelector("[data-usuario]").innerHTML =
      `<span class="avatar">${escapar(nombre.trim().charAt(0).toUpperCase())}</span>` +
      `<span>${escapar(nombre)}<small>${escapar(ROLES[usuario.rol] || usuario.rol)}</small></span>`;
  } catch {
    /* sin sesión: API ya manda al login */
  }
  compactarBarra(barra);
  window.addEventListener("resize", () => compactarBarra(barra));
}

// Deja los enlaces solo con ícono cuando con su nombre no caben, para que no
// se encimen sobre la campana y el usuario ni corten el nombre del negocio.
function compactarBarra(barra) {
  barra.classList.remove("compacta", "minima");
  const nav = barra.querySelector("nav");
  const marca = barra.querySelector("[data-negocio]");
  const noCabe = () => nav.scrollWidth > nav.clientWidth + 1 || marca.scrollWidth > marca.clientWidth + 1;
  if (noCabe()) barra.classList.add("compacta");
  // Si ni así cabe, también sin nombre la pantalla actual, Inicio y el botón de precio.
  if (noCabe()) barra.classList.add("minima");
}

// --- Campana de notificaciones (solo administradores) ----------------------
// Cuenta lo que espera a un administrador (devoluciones por autorizar y
// ventas sin existencia registrada) y lo muestra en la barra (y en el título
// de la pestaña) desde cualquier pantalla. Se revisa cada 20 segundos.

function vigilarSolicitudes(campana) {
  const revisar = async () => {
    let n = 0;
    try {
      n = (await API.get("/notificaciones/pendientes")).total;
    } catch {
      return; // sin conexión: se queda como estaba
    }
    campana.hidden = false;
    campana.classList.toggle("con-pendientes", n > 0);
    campana.querySelector(".numero").textContent = n > 0 ? String(n) : "";
    campana.title = n === 0 ? "No hay nada pendiente" : `${n} ${n === 1 ? "pendiente" : "pendientes"} en Notificaciones`;
    document.title = (n > 0 ? `(${n}) ` : "") + document.title.replace(/^\(\d+\) /, "");
    document.dispatchEvent(new CustomEvent("solicitudes-pendientes", { detail: n }));
  };
  window.revisarCampana = revisar; // para actualizarla en cuanto se resuelve algo
  revisar();
  setInterval(revisar, 20000);
}

document.addEventListener("DOMContentLoaded", pintarBarra);

// --- Consultar precio (todos) -----------------------------------------------
// Ventana para escanear un código (o buscar por nombre) y ver el precio de
// venta, sin tocar la venta en curso. Se abre con F8 desde cualquier pantalla
// con barra, con el botón de la etiqueta en la barra o desde Inicio → Ventas.

function montarConsultaPrecio() {
  if (window.abrirConsultaPrecio) return;
  let raiz = null;
  let anterior = null; // lo que tenía el foco, para regresarlo al cerrar
  let resultados = [];
  let elegido = -1;
  let espera = null;

  const crear = () => {
    raiz = document.createElement("div");
    raiz.className = "velo arriba consulta-precio";
    raiz.hidden = true;
    raiz.innerHTML = `
      <div class="panel consulta-precio-panel" role="dialog" aria-label="Consultar precio">
        <div class="encabezado">
          <span class="circulo">${icono("precio", "")}</span>
          <div><h2>Consultar precio</h2><p class="suave">Escanea el código o escribe el nombre.</p></div>
          <button type="button" class="cerrar-consulta" title="Cerrar (Esc)">${icono("tache")}</button>
        </div>
        <div class="buscador"><span class="lupa">${icono("codigo", "")}</span><input type="text" autocomplete="off" placeholder="Código de barras o nombre del producto"></div>
        <div class="consulta-resultados"></div>
        <div class="consulta-ficha" hidden></div>
        <p class="consulta-pie"><kbd>↑</kbd> <kbd>↓</kbd> elegir · <kbd>Enter</kbd> ver precio · <kbd>Esc</kbd> cerrar</p>
      </div>`;
    document.body.append(raiz);
    raiz.addEventListener("click", (ev) => { if (ev.target === raiz) cerrar(); });
    // Las teclas del popup no llegan a la pantalla de atrás (ej. Enter cobraría en Vender).
    raiz.addEventListener("keydown", (ev) => ev.stopPropagation());
    raiz.querySelector(".cerrar-consulta").addEventListener("click", cerrar);
    const campo = raiz.querySelector("input");
    campo.addEventListener("input", () => {
      clearTimeout(espera);
      espera = setTimeout(() => buscar(campo.value), 250);
    });
    campo.addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
        ev.preventDefault();
        if (!resultados.length) return;
        elegido = (elegido + (ev.key === "ArrowDown" ? 1 : -1) + resultados.length) % resultados.length;
        pintarResultados();
      } else if (ev.key === "Enter") {
        ev.preventDefault();
        clearTimeout(espera);
        enter(campo.value);
      }
    });
    raiz.querySelector(".consulta-resultados").addEventListener("click", (ev) => {
      const boton = ev.target.closest("button[data-i]");
      if (boton) mostrar(resultados[Number(boton.dataset.i)]);
    });
  };

  const campo = () => raiz.querySelector("input");
  const pintarResultados = () => {
    const caja = raiz.querySelector(".consulta-resultados");
    caja.innerHTML = resultados.map((p, i) => `
      <button type="button" data-i="${i}" class="${i === elegido ? "elegido" : ""}">
        <span>${escapar(p.nombre)}<small>${escapar(p.clave || "sin clave")}</small></span>
        <strong>${p.precio_venta ? dinero(p.precio_venta) : "Sin precio"}</strong>
      </button>`).join("");
  };
  const limpiarResultados = () => {
    resultados = [];
    elegido = -1;
    pintarResultados();
  };

  async function buscar(texto) {
    const q = texto.trim();
    if (q.length < 2) return limpiarResultados();
    try {
      const lista = await API.get(`/productos?q=${encodeURIComponent(q)}&solo_activos=true&limite=8`);
      if (campo().value.trim() !== q) return; // ya se escribió otra cosa
      resultados = lista;
      elegido = lista.length ? 0 : -1;
      pintarResultados();
    } catch { /* se reintenta al seguir escribiendo */ }
  }

  async function enter(texto) {
    const q = texto.trim();
    if (!q) return;
    if (elegido >= 0 && resultados[elegido] && !/^\d{6,}$/.test(q)) return mostrar(resultados[elegido]);
    try {
      // Lo que manda el escáner: primero por código exacto; si no, por nombre.
      const porClave = await API.get(`/productos?clave=${encodeURIComponent(q)}&limite=1`);
      if (porClave.length) return mostrar(porClave[0]);
      const lista = await API.get(`/productos?q=${encodeURIComponent(q)}&solo_activos=true&limite=8`);
      if (lista.length === 1) return mostrar(lista[0]);
      resultados = lista;
      elegido = lista.length ? 0 : -1;
      pintarResultados();
      if (!lista.length) ficha(`<div class="mensaje aviso">${icono("alerta")}<span>No se encontró ningún producto con «${escapar(q)}».</span></div>`);
    } catch (e) {
      ficha(`<div class="mensaje error">${icono("alerta")}<span>${escapar(e.message)}</span></div>`);
    }
  }

  const ficha = (html) => {
    const caja = raiz.querySelector(".consulta-ficha");
    caja.innerHTML = html;
    caja.hidden = !html;
  };

  async function mostrar(p) {
    limpiarResultados();
    const c = campo();
    c.value = "";
    c.focus();
    let existencia = null;
    let oferta = null;
    try {
      [existencia, oferta] = await Promise.all([
        API.get(`/inventario/productos/${p.id}`),
        API.get(`/ofertas/producto/${p.id}`).catch(() => null),
      ]);
    } catch { /* el precio se muestra aunque no se pueda leer la existencia */ }
    let textoOferta = "";
    if (oferta) {
      const fin = new Date(oferta.fin + "T12:00").toLocaleDateString("es-MX", { day: "numeric", month: "long" });
      const detalle = oferta.precio ? `: ${dinero(oferta.precio)} por pieza` : oferta.paquete_precio ? `: ${dinero(oferta.paquete_precio)} los dos` : "";
      textoOferta = `<p class="consulta-oferta">${icono("precio")} ${escapar(oferta.texto)}${detalle} · hasta el ${fin}</p>`;
    }
    const exist = existencia ? Number(existencia.existencia_registrada) : null;
    ficha(`
      <div class="consulta-nombre">${escapar(p.nombre)}</div>
      <div class="suave">${escapar(p.clave || "sin clave")}${p.laboratorio ? " · " + escapar(p.laboratorio) : ""}</div>
      <div class="consulta-cifras">
        <div><span>Precio de venta</span><strong class="consulta-precio-grande">${p.precio_venta ? dinero(p.precio_venta) : "Sin precio"}</strong>
          <small>${Number(p.iva_porcentaje) || Number(p.ieps_porcentaje) ? "ya incluye impuestos" : "&nbsp;"}</small></div>
        <div><span>Existencia</span><strong class="${exist !== null && exist <= 0 ? "agotado" : ""}">${exist === null ? "—" : cantidad(exist)}</strong>
          <small>${exist !== null && exist <= 0 ? "sin existencia registrada" : "&nbsp;"}</small></div>
      </div>
      ${textoOferta}
      ${p.requiere_receta ? `<p class="consulta-receta">${icono("receta")} Pide receta médica</p>` : ""}`);
  }

  function abrir() {
    if (!raiz) crear();
    if (raiz.hidden) {
      anterior = document.activeElement;
      raiz.hidden = false;
      ficha("");
      limpiarResultados();
      campo().value = "";
    }
    campo().focus();
  }

  function cerrar() {
    if (!raiz || raiz.hidden) return;
    raiz.hidden = true;
    if (anterior && document.contains(anterior)) anterior.focus();
  }

  window.abrirConsultaPrecio = abrir;
  // En captura para ganarle a los atajos de cada pantalla mientras está abierta.
  window.addEventListener("keydown", (ev) => {
    if (ev.key === "F8") {
      ev.preventDefault();
      abrir();
    } else if (raiz && !raiz.hidden && ev.key === "Escape") {
      ev.preventDefault();
      ev.stopImmediatePropagation();
      cerrar();
    }
  }, true);
}

// --- Asistente de IA (solo administradores) --------------------------------
// Botón flotante abajo a la izquierda (a la derecha está Cobrar) que abre un
// chat en un panel lateral. El asistente solo consulta: los números salen de
// consultas exactas a la base de datos (app/asistente/). Las conversaciones
// se guardan por usuario y se pueden retomar.

const NOMBRES_CONSULTA = {
  resumen_ventas: "ventas",
  productos_mas_vendidos: "más vendidos",
  productos_sin_movimiento: "sin movimiento",
  buscar_productos: "productos",
  existencia_producto: "existencia",
  por_caducar: "por caducar",
  estado_del_catalogo: "catálogo",
  cortes_de_caja: "cortes de caja",
  devoluciones: "devoluciones",
  entradas_de_mercancia: "entradas",
  pendientes: "pendientes",
};
const SUGERENCIAS = [
  "¿Cuánto vendimos hoy?",
  "¿Qué es lo más vendido de esta semana?",
  "¿Qué productos caducan en los próximos 3 meses?",
  "¿Qué tengo pendiente?",
];

// Texto de la IA a HTML seguro: se escapa todo y solo se da formato a
// **negritas**, listas con "- " o "1. " y párrafos.
function formatoAsistente(texto) {
  const lineas = escapar(texto).split("\n");
  let html = "";
  let lista = null;
  const cerrar = () => {
    if (lista) html += `</${lista}>`;
    lista = null;
  };
  for (const cruda of lineas) {
    const linea = cruda.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    const vineta = linea.match(/^\s*[-•]\s+(.*)$/);
    const numero = linea.match(/^\s*\d+[.)]\s+(.*)$/);
    if (vineta || numero) {
      const tipo = vineta ? "ul" : "ol";
      if (lista !== tipo) {
        cerrar();
        html += `<${tipo}>`;
        lista = tipo;
      }
      html += `<li>${(vineta || numero)[1]}</li>`;
    } else if (linea.trim()) {
      cerrar();
      html += `<p>${linea}</p>`;
    } else {
      cerrar();
    }
  }
  cerrar();
  return html;
}

function montarAsistente() {
  if (document.getElementById("asistente")) return;
  const raiz = document.createElement("div");
  raiz.id = "asistente";
  raiz.innerHTML = `
    <button type="button" class="asistente-boton" title="Asistente (pregúntale sobre el negocio)">${icono("chispa", "")}<span>Asistente</span></button>
    <aside class="asistente-panel" hidden aria-label="Asistente de IA">
      <header>
        <strong>${icono("chispa")} Asistente</strong>
        <button type="button" data-accion="historial" title="Conversaciones anteriores">Historial</button>
        <button type="button" data-accion="nueva" title="Empezar otra conversación">Nueva</button>
        <button type="button" data-accion="cerrar" class="cerrar" title="Cerrar">${icono("tache")}</button>
      </header>
      <div class="asistente-mensajes"></div>
      <form class="asistente-escribir">
        <textarea rows="2" placeholder="Pregunta sobre ventas, productos, caducidades, cortes…" maxlength="4000"></textarea>
        <button class="primario" title="Enviar (Enter)">${icono("enviar")}</button>
      </form>
      <p class="asistente-pie">Solo consulta; no cambia nada. Cada pregunta usa la API de Claude.</p>
    </aside>`;
  document.body.append(raiz);

  const boton = raiz.querySelector(".asistente-boton");
  // Si la pantalla tiene barra de estado abajo (Inicio), el botón va encima de ella.
  const pie = document.querySelector(".barra-estado");
  if (pie) {
    const subir = () => { boton.style.bottom = `${pie.offsetHeight + 12}px`; };
    subir();
    new ResizeObserver(subir).observe(pie);
  }
  const panel = raiz.querySelector(".asistente-panel");
  const zona = raiz.querySelector(".asistente-mensajes");
  const form = raiz.querySelector("form");
  const campo = form.querySelector("textarea");
  let conversacion = null;
  let ocupado = false;
  let configurada = null;

  // Lo que se escribe en el chat no debe llegar a los atajos de la pantalla (ej. Vender).
  panel.addEventListener("keydown", (ev) => {
    ev.stopPropagation();
    if (ev.key === "Escape") cerrarPanel();
  });

  const burbuja = (rol, html, extra = "") => {
    const div = document.createElement("div");
    div.className = `asistente-msg ${rol}`;
    div.innerHTML = html + extra;
    zona.append(div);
    zona.scrollTop = zona.scrollHeight;
    return div;
  };
  const etiquetas = (lista) => {
    const unicas = [...new Set(lista || [])];
    return unicas.length
      ? `<div class="asistente-consultas">Consultó: ${unicas.map((c) => escapar(NOMBRES_CONSULTA[c] || c)).join(", ")}</div>`
      : "";
  };

  const bienvenida = () => {
    zona.innerHTML = "";
    if (configurada === false) {
      burbuja("aviso", "<p>Falta la clave de la API de Claude. Ponla en <strong>Inicio → Configuración → Asistente de IA</strong>.</p>");
      return;
    }
    burbuja("asistente", "<p>Hola. Pregúntame sobre ventas, productos, existencias, caducidades, cortes, devoluciones, entradas o cómo usar el sistema.</p>");
    const sug = document.createElement("div");
    sug.className = "asistente-sugerencias";
    for (const s of SUGERENCIAS) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = s;
      b.addEventListener("click", () => enviar(s));
      sug.append(b);
    }
    zona.append(sug);
  };

  const abrirPanel = async () => {
    panel.hidden = false;
    boton.hidden = true;
    if (configurada === null) {
      try {
        configurada = (await API.get("/ia/estado")).configurada;
      } catch {
        configurada = false;
      }
    }
    if (!zona.childElementCount) bienvenida();
    campo.focus();
  };
  const cerrarPanel = () => {
    panel.hidden = true;
    boton.hidden = false;
  };

  const enviar = async (texto) => {
    texto = (texto || "").trim();
    if (!texto || ocupado) return;
    if (configurada === false) return bienvenida();
    const sugerencias = zona.querySelector(".asistente-sugerencias");
    if (sugerencias) sugerencias.remove();
    burbuja("usuario", `<p>${escapar(texto)}</p>`);
    campo.value = "";
    ocupado = true;
    const pensando = burbuja("asistente pensando", '<span class="girando"></span><span>Consultando…</span>');
    try {
      const r = await API.post("/asistente/preguntar", { texto, conversacion_id: conversacion });
      conversacion = r.conversacion_id;
      pensando.remove();
      burbuja("asistente", formatoAsistente(r.respuesta), etiquetas(r.consultas));
    } catch (e) {
      pensando.remove();
      burbuja("aviso", `<p>${escapar(e.message)}</p>`);
    } finally {
      ocupado = false;
      campo.focus();
    }
  };

  const historial = async () => {
    zona.innerHTML = "";
    const lista = await API.get("/asistente/conversaciones");
    if (!lista.length) {
      burbuja("aviso", "<p>Todavía no hay conversaciones.</p>");
      return;
    }
    const cont = document.createElement("div");
    cont.className = "asistente-historial";
    for (const c of lista) {
      const fila = document.createElement("div");
      fila.className = "fila-historial";
      fila.innerHTML = `<button type="button" class="abrir"><strong>${escapar(c.titulo)}</strong>
        <span>${new Date(c.updated_at).toLocaleString("es-MX", { dateStyle: "medium", timeStyle: "short" })}</span></button>
        <button type="button" class="borrar" title="Borrar">${icono("basura")}</button>`;
      fila.querySelector(".abrir").addEventListener("click", () => abrirConversacion(c.id));
      fila.querySelector(".borrar").addEventListener("click", async () => {
        await API.borrar(`/asistente/conversaciones/${c.id}`);
        if (conversacion === c.id) conversacion = null;
        historial();
      });
      cont.append(fila);
    }
    zona.append(cont);
  };

  const abrirConversacion = async (id) => {
    const mensajes = await API.get(`/asistente/conversaciones/${id}`);
    conversacion = id;
    zona.innerHTML = "";
    for (const m of mensajes) {
      if (m.rol === "usuario") burbuja("usuario", `<p>${escapar(m.texto)}</p>`);
      else burbuja("asistente", formatoAsistente(m.texto), etiquetas(m.consultas));
    }
    campo.focus();
  };

  boton.addEventListener("click", abrirPanel);
  raiz.querySelector('[data-accion="cerrar"]').addEventListener("click", cerrarPanel);
  raiz.querySelector('[data-accion="nueva"]').addEventListener("click", () => {
    conversacion = null;
    bienvenida();
    campo.focus();
  });
  raiz.querySelector('[data-accion="historial"]').addEventListener("click", () =>
    historial().catch((e) => burbuja("aviso", `<p>${escapar(e.message)}</p>`))
  );
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    enviar(campo.value);
  });
  campo.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      enviar(campo.value);
    }
  });
}
