import logging
import threading

from flask import Flask, jsonify, request


app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

# Inventario temporal para la práctica.
inventario = {
    "1": 100,
    "2": 50,
    "3": 25
}

inventario_lock = threading.Lock()


@app.get("/health")
def health():
    return jsonify({
        "servicio": "inventario-service",
        "estado": "OK"
    }), 200


@app.get("/inventario/<evento_id>")
def consultar_inventario(evento_id: str):
    disponibles = inventario.get(evento_id, 0)

    return jsonify({
        "evento_id": evento_id,
        "disponibles": disponibles
    }), 200


@app.post("/inventario/descontar")
def descontar_inventario():
    datos = request.get_json(silent=True) or {}

    evento_id = str(datos.get("evento_id", ""))
    cantidad = datos.get("cantidad")

    if not evento_id or cantidad is None:
        return jsonify({
            "estado": "error",
            "mensaje": "evento_id y cantidad son obligatorios"
        }), 400

    try:
        cantidad = int(cantidad)
    except (TypeError, ValueError):
        return jsonify({
            "estado": "error",
            "mensaje": "cantidad debe ser un número entero"
        }), 400

    if cantidad <= 0:
        return jsonify({
            "estado": "error",
            "mensaje": "cantidad debe ser mayor que cero"
        }), 400

    with inventario_lock:
        disponibles = inventario.get(evento_id, 0)

        if disponibles < cantidad:
            return jsonify({
                "estado": "sin_disponibilidad",
                "evento_id": evento_id,
                "disponibles": disponibles
            }), 409

        inventario[evento_id] = disponibles - cantidad

    app.logger.info(
        "Inventario descontado. Evento=%s, cantidad=%s, restantes=%s",
        evento_id,
        cantidad,
        inventario[evento_id]
    )

    return jsonify({
        "estado": "descontado",
        "evento_id": evento_id,
        "cantidad": cantidad,
        "disponibles": inventario[evento_id]
    }), 200


@app.post("/inventario/restaurar")
def restaurar_inventario():
    datos = request.get_json(silent=True) or {}

    evento_id = str(datos.get("evento_id", ""))
    cantidad = datos.get("cantidad")

    if not evento_id or cantidad is None:
        return jsonify({
            "estado": "error",
            "mensaje": "evento_id y cantidad son obligatorios"
        }), 400

    try:
        cantidad = int(cantidad)
    except (TypeError, ValueError):
        return jsonify({
            "estado": "error",
            "mensaje": "cantidad debe ser un número entero"
        }), 400

    with inventario_lock:
        inventario[evento_id] = inventario.get(evento_id, 0) + cantidad

    return jsonify({
        "estado": "restaurado",
        "evento_id": evento_id,
        "disponibles": inventario[evento_id]
    }), 200


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        threaded=True
    )