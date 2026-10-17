"""Datos de demostración. Los identificadores de usuario coinciden con los que
crea el API Gateway para las cuentas de prueba."""
from sqlalchemy.orm import Session

from .models import Categoria, Finca, Inventario, Producto

PRODUCTOR_DEMO_ID = "11111111-1111-1111-1111-111111111111"

PRODUCTOS = [
    # nombre, unidad, precio, categoría, disponible
    ("Aguacate Hass", "kg", 9500, "Frutas", 120),
    ("Fresa", "kg", 12000, "Frutas", 40),
    ("Mora de Castilla", "kg", 7000, "Frutas", 5),       # stock bajo: prueba de concurrencia
    ("Tomate chonto", "kg", 4200, "Hortalizas", 80),
    ("Lechuga crespa", "unidad", 2500, "Hortalizas", 60),
    ("Papa criolla", "kg", 3500, "Tubérculos", 150),
    ("Leche entera", "litro", 3800, "Lácteos", 200),
    ("Queso campesino", "libra", 11000, "Lácteos", 30),
]


def cargar(db: Session) -> None:
    if db.query(Categoria).count():
        return
    categorias = {n: Categoria(nombre=n) for n in ["Frutas", "Hortalizas", "Tubérculos", "Lácteos"]}
    db.add_all(categorias.values())
    finca = Finca(nombre="Finca La Esperanza", municipio="Marinilla", productor_id=PRODUCTOR_DEMO_ID)
    db.add(finca)
    db.flush()
    for nombre, unidad, precio, cat, disp in PRODUCTOS:
        p = Producto(nombre=nombre, unidad=unidad, precio=precio, categoria_id=categorias[cat].id,
                     finca_id=finca.id, productor_id=PRODUCTOR_DEMO_ID)
        db.add(p)
        db.flush()
        db.add(Inventario(producto_id=p.id, disponible=disp, reservado=0))
    db.commit()
