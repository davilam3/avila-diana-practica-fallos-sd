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
        "servicio": "pagos-service",
        "estado": "OK",
        "delay": os.getenv("PAYMENT_DELAY_SECONDS", "1")
    }), 200


@app.post("/pagos/procesar")
def procesar_pago():
    datos = request.get_json(silent=True) or {}

    usuario = datos.get("usuario")
    monto = datos.get("monto")

    if not usuario or monto is None:
        return jsonify({
            "estado": "error",
            "mensaje": "usuario y monto son obligatorios"
        }), 400

    try:
        monto = float(monto)
    except (TypeError, ValueError):
        return jsonify({
            "estado": "error",
            "mensaje": "monto debe ser numérico"
        }), 400

    delay = float(os.getenv("PAYMENT_DELAY_SECONDS", "1"))
    failure_rate = float(os.getenv("PAYMENT_FAILURE_RATE", "0"))

    app.logger.info(
        "Procesando pago. Usuario=%s, monto=%.2f, delay=%.1f",
        usuario,
        monto,
        delay
    )

    time.sleep(delay)

    if random.random() < failure_rate:
        app.logger.error("Fallo simulado en el Servicio de Pagos")

        return jsonify({
            "estado": "rechazado",
            "mensaje": "Error temporal en la pasarela de pagos"
        }), 500

    pago_id = f"PAG-{uuid.uuid4().hex[:10].upper()}"

    return jsonify({
        "estado": "aprobado",
        "pago_id": pago_id,
        "usuario": usuario,
        "monto": monto
    }), 200


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        threaded=True
    )