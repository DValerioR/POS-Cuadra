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
      location.href = "/login?volver=" + encodeURIComponent(location.pathname);
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

  { id: "inventario", texto: "Inventario y caducidades", icono: "paquete", grupo: "Inventario", ruta: "/inventario", existe: true, roles: ["admin", "bodega"], tecla: "F3" },
  { id: "entradas", texto: "Entradas de mercancía", icono: "camion", grupo: "Inventario", ruta: "/mercancia", existe: true, roles: ["admin", "bodega"], tecla: "F4" },
  { id: "productos", texto: "Productos y precios", icono: "precio", grupo: "Inventario", ruta: "/catalogo", existe: true, roles: ["admin"] },

  { id: "reporte-ventas", texto: "Ventas del día", icono: "grafica", grupo: "Reportes", ruta: "/reportes/ventas", existe: false, roles: ["admin"] },
  { id: "reporte-caducidades", texto: "Productos por caducar", icono: "reloj", grupo: "Reportes", ruta: "/inventario?vista=por-caducar", existe: true, roles: ["admin", "bodega"] },

  { id: "usuarios", texto: "Usuarios", icono: "usuarios", grupo: "Configuración", ruta: "/usuarios", existe: false, roles: ["admin"] },
  { id: "cajas", texto: "Cajas e impresoras", icono: "impresora", grupo: "Configuración", ruta: "/cajas", existe: false, roles: ["admin"] },
  { id: "negocio", texto: "Datos del negocio", icono: "tienda", grupo: "Configuración", ruta: "/negocio-datos", existe: false, roles: ["admin"] },
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
    <a class="campana" href="/notificaciones" title="Notificaciones" hidden>${icono("campana", "")}<span class="numero"></span></a>
    <span class="usuario" data-usuario></span>
    <button type="button" class="salir" onclick="cerrarSesion()" title="Cerrar sesión">${icono("salir")}<span>Salir</span></button>`;
  const nav = barra.querySelector("nav");
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
    if (usuario.rol === "admin") vigilarSolicitudes(barra.querySelector(".campana"));
    nav.innerHTML += seccionesDe(usuario.rol)
      // Notificaciones va en la campana; las rutas con "?" son vistas de otra pantalla.
      .filter((s) => s.ruta && s.existe && s.id !== "notificaciones" && !s.ruta.includes("?"))
      .map((s) => enlace(s.ruta, s.texto, s.icono, s.id === actual))
      .join("");
    const nombre = usuario.nombre_completo || usuario.nombre_usuario;
    barra.querySelector("[data-usuario]").innerHTML =
      `<span class="avatar">${escapar(nombre.trim().charAt(0).toUpperCase())}</span>` +
      `<span>${escapar(nombre)}<small>${escapar(ROLES[usuario.rol] || usuario.rol)}</small></span>`;
  } catch {
    /* sin sesión: API ya manda al login */
  }
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
