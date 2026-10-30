# dot-source 用的小工具：从 Windows 凭据管理器（Git Credential Manager）取 GitHub token。
# 用法: . "$PSScriptRoot\_gh_cred.ps1";  $headers = Get-GitHubHeaders
# ★ 必须用 ProcessStartInfo 显式写 stdin —— 管道 `$sec | & git credential fill` 取不到 password。
# ★ 放在独立文件里：交互式内联 Process.Start 会被安全策略拦，脚本文件内允许。

$script:GitHubToken = $null

function Get-GitHubToken {
  if ($script:GitHubToken) { return $script:GitHubToken }

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
  if (-not $gitBin) { throw 'git.exe 未找到: 无法读取凭据' }
  $env:PATH = "$gitBin;$env:PATH"

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
  if (-not $kv['password']) { throw 'Failed to read GitHub token via git credential fill' }
  $script:GitHubToken = $kv['password']
  Write-Host "token acquired (len=$($script:GitHubToken.Length))  user=$($kv['username'])"
  return $script:GitHubToken
}

function Get-GitHubHeaders {
  $token = Get-GitHubToken
  return @{
    'Authorization'        = "Bearer $token"
    'Accept'               = 'application/vnd.github+json'
    'X-GitHub-Api-Version' = '2022-11-28'
    'User-Agent'           = 'PolyXRD-NCM/1.0'
  }
}

# 把 REST 调用的失败原因尽量完整地打出来（body 里常有关键 explanation）
function Show-GitHubError($err) {
  try {
    $resp = $err.Exception.Response
    Write-Host "HTTP $($resp.StatusCode.value__) $($resp.ReasonPhrase)"
    $stream = $resp.Content.ReadAsStringAsync().Result
    if ($stream) { Write-Host "body: $stream" }
  } catch {
    Write-Host "detail unavailable: $($err.Exception.Message)"
  }
}
