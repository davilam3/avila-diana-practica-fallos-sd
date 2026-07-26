$ErrorActionPreference = "Stop"

$namespace = "sistema-reservas"
$deployment = "pagos-service"
$patchFile = ".\chaos\02-pasarela-lenta.yaml"

Write-Host ""
Write-Host "=============================================="
Write-Host " INYECTANDO FALLO: PASARELA LENTA"
Write-Host "=============================================="
Write-Host ""

Write-Host "Configurando PAYMENT_DELAY_SECONDS=20..."

kubectl patch deployment $deployment `
  -n $namespace `
  --patch-file $patchFile

Write-Host ""
Write-Host "Esperando que finalice el rollout..."

kubectl rollout status deployment/$deployment `
  -n $namespace `
  --timeout=180s

Write-Host ""
Write-Host "Verificando la variable de entorno..."

kubectl get deployment $deployment `
  -n $namespace `
  -o jsonpath="{.spec.template.spec.containers[0].env}"

Write-Host ""
Write-Host ""
Write-Host "Pods actuales del Servicio de Pagos:"

kubectl get pods `
  -n $namespace `
  -l app=pagos-service `
  -o wide

Write-Host ""
Write-Host "Fallo inyectado correctamente."
Write-Host "Pagos tardará 20 segundos por solicitud."