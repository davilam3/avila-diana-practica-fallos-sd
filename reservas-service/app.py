import logging
import os
import time
import uuid
from typing import Any
import psycopg2
import requests
from flask import Flask, jsonify, request

from resilience import CircuitBreaker


app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

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

INVENTARIO_TIMEOUT = float(os.getenv("INVENTARIO_TIMEOUT", "2"))
INVENTARIO_MAX_INTENTOS = int(
    os.getenv("INVENTARIO_MAX_INTENTOS", "3")
)

INVENTARIO_BACKOFF_BASE = float(
    os.getenv("INVENTARIO_BACKOFF_BASE", "0.5")
)

PAGOS_TIMEOUT = float(os.getenv("PAGOS_TIMEOUT", "3"))
NOTIFICACIONES_TIMEOUT = float(os.getenv("NOTIFICACIONES_TIMEOUT", "2"))

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgresql")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "reservas_user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "reservas_password")
POSTGRES_DB = os.getenv("POSTGRES_DB", "reservas_db")

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


def obtener_conexion():
    return psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        dbname=POSTGRES_DB,
        connect_timeout=3
    )


def inicializar_base_datos() -> None:
    ultimo_error = None

    for intento in range(1, 11):
        try:
            with obtener_conexion() as conexion:
                with conexion.cursor() as cursor:
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS reservas (
                            id VARCHAR(50) PRIMARY KEY,
                            evento_id VARCHAR(50) NOT NULL,
                            usuario VARCHAR(150) NOT NULL,
                            correo VARCHAR(200) NOT NULL,
                            cantidad INTEGER NOT NULL,
                            monto NUMERIC(10, 2) NOT NULL,
                            pago_id VARCHAR(100),
                            notificacion_estado VARCHAR(30),
                            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)

            app.logger.info("Base de datos inicializada")
            return

        except Exception as error:
            ultimo_error = error
            app.logger.warning(
                "PostgreSQL aún no disponible. Intento %s/10: %s",
                intento,
                error
            )
            time.sleep(3)

    app.logger.error(
        "No fue posible inicializar PostgreSQL: %s",
        ultimo_error
    )


def llamar_inventario(
    datos: dict[str, Any]
) -> dict[str, Any]:

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

    for intento in range(1, INVENTARIO_MAX_INTENTOS + 1):
        try:
            app.logger.info(
                "Inventario: intento %s/%s",
                intento,
                INVENTARIO_MAX_INTENTOS
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

    # Se registra un fallo en el Circuit Breaker solamente
    # después de agotar todos los reintentos.
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



def restaurar_inventario(datos: dict[str, Any]) -> None:
    try:
        requests.post(
            f"{INVENTARIO_URL}/inventario/restaurar",
            json=datos,
            timeout=2
        )
    except requests.RequestException as error:
        app.logger.error(
            "No fue posible compensar el inventario: %s",
            error
        )


def procesar_pago(datos: dict[str, Any]) -> dict[str, Any]:
    if not pagos_breaker.can_execute():
        raise RuntimeError("Circuit Breaker de Pagos abierto")

    try:
        respuesta = requests.post(
            f"{PAGOS_URL}/pagos/procesar",
            json=datos,
            timeout=PAGOS_TIMEOUT
        )

        respuesta.raise_for_status()
        pagos_breaker.register_success()

        return respuesta.json()

    except requests.Timeout as error:
        pagos_breaker.register_failure()

        app.logger.warning(
            "Timeout en Pagos después de %.1f segundos. Circuito=%s",
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


def enviar_notificacion(
    reserva_id: str,
    correo: str
) -> dict[str, Any]:
    try:
        respuesta = requests.post(
            f"{NOTIFICACIONES_URL}/notificaciones/enviar",
            json={
                "reserva_id": reserva_id,
                "correo": correo
            },
            timeout=NOTIFICACIONES_TIMEOUT
        )

        respuesta.raise_for_status()

        return {
            "estado": "enviada",
            "detalle": respuesta.json()
        }

    except requests.RequestException as error:
        app.logger.warning(
            "Fallback de notificaciones activado: %s",
            error
        )

        return {
            "estado": "pendiente",
            "mensaje": (
                "La reserva fue completada, pero el correo "
                "se enviará posteriormente"
            )
        }


def guardar_reserva(
    reserva_id: str,
    datos: dict[str, Any],
    pago_id: str,
    notificacion_estado: str
) -> None:
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


@app.get("/health")
def health():
    return jsonify({
        "servicio": "reservas-service",
        "estado": "OK",
        "circuitos": {
            "inventario": inventario_breaker.get_state(),
            "pagos": pagos_breaker.get_state()
        }
    }), 200


@app.get("/reservas")
def listar_reservas():
    try:
        with obtener_conexion() as conexion:
            with conexion.cursor() as cursor:
                cursor.execute("""
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
                """)

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
                "fecha_creacion": fila[8].isoformat()
            }
            for fila in filas
        ]

        return jsonify(reservas), 200

    except Exception as error:
        app.logger.error("Error consultando reservas: %s", error)

        return jsonify({
            "estado": "error",
            "mensaje": "Base de datos no disponible"
        }), 503


@app.post("/reservas")
def crear_reserva():
    datos = request.get_json(silent=True) or {}

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
    ]

    if faltantes:
        return jsonify({
            "estado": "error",
            "mensaje": "Faltan campos obligatorios",
            "campos": faltantes
        }), 400

    inventario_datos = {
        "evento_id": datos["evento_id"],
        "cantidad": datos["cantidad"]
    }

    try:
        inventario = llamar_inventario(inventario_datos)

    except RuntimeError as error:
        return jsonify({
            "estado": "rechazada",
            "codigo": "INVENTARIO_NO_DISPONIBLE",
            "mensaje": str(error),
            "circuit_breaker": inventario_breaker.get_state()
        }), 503

    try:
        pago = procesar_pago({
            "usuario": datos["usuario"],
            "monto": datos["monto"]
        })

    except RuntimeError as error:
        restaurar_inventario(inventario_datos)

        return jsonify({
            "estado": "pendiente",
            "codigo": "PAGO_NO_CONFIRMADO",
            "mensaje": str(error),
            "circuit_breaker": pagos_breaker.get_state()
        }), 504

    reserva_id = f"RES-{uuid.uuid4().hex[:12].upper()}"

    notificacion = enviar_notificacion(
        reserva_id=reserva_id,
        correo=datos["correo"]
    )

    try:
        guardar_reserva(
            reserva_id=reserva_id,
            datos=datos,
            pago_id=pago["pago_id"],
            notificacion_estado=notificacion["estado"]
        )

    except Exception as error:
        app.logger.error(
            "Error guardando reserva en PostgreSQL: %s",
            error
        )

        return jsonify({
            "estado": "error",
            "codigo": "BASE_DATOS_NO_DISPONIBLE",
            "mensaje": (
                "El pago fue aprobado, pero no fue posible "
                "registrar la reserva"
            )
        }), 503

    return jsonify({
        "estado": "confirmada",
        "reserva_id": reserva_id,
        "inventario": inventario,
        "pago": pago,
        "notificacion": notificacion
    }), 201


inicializar_base_datos()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        threaded=True
    )