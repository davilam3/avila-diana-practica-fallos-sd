import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  stages: [
    { duration: "20s", target: 20 },
    { duration: "30s", target: 60 },
    { duration: "30s", target: 100 },
    { duration: "20s", target: 0 },
  ],

  thresholds: {
    http_req_duration: ["p(95)<10000"],
    http_req_failed: ["rate<0.80"],
  },
};

export default function () {
  const numero = `${__VU}-${__ITER}`;

  const payload = JSON.stringify({
    usuario: `UsuarioCarga-${numero}`,
    correo: `carga-${numero}@correo.com`,
    evento_id: 1,
    cantidad: 1,
    monto: 25.0,
  });

  const params = {
    headers: {
      "Content-Type": "application/json",
    },
    timeout: "10s",
  };

  const respuesta = http.post(
    "http://host.docker.internal:8080/api/reservas",
    payload,
    params
  );

  check(respuesta, {
    "respuesta controlada": (r) =>
      r.status === 201 ||
      r.status === 200 ||
      r.status === 429 ||
      r.status === 503 ||
      r.status === 504,
  });

  sleep(0.2);
}