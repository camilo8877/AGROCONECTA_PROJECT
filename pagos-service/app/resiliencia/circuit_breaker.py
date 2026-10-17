"""Patrón Circuit Breaker (Nygard, 2018).

CERRADO     -> las llamadas pasan; se cuentan los fallos consecutivos.
ABIERTO     -> tras `umbral_fallos` fallos se rechazan las llamadas de inmediato
               durante `tiempo_recuperacion` segundos (falla rápida, sin bloquear hilos).
SEMIABIERTO -> pasado ese tiempo se deja pasar una llamada de prueba: si funciona
               el circuito se cierra; si falla, vuelve a abrirse.
"""
import logging
import threading
import time

log = logging.getLogger("pagos")


class CircuitoAbierto(Exception):
    pass


class CircuitBreaker:
    CERRADO, ABIERTO, SEMIABIERTO = "CERRADO", "ABIERTO", "SEMIABIERTO"

    def __init__(self, nombre: str, umbral_fallos: int = 3, tiempo_recuperacion: float = 30.0):
        self.nombre = nombre
        self.umbral = umbral_fallos
        self.recuperacion = tiempo_recuperacion
        self._lock = threading.Lock()
        self.reiniciar()

    def reiniciar(self) -> None:
        with self._lock:
            self.fallos = 0
            self.estado = self.CERRADO
            self.abierto_desde = 0.0
            self.rechazadas = 0

    def _permitir(self) -> None:
        with self._lock:
            if self.estado == self.ABIERTO:
                if time.monotonic() - self.abierto_desde < self.recuperacion:
                    self.rechazadas += 1
                    raise CircuitoAbierto(f"Circuito '{self.nombre}' abierto: servicio no disponible")
                self.estado = self.SEMIABIERTO          # permite una llamada de prueba
                log.info(f"Circuito '{self.nombre}' en SEMIABIERTO")

    def _registrar_exito(self) -> None:
        with self._lock:
            if self.estado != self.CERRADO:
                log.info(f"Circuito '{self.nombre}' CERRADO de nuevo")
            self.fallos = 0
            self.estado = self.CERRADO

    def _registrar_fallo(self) -> None:
        with self._lock:
            self.fallos += 1
            if self.estado == self.SEMIABIERTO or self.fallos >= self.umbral:
                self.estado = self.ABIERTO
                self.abierto_desde = time.monotonic()
                log.warning(f"Circuito '{self.nombre}' ABIERTO tras {self.fallos} fallos")

    def llamar(self, funcion, *args, **kwargs):
        self._permitir()
        try:
            resultado = funcion(*args, **kwargs)
        except Exception:
            self._registrar_fallo()
            raise
        self._registrar_exito()
        return resultado

    def estado_actual(self) -> dict:
        with self._lock:
            restante = 0.0
            if self.estado == self.ABIERTO:
                restante = max(0.0, self.recuperacion - (time.monotonic() - self.abierto_desde))
            return {
                "circuito": self.nombre,
                "estado": self.estado,
                "fallos_consecutivos": self.fallos,
                "umbral_fallos": self.umbral,
                "tiempo_recuperacion_s": self.recuperacion,
                "segundos_para_reintento": round(restante, 1),
                "llamadas_rechazadas": self.rechazadas,
            }
