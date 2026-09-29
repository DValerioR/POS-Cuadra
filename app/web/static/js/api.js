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
