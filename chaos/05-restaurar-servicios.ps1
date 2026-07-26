Write-Host "=== RESTAURACION DE SERVICIOS ===" -ForegroundColor Cyan

Write-Host "Restaurando Servicio de Inventario..."

kubectl scale deployment inventario-service `
  --replicas=1 `
  -n sistema-reservas

Write-Host "Restaurando Servicio de Notificaciones..."

kubectl scale deployment notificaciones-service `
  --replicas=1 `
  -n sistema-reservas

Write-Host "Restaurando Servicio de Pagos..."

kubectl set env deployment/pagos-service `
  PAYMENT_DELAY_SECONDS- `
  -n sistema-reservas

Write-Host ""
Write-Host "Esperando los despliegues..."

kubectl rollout status deployment/inventario-service `
  -n sistema-reservas `
  --timeout=120s

kubectl rollout status deployment/notificaciones-service `
  -n sistema-reservas `
  --timeout=120s

kubectl rollout status deployment/pagos-service `
  -n sistema-reservas `
  --timeout=120s

Write-Host ""
Write-Host "Estado final de los pods:"

kubectl get pods `
  -n sistema-reservas `
  -o wide

Write-Host ""
Write-Host "Servicios restaurados correctamente." `
  -ForegroundColor Green

Write-Host "Espere algunos segundos para que los Circuit Breakers se recuperen."