from pydantic import BaseModel, Field


class CategoriaIn(BaseModel):
    nombre: str = Field(min_length=2, max_length=60)


class FincaIn(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    municipio: str = Field(min_length=2, max_length=80)


class ProductoIn(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    unidad: str = Field(min_length=1, max_length=20, examples=["kg"])
    precio: float = Field(gt=0)
    categoria_id: int
    finca_id: str
    disponible_inicial: int = Field(default=0, ge=0)


class ProductoUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=120)
    precio: float | None = Field(default=None, gt=0)
    activo: bool | None = None


class InventarioUpdate(BaseModel):
    disponible: int = Field(ge=0)


class ItemReserva(BaseModel):
    producto_id: str
    cantidad: int = Field(gt=0)


class ReservaIn(BaseModel):
    pedido_id: str
    items: list[ItemReserva] = Field(min_length=1)


class PedidoRef(BaseModel):
    pedido_id: str
