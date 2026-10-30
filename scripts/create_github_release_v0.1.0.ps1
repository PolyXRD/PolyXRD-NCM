# PolyXRD-NCM v0.1.0 GitHub Release 创建 + 附件上传（幂等可重跑）
# 用法: & 'scripts\create_github_release_v0.1.0.ps1'
#
# ★ 凭据：与 PolyXRD 家族完全一致 —— `git credential fill` 读 Windows 凭据管理器
#   （系统级 credential.helper = manager）。不落盘 token。
# ★ 幂等：Release 已存在则复用；附件按 **sha256 digest + size** 比对，一致则 SKIP，
#   不一致则删旧重传（只比 size 会漏 —— 同名同大小但内容不同时会误判跳过）。
# ★ 附件顺序小 → 大：先失败先暴露，不必等 100 MB 传完才发现 token 没权限。
# ★ 上传用 curl.exe 而非 Invoke-RestMethod：PS 的 HttpClient 对 >100 MB 的
#   `--data-binary` 等价操作会整块进内存；curl 流式读，且 `-H 'Expect:'`
#   去掉 100-continue 才能稳定过 GitHub 的反向代理。
# ★ 白名单守卫：只允许本项目两个交付物 + SHA256 清单，防止误把 XRData/ 的
#   实测谱或 Maud 数据传上 Release。
param()
$ErrorActionPreference = 'Stop'
Set-Location 'D:/Project/PolyXRD-Tools/PolyXRD-NCM'
. "$PSScriptRoot\_gh_cred.ps1"

$owner   = 'PolyXRD'
$repo    = 'PolyXRD-NCM'
$tag     = 'v0.1.0'
$version = '0.1.0'
$baseURL = "https://api.github.com/repos/$owner/$repo"
$distDir = 'D:/Project/PolyXRD-Tools/PolyXRD-NCM/dist'
$instDir = 'D:/Project/PolyXRD-Tools/PolyXRD-NCM/installer_output'

$headers = Get-GitHubHeaders
$token   = Get-GitHubToken

# ---- Release notes ----
$body = @'
## PolyXRD-NCM v0.1.0

首个可用版本。面向三元锂电正极材料 **Li(NiCoMn)O₂** 及其氢氧化物前驱体的
XRD 粉末衍射全谱 Rietveld 精修工具。单窗口：左侧谱图处理，右侧内置 CIF。

### 能做什么

- **谱图处理**：平滑（Savitzky-Golay）、扣背景、去 Kα₂、寻峰（带相对突出度门槛）
- **NCM 判定门**：导入数据后先判「是不是层状 NCM 或其前驱体」，非层状相弹框中止
  - C1 特征峰齐全度｜C2 (006)/(012) 与 (108)/(110) 双峰分裂｜C3 结构指纹相关度
  - 指纹相关度的理论谱峰宽**由实测强峰 FWHM 反演**，不写死仪器参数
- **内置 CIF**：COD 来源的 NCM 811 / 622 / 523 / 111 等 14 份，另支持导入外部 CIF
- **精修**：两段式分段策略（stage1a 择优取向 → stage1b TCH 尺寸/应变 → stage2 占位）
  - 输出 a, b, c, α, β, γ、晶粒尺寸 D、微观应变 ε、Li 占位、Rwp / RB / GOF
  - 输出晶系 / 点群 / 空间群 / 劳厄群（由空间群表反查，R-3m = No.166）
- **第二相槽位**：主相之外可挂一相共精修
- **导出**：谱图（PNG / SVG / HTML）与结果表，界面与报告共用同一套色板

### 交付物

| 文件 | 说明 |
|---|---|
| `PolyXRD-NCM-Internal-v0.1.0.exe` | 内部评估版（单文件，无注册界面） |
| `PolyXRD-NCM-v0.1.0-Setup.exe` | 安装注册版（Inno Setup） |
| `SHA256-v0.1.0.txt` | 两份产物的 SHA256 |

### 已知限制（不要当成 bug 追）

1. **峰列表暂不给 hkl 列**。六方 R 晶系的 3-index 消光条件为 `2h+k+l ≡ 0 (mod 3)`，
   而 NCM 文献最常用的标注 (105)/(108)/(201) 在此约定下恰是禁戒反射 —— 给出 hkl
   反而会误导，故只给 2θ / 强度 / 相对强度。
2. **「未测定」不写成「测得 0」**。ε 触下界记「未检出可分辨微观应变」，D 达上限记
   「超出检出上限」，不显示 `0.000` 的假精度，也不显示 `inf`。
3. **Li 占位与峰形的固有耦合**：Li 占位误差在段 1 无法精修，只能被峰形吸收，
   于是 stage1a 的 U/V/W 与择优取向参数一起漂。这是两段式策略的同源代价，
   不是实现缺陷。
4. 本版只挡明显非层状相。混相含量低时判定门可能放行，请自行核对残差与 RB。

### 交叉验证

已用 GSAS-II（build 5844）对同一份 NCM 811 实测谱 + 同一份 CIF 做独立精修比对：
`a` 偏差 0.073%、`c` 偏差 0.015%。`a` 的差异可量化归因于本程序精修了零位
（zero = +0.01451°，GSAS-II 侧固定 0）：(003) 峰 2θ = 18.741° 处理论 Δa = 0.077%，
实测 0.073%，比值 0.95。Rwp 不可直接比较 —— 两侧自由参数个数不同。

联系方式：sshztx@outlook.com
'@

# ---- Idempotent: find or create release（GitHub 建 Release 偶发 500/502 假失败，需重试后核对）----
$existing = $null
$releaseId = $null
$uploadURL = $null
for ($i = 1; $i -le 5; $i++) {
  try {
    $existing = Invoke-RestMethod -Uri "$baseURL/releases/tags/$tag" -Headers $headers -Method Get -ErrorAction Stop
    Write-Host "Release ALREADY EXISTS: id=$($existing.id) url=$($existing.html_url)"
    $releaseId = $existing.id
    $uploadURL = $existing.upload_url -replace '\{.*\}$',''
    break
  } catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -ne 404) { Write-Host "GET release HTTP $code (attempt $i) - retrying" }
    else { Write-Host "Release does not exist; creating (attempt $i)..." }
    $create = @{
      tag_name               = $tag
      target_commitish       = 'main'
      name                   = "PolyXRD-NCM v$version"
      body                   = $body
      draft                  = $false
      prerelease             = $false
      make_latest            = 'true'
      generate_release_notes = $false
    } | ConvertTo-Json -Depth 5
    try {
      $created = Invoke-RestMethod -Uri "$baseURL/releases" -Headers $headers -Method Post `
        -Body ([System.Text.Encoding]::UTF8.GetBytes($create)) -ContentType 'application/json; charset=utf-8' -ErrorAction Stop
      Write-Host "CREATED release id=$($created.id) url=$($created.html_url)"
      $releaseId = $created.id
      $uploadURL = $created.upload_url -replace '\{.*\}$',''
      break
    } catch {
      # 500/502 常见于「其实已建好但响应出错」-> 回查一次再决定
      Write-Host "POST release failed: $(Show-GitHubError $_)"
      Start-Sleep -Seconds (4*$i)
      try {
        $existing = Invoke-RestMethod -Uri "$baseURL/releases/tags/$tag" -Headers $headers -Method Get -ErrorAction Stop
        Write-Host "converged: release id=$($existing.id) url=$($existing.html_url)"
        $releaseId = $existing.id
        $uploadURL = $existing.upload_url -replace '\{.*\}$',''
        break
      } catch { Write-Host "still absent; retry" }
    }
  }
}
if (-not $releaseId) { throw "无法创建或取得 Release $tag" }

# ---- Refresh body（幂等：正文以脚本为准）----
try {
  $patch = @{ body = $body; name = "PolyXRD-NCM v$version" } | ConvertTo-Json
  Invoke-RestMethod -Uri "$baseURL/releases/$releaseId" -Headers $headers -Method Patch `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($patch)) -ContentType 'application/json; charset=utf-8' | Out-Null
  Write-Host "release body refreshed"
} catch { Write-Host "WARN: body patch failed: $($_.Exception.Message)" }

$existingAssets = @()
try { $existingAssets = Invoke-RestMethod -Uri "$baseURL/releases/$releaseId/assets" -Headers $headers } catch {}

# ★ 白名单守卫：本项目只发行程序两个交付物 + 校验清单，数据资产一律不上 Release
$ALLOWED = '^(SHA256-v[\d.]+\.txt|PolyXRD-NCM-Internal-v[\d.]+\.exe|PolyXRD-NCM-v[\d.]+-Setup\.exe)$'
function Assert-Allowed([string]$s) {
  if ($s -notmatch $ALLOWED) { throw "拒绝上传 '$s' —— 不在白名单内（只发行程序产物与 SHA256 清单）" }
}

$curlExe = (Get-Command curl.exe -ErrorAction SilentlyContinue).Source
if (-not $curlExe) {
  $fallback = 'C:\Windows\System32\curl.exe'
  if (Test-Path $fallback) { $curlExe = $fallback } else { throw 'curl.exe 不存在; 无法上传附件' }
}

function Upload-Asset([string]$filePath, [string]$assetName, [string]$contentType, [int]$retries = 6) {
  Assert-Allowed $assetName
  if (-not (Test-Path $filePath)) { throw "附件不存在: $filePath" }
  $fi = Get-Item $filePath
  $size = $fi.Length
  $localHash = 'sha256:' + (Get-FileHash -Algorithm SHA256 -Path $filePath).Hash.ToLower()
  foreach ($o in $existingAssets) { if ($o.name -eq $assetName) {
    if ($o.state -eq 'uploaded' -and $o.size -eq $size -and $o.digest -eq $localHash) {
      Write-Host "SKIP $assetName (already uploaded, size+digest match)"
      return $o
    }
    Write-Host ("  stale: remote digest=" + $o.digest + " local=" + $localHash + " -> replace")
    Write-Host "  del existing asset id=$($o.id) ..."
    Invoke-RestMethod -Uri "$baseURL/releases/assets/$($o.id)" -Headers $headers -Method Delete | Out-Null
  }}
  Write-Host "Uploading $assetName ($([math]::Round($size/1MB,1)) MB)..."
  $name = [Uri]::EscapeDataString($assetName)
  $uri = "$uploadURL`?name=$name"
  $tmpOut = Join-Path $env:TEMP "ncm_curl_$assetName.out"
  $tmpErr = Join-Path $env:TEMP "ncm_curl_$assetName.err"
  for ($i=1; $i -le $retries; $i++) {
    if (Test-Path $tmpOut) { Remove-Item $tmpOut -Force -ErrorAction SilentlyContinue }
    if (Test-Path $tmpErr) { Remove-Item $tmpErr -Force -ErrorAction SilentlyContinue }
    $curlArgs = @(
      '-sS','-X','POST',
      '-H', "Authorization: Bearer $token",
      '-H', 'Accept: application/vnd.github+json',
      '-H', 'X-GitHub-Api-Version: 2022-11-28',
      '-H', 'User-Agent: PolyXRD-NCM-upload/1.0',
      '-H', "Content-Type: $contentType",
      '-H', 'Expect:',
      '--data-binary', "@$filePath",
      $uri
    )
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    & $curlExe @curlArgs 1> $tmpOut 2> $tmpErr
    $procExit = $LASTEXITCODE
    $sw.Stop()
    if ($procExit -eq 0 -and (Test-Path $tmpOut)) {
      try {
        $up = Get-Content $tmpOut -Raw | ConvertFrom-Json
        if ($up.browser_download_url) {
          $mbps = [math]::Round(($size/1MB)/$sw.Elapsed.TotalSeconds, 2)
          Write-Host ("  OK in $([math]::Round($sw.Elapsed.TotalSeconds,1))s ($mbps MB/s) -> $($up.browser_download_url)")
          return $up
        }
      } catch { Write-Host "    retry ${i}: bad JSON response" }
    } else {
      $errMsg = if (Test-Path $tmpErr) { (Get-Content $tmpErr -Raw -ErrorAction SilentlyContinue) } else { '' }
      Write-Host ("    retry ${i}/${retries} curl exit=${procExit}: " + ($errMsg -replace "`n",' '))
    }
    Start-Sleep -Seconds (5*[Math]::Min($i,6))
  }
  throw "FAILED upload $assetName after $retries tries"
}

# 小 → 大
Upload-Asset -FilePath (Join-Path $instDir "SHA256-v$version.txt")                -AssetName "SHA256-v$version.txt"                -ContentType 'text/plain'
Upload-Asset -FilePath (Join-Path $distDir "PolyXRD-NCM-Internal-v$version.exe")  -AssetName "PolyXRD-NCM-Internal-v$version.exe"  -ContentType 'application/vnd.microsoft.portable-executable'
Upload-Asset -FilePath (Join-Path $instDir "PolyXRD-NCM-v$version-Setup.exe")     -AssetName "PolyXRD-NCM-v$version-Setup.exe"     -ContentType 'application/vnd.microsoft.portable-executable'

# ---- Final summary ----
Write-Host "=== FINAL RELEASE INFO ==="
$f = Invoke-RestMethod -Uri "$baseURL/releases/tags/$tag" -Headers $headers
Write-Host "Release : $($f.html_url)"
Write-Host "Tag     : $($f.tag_name) @ $($f.target_commitish)"
Write-Host "Draft   : $($f.draft) / Prerelease: $($f.prerelease)"
foreach ($a in $f.assets) { Write-Host ("  " + $a.name + "  " + [math]::Round($a.size/1MB,1) + " MB  -> " + $a.browser_download_url) }
Write-Host "=== DONE ==="
