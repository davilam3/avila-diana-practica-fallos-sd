import logging
import os
import threading
import time
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

import psycopg2
import requests
from flask import Flask, jsonify, request

from resilience import CircuitBreaker


# ==========================================================
# CONFIGURACIÓN DE FLASK Y LOGS
# ==========================================================

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)


# ==========================================================
# CONFIGURACIÓN DE SERVICIOS
# ==========================================================

INVENTARIO_URL = os.getenv(
    "INVENTARIO_URL",
    "http://inventario-service:5000"
)

PAGOS_URL = os.getenv(
    "PAGOS_URL",
    "http://pagos-service:5000"
)

NOTIFICACIONES_URL = os.getenv(
    "NOTIFICACIONES_URL",
    "http://notificaciones-service:5000"
)


# ==========================================================
# CONFIGURACIÓN DE TIMEOUTS, RETRIES Y BACKOFF
# ==========================================================

INVENTARIO_TIMEOUT = float(
    os.getenv("INVENTARIO_TIMEOUT", "2")
)

INVENTARIO_MAX_INTENTOS = max(
    1,
    int(os.getenv("INVENTARIO_MAX_INTENTOS", "3"))
)

INVENTARIO_BACKOFF_BASE = max(
    0.1,
    float(os.getenv("INVENTARIO_BACKOFF_BASE", "0.5"))
)

PAGOS_TIMEOUT = float(
    os.getenv("PAGOS_TIMEOUT", "3")
)

NOTIFICACIONES_TIMEOUT = float(
    os.getenv("NOTIFICACIONES_TIMEOUT", "2")
)

COMPENSACION_TIMEOUT = float(
    os.getenv("COMPENSACION_TIMEOUT", "2")
)


# ==========================================================
# CONFIGURACIÓN DE POSTGRESQL
# ==========================================================

POSTGRES_HOST = os.getenv(
    "POSTGRES_HOST",
    "postgresql"
)

POSTGRES_PORT = int(
    os.getenv("POSTGRES_PORT", "5432")
)

POSTGRES_USER = os.getenv(
    "POSTGRES_USER",
    "reservas_user"
)

POSTGRES_PASSWORD = os.getenv(
    "POSTGRES_PASSWORD",
    "reservas_password"
)

POSTGRES_DB = os.getenv(
    "POSTGRES_DB",
    "reservas_db"
)


# ==========================================================
# CONFIGURACIÓN DEL BULKHEAD
# ==========================================================

BULKHEAD_MAX_CONCURRENT = max(
    1,
    int(os.getenv("BULKHEAD_MAX_CONCURRENT", "5"))
)

reservas_bulkhead = threading.BoundedSemaphore(
    BULKHEAD_MAX_CONCURRENT
)


# ==========================================================
# CIRCUIT BREAKERS
# ==========================================================

inventario_breaker = CircuitBreaker(
    name="inventario",
    failure_threshold=3,
    recovery_timeout=15
)

pagos_breaker = CircuitBreaker(
    name="pagos",
    failure_threshold=2,
    recovery_timeout=20
)


# ==========================================================
# CONEXIÓN A POSTGRESQL
# ==========================================================

def obtener_conexion():
    """
    Crea una conexión nueva con PostgreSQL.
    """

    return psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        dbname=POSTGRES_DB,
        connect_timeout=3
    )


def inicializar_base_datos() -> None:
    """
    Intenta conectarse a PostgreSQL hasta diez veces
    y crea la tabla de reservas si no existe.
    """

    ultimo_error: Exception | None = None

    for intento in range(1, 11):
        try:
            with obtener_conexion() as conexion:
                with conexion.cursor() as cursor:
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS reservas (
                            id VARCHAR(50) PRIMARY KEY,
                            evento_id VARCHAR(50) NOT NULL,
                            usuario VARCHAR(150) NOT NULL,
                            correo VARCHAR(200) NOT NULL,
                            cantidad INTEGER NOT NULL,
                            monto NUMERIC(10, 2) NOT NULL,
                            pago_id VARCHAR(100),
                            notificacion_estado VARCHAR(30),
                            fecha_creacion TIMESTAMP
                                DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )

            app.logger.info(
                "Base de datos inicializada correctamente"
            )

            return

        except Exception as error:
            ultimo_error = error

            app.logger.warning(
                "PostgreSQL aún no disponible. "
                "Intento %s/10. Error=%s",
                intento,
                error
            )

            time.sleep(3)

    app.logger.error(
        "No fue posible inicializar PostgreSQL "
        "después de diez intentos. Error=%s",
        ultimo_error
    )


# ==========================================================
# VALIDACIÓN DE DATOS
# ==========================================================

def validar_datos_reserva(
    datos: dict[str, Any]
) -> tuple[dict[str, Any] | None, tuple[Any, int] | None]:
    """
    Valida los campos requeridos y convierte cantidad
    y monto a tipos numéricos.
    """

    campos_requeridos = [
        "evento_id",
        "usuario",
        "correo",
        "cantidad",
        "monto"
    ]

    faltantes = [
        campo
        for campo in campos_requeridos
        if campo not in datos
        or datos[campo] is None
        or (
            isinstance(datos[campo], str)
            and not datos[campo].strip()
        )
    ]

    if faltantes:
        respuesta = jsonify({
            "estado": "error",
            "codigo": "DATOS_INCOMPLETOS",
            "mensaje": "Faltan campos obligatorios",
            "campos": faltantes
        })

        return None, (respuesta, 400)

    try:
        cantidad = int(datos["cantidad"])
    except (TypeError, ValueError):
        respuesta = jsonify({
            "estado": "error",
            "codigo": "CANTIDAD_INVALIDA",
            "mensaje": (
                "El campo cantidad debe contener "
                "un número entero"
            )
        })

        return None, (respuesta, 400)

    try:
        monto = Decimal(str(datos["monto"]))
    except (InvalidOperation, TypeError, ValueError):
        respuesta = jsonify({
            "estado": "error",
            "codigo": "MONTO_INVALIDO",
            "mensaje": (
                "El campo monto debe contener "
                "un valor numérico"
            )
        })

        return None, (respuesta, 400)

    if cantidad <= 0:
        respuesta = jsonify({
            "estado": "error",
            "codigo": "CANTIDAD_INVALIDA",
            "mensaje": "La cantidad debe ser mayor que cero"
        })

        return None, (respuesta, 400)

    if monto <= 0:
        respuesta = jsonify({
            "estado": "error",
            "codigo": "MONTO_INVALIDO",
            "mensaje": "El monto debe ser mayor que cero"
        })

        return None, (respuesta, 400)

    usuario = str(datos["usuario"]).strip()
    correo = str(datos["correo"]).strip()
    evento_id = str(datos["evento_id"]).strip()

    if "@" not in correo:
        respuesta = jsonify({
            "estado": "error",
            "codigo": "CORREO_INVALIDO",
            "mensaje": "El correo electrónico no es válido"
        })

        return None, (respuesta, 400)

    datos_validados = {
        "evento_id": evento_id,
        "usuario": usuario,
        "correo": correo,
        "cantidad": cantidad,
        "monto": float(monto)
    }

    return datos_validados, None


# ==========================================================
# INVENTARIO: RETRY, BACKOFF Y CIRCUIT BREAKER
# ==========================================================

def llamar_inventario(
    datos: dict[str, Any]
) -> dict[str, Any]:
    """
    Descuenta el inventario aplicando:

    - Timeout.
    - Retry.
    - Backoff exponencial.
    - Circuit Breaker.
    """

    if not inventario_breaker.can_execute():
        estado = inventario_breaker.get_state()

        app.logger.warning(
            "Circuit Breaker de Inventario abierto. "
            "Solicitud rechazada sin contactar al servicio. "
            "Circuito=%s",
            estado
        )

        raise RuntimeError(
            "Circuit Breaker de Inventario abierto"
        )

    ultimo_error: Exception | None = None

    for intento in range(
        1,
        INVENTARIO_MAX_INTENTOS + 1
    ):
        try:
            app.logger.info(
                "Inventario: intento %s/%s. "
                "Evento=%s, cantidad=%s",
                intento,
                INVENTARIO_MAX_INTENTOS,
                datos["evento_id"],
                datos["cantidad"]
            )

            respuesta = requests.post(
                f"{INVENTARIO_URL}/inventario/descontar",
                json=datos,
                timeout=INVENTARIO_TIMEOUT
            )

            respuesta.raise_for_status()

            inventario_breaker.register_success()

            app.logger.info(
                "Inventario respondió correctamente. "
                "Circuito=%s",
                inventario_breaker.get_state()
            )

            return respuesta.json()

        except requests.RequestException as error:
            ultimo_error = error

            app.logger.warning(
                "Fallo consultando Inventario. "
                "Intento=%s/%s. Error=%s",
                intento,
                INVENTARIO_MAX_INTENTOS,
                error
            )

            if intento < INVENTARIO_MAX_INTENTOS:
                espera = INVENTARIO_BACKOFF_BASE * (
                    2 ** (intento - 1)
                )

                app.logger.info(
                    "Retry de Inventario en %.1f segundos",
                    espera
                )

                time.sleep(espera)

    inventario_breaker.register_failure()

    estado = inventario_breaker.get_state()

    app.logger.error(
        "Inventario no disponible después de %s intentos. "
        "Circuito=%s. Último error=%s",
        INVENTARIO_MAX_INTENTOS,
        estado,
        ultimo_error
    )

    raise RuntimeError(
        "Servicio de Inventario no disponible "
        "después de varios intentos"
    ) from ultimo_error


# ==========================================================
# COMPENSACIÓN DE INVENTARIO
# ==========================================================

def restaurar_inventario(
    datos: dict[str, Any]
) -> bool:
    """
    Restaura el inventario cuando el pago no puede
    confirmarse.

    Retorna True si la compensación fue exitosa.
    """

    try:
        app.logger.info(
            "Iniciando compensación de inventario. "
            "Evento=%s, cantidad=%s",
            datos["evento_id"],
            datos["cantidad"]
        )

        respuesta = requests.post(
            f"{INVENTARIO_URL}/inventario/restaurar",
            json=datos,
            timeout=COMPENSACION_TIMEOUT
        )

        respuesta.raise_for_status()

        app.logger.info(
            "Inventario restaurado correctamente. "
            "Evento=%s, cantidad=%s",
            datos["evento_id"],
            datos["cantidad"]
        )

        return True

    except requests.RequestException as error:
        app.logger.error(
            "No fue posible compensar el inventario. "
            "Evento=%s, cantidad=%s, error=%s",
            datos.get("evento_id"),
            datos.get("cantidad"),
            error
        )

        return False


# ==========================================================
# PAGOS: TIMEOUT Y CIRCUIT BREAKER
# ==========================================================

def procesar_pago(
    datos: dict[str, Any]
) -> dict[str, Any]:
    """
    Procesa el pago aplicando Timeout y Circuit Breaker.
    """

    if not pagos_breaker.can_execute():
        estado = pagos_breaker.get_state()

        app.logger.warning(
            "Circuit Breaker de Pagos abierto. "
            "Solicitud rechazada sin contactar al servicio. "
            "Circuito=%s",
            estado
        )

        raise RuntimeError(
            "Circuit Breaker de Pagos abierto"
        )

    try:
        app.logger.info(
            "Enviando solicitud al Servicio de Pagos. "
            "Timeout configurado=%.1f segundos",
            PAGOS_TIMEOUT
        )

        respuesta = requests.post(
            f"{PAGOS_URL}/pagos/procesar",
            json=datos,
            timeout=PAGOS_TIMEOUT
        )

        respuesta.raise_for_status()

        pagos_breaker.register_success()

        app.logger.info(
            "Pago procesado correctamente. "
            "Circuito=%s",
            pagos_breaker.get_state()
        )

        return respuesta.json()

    except requests.Timeout as error:
        pagos_breaker.register_failure()

        app.logger.warning(
            "Timeout en Pagos después de %.1f segundos. "
            "Circuito=%s",
            PAGOS_TIMEOUT,
            pagos_breaker.get_state()
        )

        raise RuntimeError(
            "El Servicio de Pagos tardó demasiado"
        ) from error

    except requests.RequestException as error:
        pagos_breaker.register_failure()

        app.logger.error(
            "Fallo en Pagos. Circuito=%s. Error=%s",
            pagos_breaker.get_state(),
            error
        )

        raise RuntimeError(
            "Servicio de Pagos no disponible"
        ) from error


# ==========================================================
# NOTIFICACIONES: FALLBACK
# ==========================================================

def enviar_notificacion(
    reserva_id: str,
    correo: str
) -> dict[str, Any]:
    """
    Intenta enviar la notificación.

    Si el servicio no responde, la reserva continúa
    y la notificación queda pendiente.
    """

    try:
        app.logger.info(
            "Enviando notificación. "
            "Reserva=%s, correo=%s",
            reserva_id,
            correo
        )

        respuesta = requests.post(
            (
                f"{NOTIFICACIONES_URL}"
                "/notificaciones/enviar"
            ),
            json={
                "reserva_id": reserva_id,
                "correo": correo
            },
            timeout=NOTIFICACIONES_TIMEOUT
        )

        respuesta.raise_for_status()

        app.logger.info(
            "Notificación enviada correctamente. "
            "Reserva=%s",
            reserva_id
        )

        return {
            "estado": "enviada",
            "detalle": respuesta.json()
        }

    except requests.RequestException as error:
        app.logger.warning(
            "Fallback de notificaciones activado. "
            "Reserva=%s, error=%s",
            reserva_id,
            error
        )

        return {
            "estado": "pendiente",
            "mensaje": (
                "La reserva fue completada, pero el correo "
                "se enviará posteriormente"
            )
        }


# ==========================================================
# PERSISTENCIA DE RESERVAS
# ==========================================================

def guardar_reserva(
    reserva_id: str,
    datos: dict[str, Any],
    pago_id: str,
    notificacion_estado: str
) -> None:
    """
    Guarda la reserva confirmada en PostgreSQL.
    """

    with obtener_conexion() as conexion:
        with conexion.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO reservas (
                    id,
                    evento_id,
                    usuario,
                    correo,
                    cantidad,
                    monto,
                    pago_id,
                    notificacion_estado
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    reserva_id,
                    str(datos["evento_id"]),
                    datos["usuario"],
                    datos["correo"],
                    int(datos["cantidad"]),
                    float(datos["monto"]),
                    pago_id,
                    notificacion_estado
                )
            )


# ==========================================================
# ENDPOINT DE SALUD
# ==========================================================

@app.get("/health")
def health():
    return jsonify({
        "servicio": "reservas-service",
        "estado": "OK",
        "circuitos": {
            "inventario": inventario_breaker.get_state(),
            "pagos": pagos_breaker.get_state()
        },
        "bulkhead": {
            "capacidad_maxima_por_pod":
                BULKHEAD_MAX_CONCURRENT
        },
        "timeouts": {
            "inventario": INVENTARIO_TIMEOUT,
            "pagos": PAGOS_TIMEOUT,
            "notificaciones": NOTIFICACIONES_TIMEOUT
        },
        "reintentos_inventario":
            INVENTARIO_MAX_INTENTOS
    }), 200


# ==========================================================
# CONSULTAR RESERVAS
# ==========================================================

@app.get("/reservas")
def listar_reservas():
    try:
        with obtener_conexion() as conexion:
            with conexion.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        evento_id,
                        usuario,
                        correo,
                        cantidad,
                        monto,
                        pago_id,
                        notificacion_estado,
                        fecha_creacion
                    FROM reservas
                    ORDER BY fecha_creacion DESC
                    LIMIT 100
                    """
                )

                filas = cursor.fetchall()

        reservas = [
            {
                "id": fila[0],
                "evento_id": fila[1],
                "usuario": fila[2],
                "correo": fila[3],
                "cantidad": fila[4],
                "monto": float(fila[5]),
                "pago_id": fila[6],
                "notificacion_estado": fila[7],
                "fecha_creacion": (
                    fila[8].isoformat()
                    if fila[8]
                    else None
                )
            }
            for fila in filas
        ]

        return jsonify(reservas), 200

    except Exception as error:
        app.logger.error(
            "Error consultando reservas: %s",
            error
        )

        return jsonify({
            "estado": "error",
            "codigo": "BASE_DATOS_NO_DISPONIBLE",
            "mensaje": "Base de datos no disponible"
        }), 503


# ==========================================================
# CREAR RESERVA CON BULKHEAD
# ==========================================================

@app.post("/reservas")
def crear_reserva():
    """
    Procesa una reserva completa.

    El Bulkhead limita la cantidad de reservas concurrentes
    procesadas por cada pod.
    """

    permiso_adquirido = reservas_bulkhead.acquire(
        blocking=False
    )

    if not permiso_adquirido:
        app.logger.warning(
            "Bulkhead saturado. "
            "Solicitud rechazada con HTTP 503. "
            "Capacidad máxima por pod=%s",
            BULKHEAD_MAX_CONCURRENT
        )

        return jsonify({
            "estado": "rechazada",
            "codigo": "SERVICIO_SATURADO",
            "mensaje": (
                "El servicio alcanzó su capacidad máxima "
                "de procesamiento concurrente"
            ),
            "bulkhead": {
                "capacidad": BULKHEAD_MAX_CONCURRENT,
                "estado": "SATURADO"
            }
        }), 503

    app.logger.info(
        "Solicitud admitida por el Bulkhead. "
        "Capacidad máxima por pod=%s",
        BULKHEAD_MAX_CONCURRENT
    )

    try:
        datos_recibidos = (
            request.get_json(silent=True) or {}
        )

        datos, error_validacion = validar_datos_reserva(
            datos_recibidos
        )

        if error_validacion is not None:
            return error_validacion

        if datos is None:
            return jsonify({
                "estado": "error",
                "codigo": "DATOS_INVALIDOS",
                "mensaje": "Los datos recibidos no son válidos"
            }), 400

        inventario_datos = {
            "evento_id": datos["evento_id"],
            "cantidad": datos["cantidad"]
        }

        # --------------------------------------------------
        # PASO 1: DESCONTAR INVENTARIO
        # --------------------------------------------------

        try:
            inventario = llamar_inventario(
                inventario_datos
            )

        except RuntimeError as error:
            return jsonify({
                "estado": "rechazada",
                "codigo": "INVENTARIO_NO_DISPONIBLE",
                "mensaje": str(error),
                "circuit_breaker":
                    inventario_breaker.get_state()
            }), 503

        # --------------------------------------------------
        # PASO 2: PROCESAR PAGO
        # --------------------------------------------------

        try:
            pago = procesar_pago({
                "usuario": datos["usuario"],
                "monto": datos["monto"]
            })

        except RuntimeError as error:
            compensacion_exitosa = restaurar_inventario(
                inventario_datos
            )

            return jsonify({
                "estado": "pendiente",
                "codigo": "PAGO_NO_CONFIRMADO",
                "mensaje": str(error),
                "circuit_breaker":
                    pagos_breaker.get_state(),
                "compensacion_inventario": (
                    "exitosa"
                    if compensacion_exitosa
                    else "fallida"
                )
            }), 504

        # --------------------------------------------------
        # PASO 3: GENERAR ID
        # --------------------------------------------------

        reserva_id = (
            f"RES-{uuid.uuid4().hex[:12].upper()}"
        )

        # --------------------------------------------------
        # PASO 4: ENVIAR NOTIFICACIÓN
        # --------------------------------------------------

        notificacion = enviar_notificacion(
            reserva_id=reserva_id,
            correo=datos["correo"]
        )

        # --------------------------------------------------
        # PASO 5: GUARDAR EN POSTGRESQL
        # --------------------------------------------------

        try:
            guardar_reserva(
                reserva_id=reserva_id,
                datos=datos,
                pago_id=str(pago["pago_id"]),
                notificacion_estado=(
                    notificacion["estado"]
                )
            )

        except Exception as error:
            app.logger.error(
                "Error guardando reserva en PostgreSQL. "
                "Reserva=%s, pago=%s, error=%s",
                reserva_id,
                pago.get("pago_id"),
                error
            )

            # Se intenta restaurar el inventario.
            # En producción también debería compensarse
            # el pago mediante reembolso o anulación.
            compensacion_exitosa = restaurar_inventario(
                inventario_datos
            )

            return jsonify({
                "estado": "error",
                "codigo": "BASE_DATOS_NO_DISPONIBLE",
                "mensaje": (
                    "El pago fue aprobado, pero no fue "
                    "posible registrar la reserva"
                ),
                "pago_id": pago.get("pago_id"),
                "requiere_revision_pago": True,
                "compensacion_inventario": (
                    "exitosa"
                    if compensacion_exitosa
                    else "fallida"
                )
            }), 503

        app.logger.info(
            "Reserva creada correctamente. "
            "Reserva=%s, usuario=%s, evento=%s",
            reserva_id,
            datos["usuario"],
            datos["evento_id"]
        )

        return jsonify({
            "estado": "confirmada",
            "reserva_id": reserva_id,
            "inventario": inventario,
            "pago": pago,
            "notificacion": notificacion
        }), 201

    except Exception as error:
        app.logger.exception(
            "Error inesperado procesando la reserva: %s",
            error
        )

        return jsonify({
            "estado": "error",
            "codigo": "ERROR_INTERNO",
            "mensaje": (
                "Ocurrió un error interno procesando "
                "la reserva"
            )
        }), 500

    finally:
        reservas_bulkhead.release()

        app.logger.info(
            "Permiso del Bulkhead liberado"
        )


# ==========================================================
# INICIALIZACIÓN
# ==========================================================

inicializar_base_datos()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        threaded=True
    )