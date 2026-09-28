# Disposable native EXE lifecycle only. Exit 0: executed subset passed; 1: failed; 2: refused.
param(
    [string]$Plan,
    [string]$Python = 'python',
    [switch]$DisposableVm,
    [string]$ConfirmDisposableVm = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$trusted = $env:GITHUB_ACTIONS -ceq 'true' -and $env:RUNNER_ENVIRONMENT -ceq 'github-hosted' -and $env:GITHUB_REPOSITORY -ceq 'gx0404/ohmyzsh'
if (-not $trusted -and -not ($DisposableVm -and $ConfirmDisposableVm -ceq 'I_UNDERSTAND_THIS_IS_A_DISPOSABLE_VM')) {
    [Console]::Error.WriteLine('REFUSED: EXE installation requires the trusted GitHub-hosted runner or explicit disposable-VM acknowledgement.')
    exit 2
}
if (-not $Plan -or -not (Test-Path -LiteralPath $Plan -PathType Leaf)) { throw 'A verified lifecycle plan is required.' }
$p = Get-Content -LiteralPath $Plan -Raw -Encoding UTF8 | ConvertFrom-Json
if ($p.product -cne 'ohmyzsh-gx' -or $p.platform -cne 'windows-x64') { throw 'Wrong lifecycle product/platform.' }
$evidence = [IO.Path]::GetFullPath($p.evidence)
if ([IO.Path]::GetFullPath($Plan) -cne (Join-Path $evidence 'plan.json')) { throw 'Plan must belong to its evidence directory.' }
$install = [IO.Path]::GetFullPath($p.install_root)
if ($install -notmatch '^[A-Za-z]:\\gx-lifecycle-[0-9a-f]{12}$' -or (Test-Path -LiteralPath $install)) { throw 'Install target must be a new lifecycle-owned root.' }
$driver = Join-Path $PSScriptRoot 'gx_lifecycle.py'
$owner = 'HKCU:\Software\OhMyZshGX'
$environmentKey = 'HKCU:\Environment'
$fontKey = 'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Fonts'
if (Test-Path -LiteralPath $owner) { throw 'Refusing to replace an existing OhMyZshGX installation.' }
$checks = @{}
$current = 'install'
$installed = $false
$failed = $false
$changedConflict = $false
$sentinelCreated = $false
$oldEnvironment = @{}
$workerApproval = @()
if ($DisposableVm) { $workerApproval = @('--disposable-vm', '--confirm-disposable-vm', $ConfirmDisposableVm) }

function Save-Json([string]$Name, $Value) {
    $text = $Value | ConvertTo-Json -Depth 30
    [IO.File]::WriteAllText((Join-Path $evidence $Name), $text, [Text.UTF8Encoding]::new($false))
}
function Check-Equal($Actual, $Expected, [string]$Message) {
    if (($Actual | ConvertTo-Json -Depth 30 -Compress) -cne ($Expected | ConvertTo-Json -Depth 30 -Compress)) { throw $Message }
}
function Snapshot-Fonts {
    $values = [ordered]@{}
    if (Test-Path -LiteralPath $fontKey) {
        $key = Get-Item -LiteralPath $fontKey
        foreach ($name in ($key.GetValueNames() | Sort-Object)) { $values[$name] = [string]$key.GetValue($name) }
    }
    return $values
}
function User-Path {
    $key = Get-Item -LiteralPath $environmentKey
    return [string]$key.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
}
function Set-UserPath([string]$Value) {
    New-ItemProperty -LiteralPath $environmentKey -Name Path -Value $Value -PropertyType ExpandString -Force | Out-Null
}
function Set-Result([string]$Name, [string[]]$Files) {
    $checks[$Name] = @{ status = 'passed'; evidence = $Files }
}
function Run-Installer([string]$File, [string]$Label, [switch]$Reject, [switch]$Uninstall) {
    if (-not (Test-Path -LiteralPath $File -PathType Leaf)) { throw "Installer missing: $File" }
    $arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=`"$(Join-Path $evidence "logs/$Label-installer.log")`"")
    if (-not $Uninstall) { $arguments += "/DIR=`"$install`"" }
    $process = Start-Process -FilePath $File -ArgumentList $arguments -Wait -PassThru
    Save-Json "logs/$Label-process.json" @{ file = $File; arguments = $arguments; exit_code = $process.ExitCode }
    if ($Reject) {
        if ($process.ExitCode -eq 0) { throw "$Label unexpectedly accepted the unsafe installation" }
    } elseif ($process.ExitCode -ne 0) { throw "$Label returned $($process.ExitCode)" }
}
function Worker([string]$Kind, [string]$Phase, [string]$Reference = '') {
    $arguments = @($driver, '--worker', $Kind, '--plan', $Plan, '--phase', $Phase) + $workerApproval
    if ($Reference) { $arguments += @('--reference', $Reference) }
    & $Python @arguments 2>&1 | Out-File -LiteralPath (Join-Path $evidence "logs/$Phase-worker.log") -Encoding UTF8
    if ($LASTEXITCODE -ne 0) { throw "$Kind worker $Phase failed ($LASTEXITCODE)" }
}
function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = $machine + ';' + $user
}
function Resolve-Commands([string]$Label) {
    Refresh-Path
    $code = '[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); Get-Command gx-zsh,herdr -CommandType Application | ForEach-Object { $_.Source }'
    $resolved = & (Join-Path $env:SYSTEMROOT 'System32/WindowsPowerShell/v1.0/powershell.exe') -NoProfile -NonInteractive -Command $code 2>&1
    $exitCode = $LASTEXITCODE
    $resolved | Out-File -LiteralPath (Join-Path $evidence "logs/$Label-resolution.log") -Encoding UTF8
    if ($exitCode -ne 0) { throw 'Fresh-process command resolution failed.' }
    $expected = @((Join-Path $install 'bin/gx-zsh.exe'), (Join-Path $install 'bin/herdr.exe'))
    for ($index = 0; $index -lt 2; $index++) {
        if ([IO.Path]::GetFullPath([string]$resolved[$index]) -ine [IO.Path]::GetFullPath($expected[$index])) { throw 'A fresh process resolved a foreign command.' }
    }
    & (Join-Path $install 'bin/herdr.exe') --version 2>&1 | Out-File -LiteralPath (Join-Path $evidence "logs/$Label-version.log") -Encoding UTF8
    if ($LASTEXITCODE -ne 0) { throw 'Installed herdr entry point failed.' }
    Set-Result 'command-resolution' @("logs/$Label-resolution.log", "logs/$Label-version.log")
}

$baselinePath = User-Path
$baselineFonts = Snapshot-Fonts
$baselinePathExists = (Get-Item -LiteralPath $environmentKey).GetValueNames() -contains 'Path'
$foreignFont = 'GX lifecycle foreign sentinel ' + $p.session
try {
    foreach ($name in @('USERPROFILE','HOME','APPDATA','LOCALAPPDATA','XDG_CONFIG_HOME','XDG_CACHE_HOME','XDG_DATA_HOME','XDG_STATE_HOME','TEMP','TMP','TMPDIR','PATH','HERDR_SESSION')) {
        $oldEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    }
    $env:USERPROFILE = $p.paths.home; $env:HOME = $p.paths.home
    $env:APPDATA = $p.paths.roaming; $env:LOCALAPPDATA = $p.paths.local
    $env:XDG_CONFIG_HOME = $p.paths.config; $env:XDG_CACHE_HOME = $p.paths.cache
    $env:XDG_DATA_HOME = $p.paths.data; $env:XDG_STATE_HOME = $p.paths.state
    $env:TEMP = $p.paths.tmp; $env:TMP = $p.paths.tmp; $env:TMPDIR = $p.paths.tmp
    $env:HERDR_SESSION = $p.session
    Worker 'snapshot' 'preinstall'
    Save-Json 'logs/registry-before.json' @{ path = $baselinePath; fonts = $baselineFonts }
    $current = 'path-conflict'
    Refresh-Path
    if (Get-Command herdr -CommandType Application -ErrorAction SilentlyContinue) { throw 'Clean runner unexpectedly already resolves herdr; foreign installation is not overwritten.' }
    $conflict = Join-Path $evidence 'owned-conflict-fixture'
    New-Item -ItemType Directory -Path $conflict | Out-Null
    [IO.File]::WriteAllText((Join-Path $conflict 'herdr.cmd'), '@exit /b 77', [Text.Encoding]::ASCII)
    Set-UserPath ($baselinePath + ';' + $conflict)
    $changedConflict = $true
    try {
        Run-Installer $p.effective.installer.path 'path-conflict' -Reject
        if (Test-Path -LiteralPath (Join-Path $install 'bin/herdr.exe')) { throw 'Rejected conflict left an installed executable.' }
    } finally {
        Set-UserPath $baselinePath
        if (-not $baselinePathExists) { Remove-ItemProperty -LiteralPath $environmentKey -Name Path }
        $changedConflict = $false
    }
    Set-Result 'path-conflict' @('logs/path-conflict-process.json', 'logs/path-conflict-installer.log')
    $current = 'install'
    Run-Installer $p.initial.installer.path 'install'
    $installed = $true
    Worker 'compare' 'postinstall-no-home' 'preinstall'
    Resolve-Commands 'installed'
    Worker 'profile' 'installed'
    Set-Result 'install' @('logs/install-process.json', 'logs/installed-cold.stdout.log')
    $current = 'path-ownership'
    $entry = Join-Path $install 'bin'
    $registered = User-Path
    if (@($registered.Split(';') | Where-Object { $_.TrimEnd('\') -ieq $entry.TrimEnd('\') }).Count -ne 1) { throw 'PATH must contain exactly one owned entry.' }
    $afterFonts = Snapshot-Fonts
    $ownedFonts = @($afterFonts.Keys | Where-Object { -not $baselineFonts.Contains($_) })
    if ($ownedFonts.Count -ne 4) { throw 'Expected four new owned font registrations.' }
    foreach ($name in $ownedFonts) { if (-not $afterFonts[$name].StartsWith($install, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unowned font registration modified.' } }
    $foreignPath = Join-Path $evidence 'foreign-path-preserve'
    New-Item -ItemType Directory -Path $foreignPath | Out-Null
    Set-UserPath ($registered + ';' + $foreignPath)
    New-ItemProperty -LiteralPath $fontKey -Name $foreignFont -Value (Join-Path $foreignPath 'foreign.ttf') -PropertyType String -Force | Out-Null
    $sentinelCreated = $true
    Save-Json 'logs/registry-installed.json' @{ path = (User-Path); fonts = (Snapshot-Fonts); owned_fonts = $ownedFonts }
    $current = 'zsh-pane'
    Worker 'headless' 'installed'
    $current = 'herdr-tui'
    Worker 'tui' 'installed'
    $profileRc = Join-Path $p.paths.profile '.zshrc'
    [IO.File]::AppendAllText($profileRc, "`n# lifecycle user edit retained`n", [Text.UTF8Encoding]::new($false))
    Worker 'snapshot' 'preserve'
    $current = 'locked-file-rollback'
    $held = [IO.File]::Open((Join-Path $install 'bin/herdr.exe'), [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
    $beforeLockedPath = User-Path
    $beforeLockedFonts = Snapshot-Fonts
    try { Run-Installer $p.effective.installer.path 'locked-file' -Reject } finally { $held.Dispose() }
    Check-Equal (User-Path) $beforeLockedPath 'Locked-file rejection changed PATH.'
    Check-Equal (Snapshot-Fonts) $beforeLockedFonts 'Locked-file rejection changed font registration.'
    Worker 'compare' 'locked-preserved' 'preserve'
    Set-Result 'locked-file-rollback' @('logs/locked-file-process.json', 'logs/locked-preserved-preserved.json')
    $current = 'reinstall'
    Run-Installer $p.initial.installer.path 'reinstall'
    Worker 'compare' 'reinstall-preserved' 'preserve'
    Set-Result 'reinstall' @('logs/reinstall-process.json', 'logs/reinstall-preserved-preserved.json')
    if ($null -ne $p.upgrade) {
        $current = 'upgrade'
        Run-Installer $p.upgrade.installer.path 'upgrade'
        Worker 'compare' 'upgrade-preserved' 'preserve'
        $origin = Get-Content -LiteralPath (Join-Path $install 'share/ohmyzsh-gx/package-origin.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($origin.source.version -cne $p.upgrade.version -or $origin.source.revision -cne $p.upgrade.source_revision) { throw 'Installed upgrade provenance mismatch.' }
        Resolve-Commands 'upgraded'
        Worker 'profile' 'upgraded'
        Worker 'snapshot' 'preserve-upgraded'
        Set-Result 'upgrade' @('logs/upgrade-process.json', 'logs/upgrade-preserved-preserved.json', 'logs/upgraded-cold.stdout.log')
        $preserve = 'preserve-upgraded'
    } else { $preserve = 'preserve' }
    $current = 'uninstall'
    Run-Installer (Join-Path $install 'unins000.exe') 'uninstall' -Uninstall
    $installed = $false
    Worker 'compare' 'uninstall-preserved' $preserve
    if (Test-Path -LiteralPath (Join-Path $install 'bin/gx-zsh.exe')) { throw 'Uninstall retained program executable.' }
    Check-Equal (User-Path) ($baselinePath + ';' + $foreignPath) 'Uninstall did not remove only its owned PATH entry.'
    $expectedFonts = Snapshot-Fonts
    if (-not $expectedFonts.Contains($foreignFont)) { throw 'Uninstall removed the foreign font sentinel.' }
    $expectedFonts.Remove($foreignFont)
    Check-Equal $expectedFonts $baselineFonts 'Uninstall changed pre-existing font registrations.'
    Save-Json 'logs/registry-uninstalled.json' @{ path = (User-Path); fonts = (Snapshot-Fonts); foreign_entries_preserved = $true }
    Set-Result 'path-ownership' @('logs/registry-before.json', 'logs/registry-installed.json', 'logs/registry-uninstalled.json')
    Set-Result 'uninstall' @('logs/uninstall-process.json', 'logs/registry-uninstalled.json')
    Set-Result 'user-data-preserved' @('logs/reinstall-preserved-preserved.json', 'logs/uninstall-preserved-preserved.json')
    if ($null -ne $p.upgrade) {
        $current = 'install'
        Run-Installer $p.upgrade.installer.path 'candidate-fresh-install'
        $installed = $true
        Worker 'compare' 'candidate-fresh-preserved' $preserve
        Resolve-Commands 'candidate-fresh'
        Worker 'profile' 'candidate-fresh'
        Worker 'headless' 'candidate-fresh'
        $current = 'herdr-tui'
        Worker 'tui' 'candidate-fresh'
        Worker 'snapshot' 'candidate-preserve'
        Set-Result 'install' @('logs/candidate-fresh-install-process.json', 'logs/candidate-fresh-cold.stdout.log')
        $current = 'reinstall'
        Run-Installer $p.upgrade.installer.path 'candidate-reinstall'
        Worker 'compare' 'candidate-reinstall-preserved' 'candidate-preserve'
        Set-Result 'reinstall' @('logs/candidate-reinstall-process.json', 'logs/candidate-reinstall-preserved-preserved.json')
        $current = 'uninstall'
        Run-Installer (Join-Path $install 'unins000.exe') 'candidate-uninstall' -Uninstall
        $installed = $false
        Worker 'compare' 'candidate-uninstall-preserved' 'candidate-preserve'
        if (Test-Path -LiteralPath (Join-Path $install 'bin/gx-zsh.exe')) { throw 'Candidate uninstall retained executable.' }
        Check-Equal (User-Path) ($baselinePath + ';' + $foreignPath) 'Candidate uninstall changed foreign PATH entries.'
        $finalFonts = Snapshot-Fonts
        if (-not $finalFonts.Contains($foreignFont)) { throw 'Candidate uninstall removed a foreign font entry.' }
        $finalFonts.Remove($foreignFont)
        Check-Equal $finalFonts $baselineFonts 'Candidate uninstall changed foreign fonts.'
        Save-Json 'logs/candidate-registry-uninstalled.json' @{ path = (User-Path); fonts = (Snapshot-Fonts) }
        Set-Result 'path-ownership' @('logs/registry-before.json', 'logs/candidate-registry-uninstalled.json')
        Set-Result 'uninstall' @('logs/candidate-uninstall-process.json', 'logs/candidate-uninstall-preserved-preserved.json')
        Set-Result 'user-data-preserved' @('logs/upgrade-preserved-preserved.json', 'logs/candidate-uninstall-preserved-preserved.json')
    }
} catch {
    $failed = $true
    Save-Json 'logs/windows-error.json' @{ check = $current; error = $_.Exception.Message }
    $checks[$current] = @{ status = 'failed'; reason = $_.Exception.Message; evidence = @('logs/windows-error.json') }
} finally {
    if ($installed -and (Test-Path -LiteralPath (Join-Path $install 'unins000.exe'))) {
        try { Run-Installer (Join-Path $install 'unins000.exe') 'cleanup-uninstall' -Uninstall }
        catch { $failed = $true; Save-Json 'logs/cleanup-error.json' @{ error = $_.Exception.Message } }
    }
    if ($changedConflict) { Set-UserPath $baselinePath }
    if ($sentinelCreated) {
        $now = User-Path
        $parts = @($now.Split(';') | Where-Object { $_ -cne $foreignPath })
        Set-UserPath ($parts -join ';')
        if (-not $baselinePathExists -and (User-Path) -eq '') { Remove-ItemProperty -LiteralPath $environmentKey -Name Path }
        Remove-ItemProperty -LiteralPath $fontKey -Name $foreignFont -ErrorAction SilentlyContinue
    }
    foreach ($name in $oldEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $oldEnvironment[$name], 'Process') }
    Save-Json 'results/windows.json' @{ status = $(if ($failed) { 'failed' } else { 'passed' }); checks = $checks; scope = 'native EXE lifecycle subset; unimplemented release checks remain pending' }
}
if ($failed) { exit 1 }
exit 0
