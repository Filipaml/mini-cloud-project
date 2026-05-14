# ─── Registar ───────────────────────────────────────────────────────────────
Write-Host "`n[1] Registar utilizador..." -ForegroundColor Cyan
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/register" `
  -ContentType "application/json" `
  -Body '{"username":"alice","password":"secret"}'

# ─── Login ───────────────────────────────────────────────────────────────────
Write-Host "`n[2] Login..." -ForegroundColor Cyan
$token = (Invoke-RestMethod -Method Post -Uri "http://localhost:8000/login" `
  -ContentType "application/json" `
  -Body '{"username":"alice","password":"secret"}').access_token
Write-Host "Token obtido: $($token.Substring(0, 20))..."

# ─── Ficheiro de teste (5 MB) ─────────────────────────────────────────────
Write-Host "`n[3] Criar ficheiro de teste (5 MB)..." -ForegroundColor Cyan
$bytes = New-Object byte[] (5MB)
(New-Object Random).NextBytes($bytes)
[IO.File]::WriteAllBytes("$PWD\test.bin", $bytes)
Write-Host "Ficheiro criado: $PWD\test.bin"

# ─── Upload ──────────────────────────────────────────────────────────────────
Write-Host "`n[4] Upload..." -ForegroundColor Cyan
$resp = curl.exe -s -X POST "http://localhost:8000/files/upload" `
  -H "Authorization: Bearer $token" `
  -F "file=@$PWD\test.bin" | ConvertFrom-Json

$resp
$fileId = $resp.file_id
Write-Host "file_id: $fileId"

# ─── Listar ficheiros ────────────────────────────────────────────────────────
Write-Host "`n[5] Listar ficheiros..." -ForegroundColor Cyan
Invoke-RestMethod -Uri "http://localhost:8000/files" `
  -Headers @{Authorization = "Bearer $token"}

# ─── Download ────────────────────────────────────────────────────────────────
Write-Host "`n[6] Download..." -ForegroundColor Cyan
Invoke-WebRequest -Uri "http://localhost:8000/files/$fileId" `
  -Headers @{Authorization = "Bearer $token"} -OutFile "$PWD\downloaded.bin"

# ─── Verificação SHA-256 ─────────────────────────────────────────────────────
Write-Host "`n[7] Verificacao SHA-256..." -ForegroundColor Cyan
$hashOriginal  = (Get-FileHash "$PWD\test.bin"       -Algorithm SHA256).Hash
$hashDownload  = (Get-FileHash "$PWD\downloaded.bin" -Algorithm SHA256).Hash

Write-Host "Original : $hashOriginal"
Write-Host "Download : $hashDownload"

if ($hashOriginal -eq $hashDownload) {
    Write-Host "`nOK - Hashes identicos, ficheiro integro!" -ForegroundColor Green
} else {
    Write-Host "`nERRO - Hashes diferentes!" -ForegroundColor Red
}
