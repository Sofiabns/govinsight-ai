param(
  [string]$Url = "https://repositorio.dados.gov.br/seges/comprasgov/anual/comprasGOV-anual-VW_FT_PNCP_COMPRA-latest.csv",
  [string]$OutputPath = "data/pncp_demo.csv",
  [int64]$MaxBytes = 8388608
)

$ErrorActionPreference = "Stop"
$directory = Split-Path -Parent $OutputPath
if ($directory) { New-Item -ItemType Directory -Force -Path $directory | Out-Null }
$request = [System.Net.HttpWebRequest]::Create($Url)
$request.Method = "GET"
$request.AddRange(0, $MaxBytes - 1)
$response = $request.GetResponse()
try {
  $statusCode = [int]$response.StatusCode
  if ($statusCode -notin 200, 206) { throw "Unexpected source status: $statusCode" }
  $contentType = [string]$response.ContentType
  if ($contentType -match "text/html") { throw "Source returned HTML instead of CSV" }

  $sourceStream = $response.GetResponseStream()
  $targetStream = [System.IO.File]::Create($OutputPath)
  try {
    $buffer = New-Object byte[] 81920
    $remaining = $MaxBytes
    while ($remaining -gt 0) {
      $read = $sourceStream.Read($buffer, 0, [Math]::Min($buffer.Length, $remaining))
      if ($read -le 0) { break }
      $targetStream.Write($buffer, 0, $read)
      $remaining -= $read
    }
  } finally {
    $targetStream.Dispose()
    $sourceStream.Dispose()
  }
  $etag = [string]$response.Headers["ETag"]
  $lastModified = [string]$response.Headers["Last-Modified"]
} finally {
  $response.Dispose()
}
$fileLength = (Get-Item $OutputPath).Length
if ($fileLength -eq 0) { throw "Source returned an empty file" }
$firstBytes = [System.IO.File]::ReadAllBytes($OutputPath)[0..([Math]::Min(31, (Get-Item $OutputPath).Length - 1))]
$prefix = [Text.Encoding]::UTF8.GetString($firstBytes).TrimStart()
if ($prefix.StartsWith("<")) { throw "Source payload is not CSV" }

[ordered]@{
  source_url = $Url
  retrieved_at_utc = [DateTime]::UtcNow.ToString("o")
  status_code = $statusCode
  etag = $etag
  last_modified = $lastModified
  bytes = $fileLength
} | ConvertTo-Json | Set-Content -Encoding utf8 "$OutputPath.metadata.json"
