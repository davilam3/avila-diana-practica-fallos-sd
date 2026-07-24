Write-Host "=== LA PASARELA LENTA ===" -ForegroundColor Cyan

Write-Host "Configurando Pagos con una latencia de 20 segundos..."

kubectl patch deployment pagos-service `
  -n sistema-reservas `
  --type strategic `
  --patch-file ".\chaos\02-pasarela-lenta.yaml"

if ($LASTEXITCODE -ne 0) {
    Write-Host "No se pudo aplicar el parche." -ForegroundColor Red
    exit 1
}

Write-Host "`nEsperando que termine el despliegue..."

kubectl rollout status deployment/pagos-service `
  -n sistema-reservas `
  --timeout=120s

Write-Host "`nConfiguración aplicada:"

kubectl get deployment pagos-service `
  -n sistema-reservas `
  -o jsonpath="{.spec.template.spec.containers[0].env}"

Write-Host "`n`nEstado del pod de Pagos:"

kubectl get pods `
  -n sistema-reservas `
  -l app=pagos-service `
  -o wide

Write-Host "`nEl Servicio de Pagos tardará 20 segundos." `
  -ForegroundColor Yellow

Write-Host "Realice una reserva y compruebe que:"
Write-Host "- Reservas cancela la espera mediante un timeout."
Write-Host "- El cliente recibe un error controlado."
Write-Host "- Después de varios fallos se abre el Circuit Breaker."