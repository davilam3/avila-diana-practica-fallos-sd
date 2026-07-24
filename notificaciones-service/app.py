import logging
import os
import random
import time
import uuid

from flask import Flask, jsonify, request


app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)


@app.get("/health")
def health():
    return jsonify({
        "servicio": "notificaciones-service",
        "estado": "OK"
    }), 200


@app.post("/notificaciones/enviar")
def enviar_notificacion():
    datos = request.get_json(silent=True) or {}

    reserva_id = datos.get("reserva_id")
    correo = datos.get("correo")

    if not reserva_id or not correo:
        return jsonify({
            "estado": "error",
            "mensaje": "reserva_id y correo son obligatorios"
        }), 400

    delay = float(os.getenv("NOTIFICATION_DELAY_SECONDS", "0.5"))
    failure_rate = float(os.getenv("NOTIFICATION_FAILURE_RATE", "0"))

    time.sleep(delay)

    if random.random() < failure_rate:
        return jsonify({
            "estado": "error",
            "mensaje": "No fue posible enviar el correo"
        }), 500

    notificacion_id = f"NOT-{uuid.uuid4().hex[:10].upper()}"

    app.logger.info(
        "Notificación enviada. Reserva=%s, correo=%s",
        reserva_id,
        correo
    )

    return jsonify({
        "estado": "enviada",
        "notificacion_id": notificacion_id,
        "reserva_id": reserva_id,
        "correo": correo
    }), 200


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        threaded=True
    )