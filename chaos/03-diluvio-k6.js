import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  stages: [
    { duration: "10s", target: 20 },
    { duration: "20s", target: 100 },
    { duration: "10s", target: 0 }
  ],
  thresholds: {
    http_req_duration: ["p(95)<5000"],
    http_req_failed: ["rate<0.80"]
  }
};

export default function () {
  const payload = JSON.stringify({
    evento_id: 1,
    usuario: `usuario-${__VU}`,
    correo: `usuario${__VU}@correo.com`,
    cantidad: 1,
    monto: 25.00
  });

  const params = {
    headers: {
      "Content-Type": "application/json"
    }
  };

  const response = http.post(
    "http://localhost:8080/api/reservas",
    payload,
    params
  );

  check(response, {
    "respuesta controlada": (r) =>
      [201, 429, 503, 504].includes(r.status)
  });

  sleep(0.1);
}