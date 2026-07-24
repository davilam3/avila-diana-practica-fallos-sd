Write-Host "=== EL CORREO PERDIDO ===" `
  -ForegroundColor Cyan

Write-Host "Desactivando Notificaciones..."

kubectl scale deployment notificaciones-service `
  --replicas=0 `
  -n sistema-reservas

Start-Sleep -Seconds 3

Write-Host "`nEstado del servicio:"

kubectl get deployment notificaciones-service `
  -n sistema-reservas

kubectl get pods `
  -n sistema-reservas `
  -l app=notificaciones-service

Write-Host "`nRealice una reserva." `
  -ForegroundColor Yellow

Write-Host "El comportamiento esperado es:"
Write-Host "- Inventario descontado."
Write-Host "- Pago aprobado."
Write-Host "- Reserva confirmada."
Write-Host "- Notificación marcada como pendiente."
Write-Host "- La compra no debe anularse por el fallo del correo."