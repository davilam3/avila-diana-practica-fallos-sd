Write-Host "=== EL DILUVIO DE PETICIONES ===" `
  -ForegroundColor Cyan

Write-Host "Comprobando que el API Gateway esté disponible..."

try {
    $health = Invoke-RestMethod `
        -Uri "http://localhost:8080/health" `
        -Method GET `
        -TimeoutSec 5

    Write-Host "API Gateway disponible: $($health.estado)" `
      -ForegroundColor Green
}
catch {
    Write-Host "No se puede acceder a http://localhost:8080." `
      -ForegroundColor Red

    Write-Host "Ejecute primero:"
    Write-Host `
      "kubectl port-forward service/api-gateway 8080:80 -n sistema-reservas"

    exit 1
}

Write-Host "`nEstado inicial del HPA:"

kubectl get hpa `
  -n sistema-reservas

Write-Host "`nPods iniciales del API Gateway:"

kubectl get pods `
  -n sistema-reservas `
  -l app=api-gateway `
  -o wide

Write-Host "`nIniciando la prueba de carga con k6..." `
  -ForegroundColor Yellow

k6 run ".\chaos\03-diluvio-k6.js"

if ($LASTEXITCODE -ne 0) {
    Write-Host `
      "k6 terminó con umbrales incumplidos; revise los resultados." `
      -ForegroundColor Yellow
}

Write-Host "`nEstado final del HPA:"

kubectl get hpa `
  -n sistema-reservas

Write-Host "`nPods finales del API Gateway:"

kubectl get pods `
  -n sistema-reservas `
  -l app=api-gateway `
  -o wide

Write-Host "`nUso de recursos:"

kubectl top pods `
  -n sistema-reservas `
  -l app=api-gateway

Write-Host "`nPrueba de sobrecarga terminada." `
  -ForegroundColor Green