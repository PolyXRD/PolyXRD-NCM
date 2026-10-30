# 发布后终验：仓库私有性 / refs / Release / 附件可下载性 / 本地产物一致性
param()
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_gh_cred.ps1"
$headers = Get-GitHubHeaders
$token   = Get-GitHubToken
$root    = 'D:/Project/PolyXRD-Tools/PolyXRD-NCM'
$owner   = 'PolyXRD'
$repo    = 'PolyXRD-NCM'

Write-Host '=== 1) 仓库 ==='
$repoObj = Invoke-RestMethod -Uri 'https://api.github.com/repos/PolyXRD/PolyXRD-NCM' -Headers $headers
Write-Host "full_name=$($repoObj.full_name)  private=$($repoObj.private)  default_branch=$($repoObj.default_branch)"
Write-Host "pushed_at=$($repoObj.pushed_at)"

Write-Host ''
Write-Host '=== 2) Release + 附件 ==='
$rel = Invoke-RestMethod -Uri 'https://api.github.com/repos/PolyXRD/PolyXRD-NCM/releases/tags/v0.1.0' -Headers $headers
Write-Host "tag=$($rel.tag_name)  name='$($rel.name)'  draft=$($rel.draft)  pre=$($rel.prerelease)  bodyLen=$($rel.body.Length)"
$expect = @{
  'PolyXRD-NCM-Internal-v0.1.0.exe' = @{ path = "$root/dist/PolyXRD-NCM-Internal-v0.1.0.exe"; size = 104099608 }
  'PolyXRD-NCM-v0.1.0-Setup.exe'    = @{ path = "$root/installer_output/PolyXRD-NCM-v0.1.0-Setup.exe"; size = 105133685 }
}
foreach ($a in $rel.assets) {
  Write-Host ("  {0,-36} {1,11} B  state={2}" -f $a.name, $a.size, $a.state)
  if ($expect.ContainsKey($a.name)) {
    $localHash = 'sha256:' + (Get-FileHash -Algorithm SHA256 -Path $expect[$a.name].path).Hash.ToLower()
    $hit = ($a.digest -eq $localHash) -and ($a.size -eq $expect[$a.name].size)
    Write-Host ("      local-vs-remote digest+size: " + $(if ($hit) { 'MATCH' } else { 'MISMATCH!' }))
  }
}

Write-Host ''
Write-Host '=== 3) 附件可下载性（私有库必须走 API assets 端点 + Accept: octet-stream）==='
# ★ 私有仓库不能用 browser_download_url 探测：github.com/.../releases/download/...
#   认的是浏览器会话 cookie，Bearer token 在网页域无效，会得到 404（假阴性）。
#   正确做法是 GET /repos/{o}/{r}/releases/assets/{id} 带 Accept: application/octet-stream，
#   由 API 302 到 objects CDN。用 Range 只取头 1 KB，不真下 100 MB。
foreach ($a in $rel.assets) {
  $apiUrl = "https://api.github.com/repos/$owner/$repo/releases/assets/$($a.id)"
  $tmp = Join-Path $env:TEMP ("ncm_verify_" + $a.id + ".bin")
  $code = & curl.exe -sS -o $tmp -L -w '%{http_code}' `
    -H "Authorization: Bearer $token" `
    -H 'Accept: application/octet-stream' `
    -H 'X-GitHub-Api-Version: 2022-11-28' `
    -H 'User-Agent: PolyXRD-NCM/1.0' `
    -r 0-1023 $apiUrl
  $got = if (Test-Path $tmp) { (Get-Item $tmp).Length } else { 0 }
  # 首字节比对：exe 应为 'MZ'（0x4D 0x5A），txt 应为可打印 ASCII
  $head = ''
  if ($got -gt 0) {
    $bytes = [System.IO.File]::ReadAllBytes($tmp)
    $head = (($bytes[0..([Math]::Min(1, $bytes.Length-1))] | ForEach-Object { [char]$_ }) -join '')
  }
  Write-Host ("  {0,-36} HTTP {1}  first {2} B  head='{3}'" -f $a.name, $code, $got, $head)
  Remove-Item $tmp -Force -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Host '=== 4) git refs（本地）==='
Push-Location $root
& git log --oneline --decorate -3
& git status --porcelain
Pop-Location

Write-Host ''
Write-Host '=== 5) 交付物目录 ==='
Get-ChildItem "$root/dist","$root/installer_output" -File | ForEach-Object {
  Write-Host ("  {0,-42} {1,11} B  {2}" -f $_.Name, $_.Length, $_.Directory.Name)
}
Write-Host '=== VERIFY DONE ==='
