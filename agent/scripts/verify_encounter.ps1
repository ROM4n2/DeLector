# verify_encounter.ps1 — 一键验证 encounter-pack job#1 真链路（计划门 4a/b 前置）
#
# 用法（在仓库根或任意位置用 pwsh 跑）：
#   pwsh agent/scripts/verify_encounter.ps1                 # 仅 dry-run（不需要 key）
#   pwsh agent/scripts/verify_encounter.ps1 -Real           # 真跑 gloss + 落盘校验
#   pwsh agent/scripts/verify_encounter.ps1 -Corpus d:\语料 -Out d:\out -Real
#   pwsh agent/scripts/verify_encounter.ps1 -ValidateOnly    # 只校验已落盘 pack（不重跑，省 token）
#
# 行为：
#   1. 加载 cwd 的 .env（模板见 agent/env.example）到当前进程环境（仅进程内，绝不写盘）。
#   2. 生成/使用语料 fixture（2 篇 A1 德语短文）；可用 -Corpus 指定真实语料。
#   3. dry-run：验证 supervisor 起 python + 语料扫描（不需要 key）。
#   4. 传 -Real 且 DEEPSEEK_API_KEY 就绪：真跑 gloss + 落盘；默认 --deliver-url ""
#      不投真实 app，仅按 encounter-pack/v1 schema 校验本地 *.pack.json：
#      schema=encounter-pack/v1、pack_id 非空、article.title/raw_text 非空、
#      estimated_cefr∈{A1,A2,B1}（schema 见 agent/internal/job/pack.go）。
#
# 退出码：全过 0；任一步失败 1。

param(
  [string]$Corpus = "",
  [string]$Out = "",
  [switch]$Real,
  [switch]$ValidateOnly,
  # 仓库根：脚本位于 agent/scripts，故上溯两层即仓库根
  [string]$RepoRoot = (Join-Path (Split-Path $PSScriptRoot -Parent) "..")
)

$ErrorActionPreference = "Stop"

# Validate-Packs 校验目录下的 *.pack.json 是否符合 encounter-pack/v1。
# 返回 $true 表示全部通过。
function Validate-Packs([string]$dir) {
  $packs = Get-ChildItem $dir -Filter *.pack.json -ErrorAction SilentlyContinue
  if (-not $packs -or $packs.Count -eq 0) {
    Write-Host "[verify] FAIL: $dir 下无 *.pack.json" -ForegroundColor Red
    return $false
  }
  $ok = $true
  foreach ($p in $packs) {
    try {
      $j = Get-Content $p.FullName -Raw | ConvertFrom-Json
    } catch {
      Write-Host "[verify] FAIL: $($p.Name) JSON 解析失败：$_" -ForegroundColor Red
      $ok = $false
      continue
    }
    $probs = @()
    if ($j.schema -ne "encounter-pack/v1") { $probs += "schema=$($j.schema)（应为 encounter-pack/v1）" }
    if (-not $j.pack_id) { $probs += "pack_id 为空" }
    if (-not $j.article) {
      $probs += "缺 article"
    } elseif (-not $j.article.title -or -not $j.article.raw_text) {
      $probs += "article.title/raw_text 为空"
    }
    if ($j.estimated_cefr -and ("A1", "A2", "B1") -notcontains $j.estimated_cefr.Trim().ToUpper()) {
      $probs += "estimated_cefr=$($j.estimated_cefr) 不在 A1/A2/B1"
    }
    if ($probs.Count -gt 0) {
      Write-Host "[verify] FAIL: $($p.Name) → $($probs -join '; ')" -ForegroundColor Red
      $ok = $false
    } else {
      $glossN = @($j.glosses).Count
      $rate = if ($j.analysis) { $j.analysis.known_rate } else { "-" }
      Write-Host "[verify] pack OK: $($p.Name) cefr=$($j.estimated_cefr) glosses=$glossN chars=$($j.article.char_count) known_rate=$rate" -ForegroundColor Green
    }
  }
  if ($ok) {
    Write-Host "[verify] 落盘校验 PASS（共 $(@($packs).Count) 个 pack）" -ForegroundColor Green
    return $true
  }
  return $false
}

$agentDir = Join-Path $RepoRoot "agent"
if (-not (Test-Path $agentDir)) {
  Write-Host "[verify] 找不到 agent 目录：$agentDir（请用 -RepoRoot 指定仓库根）" -ForegroundColor Red
  exit 1
}
Push-Location $agentDir
try {
  # 1) 加载 .env（仅当前进程）
  if (Test-Path ".env") {
    foreach ($line in (Get-Content ".env")) {
      $line = $line.Trim()
      if ($line -eq "" -or $line.StartsWith("#")) { continue }
      $eq = $line.IndexOf("=")
      if ($eq -lt 0) { continue }
      $k = $line.Substring(0, $eq).Trim()
      $v = $line.Substring($eq + 1).Trim().Trim('"').Trim("'")
      if ($k -ne "" -and [Environment]::GetEnvironmentVariable($k) -eq $null) {
        [Environment]::SetEnvironmentVariable($k, $v, "Process")
      }
    }
    Write-Host "[verify] 已从 .env 载入环境变量（仅当前进程）" -ForegroundColor Cyan
  }

  if (-not $Out) { $Out = Join-Path $env:TEMP "encounter_verify_packs" }

  # -ValidateOnly：只校验已落盘 pack，不重跑（省 token）
  if ($ValidateOnly) {
    Write-Host "[verify] -ValidateOnly：仅校验 $Out 下已落盘 pack" -ForegroundColor Yellow
    if (Validate-Packs $Out) { exit 0 } else { exit 1 }
  }

  # 2) 语料 fixture
  if (-not $Corpus) {
    $Corpus = Join-Path $env:TEMP "encounter_verify_corpus"
    New-Item -ItemType Directory -Force -Path $Corpus | Out-Null
    Set-Content (Join-Path $Corpus "a1_1.txt") @"
Liebe Anna,
ich komme am Montag nach Berlin. Wir trinken Kaffee und essen Kuchen.
Viele Gruesse,
Tom
"@
    Set-Content (Join-Path $Corpus "a1_2.txt") @"
Hallo!
Mein Name ist Paul und ich lerne Deutsch. Ich habe einen Hund und eine Katze.
Bis bald!
"@
    Write-Host "[verify] 已生成 fixture 语料：$Corpus" -ForegroundColor Cyan
  }
  New-Item -ItemType Directory -Force -Path $Out | Out-Null

  # 3) dry-run（无需 key）
  Write-Host "`n[verify] 步骤 1/2：dry-run（启动 supervisor + 语料扫描）" -ForegroundColor Yellow
  go run ./cmd/delector job run encounter-pack --corpus $Corpus --out $Out --dry-run
  if ($LASTEXITCODE -ne 0) {
    Write-Host "[verify] FAIL: dry-run 异常（python/supervisor 或语料扫描失败）" -ForegroundColor Red
    exit 1
  }
  Write-Host "[verify] dry-run OK" -ForegroundColor Green

  # 4) real（需 key）
  if ($Real) {
    if ([Environment]::GetEnvironmentVariable("DEEPSEEK_API_KEY") -eq $null) {
      Write-Host "[verify] 需要 DEEPSEEK_API_KEY（.env 或 `$env:DEEPSEEK_API_KEY）才能 -Real。" -ForegroundColor Red
      exit 1
    }
    Write-Host "`n[verify] 步骤 2/2：真跑 gloss + 落盘（--deliver-url '' 不投真实 app）" -ForegroundColor Yellow
    go run ./cmd/delector job run encounter-pack --corpus $Corpus --out $Out --deliver-url ""
    if ($LASTEXITCODE -ne 0) {
      Write-Host "[verify] FAIL: 真跑异常（检查 DEEPSEEK_API_KEY / 网络 / token 预算）" -ForegroundColor Red
      exit 1
    }
    if (-not (Validate-Packs $Out)) { exit 1 }
    Write-Host "[verify] 注：token 消耗请在 DeepSeek 平台「用量」页查看并回填计划门 4a。" -ForegroundColor Cyan
  } else {
    Write-Host "`n[verify] 跳过真跑（未传 -Real 或缺少 key）。要真跑 gloss 请：pwsh agent/scripts/verify_encounter.ps1 -Real" -ForegroundColor Cyan
  }
} finally {
  Pop-Location
}
