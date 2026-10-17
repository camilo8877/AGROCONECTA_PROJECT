// AgroConecta · frontend de demostración. Todas las llamadas pasan por el API Gateway.
const API = (window.API_URL || "http://localhost:8000").replace(/\/$/, "");
const DEMO = {
  comprador: ["comprador@agroconecta.co", "Comprador123*"],
  productor: ["productor@agroconecta.co", "Productor123*"],
  admin: ["admin@agroconecta.co", "Admin123*"],
};
const $ = (s) => document.querySelector(s);
const pesos = (n) => "$" + Number(n || 0).toLocaleString("es-CO", { maximumFractionDigits: 0 });
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let sesion = null;
let carrito = {};
let productosCache = [];
let intervaloSalud = null;

try { sesion = JSON.parse(sessionStorage.getItem("agro_sesion") || "null"); } catch { sesion = null; }

// ---------- utilidades ----------
async function api(ruta, opciones = {}) {
  const headers = { "Content-Type": "application/json", ...(opciones.headers || {}) };
  if (sesion?.token) headers.Authorization = `Bearer ${sesion.token}`;
  const r = await fetch(API + ruta, { ...opciones, headers });
  let datos = null;
  try { datos = await r.json(); } catch { datos = null; }
  if (r.status === 401 && sesion) { cerrarSesion(); throw new Error("La sesión expiró, ingresa de nuevo"); }
  return { ok: r.ok, status: r.status, datos };
}
function detalle(res) {
  const d = res.datos?.detail;
  if (Array.isArray(d)) return d.map((x) => x.msg).join(", ");
  return d || res.datos?.motivo_cancelacion || `Error ${res.status}`;
}
let avisoTimer;
function avisar(texto, error = false) {
  const el = $("#aviso");
  el.textContent = texto;
  el.className = "aviso" + (error ? " error" : "");
  clearTimeout(avisoTimer);
  avisoTimer = setTimeout(() => el.classList.add("oculto"), 4500);
}
function datosForm(form) {
  return Object.fromEntries(new FormData(form).entries());
}

// ---------- sesión ----------
async function entrar(email, clave) {
  const r = await api("/api/auth/login", { method: "POST", body: JSON.stringify({ email, clave }) });
  if (!r.ok) return avisar(detalle(r), true);
  iniciarSesion(r.datos);
}
function iniciarSesion(datos) {
  sesion = { token: datos.access_token, usuario: datos.usuario };
  try { sessionStorage.setItem("agro_sesion", JSON.stringify(sesion)); } catch { /* sin almacenamiento */ }
  carrito = {};
  mostrarApp();
}
function cerrarSesion() {
  sesion = null;
  try { sessionStorage.removeItem("agro_sesion"); } catch { /* sin almacenamiento */ }
  clearInterval(intervaloSalud);
  $("#vista-app").classList.add("oculto");
  $("#vista-acceso").classList.remove("oculto");
  $("#sesion").innerHTML = "";
}

// ---------- navegación ----------
function pestanasPorRol(rol) {
  const t = [["catalogo", "🛒 Catálogo"]];
  if (rol === "comprador") t.push(["pedidos", "📦 Mis pedidos"]);
  if (rol === "productor") t.push(["pedidos", "📦 Pedidos recibidos"], ["productor", "🧑‍🌾 Mis productos"]);
  if (rol === "admin") t.push(["pedidos", "📦 Todos los pedidos"], ["admin", "🛠️ Administración"]);
  t.push(["arquitectura", "🧩 Arquitectura en vivo"]);
  return t;
}
function mostrarApp() {
  $("#vista-acceso").classList.add("oculto");
  $("#vista-app").classList.remove("oculto");
  const u = sesion.usuario;
  $("#sesion").innerHTML = `<span>${esc(u.nombre)} · <b>${esc(u.rol)}</b></span><button id="btn-salir">Salir</button>`;
  $("#btn-salir").onclick = cerrarSesion;
  const nav = $("#pestanas");
  nav.innerHTML = pestanasPorRol(u.rol).map(([id, t]) => `<button data-tab="${id}">${t}</button>`).join("");
  nav.querySelectorAll("button").forEach((b) => (b.onclick = () => abrirTab(b.dataset.tab)));
  $("#carrito").classList.toggle("oculto", u.rol !== "comprador");
  abrirTab("catalogo");
}
function abrirTab(id) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.add("oculto"));
  $(`#tab-${id}`).classList.remove("oculto");
  document.querySelectorAll("#pestanas button").forEach((b) => b.classList.toggle("activa", b.dataset.tab === id));
  clearInterval(intervaloSalud);
  if (id === "catalogo") cargarCatalogo();
  if (id === "pedidos") cargarPedidos();
  if (id === "productor") cargarPanelProductor();
  if (id === "admin") cargarAdmin();
  if (id === "arquitectura") { cargarArquitectura(); intervaloSalud = setInterval(cargarArquitectura, 5000); }
}

// ---------- catálogo (CU-04) ----------
async function cargarCategorias(select, conTodas) {
  const r = await api("/api/categorias");
  if (!r.ok) return;
  select.innerHTML = (conTodas ? '<option value="">Todas las categorías</option>' : "") +
    r.datos.map((c) => `<option value="${c.id}">${esc(c.nombre)}</option>`).join("");
}
async function cargarCatalogo() {
  if ($("#f-categoria").options.length <= 1) await cargarCategorias($("#f-categoria"), true);
  const p = new URLSearchParams();
  if ($("#f-categoria").value) p.set("categoria_id", $("#f-categoria").value);
  if ($("#f-municipio").value.trim()) p.set("municipio", $("#f-municipio").value.trim());
  if ($("#f-disponibles").checked) p.set("solo_disponibles", "true");
  const r = await api("/api/productos?" + p);
  if (!r.ok) return avisar(detalle(r), true);
  productosCache = r.datos;
  const comprador = sesion.usuario.rol === "comprador";
  $("#productos").innerHTML = r.datos.map((x) => {
    const clase = x.disponible === 0 ? "agotado" : x.disponible <= 5 ? "bajo" : "";
    return `<article class="producto">
      <span class="cat">${esc(x.categoria)}</span>
      <h4>${esc(x.nombre)}</h4>
      <span class="sutil">${esc(x.finca)} · ${esc(x.municipio)}</span>
      <span class="precio">${pesos(x.precio)} <small class="sutil">/ ${esc(x.unidad)}</small></span>
      <span class="stock ${clase}">${x.disponible === 0 ? "Agotado" : `${x.disponible} ${esc(x.unidad)} disponibles`}</span>
      ${comprador ? `<div class="comprar"><input type="number" min="1" max="${x.disponible}" value="1" id="q-${x.id}">
        <button class="primario" data-agregar="${x.id}" ${x.disponible === 0 ? "disabled" : ""}>Agregar</button></div>` : ""}
    </article>`;
  }).join("") || '<p class="sutil">No hay productos con esos filtros.</p>';
  document.querySelectorAll("[data-agregar]").forEach((b) => (b.onclick = () => {
    const cant = parseInt($(`#q-${b.dataset.agregar}`).value, 10) || 1;
    carrito[b.dataset.agregar] = (carrito[b.dataset.agregar] || 0) + cant;
    pintarCarrito();
  }));
  pintarCarrito();
}
function pintarCarrito() {
  const items = Object.entries(carrito);
  let total = 0;
  const filas = items.map(([id, cant]) => {
    const p = productosCache.find((x) => x.id === id);
    if (!p) return "";
    total += p.precio * cant;
    return `<div class="item"><span>${cant} × ${esc(p.nombre)}</span><span>${pesos(p.precio * cant)}
      <button data-quitar="${id}" title="Quitar">✕</button></span></div>`;
  }).join("");
  $("#carrito").innerHTML = `<h3>Tu pedido</h3>${filas || '<p class="sutil">Agrega productos del catálogo.</p>'}
    <div class="total"><span>Total</span><span>${pesos(total)}</span></div>
    <button class="primario" id="btn-pedir" ${items.length ? "" : "disabled"}>Realizar pedido y pagar</button>
    <div id="resultado-pedido"></div>`;
  document.querySelectorAll("[data-quitar]").forEach((b) => (b.onclick = () => { delete carrito[b.dataset.quitar]; pintarCarrito(); }));
  const btn = $("#btn-pedir");
  if (btn) btn.onclick = realizarPedido;
}

// ---------- pedidos (CU-05 a CU-09) ----------
async function realizarPedido() {
  const btn = $("#btn-pedir");
  btn.disabled = true;
  btn.textContent = "Procesando Saga…";
  const items = Object.entries(carrito).map(([producto_id, cantidad]) => ({ producto_id, cantidad }));
  const r = await api("/api/pedidos", { method: "POST", body: JSON.stringify({ items }) });
  if (r.datos?.estado === "PAGADO") {
    carrito = {};
    avisar("✅ Pedido pagado. Revisa “Mis pedidos” para seguir su estado.");
  } else {
    avisar("Pedido no completado: " + detalle(r), true);
  }
  await cargarCatalogo();
  if (r.datos?.id) $("#resultado-pedido").innerHTML = tarjetaPedido(r.datos);
}
function pasosSaga(saga) {
  if (!saga) return "";
  const h = saga.historial || [];
  return `<div class="saga"><small class="sutil">Saga:</small>${h.map((x, i) => {
    const fin = i === h.length - 1 ? (x.paso === "COMPLETADA" ? "fin-ok" : x.paso.includes("PENDIENTE") || x.paso === "COMPENSADA" || x.paso === "CANCELADA" ? "fin-mal" : "") : "";
    return `<span class="${fin}" title="${esc(x.detalle)}">${esc(x.paso)}</span>`;
  }).join("→")}</div>`;
}
function tarjetaPedido(p) {
  const rol = sesion.usuario.rol;
  const acciones = [];
  if ((rol === "productor" || rol === "admin") && p.estado === "PAGADO") acciones.push(["DESPACHADO", "Marcar despachado"]);
  if ((rol === "productor" || rol === "admin") && p.estado === "DESPACHADO") acciones.push(["ENTREGADO", "Marcar entregado"]);
  return `<article class="pedido">
    <header><b>Pedido #${esc(p.id.slice(0, 8))}</b><span class="insignia ${esc(p.estado)}">${esc(p.estado)}</span></header>
    <div class="sutil">${new Date(p.fecha).toLocaleString("es-CO")} · Total ${pesos(p.total)}</div>
    <div>${p.items.map((i) => `${i.cantidad} ${esc(i.unidad)} ${esc(i.nombre)}`).join(" · ")}</div>
    ${p.motivo_cancelacion ? `<div class="motivo">${esc(p.motivo_cancelacion)}</div>` : ""}
    ${pasosSaga(p.saga)}
    ${acciones.map(([e, t]) => `<button data-estado="${e}" data-pedido="${p.id}">${t}</button>`).join(" ")}
  </article>`;
}
async function cargarPedidos() {
  const r = await api("/api/pedidos");
  if (!r.ok) return avisar(detalle(r), true);
  $("#lista-pedidos").innerHTML = r.datos.map(tarjetaPedido).join("") || '<p class="sutil">Aún no hay pedidos.</p>';
  document.querySelectorAll("[data-estado]").forEach((b) => (b.onclick = async () => {
    const res = await api(`/api/pedidos/${b.dataset.pedido}/estado`, { method: "PATCH", body: JSON.stringify({ estado: b.dataset.estado }) });
    avisar(res.ok ? `Pedido ${b.dataset.estado.toLowerCase()}` : detalle(res), !res.ok);
    cargarPedidos();
  }));
}

// ---------- productor (CU-02, CU-03) ----------
async function cargarPanelProductor() {
  await cargarCategorias($("#p-categoria"), false);
  const f = await api("/api/fincas");
  if (f.ok) $("#p-finca").innerHTML = f.datos.map((x) => `<option value="${x.id}">${esc(x.nombre)} (${esc(x.municipio)})</option>`).join("");
  const r = await api(`/api/productos?productor_id=${sesion.usuario.id}`);
  if (!r.ok) return;
  $("#mis-productos").innerHTML = r.datos.map((p) => `<div class="renglon">
      <span><b>${esc(p.nombre)}</b><br><small class="sutil">${pesos(p.precio)} / ${esc(p.unidad)}</small></span>
      <span><input type="number" min="0" value="${p.disponible}" id="s-${p.id}"> <button data-stock="${p.id}">Actualizar</button></span>
    </div>`).join("") || '<p class="sutil">Aún no tienes productos.</p>';
  document.querySelectorAll("[data-stock]").forEach((b) => (b.onclick = async () => {
    const disponible = parseInt($(`#s-${b.dataset.stock}`).value, 10);
    const res = await api(`/api/productos/${b.dataset.stock}/inventario`, { method: "PATCH", body: JSON.stringify({ disponible }) });
    avisar(res.ok ? "Inventario actualizado" : detalle(res), !res.ok);
  }));
}

// ---------- administración (CU-11, CU-12) ----------
async function cargarAdmin() {
  const r = await api("/api/admin/productores");
  if (r.ok) {
    $("#productores").innerHTML = r.datos.map((u) => `<div class="renglon"><span><b>${esc(u.nombre)}</b><br><small class="sutil">${esc(u.email)}</small></span>
      ${u.verificado ? '<span class="insignia">Validado</span>' : `<button data-validar="${u.id}">Validar</button>`}</div>`).join("");
    document.querySelectorAll("[data-validar]").forEach((b) => (b.onclick = async () => {
      const res = await api(`/api/admin/productores/${b.dataset.validar}/validar`, { method: "PATCH" });
      avisar(res.ok ? "Productor validado" : detalle(res), !res.ok);
      cargarAdmin();
    }));
  }
  const v = await api("/api/reportes/ventas");
  if (v.ok) {
    const d = v.datos;
    $("#reporte").innerHTML = `<div class="metricas">
      <div class="metrica"><b>${pesos(d.ventas_totales)}</b><small>Ventas</small></div>
      <div class="metrica"><b>${d.pedidos_vendidos}</b><small>Pedidos vendidos</small></div>
      <div class="metrica"><b>${d.pedidos_cancelados}</b><small>Cancelados</small></div></div>`;
  }
}

// ---------- arquitectura en vivo ----------
async function cargarArquitectura() {
  const s = await api("/api/estado").catch(() => null);
  if (s?.ok) {
    $("#salud").innerHTML = [["gateway", { estado: "ok", servicio: "api-gateway" }], ...Object.entries(s.datos.servicios)].map(([n, x]) => {
      const deps = x.dependencias ? Object.entries(x.dependencias).map(([k, v]) => `${esc(k)}: ${esc(v)}`).join(" · ") : "";
      return `<div class="servicio ${esc(x.estado)}"><b>${esc(x.servicio || n)}</b><span class="insignia ${esc(x.estado)}">${esc(x.estado)}</span>
        <div class="sutil">${deps}</div></div>`;
    }).join("");
  }
  const c = await api("/api/pagos/estado-circuito").catch(() => null);
  if (c?.ok) {
    const d = c.datos;
    $("#circuito").innerHTML = `<p>Estado: <span class="insignia ${esc(d.estado)}">${esc(d.estado)}</span></p>
      <div class="metricas">
        <div class="metrica"><b>${d.fallos_consecutivos}/${d.umbral_fallos}</b><small>Fallos</small></div>
        <div class="metrica"><b>${d.segundos_para_reintento}s</b><small>Para reintentar</small></div>
        <div class="metrica"><b>${d.llamadas_rechazadas}</b><small>Rechazadas rápido</small></div>
        <div class="metrica"><b>${Math.round(d.pasarela.tasa_fallo * 100)}%</b><small>Tasa de fallo</small></div></div>`;
    if (sesion.usuario.rol === "admin") {
      $("#control-pasarela").classList.remove("oculto");
      if (document.activeElement !== $("#tasa")) {
        $("#tasa").value = Math.round(d.pasarela.tasa_fallo * 100);
        $("#tasa-valor").textContent = $("#tasa").value + "%";
      }
    }
  }
  const k = await api("/api/cache/estadisticas").catch(() => null);
  if (k?.ok) {
    const d = k.datos;
    $("#cache").innerHTML = `<div class="metricas">
      <div class="metrica"><b>${d.aciertos}</b><small>Aciertos</small></div>
      <div class="metrica"><b>${d.fallos}</b><small>Fallos</small></div>
      <div class="metrica"><b>${Math.round(d.tasa_aciertos * 100)}%</b><small>Tasa de aciertos</small></div></div>
      <p class="sutil">Backend: ${esc(d.backend)}. El inventario no se guarda en caché para no mostrar cantidades desactualizadas.</p>`;
  }
  const n = await api("/api/notificaciones").catch(() => null);
  if (n?.ok) {
    $("#notificaciones").innerHTML = n.datos.slice(0, 15).map((x) => `<div class="renglon"><span>${esc(x.mensaje)}</span>
      <small class="sutil">${new Date(x.fecha).toLocaleTimeString("es-CO")}</small></div>`).join("") || '<p class="sutil">Sin notificaciones aún.</p>';
  }
}

// ---------- eventos ----------
document.querySelectorAll("[data-demo]").forEach((b) => (b.onclick = () => entrar(...DEMO[b.dataset.demo])));
$("#form-login").onsubmit = (e) => { e.preventDefault(); const d = datosForm(e.target); entrar(d.email, d.clave); };
$("#form-registro").onsubmit = async (e) => {
  e.preventDefault();
  const r = await api("/api/auth/registro", { method: "POST", body: JSON.stringify(datosForm(e.target)) });
  if (!r.ok) return avisar(detalle(r), true);
  iniciarSesion(r.datos);
  if (r.datos.usuario.rol === "productor") avisar("Cuenta creada. Un administrador debe validarla antes de publicar productos.");
};
$("#form-producto").onsubmit = async (e) => {
  e.preventDefault();
  const d = datosForm(e.target);
  const cuerpo = { ...d, precio: Number(d.precio), categoria_id: Number(d.categoria_id), disponible_inicial: Number(d.disponible_inicial) };
  const r = await api("/api/productos", { method: "POST", body: JSON.stringify(cuerpo) });
  avisar(r.ok ? "Producto publicado" : detalle(r), !r.ok);
  if (r.ok) { e.target.reset(); cargarPanelProductor(); }
};
$("#form-finca").onsubmit = async (e) => {
  e.preventDefault();
  const r = await api("/api/fincas", { method: "POST", body: JSON.stringify(datosForm(e.target)) });
  avisar(r.ok ? "Finca registrada" : detalle(r), !r.ok);
  if (r.ok) { e.target.reset(); cargarPanelProductor(); }
};
["#f-categoria", "#f-disponibles"].forEach((s) => ($(s).onchange = cargarCatalogo));
let filtroTimer;
$("#f-municipio").oninput = () => { clearTimeout(filtroTimer); filtroTimer = setTimeout(cargarCatalogo, 350); };
$("#tasa").oninput = () => ($("#tasa-valor").textContent = $("#tasa").value + "%");
$("#tasa").onchange = async () => {
  const r = await api("/api/admin/pasarela", { method: "POST", body: JSON.stringify({ tasa_fallo: Number($("#tasa").value) / 100 }) });
  avisar(r.ok ? `Pasarela con ${$("#tasa").value}% de fallos` : detalle(r), !r.ok);
  cargarArquitectura();
};
$("#btn-reset").onclick = async () => {
  const r = await api("/api/admin/circuito/reiniciar", { method: "POST" });
  avisar(r.ok ? "Circuito reiniciado" : detalle(r), !r.ok);
  cargarArquitectura();
};

if (sesion?.token) mostrarApp();
