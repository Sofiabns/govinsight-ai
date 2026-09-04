param(
  [string]$Url = "https://repositorio.dados.gov.br/seges/comprasgov/anual/2025/comprasGOV-anual-VW_FT_PNCP_COMPRA-2025.csv",
  [string]$OutputPath = "data/pncp_demo.csv",
  [int64]$MaxBytes = 8388608
)

$ErrorActionPreference = "Stop"
$directory = Split-Path -Parent $OutputPath
if ($directory) { New-Item -ItemType Directory -Force -Path $directory | Out-Null }
$response = Invoke-WebRequest -Uri $Url -Headers @{ Range = "bytes=0-$($MaxBytes - 1)" } -OutFile $OutputPath -PassThru
if ($response.StatusCode -notin 200, 206) { throw "Unexpected source status: $($response.StatusCode)" }
$contentType = [string]$response.Headers["Content-Type"]
if ($contentType -match "text/html") { throw "Source returned HTML instead of CSV" }
$firstBytes = [System.IO.File]::ReadAllBytes($OutputPath)[0..([Math]::Min(31, (Get-Item $OutputPath).Length - 1))]
$prefix = [Text.Encoding]::UTF8.GetString($firstBytes).TrimStart()
if ($prefix.StartsWith("<")) { throw "Source payload is not CSV" }

[ordered]@{
  source_url = $Url
  retrieved_at_utc = [DateTime]::UtcNow.ToString("o")
  status_code = $response.StatusCode
  etag = [string]$response.Headers["ETag"]
  last_modified = [string]$response.Headers["Last-Modified"]
  bytes = (Get-Item $OutputPath).Length
} | ConvertTo-Json | Set-Content -Encoding utf8 "$OutputPath.metadata.json"
