import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  stages: [
    { duration: "10s", target: 20 },
    { duration: "20s", target: 100 },
    { duration: "10s", target: 0 }
  ],

  thresholds: {
    http_req_duration: ["p(95)<10000"],
    http_req_failed: ["rate<0.90"]
  }
};

export default function () {
  const payload = JSON.stringify({
    evento_id: 1,
    usuario: `usuario-${__VU}-${__ITER}`,
    correo: `usuario${__VU}-${__ITER}@correo.com`,
    cantidad: 1,
    monto: 25.00
  });

  const params = {
    headers: {
      "Content-Type": "application/json"
    },

    timeout: "15s"
  };

  const response = http.post(
    "http://localhost:8080/api/reservas",
    payload,
    params
  );

  check(response, {
    "respuesta controlada": (r) =>
      [200, 201, 400, 409, 429, 503, 504].includes(r.status),

    "gateway no colapsó": (r) =>
      r.status !== 0
  });

  sleep(0.1);
}