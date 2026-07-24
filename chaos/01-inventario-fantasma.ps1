Write-Host "=== INVENTARIO FANTASMA ==="

Write-Host "Desactivando Servicio de Inventario..."

kubectl scale deployment inventario-service `
  --replicas=0 `
  -n sistema-reservas

Write-Host "Estado actual:"

kubectl get pods `
  -n sistema-reservas `
  -l app=inventario-service

Write-Host "El Servicio de Inventario está desactivado."
Write-Host "Ejecute varias reservas para abrir el Circuit Breaker."