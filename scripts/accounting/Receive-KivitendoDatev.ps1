<#
.SYNOPSIS
Adapt first: pull approved kivitendo DATEV packets over restricted SSH.
.DESCRIPTION
PowerShell 5.1 / Windows 11 with OpenSSH. Run as the configured desktop user.
Uses a dedicated key and pinned host key from the supplied SSH configuration.
Reads only the Linux controlled outbox. Checks client identity, packet/file
hashes, names and EXTF identity. Keeps immutable Received copies, Kanzlei CSVs,
and persistent local state. PublishEnabled defaults false: no watched-folder
publication until the DATEV target is configured and a test is agreed.
Once enabled, writes one uniquely named XML ZIP atomically to Belegtransfer.
Published means handed to the local watcher, NOT successfully uploaded/imported.
An interrupted publication fails closed instead of silently sending twice.
No credentials, email, financial posting or automatic DATEV authentication.
Errors update status.json and return exit 1. Private key stays on this PC.
See kivitendo-datev-handover.md for installation, state recovery and limits.
.PARAMETER Config
Absolute path to a private local JSON config; sanitized example is in the repo.
#>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Config)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Write-AtomicJson {
    <# .SYNOPSIS Atomically replace a UTF-8 JSON file; throws on I/O failure.
    .PARAMETER Path Destination within the private root.
    .PARAMETER Value JSON-compatible value. Creates only its own temporary file.
    #>
    param([string]$Path,$Value)
    $temporary=$Path+'.'+[Guid]::NewGuid().ToString('N')+'.tmp'
    [IO.File]::WriteAllText($temporary,($Value | ConvertTo-Json -Depth 30),[Text.UTF8Encoding]::new($false))
    if([IO.File]::Exists($Path)){
        # Windows PowerShell 5.1 binds $null to an empty backup path here.
        # A real unique backup path preserves atomic replacement on .NET 4.x.
        $backup=$temporary+'.bak'
        [IO.File]::Replace($temporary,$Path,$backup)
        [IO.File]::Delete($backup)
    }
    else{[IO.File]::Move($temporary,$Path)}
}

function Get-ByteHash {
    <# .SYNOPSIS Return lowercase SHA256 for bytes; disposes hash provider.
    .PARAMETER Bytes File content; no writes or external calls.
    #>
    param([byte[]]$Bytes)
    $hasher=[Security.Cryptography.SHA256]::Create()
    try{return ([BitConverter]::ToString($hasher.ComputeHash($Bytes))).Replace('-','').ToLowerInvariant()}
    finally{$hasher.Dispose()}
}

function Assert-Identity {
    <# .SYNOPSIS Reject a response/manifest for any other configured client.
    .PARAMETER Value Object with database, consultant_number and client_number.
    #>
    param($Value)
    foreach($field in 'database','consultant_number','client_number'){
        if([string]$Value.$field -cne [string]$script:cfg.$field){throw "Wrong client identity: $field"}
    }
}

function Invoke-Reader {
    <# .SYNOPSIS Read JSON over pinned, noninteractive SSH with a 90-second limit.
    .PARAMETER Request Only index or get PERIOD BASENAME is accepted.
    .OUTPUTS Parsed JSON; throws on timeout, protocol or authentication failure.
    Starts ssh.exe; captures text without PowerShell 5.1 binary-redirection loss.
    #>
    param([string]$Request)
    if($Request -cne 'index' -and $Request -cnotmatch '^get \d{4}-(0[1-9]|1[0-2]) [A-Za-z0-9][A-Za-z0-9_.-]{0,179}$'){
        throw 'Unsafe SSH request'
    }
    $psi=New-Object Diagnostics.ProcessStartInfo
    $psi.FileName=$script:cfg.ssh_executable
    $psi.Arguments='-F "'+$script:cfg.ssh_config+'" datev-handover '+$Request
    $psi.UseShellExecute=$false
    $psi.CreateNoWindow=$true
    $psi.RedirectStandardOutput=$true
    $psi.RedirectStandardError=$true
    # Some remote-agent sessions omit ProgramData, causing Win32 OpenSSH to
    # exit 255 without diagnostics. Restore the real OS value for this child.
    $psi.EnvironmentVariables['ProgramData']=[Environment]::GetFolderPath('CommonApplicationData')
    $psi.EnvironmentVariables['COMPUTERNAME']=[Environment]::MachineName
    $process=[Diagnostics.Process]::Start($psi)
    try{
        $outputTask=$process.StandardOutput.ReadToEndAsync()
        $errorTask=$process.StandardError.ReadToEndAsync()
        if(!$process.WaitForExit(90000)){$process.Kill();throw 'SSH read timed out'}
        $outputText=$outputTask.GetAwaiter().GetResult()
        $errorText=$errorTask.GetAwaiter().GetResult()
        if($process.ExitCode -ne 0){throw ('SSH read failed: '+$errorText.Trim())}
        if($outputText.Length -gt 95000000){throw 'Oversized reader response'}
        $response=$outputText | ConvertFrom-Json
        if($response.schema -ne 1){throw 'Unknown reader protocol'}
        Assert-Identity $response
        return $response
    }finally{$process.Dispose()}
}

function Assert-Packet {
    <# .SYNOPSIS Verify a downloaded packet against the authenticated index.
    .PARAMETER Folder Private cache/staging directory.
    .PARAMETER Packet Index descriptor. Reads files; does not extract ZIPs.
    Rejects extra files, hash/identity mismatches and a wrong EXTF client.
    #>
    param([string]$Folder,$Packet)
    $actual=@(Get-ChildItem -LiteralPath $Folder -Force)
    if($actual.Count -ne @($Packet.files).Count){throw 'Unexpected cached packet contents'}
    foreach($file in $Packet.files){
        $path=Join-Path $Folder $file.name
        $item=Get-Item -LiteralPath $path
        if($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Unsafe cached file'}
        if($item.Length -ne $file.size -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $file.sha256){
            throw 'Cached packet integrity failure'
        }
    }
    $manifest=Get-Content -LiteralPath (Join-Path $Folder 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Identity $manifest
    if($manifest.schema -ne 2 -or $manifest.period -cne $Packet.period -or $manifest.snapshot -cne $Packet.snapshot){throw 'Manifest does not match index'}
    if($manifest.file -cnotmatch '^EXTF_[A-Za-z0-9_.-]+\.csv$'){throw 'Unsafe CSV filename'}
    $csv=[Text.Encoding]::GetEncoding(1252).GetString([IO.File]::ReadAllBytes((Join-Path $Folder $manifest.file)))
    $header=@(($csv -split '\r\n',2)[0] -split ';' | ForEach-Object {$_.Trim('"')})
    if($header.Count -ne 31 -or $header[0] -cne 'EXTF' -or $header[1] -cne '700' -or $header[4] -cne '13' -or
       $header[10] -cne [string]$script:cfg.consultant_number -or $header[11] -cne [string]$script:cfg.client_number -or
       $header[20] -cne '0' -or $header[26] -cne '04'){throw 'Unexpected EXTF identity/format/finalization'}
    return $manifest
}

function Copy-VerifiedOnce {
    <# .SYNOPSIS Atomically create a local handoff file or verify an existing one.
    .PARAMETER Source Verified immutable cached source.
    .PARAMETER Destination Target file. Never overwrites differing content.
    #>
    param([string]$Source,[string]$Destination)
    if(Test-Path -LiteralPath $Destination){
        if((Get-FileHash -LiteralPath $Source).Hash -cne (Get-FileHash -LiteralPath $Destination).Hash){throw 'Existing handoff file differs'}
        return
    }
    # Staging is on the same local volume, outside the watched directory.
    $temporary=Join-Path (Join-Path $script:cfg.root 'Staging') ('handoff-'+[Guid]::NewGuid().ToString('N')+'.tmp')
    [IO.File]::Copy($Source,$temporary,$false)
    [IO.File]::Move($temporary,$Destination)
}

$lock=$null
$root=$null
$logStarted=$false
try{
    $script:cfg=Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
    $root=$cfg.root
    if(![IO.Path]::IsPathRooted($root) -or $root.Contains('"') -or $cfg.ssh_config.Contains('"')){throw 'Invalid configured path'}
    if((Get-Item -LiteralPath $root).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Root must not be a reparse point'}
    $watchRoot=Join-Path $root 'Belegtransfer'
    $watchProperty=$cfg.PSObject.Properties['watch_subdirectory']
    if($null -ne $watchProperty -and $watchProperty.Value){
        $relative=[string]$watchProperty.Value
        if($relative -cnotmatch '^[A-Za-z0-9 _-]+(?:[\\/][A-Za-z0-9 _-]+)*$'){throw 'Invalid watched subdirectory'}
        $watchRoot=Join-Path $watchRoot $relative
    }
    if($cfg.publish_enabled -eq $true){
        New-Item -ItemType Directory -Path $watchRoot -Force | Out-Null
        $checkPath=Get-Item -LiteralPath $watchRoot
        while($checkPath.FullName.Length -ge $root.Length){
            if($checkPath.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Watched path contains a reparse point'}
            $checkPath=$checkPath.Parent
        }
    }
    $lock=[IO.File]::Open((Join-Path $root 'receiver.lock'),'OpenOrCreate','ReadWrite','None')
    Start-Transcript -Path (Join-Path $root 'Logs\receiver-last-run.log') -Force | Out-Null
    $logStarted=$true
    $statePath=Join-Path $root 'state.json'
    $state=if(Test-Path -LiteralPath $statePath){Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json}
           else{[pscustomobject]@{schema=1;packets=[pscustomobject]@{}}}
    if($state.schema -ne 1){throw 'Unknown local state schema'}
    $index=Invoke-Reader 'index'
    $periods=@{}
    foreach($packet in @($index.packets)){
        $period=$packet.period
        if($period -cnotmatch '^\d{4}-(0[1-9]|1[0-2])$' -or $periods.ContainsKey($period) -or
           $packet.snapshot -cnotmatch '^[a-f0-9]{24}$' -or $packet.packet_sha256 -cnotmatch '^[a-f0-9]{64}$'){throw 'Invalid/duplicate packet identity'}
        $periods[$period]=$true
        $names=@{}
        foreach($file in @($packet.files)){
            if($file.name -cnotmatch '^(manifest\.json|Belege-XML\.zip|EXTF_[A-Za-z0-9_.-]+\.csv)$' -or $names.ContainsKey($file.name) -or
               $file.size -lt 1 -or $file.size -gt 67108864 -or $file.sha256 -cnotmatch '^[a-f0-9]{64}$'){throw 'Invalid file descriptor'}
            $names[$file.name]=$true
        }
        if(@($packet.files).Count -lt 2 -or @($packet.files).Count -gt 3 -or !$names.ContainsKey('manifest.json')){throw 'Incomplete packet index'}
        $property=$state.packets.PSObject.Properties[$period]
        $record=if($null -ne $property){$property.Value}else{$null}
        if($null -ne $record -and $record.packet_sha256 -cne $packet.packet_sha256){throw 'Previously received month changed; reconcile before further processing'}
        $destination=Join-Path (Join-Path $root 'Received') $period
        if(!(Test-Path -LiteralPath $destination)){
            $stage=Join-Path (Join-Path $root 'Staging') ($period+'-'+[Guid]::NewGuid().ToString('N'))
            New-Item -ItemType Directory -Path $stage | Out-Null
            foreach($file in $packet.files){
                $reply=Invoke-Reader ('get '+$period+' '+$file.name)
                if($reply.period -cne $period -or $reply.name -cne $file.name -or $reply.packet_sha256 -cne $packet.packet_sha256){throw 'Download identity changed'}
                $bytes=[Convert]::FromBase64String($reply.content_base64)
                if($bytes.Length -ne $file.size -or (Get-ByteHash $bytes) -cne $file.sha256 -or $reply.sha256 -cne $file.sha256){throw 'Download checksum mismatch'}
                [IO.File]::WriteAllBytes((Join-Path $stage $file.name),$bytes)
            }
            $null=Assert-Packet $stage $packet
            [IO.Directory]::Move($stage,$destination)
        }
        $manifest=Assert-Packet $destination $packet
        if($null -eq $record){
            $record=[pscustomobject]@{packet_sha256=$packet.packet_sha256;snapshot=$packet.snapshot;status='staged';received_at=[DateTime]::UtcNow.ToString('o');published_at=$null}
            $state.packets | Add-Member -MemberType NoteProperty -Name $period -Value $record
            Write-AtomicJson $statePath $state
        }
        $kanzlei=Join-Path (Join-Path $root 'Kanzlei') $period
        New-Item -ItemType Directory -Path $kanzlei -Force | Out-Null
        Copy-VerifiedOnce (Join-Path $destination $manifest.file) (Join-Path $kanzlei $manifest.file)
        $note=Join-Path $kanzlei 'IMPORTSTATUS.txt'
        if(!(Test-Path -LiteralPath $note)){
            [IO.File]::WriteAllText($note,"Lokal bereitgestellt. DATEV-Belegupload und Buchungsimport sind NICHT bestaetigt.`r`nDiesen Monat nur einmal importieren. Belegverknuepfungen nach Upload pruefen.`r`n",[Text.UTF8Encoding]::new($false))
        }
        if($cfg.publish_enabled -eq $true -and $names.ContainsKey('Belege-XML.zip')){
            $watchName=$period+'-'+$packet.snapshot+'-Belege-XML.zip'
            $watchPath=Join-Path $watchRoot $watchName
            if($record.status -ceq 'publish_pending'){
                if(!(Test-Path -LiteralPath $watchPath)){throw 'Interrupted publication is ambiguous; reconcile Belegtransfer before retry'}
                Copy-VerifiedOnce (Join-Path $destination 'Belege-XML.zip') $watchPath
                $record.status='published_to_local_watcher'
                $record.published_at=[DateTime]::UtcNow.ToString('o')
                Write-AtomicJson $statePath $state
            }elseif($record.status -ceq 'staged'){
                $record.status='publish_pending'
                Write-AtomicJson $statePath $state
                Copy-VerifiedOnce (Join-Path $destination 'Belege-XML.zip') $watchPath
                $record.status='published_to_local_watcher'
                $record.published_at=[DateTime]::UtcNow.ToString('o')
                Write-AtomicJson $statePath $state
            }elseif($record.status -cne 'published_to_local_watcher'){throw 'Unknown packet delivery state'}
        }
    }
    $status=[pscustomobject]@{status='success';checked_at=[DateTime]::UtcNow.ToString('o');source_checked_at=$index.source_checked_at;
        queued_periods=@($periods.Keys | Sort-Object);publish_enabled=[bool]$cfg.publish_enabled;datev_upload_confirmed=$false;datev_import_confirmed=$false}
    Write-AtomicJson (Join-Path $root 'status.json') $status
    $status | ConvertTo-Json -Depth 8
}catch{
    if($root -and $null -ne $lock){
        try{Write-AtomicJson (Join-Path $root 'status.json') @{status='failed';checked_at=[DateTime]::UtcNow.ToString('o');error=$_.Exception.Message}}
        catch{Write-Warning ('Could not save receiver failure status: '+$_.Exception.Message)}
    }
    Write-Error $_ -ErrorAction Continue
    exit 1
}finally{
    if($logStarted){Stop-Transcript | Out-Null}
    if($null -ne $lock){$lock.Dispose()}
}
