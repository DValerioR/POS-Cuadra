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

async function cerrarSesion() {
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
  { id: "devoluciones", texto: "Devoluciones y cambios", icono: "regresar", grupo: "Ventas", ruta: "/devoluciones", existe: true, roles: ["admin"] },

  { id: "inventario", texto: "Inventario y caducidades", icono: "paquete", grupo: "Inventario", ruta: "/inventario", existe: false, roles: ["admin", "bodega"], tecla: "F3" },
  { id: "entradas", texto: "Entradas de mercancía", icono: "camion", grupo: "Inventario", ruta: "/entradas", existe: false, roles: ["admin", "bodega"], tecla: "F4" },
  { id: "productos", texto: "Productos y precios", icono: "precio", grupo: "Inventario", ruta: "/productos", existe: false, roles: ["admin"] },

  { id: "reporte-ventas", texto: "Ventas del día", icono: "grafica", grupo: "Reportes", ruta: "/reportes/ventas", existe: false, roles: ["admin"] },
  { id: "reporte-caducidades", texto: "Productos por caducar", icono: "reloj", grupo: "Reportes", ruta: "/reportes/caducidades", existe: false, roles: ["admin"] },

  { id: "usuarios", texto: "Usuarios", icono: "usuarios", grupo: "Configuración", ruta: "/usuarios", existe: false, roles: ["admin"] },
  { id: "cajas", texto: "Cajas e impresoras", icono: "impresora", grupo: "Configuración", ruta: "/cajas", existe: false, roles: ["admin"] },
  { id: "negocio", texto: "Datos del negocio", icono: "tienda", grupo: "Configuración", ruta: "/negocio-datos", existe: false, roles: ["admin"] },
  { id: "imagen", texto: "Imagen de inicio", icono: "imagen", grupo: "Configuración", accion: "imagen", existe: true, roles: ["admin"] },
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
    <span class="usuario" data-usuario></span>
    <button type="button" class="salir" onclick="cerrarSesion()" title="Cerrar sesión">${icono("salir")}<span>Salir</span></button>`;
  const nav = barra.querySelector("nav");
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
    nav.innerHTML += seccionesDe(usuario.rol)
      .filter((s) => s.ruta && s.existe)
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

document.addEventListener("DOMContentLoaded", pintarBarra);
