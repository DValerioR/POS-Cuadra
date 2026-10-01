// Horario de atención en Datos del negocio (ver app/services/horario.py).
//
// En la pantalla se edita una forma cómoda y al guardar se convierte a la
// que guarda el servidor:
//   pantalla: { modo, turnos: ["Matutino", ...],
//               dias: { lunes: [{ activo, abre, cierra }, ...] },   // un renglón por turno
//               especiales: [{ fecha, tarde, abre, temprano, cierra, cerrado, nota }] }
//   servidor: { modo, turnos, semana: { lunes: [{ nombre, abre, cierra }] },
//               especiales: [{ fecha, abre, cierra, cerrado, nota }] }

const DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"];
const DIAS_CORTOS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
const TURNOS_SUGERIDOS = ["Matutino", "Vespertino", "Nocturno", "Cuarto turno"];

const aMinutos = (h) => Number(h.slice(0, 2)) * 60 + Number(h.slice(3, 5));
const aHora = (m) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
const fechaISO = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

function horarioAEditar(h) {
  if (!h) return null;
  const turnos = h.modo === "turnos" ? [...h.turnos] : [""];
  const dias = {};
  for (const d of DIAS) {
    const lista = h.semana[d] || [];
    dias[d] = turnos.map((nombre, i) => {
      const t = h.modo === "turnos" ? lista.find((x) => x.nombre === nombre) : lista[0];
      return t ? { activo: true, abre: t.abre, cierra: t.cierra } : { activo: false, ...horaSugerida(i, turnos.length) };
    });
  }
  const especiales = (h.especiales || []).map((e) => ({
    fecha: e.fecha, cerrado: !!e.cerrado, nota: e.nota || "",
    tarde: !!e.abre, abre: e.abre || "10:00", temprano: !!e.cierra, cierra: e.cierra || "18:00",
  }));
  return { modo: h.modo || "corrido", turnos: h.modo === "turnos" ? turnos : [], dias, especiales };
}

function horarioAGuardar(h) {
  if (!h) return null;
  const semana = {};
  for (const d of DIAS) {
    semana[d] = h.dias[d].flatMap((c, i) => c.activo
      ? [{ nombre: h.modo === "turnos" ? h.turnos[i].trim() : "", abre: c.abre, cierra: c.cierra }] : []);
  }
  return {
    modo: h.modo, turnos: h.modo === "turnos" ? h.turnos.map((n) => n.trim()) : [], semana,
    especiales: h.especiales.map((e) => ({
      fecha: e.fecha, cerrado: e.cerrado, nota: e.nota.trim() || null,
      abre: !e.cerrado && e.tarde ? e.abre : null, cierra: !e.cerrado && e.temprano ? e.cierra : null,
    })),
  };
}

// Horas que se proponen a un turno nuevo (el día de 08:00 a 22:00 repartido).
function horaSugerida(i, cuantos) {
  const paso = Math.floor((22 - 8) * 60 / cuantos);
  return { abre: aHora(8 * 60 + paso * i), cierra: aHora(i === cuantos - 1 ? 22 * 60 : 8 * 60 + paso * (i + 1)) };
}

// Los turnos del día con las reglas del día especial (igual que aplicar_reglas en Python).
function turnosConReglas(turnos, e) {
  if (!e) return turnos;
  if (e.cerrado) return [];
  return turnos.map((t) => ({
    ...t,
    abre: e.tarde && e.abre > t.abre ? e.abre : t.abre,
    cierra: e.temprano && e.cierra < t.cierra ? e.cierra : t.cierra,
  })).filter((t) => t.abre < t.cierra);
}

// Lo que ve el cliente: los turnos juntos (8-15 y 15-22 = de 8 a 22).
function enPalabras(turnos) {
  const tramos = [];
  for (const t of [...turnos].sort((a, b) => a.abre.localeCompare(b.abre))) {
    const ultimo = tramos[tramos.length - 1];
    if (ultimo && t.abre <= ultimo[1]) ultimo[1] = t.cierra > ultimo[1] ? t.cierra : ultimo[1];
    else tramos.push([t.abre, t.cierra]);
  }
  return tramos.length ? tramos.map(([a, c]) => `de ${a} a ${c}`).join(" y ") : "cerrado";
}

// Partes de la pantalla de Datos del negocio que manejan el horario
// (se mezclan en pantallaNegocio(); son métodos, no getters, para poder mezclarlos).
function horarioNegocio() {
  return {
    dias: DIAS,

    capturarHorario() {
      this.f.horario = horarioAEditar({
        modo: "corrido", turnos: [],
        semana: Object.fromEntries(DIAS.map((d) => [d, [{ nombre: "", abre: "08:00", cierra: "22:00" }]])),
        especiales: [],
      });
    },
    nombreDia(d) {
      return d.charAt(0).toUpperCase() + d.slice(1);
    },

    // --- Corrido o por turnos ---
    cambiarModo(modo) {
      const h = this.f.horario;
      if (h.modo === modo) return;
      if (modo === "turnos") {
        // El horario corrido de cada día se parte en dos turnos a la mitad.
        h.turnos = ["Matutino", "Vespertino"];
        for (const d of DIAS) {
          const c = h.dias[d][0];
          const mitad = aHora(Math.round((aMinutos(c.abre) + aMinutos(c.cierra)) / 2 / 30) * 30);
          h.dias[d] = [{ activo: c.activo, abre: c.abre, cierra: mitad }, { activo: c.activo, abre: mitad, cierra: c.cierra }];
        }
      } else {
        // Los turnos de cada día se juntan: de la primera entrada a la última salida.
        for (const d of DIAS) {
          const activos = h.dias[d].filter((c) => c.activo);
          h.dias[d] = [activos.length
            ? { activo: true, abre: activos.map((c) => c.abre).sort()[0], cierra: activos.map((c) => c.cierra).sort().pop() }
            : { activo: false, abre: "08:00", cierra: "22:00" }];
        }
        h.turnos = [];
      }
      h.modo = modo;
    },
    agregarTurno() {
      const h = this.f.horario;
      const nombre = TURNOS_SUGERIDOS.find((n) => !h.turnos.includes(n)) || `Turno ${h.turnos.length + 1}`;
      h.turnos.push(nombre);
      for (const d of DIAS) h.dias[d].push({ activo: false, ...horaSugerida(h.turnos.length - 1, h.turnos.length) });
    },
    quitarTurno(i) {
      const h = this.f.horario;
      if (h.turnos.length <= 1) return;
      h.turnos.splice(i, 1);
      for (const d of DIAS) h.dias[d].splice(i, 1);
    },
    copiarLunes() {
      const h = this.f.horario;
      for (const d of ["martes", "miércoles", "jueves", "viernes"]) h.dias[d] = JSON.parse(JSON.stringify(h.dias.lunes));
      this.avisar("Se copió el horario del lunes de martes a viernes.");
    },

    // --- Días especiales ---
    // Los 7 días de la semana actual (lunes a domingo), para marcarlos con un clic.
    semanaActual() {
      const hoy = new Date();
      hoy.setHours(0, 0, 0, 0);
      const lunes = new Date(hoy);
      lunes.setDate(hoy.getDate() - ((hoy.getDay() + 6) % 7));
      return DIAS.map((d, i) => {
        const dia = new Date(lunes);
        dia.setDate(lunes.getDate() + i);
        const fecha = fechaISO(dia);
        return { fecha, corto: DIAS_CORTOS[i], numero: dia.getDate(), pasado: dia < hoy, hoy: dia.getTime() === hoy.getTime(),
                 especial: this.f.horario.especiales.some((e) => e.fecha === fecha) };
      });
    },
    agregarEspecial(fecha = "") {
      const h = this.f.horario;
      if (fecha && h.especiales.some((e) => e.fecha === fecha)) return this.avisar("Ese día ya es especial; está abajo en la lista.");
      h.especiales.push({ fecha, cerrado: false, nota: "", tarde: true, abre: "10:00", temprano: false, cierra: "18:00" });
      if (fecha) this.proponerHoras(h.especiales[h.especiales.length - 1]);
      h.especiales.sort((a, b) => (a.fecha || "9999").localeCompare(b.fecha || "9999"));
    },
    // Al elegir la fecha, se proponen horas a partir del horario normal de ese día.
    proponerHoras(e) {
      const turnos = this.turnosNormales(e.fecha);
      if (!turnos.length) return;
      e.abre = aHora(Math.min(aMinutos(turnos[0].abre) + 120, 23 * 60));
      e.cierra = aHora(Math.max(aMinutos(turnos[turnos.length - 1].cierra) - 180, 60));
    },
    diaDeLaSemana(fecha) {
      return fecha ? DIAS[(new Date(fecha + "T12:00").getDay() + 6) % 7] : null;
    },
    turnosNormales(fecha) {
      const h = this.f.horario;
      const d = this.diaDeLaSemana(fecha);
      if (!d) return [];
      return h.dias[d].flatMap((c, i) => c.activo ? [{ nombre: h.modo === "turnos" ? h.turnos[i] : "", abre: c.abre, cierra: c.cierra }] : [])
        .sort((a, b) => a.abre.localeCompare(b.abre));
    },
    // Cómo queda ese día con sus reglas, en palabras.
    resultadoEspecial(e) {
      if (!e.fecha) return "Elige la fecha.";
      const normales = this.turnosNormales(e.fecha);
      if (!normales.length) return `Ese día de la semana (${this.diaDeLaSemana(e.fecha)}) normalmente no se abre.`;
      const turnos = turnosConReglas(normales, e);
      if (!turnos.length) return "Ese día no se abre.";
      if (this.f.horario.modo !== "turnos") return `Ese día se abre ${enPalabras(turnos)}.`;
      const quedan = turnos.map((t) => `${t.nombre} de ${t.abre} a ${t.cierra}`);
      const fuera = normales.filter((n) => !turnos.some((t) => t.nombre === n.nombre)).map((n) => n.nombre);
      return `Ese día: ${quedan.join(" · ")}${fuera.length ? ` (no se abre: ${fuera.join(", ")})` : ""}.`;
    },
    fechaLarga(fecha) {
      if (!fecha) return "";
      return new Date(fecha + "T12:00").toLocaleDateString("es-MX", { weekday: "long", day: "numeric", month: "long" });
    },

    // El horario en palabras, como lo dirá el bot (igual que services/horario.py).
    horarioTexto() {
      const h = this.f && this.f.horario;
      if (!h) return "";
      const grupos = [];
      DIAS.forEach((d, i) => {
        const texto = enPalabras(h.dias[d].filter((c) => c.activo));
        const ultimo = grupos[grupos.length - 1];
        if (ultimo && ultimo.texto === texto) ultimo.fin = i;
        else grupos.push({ ini: i, fin: i, texto });
      });
      const frase = grupos.map((g) => (g.ini === g.fin ? DIAS[g.ini] : g.fin === g.ini + 1 ? `${DIAS[g.ini]} y ${DIAS[g.fin]}` : `${DIAS[g.ini]} a ${DIAS[g.fin]}`) + " " + g.texto).join("; ");
      return frase.charAt(0).toUpperCase() + frase.slice(1) + ".";
    },
  };
}
