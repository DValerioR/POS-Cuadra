// Utilidades comunes de las pantallas: llamadas al API, formato y la caja
// de esta computadora.

const API = {
  async pedir(metodo, ruta, cuerpo) {
    const respuesta = await fetch(ruta, {
      method: metodo,
      headers: cuerpo === undefined ? {} : { "Content-Type": "application/json" },
      body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo),
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

// Barra superior común: <header class="barra" data-pagina="venta"></header>.
// Se dibuja sola al cargar la página; así todas las pantallas se ven igual
// y agregar una sección nueva es cambiar solo esta lista.
const SECCIONES = [
  { pagina: "venta", texto: "Vender", icono: "carrito" },
  { pagina: "turno", texto: "Turno y corte", icono: "caja" },
];

function escapar(texto) {
  const div = document.createElement("div");
  div.textContent = texto ?? "";
  return div.innerHTML;
}

async function pintarBarra() {
  const barra = document.querySelector("header.barra[data-pagina]");
  if (!barra) return;
  const actual = barra.dataset.pagina;
  const enlaces = SECCIONES.map(
    (s) => `<a href="/${s.pagina}" class="${s.pagina === actual ? "activo" : ""}">${icono(s.icono)}${s.texto}</a>`
  ).join("");
  barra.innerHTML = `
    <span class="marca"><span class="logo">${icono("cruz", "")}</span><span data-negocio>Farmacia</span></span>
    <nav>${enlaces}</nav>
    <span class="usuario" data-usuario></span>
    <button type="button" onclick="cerrarSesion()">${icono("salir")}Salir</button>`;
  try {
    const [usuario, negocio] = await Promise.all([API.get("/auth/yo"), API.get("/negocio")]);
    barra.querySelector("[data-negocio]").textContent = negocio.nombre;
    const nombre = usuario.nombre_completo || usuario.nombre_usuario;
    barra.querySelector("[data-usuario]").innerHTML =
      `<span class="avatar">${escapar(nombre.trim().charAt(0).toUpperCase())}</span>` +
      `<span>${escapar(nombre)}<small>${escapar(ROLES[usuario.rol] || usuario.rol)}</small></span>`;
  } catch {
    /* sin sesión: API ya manda al login */
  }
}

const ROLES = { admin: "Administrador", mostrador: "Mostrador", bodega: "Bodega" };

document.addEventListener("DOMContentLoaded", pintarBarra);
