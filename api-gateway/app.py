import logging
import os
import threading
import time
from collections import defaultdict, deque

import requests
from flask import Flask, jsonify, request


app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

RESERVAS_URL = os.getenv(
    "RESERVAS_URL",
    "http://reservas-service:5000"
)

MAX_CONCURRENT_REQUESTS = int(
    os.getenv("MAX_CONCURRENT_REQUESTS", "10")
)

RATE_LIMIT = int(
    os.getenv("RATE_LIMIT", "30")
)

RATE_WINDOW_SECONDS = int(
    os.getenv("RATE_WINDOW_SECONDS", "60")
)

bulkhead = threading.BoundedSemaphore(
    MAX_CONCURRENT_REQUESTS
)

request_history = defaultdict(deque)
history_lock = threading.Lock()


def limite_superado(client_ip: str) -> bool:
    ahora = time.time()

    with history_lock:
        historial = request_history[client_ip]

        while (
            historial
            and ahora - historial[0] > RATE_WINDOW_SECONDS
        ):
            historial.popleft()

        if len(historial) >= RATE_LIMIT:
            return True

        historial.append(ahora)
        return False


@app.get("/health")
def health():
    return jsonify({
        "servicio": "api-gateway",
        "estado": "OK",
        "max_concurrent_requests": MAX_CONCURRENT_REQUESTS,
        "rate_limit": RATE_LIMIT,
        "rate_window_seconds": RATE_WINDOW_SECONDS
    }), 200


@app.get("/api/reservas")
def listar_reservas():
    try:
        respuesta = requests.get(
            f"{RESERVAS_URL}/reservas",
            timeout=5
        )

        return (
            jsonify(respuesta.json()),
            respuesta.status_code
        )

    except requests.RequestException as error:
        app.logger.error(
            "Reservas Service no disponible: %s",
            error
        )

        return jsonify({
            "estado": "error",
            "codigo": "RESERVAS_NO_DISPONIBLE"
        }), 503


@app.post("/api/reservas")
def crear_reserva():
    client_ip = (
        request.headers.get("X-Forwarded-For")
        or request.remote_addr
        or "desconocido"
    )

    if limite_superado(client_ip):
        app.logger.warning(
            "Rate limit superado por %s",
            client_ip
        )

        return jsonify({
            "estado": "rechazada",
            "codigo": "RATE_LIMIT_EXCEEDED",
            "mensaje": (
                "Se superó el límite de solicitudes. "
                "Intente nuevamente más tarde."
            )
        }), 429

    adquirido = bulkhead.acquire(blocking=False)

    if not adquirido:
        app.logger.warning(
            "Bulkhead saturado. Solicitud rechazada."
        )

        return jsonify({
            "estado": "rechazada",
            "codigo": "GATEWAY_SATURADO",
            "mensaje": (
                "El sistema alcanzó su capacidad máxima "
                "de procesamiento."
            )
        }), 503

    try:
        respuesta = requests.post(
            f"{RESERVAS_URL}/reservas",
            json=request.get_json(silent=True) or {},
            timeout=10
        )

        try:
            contenido = respuesta.json()
        except ValueError:
            contenido = {
                "estado": "error",
                "mensaje": respuesta.text
            }

        return jsonify(contenido), respuesta.status_code

    except requests.Timeout:
        return jsonify({
            "estado": "error",
            "codigo": "RESERVAS_TIMEOUT",
            "mensaje": "El Servicio de Reservas tardó demasiado"
        }), 504

    except requests.RequestException as error:
        app.logger.error(
            "Error comunicándose con Reservas: %s",
            error
        )

        return jsonify({
            "estado": "error",
            "codigo": "RESERVAS_NO_DISPONIBLE",
            "mensaje": "No fue posible procesar la solicitud"
        }), 503

    finally:
        bulkhead.release()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        threaded=True
    )