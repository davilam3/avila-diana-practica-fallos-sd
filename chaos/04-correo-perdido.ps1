Write-Host "=== EL CORREO PERDIDO ==="

Write-Host "Desactivando Notificaciones..."

kubectl scale deployment notificaciones-service `
  --replicas=0 `
  -n sistema-reservas

Write-Host "Estado del servicio:"

kubectl get pods `
  -n sistema-reservas `
  -l app=notificaciones-service

Write-Host "Realice una reserva."
Write-Host "La compra debe completarse con correo pendiente."