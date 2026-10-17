"""Patrón Repository: encapsula el acceso a datos del catálogo."""
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import Categoria, Finca, Inventario, Producto, Reserva


class RepositorioCatalogo:
    def __init__(self, db: Session):
        self.db = db

    # --- categorías y fincas ---
    def categorias(self) -> list[Categoria]:
        return list(self.db.scalars(select(Categoria).order_by(Categoria.nombre)))

    def crear_categoria(self, nombre: str) -> Categoria:
        c = Categoria(nombre=nombre)
        self.db.add(c)
        self.db.commit()
        return c

    def fincas(self, productor_id: str | None = None) -> list[Finca]:
        q = select(Finca)
        if productor_id:
            q = q.where(Finca.productor_id == productor_id)
        return list(self.db.scalars(q))

    def finca(self, finca_id: str) -> Finca | None:
        return self.db.get(Finca, finca_id)

    def crear_finca(self, nombre: str, municipio: str, productor_id: str) -> Finca:
        f = Finca(nombre=nombre, municipio=municipio, productor_id=productor_id)
        self.db.add(f)
        self.db.commit()
        return f

    # --- productos ---
    def por_id(self, producto_id: str) -> Producto | None:
        return self.db.get(Producto, producto_id)

    def listar(self, categoria_id: int | None, municipio: str | None, productor_id: str | None) -> list[Producto]:
        q = select(Producto).join(Finca).where(Producto.activo.is_(True))
        if categoria_id:
            q = q.where(Producto.categoria_id == categoria_id)
        if municipio:
            q = q.where(Finca.municipio.ilike(f"%{municipio}%"))
        if productor_id:
            q = q.where(Producto.productor_id == productor_id)
        return list(self.db.scalars(q.order_by(Producto.nombre)).unique())

    def crear(self, datos: dict, disponible: int) -> Producto:
        p = Producto(**datos)
        self.db.add(p)
        self.db.flush()
        self.db.add(Inventario(producto_id=p.id, disponible=disponible, reservado=0))
        self.db.commit()
        return self.por_id(p.id)

    def actualizar(self, producto: Producto, cambios: dict) -> Producto:
        for k, v in cambios.items():
            setattr(producto, k, v)
        self.db.commit()
        return producto

    def inventarios(self, ids: list[str]) -> dict[str, Inventario]:
        if not ids:
            return {}
        filas = self.db.scalars(select(Inventario).where(Inventario.producto_id.in_(ids)))
        return {i.producto_id: i for i in filas}

    def fijar_disponible(self, producto_id: str, disponible: int) -> None:
        self.db.execute(update(Inventario).where(Inventario.producto_id == producto_id).values(disponible=disponible))
        self.db.commit()

    # --- reservas (pasos de la Saga) ---
    def reservas_de(self, pedido_id: str, estado: str | None = None) -> list[Reserva]:
        q = select(Reserva).where(Reserva.pedido_id == pedido_id)
        if estado:
            q = q.where(Reserva.estado == estado)
        return list(self.db.scalars(q))

    def descontar_si_hay(self, producto_id: str, cantidad: int) -> bool:
        """Reserva atómica: una sola sentencia condicional evita la sobreventa.

        UPDATE inventario SET disponible = disponible - :cant, reservado = reservado + :cant
         WHERE producto_id = :id AND disponible >= :cant
        """
        resultado = self.db.execute(
            update(Inventario)
            .where(Inventario.producto_id == producto_id, Inventario.disponible >= cantidad)
            .values(disponible=Inventario.disponible - cantidad, reservado=Inventario.reservado + cantidad)
        )
        return resultado.rowcount == 1

    def devolver(self, producto_id: str, cantidad: int) -> None:
        self.db.execute(
            update(Inventario)
            .where(Inventario.producto_id == producto_id)
            .values(disponible=Inventario.disponible + cantidad, reservado=Inventario.reservado - cantidad)
        )

    def consumir_reservado(self, producto_id: str, cantidad: int) -> None:
        self.db.execute(
            update(Inventario)
            .where(Inventario.producto_id == producto_id)
            .values(reservado=Inventario.reservado - cantidad)
        )
