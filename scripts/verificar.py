"""Plan de verificación de los patrones (Tabla 7 del informe).

Uso:
    pip install httpx
    python scripts/verificar.py                                   # local (http://localhost:8000)
    python scripts/verificar.py https://agroconecta-gateway.onrender.com

Ejecuta las seis pruebas y muestra un resumen. Usa las cuentas de demostración.
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

API = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
c = httpx.Client(base_url=API, timeout=90)
resultados: list[tuple[str, bool, str]] = []


def titulo(t: str) -> None:
    print(f"\n\033[1;32m▶ {t}\033[0m")


def registrar(nombre: str, ok: bool, detalle: str) -> None:
    resultados.append((nombre, ok, detalle))
    print(("  ✅ " if ok else "  ❌ ") + detalle)


def login(email: str, clave: str) -> dict:
    r = c.post("/api/auth/login", json={"email": email, "clave": clave})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def producto(nombre: str) -> dict:
    return next(p for p in c.get("/api/productos").json() if p["nombre"].startswith(nombre))


def pasarela(admin: dict, tasa: float) -> None:
    c.post("/api/admin/pasarela", json={"tasa_fallo": tasa}, headers=admin).raise_for_status()
    c.post("/api/admin/circuito/reiniciar", headers=admin).raise_for_status()


def main() -> None:
    print(f"Verificando AgroConecta en {API}")
    titulo("0. Despertando servicios y comprobando salud (Health Endpoint Monitoring)")
    for _ in range(10):
        try:
            estado = c.get("/api/estado").json()
            if estado["estado"] == "ok":
                break
        except Exception:
            pass
        print("  … esperando que los servicios respondan")
        time.sleep(10)
    for nombre, s in estado["servicios"].items():
        print(f"  {nombre:15s} {s.get('estado')}")
    registrar("Salud", estado["estado"] == "ok", f"Estado general: {estado['estado']}")

    admin = login("admin@agroconecta.co", "Admin123*")
    comprador = login("comprador@agroconecta.co", "Comprador123*")
    productor = login("productor@agroconecta.co", "Productor123*")
    pasarela(admin, 0.0)

    titulo("1. Pedido exitoso (Saga + Publisher/Subscriber)")
    aguacate = producto("Aguacate")
    r = c.post("/api/pedidos", json={"items": [{"producto_id": aguacate["id"], "cantidad": 2}]}, headers=comprador)
    pedido = r.json()
    print(f"  HTTP {r.status_code} · estado {pedido['estado']} · pasos Saga: "
          f"{' → '.join(h['paso'] for h in pedido['saga']['historial'])}")
    time.sleep(1.5)
    notifs = c.get("/api/notificaciones", headers=comprador).json()
    notificado = any(n["pedido_id"] == pedido["id"] for n in notifs)
    registrar("Pedido exitoso", r.status_code == 201 and pedido["estado"] == "PAGADO" and notificado,
              f"Pedido PAGADO y notificación recibida: {notificado}")

    titulo("2. Pago rechazado → compensación de la Saga")
    fresa = producto("Fresa")
    antes = fresa["disponible"]
    pasarela(admin, 1.0)
    r = c.post("/api/pedidos", json={"items": [{"producto_id": fresa["id"], "cantidad": 3}]}, headers=comprador)
    pedido = r.json()
    despues = producto("Fresa")["disponible"]
    print(f"  HTTP {r.status_code} · estado {pedido['estado']} · motivo: {pedido.get('motivo_cancelacion')}")
    print(f"  Inventario de fresa antes {antes} · después {despues}")
    registrar("Compensación", pedido["estado"] == "CANCELADO" and antes == despues,
              "Pedido CANCELADO y stock liberado")

    titulo("3. Falla en cascada → Circuit Breaker")
    for _ in range(3):
        c.post("/api/pedidos", json={"items": [{"producto_id": fresa["id"], "cantidad": 1}]}, headers=comprador)
    circuito = c.get("/api/pagos/estado-circuito").json()
    t0 = time.perf_counter()
    r = c.post("/api/pedidos", json={"items": [{"producto_id": fresa["id"], "cantidad": 1}]}, headers=comprador)
    t_rapido = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    catalogo_ok = c.get("/api/productos").status_code == 200
    t_catalogo = (time.perf_counter() - t0) * 1000
    print(f"  Circuito: {circuito['estado']} ({circuito['fallos_consecutivos']} fallos) · "
          f"respuesta con circuito abierto: HTTP {r.status_code} en {t_rapido:.0f} ms")
    print(f"  Catálogo sigue respondiendo: {catalogo_ok} ({t_catalogo:.0f} ms)")
    registrar("Circuit Breaker", circuito["estado"] == "ABIERTO" and r.status_code == 503 and catalogo_ok,
              "Circuito ABIERTO, falla rápida y catálogo disponible")
    pasarela(admin, 0.0)

    titulo("4. Concurrencia: 20 pedidos simultáneos por 5 kg de mora")
    mora = producto("Mora")
    c.patch(f"/api/productos/{mora['id']}/inventario", json={"disponible": 5}, headers=productor).raise_for_status()

    def comprar(_):
        with httpx.Client(base_url=API, timeout=90) as cli:
            return cli.post("/api/pedidos", json={"items": [{"producto_id": mora["id"], "cantidad": 1}]},
                            headers=comprador).json().get("estado")

    with ThreadPoolExecutor(max_workers=20) as ex:
        estados = list(ex.map(comprar, range(20)))
    pagados = estados.count("PAGADO")
    final = producto("Mora")["disponible"]
    print(f"  PAGADOS: {pagados} · CANCELADOS: {estados.count('CANCELADO')} · stock final: {final}")
    registrar("Concurrencia", pagados == 5 and final == 0, f"Exactamente {pagados} ventas y 0 sobreventa")

    titulo("5. Cache-Aside: 100 consultas del mismo producto")
    c.post("/api/cache/estadisticas/reiniciar", headers=admin)
    c.patch(f"/api/productos/{aguacate['id']}", json={"precio": aguacate["precio"]}, headers=productor)
    for _ in range(100):
        c.get(f"/api/productos/{aguacate['id']}")
    stats = c.get("/api/cache/estadisticas").json()
    print(f"  Backend: {stats['backend']} · aciertos {stats['aciertos']} · fallos {stats['fallos']}")
    registrar("Cache-Aside", stats["fallos"] <= 1 and stats["aciertos"] >= 99,
              f"Tasa de aciertos {stats['tasa_aciertos']:.0%}")

    titulo("6. Salud de cada servicio")
    estado = c.get("/api/estado").json()
    registrar("Health", all(s.get("estado") == "ok" for s in estado["servicios"].values()),
              "Todos los servicios responden /health")

    print("\n" + "=" * 60)
    for nombre, ok, _ in resultados:
        print(f"  {'✅' if ok else '❌'} {nombre}")
    total = sum(ok for _, ok, _ in resultados)
    print(f"  {total}/{len(resultados)} pruebas superadas")
    sys.exit(0 if total == len(resultados) else 1)


if __name__ == "__main__":
    main()
