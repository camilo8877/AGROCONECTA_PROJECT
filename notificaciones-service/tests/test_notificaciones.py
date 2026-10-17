from app.main import notificaciones, procesar_evento


def test_evento_pagado_notifica_a_comprador_y_productores():
    nuevas = procesar_evento({"tipo": "pedido.pagado", "pedido_id": "abcdef123", "comprador_id": "c1",
                              "productor_ids": ["p1", "p2"], "total": 12000})
    assert {n["usuario_id"] for n in nuevas} == {"c1", "p1", "p2"}
    assert "$12.000" in nuevas[0]["mensaje"]
    assert len(notificaciones) >= 3


def test_evento_cancelado_solo_al_comprador():
    nuevas = procesar_evento({"tipo": "pedido.cancelado", "pedido_id": "x", "comprador_id": "c1",
                              "productor_ids": ["p1"], "motivo": "Pago rechazado"})
    assert [n["usuario_id"] for n in nuevas] == ["c1"]
