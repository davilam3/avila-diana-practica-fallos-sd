Write-Host "=== RESTAURACIÓN DE SERVICIOS ===" `
  -ForegroundColor Cyan

Write-Host "Restaurando Servicio de Inventario..."

kubectl scale deployment inventario-service `
  --replicas=1 `
  -n sistema-reservas

Write-Host "Restaurando Servicio de Notificaciones..."

kubectl scale deployment notificaciones-service `
  --replicas=1 `
  -n sistema-reservas

Write-Host "Eliminando la latencia forzada de Pagos..."

kubectl set env deployment/pagos-service `
  PAYMENT_DELAY_SECONDS=0 `
  -n sistema-reservas

Write-Host "`nEsperando los rollouts..."

kubectl rollout status deployment/inventario-service `
  -n sistema-reservas `
  --timeout=120s

kubectl rollout status deployment/notificaciones-service `
  -n sistema-reservas `
  --timeout=120s

kubectl rollout status deployment/pagos-service `
  -n sistema-reservas `
  --timeout=120s

Write-Host "`nEsperando que los pods estén disponibles..."

kubectl wait `
  --for=condition=Ready `
  pod `
  -l app=inventario-service `
  -n sistema-reservas `
  --timeout=120s

kubectl wait `
  --for=condition=Ready `
  pod `
  -l app=notificaciones-service `
  -n sistema-reservas `
  --timeout=120s

kubectl wait `
  --for=condition=Ready `
  pod `
  -l app=pagos-service `
  -n sistema-reservas `
  --timeout=120s

Write-Host "`nEstado final del sistema:"

kubectl get pods `
  -n sistema-reservas `
  -o wide

Write-Host "`nServicios restaurados correctamente." `
  -ForegroundColor Green

Write-Host `
  "Espere algunos segundos para que los Circuit Breakers salgan del estado abierto."