import os
import sys
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ.pop("REDIS_URL", None)
os.environ.pop("INTERNAL_TOKEN", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
# Puertos sin servicio: las pruebas no dependen de que otros servicios estén levantados
for _var in ("CATALOGO_URL", "PEDIDOS_URL", "PAGOS_URL", "NOTIFICACIONES_URL"):
    os.environ[_var] = "http://127.0.0.1:9"
