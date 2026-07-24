Write-Host "=== INVENTARIO FANTASMA ===" -ForegroundColor Cyan

Write-Host "Desactivando Servicio de Inventario..."

kubectl scale deployment inventario-service `
  --replicas=0 `
  -n sistema-reservas

Start-Sleep -Seconds 3

Write-Host "`nEstado actual:"

kubectl get deployment inventario-service `
  -n sistema-reservas

kubectl get pods `
  -n sistema-reservas `
  -l app=inventario-service

Write-Host "`nEl Servicio de Inventario está desactivado." `
  -ForegroundColor Yellow

Write-Host "Ejecute varias reservas para comprobar:"
Write-Host "- Retries con backoff"
Write-Host "- Apertura del Circuit Breaker"
Write-Host "- Respuesta controlada al cliente"