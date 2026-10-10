<#
.SYNOPSIS
Adapt first: exercise the receiver in isolated, unwatched local test folders.
.DESCRIPTION
PowerShell 5.1, Windows, working SSH reader and at least one approved packet
with a Belege-XML.zip. Uses the configured SSH identity only for read requests.
Copies verified Received files into a unique test root; never writes to the
real Belegtransfer watcher, real state or accounting. Retains its test directory
for inspection; it contains financial files and inherits the private root ACL.
Checks repeat-run dedupe, consumed-file protection, interrupted publication,
wrong-client rejection and local corruption. Calls the real receiver as child
PowerShell with process-only RemoteSigned; no persistent execution-policy change.
.PARAMETER Config
Original private receiver JSON. Its root is used only to locate copies/code.
#>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Config)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$original=Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
$testRoot=Join-Path (Join-Path $original.root 'Tests') ([Guid]::NewGuid().ToString('N'))
$utf8=[Text.UTF8Encoding]::new($false)
foreach($name in 'Staging','Received','Belegtransfer','Kanzlei','Logs'){
    New-Item -ItemType Directory -Path (Join-Path $testRoot $name) -Force | Out-Null
}
Get-ChildItem -LiteralPath (Join-Path $original.root 'Received') -Directory |
    Copy-Item -Destination (Join-Path $testRoot 'Received') -Recurse
$testConfig=$original | ConvertTo-Json | ConvertFrom-Json
$testConfig.root=$testRoot
$testConfig.publish_enabled=$true
$configPath=Join-Path $testRoot 'receiver.json'
[IO.File]::WriteAllText($configPath,($testConfig | ConvertTo-Json),$utf8)
$receiver=Join-Path $original.root 'Scripts\Receive-KivitendoDatev.ps1'

function Invoke-TestReceiver {
    <# .SYNOPSIS Invoke isolated receiver, enforce expected success/failure.
    .PARAMETER ShouldSucceed Expected child outcome. No real watcher writes.
    .PARAMETER Label Test label printed only after the expectation passes.
    #>
    param([bool]$ShouldSucceed,[string]$Label)
    $psi=New-Object Diagnostics.ProcessStartInfo
    $psi.FileName='C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
    $psi.Arguments='-NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -File "'+$receiver+'" -Config "'+$configPath+'"'
    $psi.UseShellExecute=$false
    $psi.CreateNoWindow=$true
    $psi.RedirectStandardOutput=$true
    $psi.RedirectStandardError=$true
    $p=[Diagnostics.Process]::Start($psi)
    $outTask=$p.StandardOutput.ReadToEndAsync()
    $errTask=$p.StandardError.ReadToEndAsync()
    if(!$p.WaitForExit(120000)){$p.Kill();throw 'Test child timed out'}
    $outText=$outTask.GetAwaiter().GetResult()
    $errText=$errTask.GetAwaiter().GetResult()
    $ok=$p.ExitCode -eq 0
    $p.Dispose()
    if($ok -ne $ShouldSucceed){throw ('Unexpected test result: '+$Label+' '+$outText+' '+$errText)}
    Write-Output ('PASS '+$Label)
}

Invoke-TestReceiver $true 'isolated publication'
$watch=Join-Path $testRoot 'Belegtransfer'
if($null -ne $testConfig.PSObject.Properties['watch_subdirectory'] -and $testConfig.watch_subdirectory){
    $watch=Join-Path $watch $testConfig.watch_subdirectory
}
$published=@(Get-ChildItem -LiteralPath $watch -Filter '*.zip')
if($published.Count -lt 1){throw 'No test packet published'}
$initialState=[IO.File]::ReadAllText((Join-Path $testRoot 'state.json'))
Invoke-TestReceiver $true 'unchanged repeat'
if([IO.File]::ReadAllText((Join-Path $testRoot 'state.json')) -cne $initialState){throw 'Repeat changed delivery state'}
# Deletion is confined to ZIPs just created in the unique unwatched test folder.
$published | Remove-Item
Invoke-TestReceiver $true 'consumed packet is not republished'
if(@(Get-ChildItem -LiteralPath $watch -Filter '*.zip').Count){throw 'Duplicate publication'}
$state=$initialState | ConvertFrom-Json
$first=@($state.packets.PSObject.Properties)[0]
$first.Value.status='publish_pending'
[IO.File]::WriteAllText((Join-Path $testRoot 'state.json'),($state | ConvertTo-Json -Depth 20),$utf8)
Invoke-TestReceiver $false 'interrupted publication fails closed'
[IO.File]::WriteAllText((Join-Path $testRoot 'state.json'),$initialState,$utf8)
$realClient=$testConfig.client_number
$testConfig.client_number='99999'
[IO.File]::WriteAllText($configPath,($testConfig | ConvertTo-Json),$utf8)
Invoke-TestReceiver $false 'wrong client rejected'
$testConfig.client_number=$realClient
[IO.File]::WriteAllText($configPath,($testConfig | ConvertTo-Json),$utf8)
$csv=Get-ChildItem -LiteralPath (Join-Path $testRoot 'Received') -Filter 'EXTF_*.csv' -Recurse | Select-Object -First 1
[IO.File]::AppendAllText($csv.FullName,'corruption')
Invoke-TestReceiver $false 'altered cached CSV rejected'
Write-Output ('RECEIVER_TESTS_PASSED '+$testRoot)
