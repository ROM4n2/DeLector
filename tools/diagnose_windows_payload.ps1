# 便携版产物诊断：定位「dist → zip → 解压 → 安装」链路里哪一段开始缺文件。
#
# 只读、不改任何产物：打印 zip 条目、_internal 子目录计数、webview/pythonnet 的
# 扩展名分布 / 隐藏与系统属性 / reparse point（symlink、junction），以及
# installer/DeLector.iss 的 [Files] 段原文。
#
# 用法：
#   & tools/diagnose_windows_payload.ps1 -Artifact <目录> [-Zip <zip 路径>]
#
# 判 PASS/FAIL 由调用方紧接着跑 tools/verify_windows_portable.py；本脚本只出证据，
# 自身不设断言，避免「诊断脚本红了但看不出原因」。

param(
    [Parameter(Mandatory = $true)][string]$Artifact,
    [string]$Zip = "",
    [string]$IssPath = "installer/DeLector.iss"
)

$ErrorActionPreference = "Stop"

function Show-Section([string]$Title) {
    Write-Host ""
    Write-Host "==== $Title ===="
}

Show-Section "产物目录"
$root = (Resolve-Path -LiteralPath $Artifact).Path
Write-Host "path=$root"
$artifactFiles = @(Get-ChildItem -LiteralPath $root -File -Recurse -Force -ErrorAction SilentlyContinue)
Write-Host "files_total=$($artifactFiles.Count)"

if ($Zip) {
    Show-Section "zip 条目"
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $Zip).Path)
    try {
        $entries = @($archive.Entries)
        Write-Host "entries_total=$($entries.Count)"
        $webviewEntries = @($entries | Where-Object { $_.FullName -match 'webview' })
        Write-Host "entries_webview=$($webviewEntries.Count)"
        $webviewEntries | Select-Object -First 40 | ForEach-Object {
            Write-Host ("  entry " + $_.FullName + " bytes=" + $_.Length)
        }
        $internalEntries = @($entries | Where-Object { $_.FullName -match '(^|/)_internal/' })
        Write-Host "entries_internal=$($internalEntries.Count)"
        $internalEntries | Select-Object -First 20 | ForEach-Object {
            Write-Host ("  entry " + $_.FullName)
        }
    } finally {
        $archive.Dispose()
    }
}

Show-Section "_internal 子目录文件计数"
$internal = Join-Path $root "_internal"
if (Test-Path -LiteralPath $internal) {
    Get-ChildItem -LiteralPath $internal -Directory | Sort-Object Name | ForEach-Object {
        $count = @(Get-ChildItem -LiteralPath $_.FullName -File -Recurse -Force -ErrorAction SilentlyContinue).Count
        Write-Host ("  " + $_.Name + " files=" + $count)
    }
} else {
    Write-Host "  (缺少 _internal)"
}

foreach ($name in @("webview", "pythonnet")) {
    Show-Section "_internal/$name 明细"
    $dir = Join-Path $internal $name
    if (-not (Test-Path -LiteralPath $dir)) {
        Write-Host "  (目录不存在)"
        continue
    }
    $files = @(Get-ChildItem -LiteralPath $dir -File -Recurse -Force -ErrorAction SilentlyContinue)
    Write-Host "  files=$($files.Count)"
    $files | Group-Object Extension | Sort-Object Count -Descending | ForEach-Object {
        $label = if ($_.Name) { $_.Name } else { "(none)" }
        Write-Host ("  ext " + $label + " x" + $_.Count)
    }
    $hidden = @($files | Where-Object { $_.Attributes -band [IO.FileAttributes]::Hidden })
    $system = @($files | Where-Object { $_.Attributes -band [IO.FileAttributes]::System })
    $links = @($files | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })
    Write-Host "  hidden=$($hidden.Count) system=$($system.Count) reparse_points=$($links.Count)"
    $links | Select-Object -First 10 | ForEach-Object {
        Write-Host ("  link " + $_.FullName + " -> " + $_.LinkTarget)
    }
    $files | Select-Object -First 15 | ForEach-Object {
        Write-Host ("  file " + $_.FullName.Substring($dir.Length) + " attr=" + $_.Attributes)
    }
}

Show-Section "目录属性（webview/pythonnet 本身是否 reparse）"
@($internal, (Join-Path $internal "webview"), (Join-Path $internal "pythonnet")) | ForEach-Object {
    if (Test-Path -LiteralPath $_) {
        $item = Get-Item -LiteralPath $_ -Force
        Write-Host ("  " + $_ + " attr=" + $item.Attributes)
    }
}

Show-Section "$IssPath 的 [Files] 段"
if (Test-Path -LiteralPath $IssPath) {
    $inFiles = $false
    foreach ($line in (Get-Content -LiteralPath $IssPath)) {
        if ($line -match '^\s*\[Files\]') { $inFiles = $true; Write-Host $line; continue }
        if ($inFiles -and $line -match '^\s*\[') { break }
        if ($inFiles) { Write-Host $line }
    }
} else {
    Write-Host "  (找不到 $IssPath)"
}

Write-Host ""
Write-Host "诊断输出结束（判定由紧随其后的 verify_windows_portable.py 给出）"
