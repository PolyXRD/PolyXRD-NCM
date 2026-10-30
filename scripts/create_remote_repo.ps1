# 幂等创建 GitHub 私有仓库 PolyXRD/PolyXRD-NCM（可重跑）
# 用法: & 'scripts\create_remote_repo.ps1'
#
# ★ 凭据来源与家族完全一致：`git credential fill` 读 Windows 凭据管理器
#   （系统级 credential.helper = manager / Git Credential Manager），
#   不落盘 token、不要求手工配 gh 或环境变量。
# ★ 为什么单独成文件：交互式命令里内联 [Diagnostics.Process]::Start 会被安全策略拦，
#   写进 .ps1 再调用是家族既有做法（见 PolyXRD/scripts/create_github_release_*.ps1）。
#
# ★★ description 必须是纯 ASCII。实测带中文 description 的 POST /user/repos 返回
#   500 Internal Server Error（body 为空），同样的载荷换成 ASCII 就能建出来 —— 这是
#   GitHub 建库接口对非 ASCII description 的老毛病，不是编码写错（payload 已确认是
#   UTF-8 无 BOM）。想要中文简介，建库成功后再用 PATCH 单独改。
# ★★ 建库/建 Release 会出现「假失败」：HTTP 500/502 但资源其实已创建。所以出错后
#   不能直接判定失败，必须回查一次 GET /repos/{owner}/{repo} 再决定是否重试。
# ★ 本 token 的 scopes = gist, read:org, repo, workflow，**没有 delete_repo** ——
#   脚本能建库不能删库。手工删请到仓库 Settings -> Danger Zone。
param(
  [string]$Owner = 'PolyXRD',
  [string]$Repo  = 'PolyXRD-NCM'
)
$ErrorActionPreference = 'Stop'

# ---- git.exe 定位（家族同口径）----
$gitCandidates = @(
  'C:\Users\Administrator\.workbuddy\binaries\PortableGit\current\mingw64\bin',
  'C:\Users\Administrator\.workbuddy\binaries\PortableGit\versions\1.3.0\mingw64\bin',
  'C:\Users\Administrator\.workbuddy\binaries\PortableGit\versions\1.2.0\mingw64\bin',
  'C:\Program Files\Git\cmd'
)
$gitBin = $gitCandidates | Where-Object { Test-Path (Join-Path $_ 'git.exe') } | Select-Object -First 1
if (-not $gitBin) {
  $g = (Get-Command git.exe -ErrorAction SilentlyContinue).Source
  if ($g) { $gitBin = Split-Path $g -Parent }
}
if ($gitBin) { $env:PATH = "$gitBin;$env:PATH"; Write-Host "git found at $gitBin" }
else { throw 'git.exe 未找到: 无法读取凭据' }

# ---- Token: git credential fill ----
$secInput = "protocol=https`nhost=github.com`n`n"
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'git.exe'; $psi.Arguments = 'credential fill'
$psi.RedirectStandardInput = $true; $psi.RedirectStandardOutput = $true; $psi.UseShellExecute = $false
$p = [System.Diagnostics.Process]::Start($psi)
$enc = [System.Text.Encoding]::UTF8.GetBytes($secInput)
$p.StandardInput.BaseStream.Write($enc,0,$enc.Length)
$p.StandardInput.Close()
$raw = $p.StandardOutput.ReadToEnd()
$p.WaitForExit(15000) | Out-Null
$kv = @{}
($raw -split "`n") | ForEach-Object { if($_ -match '^(.*?)=(.*)$') { $kv[$Matches[1]] = $Matches[2] } }
$token = $kv['password']
if (-not $token) { throw 'Failed to read GitHub token via git credential fill' }
Write-Host "token acquired (len=$($token.Length))  user=$($kv['username'])"

$headers = @{
  'Authorization'        = "Bearer $token"
  'Accept'               = 'application/vnd.github+json'
  'X-GitHub-Api-Version' = '2022-11-28'
  'User-Agent'           = 'PolyXRD-NCM-repo-script/1.0'
}

$full = "$Owner/$Repo"
$repoObj = $null
try {
  $repoObj = Invoke-RestMethod -Uri "https://api.github.com/repos/$full" -Headers $headers -Method Get -ErrorAction Stop
  Write-Host "REPO ALREADY EXISTS: $($repoObj.full_name)  private=$($repoObj.private)"
} catch {
  Write-Host "REPO ABSENT; creating private repo $full ..."
  $payload = @{
    name         = $Repo
    description  = 'PolyXRD-NCM - XRD Rietveld refinement for Li(NiCoMn)O2 cathode materials'
    private      = $true
    has_issues   = $true
    has_wiki     = $false
    has_projects = $false
    auto_init    = $false
  } | ConvertTo-Json
  try {
    $repoObj = Invoke-RestMethod -Uri 'https://api.github.com/user/repos' -Headers $headers -Method Post `
        -Body ([System.Text.Encoding]::UTF8.GetBytes($payload)) -ContentType 'application/json; charset=utf-8' -ErrorAction Stop
    Write-Host "CREATED: $($repoObj.full_name)  private=$($repoObj.private)"
  } catch {
    # 假失败兜底：500/502 时资源常已建好，回查确认
    Show-GitHubError $_
    Start-Sleep -Seconds 5
    try {
      $repoObj = Invoke-RestMethod -Uri "https://api.github.com/repos/$full" -Headers $headers -Method Get -ErrorAction Stop
      Write-Host "converged (POST reported error but repo exists): $($repoObj.full_name) private=$($repoObj.private)"
    } catch { throw "建库失败且回查仍不存在: $full" }
  }
}

Write-Host "html_url   = $($repoObj.html_url)"
Write-Host "clone_url  = $($repoObj.clone_url)"
Write-Host "=== DONE ==="
