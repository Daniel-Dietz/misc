<#
.SYNOPSIS
Adapt first: stage a reviewed complete DATEV receipt package on Windows.
.DESCRIPTION
Windows PowerShell 5.1 and .NET ZIP APIs. Reads a hash-pinned private template
ZIP with document.xml, receipt mapping and fresh CSVs; verifies the existing
local receipt files; writes a NEW unwatched output directory. No UI automation,
network, upload, watcher publication, ledger changes or old-state reset.
The template's XML must already have passed official DATEV XSD validation.
ZIP compression may differ from Linux: document/CSV bytes remain identical,
but Windows archive hashes are recorded separately. Target verification and
DATEV acceptance/import remain pending. Templates/mappings contain private
financial data and MUST NOT be committed. Failed runs may leave partial NEW
output; inspect it and choose a new path. Retain source receipts and history.
.PARAMETER Template
Private local metadata ZIP; includes no invoice bytes.
.PARAMETER TemplateSha256
Expected SHA256 supplied through the trusted preparation channel.
.PARAMETER ReceiptRoot
Existing private directory containing the reviewed Einzelbelege paths.
.PARAMETER Output
New directory outside all Belegtransfer watched folders.
.PARAMETER Consultant
Expected adviser number, passed separately from the template.
.PARAMETER Client
Expected client number, passed separately from the template.
#>
[CmdletBinding()]
param(
 [Parameter(Mandatory=$true)][string]$Template,
 [Parameter(Mandatory=$true)][string]$TemplateSha256,
 [Parameter(Mandatory=$true)][string]$ReceiptRoot,
 [Parameter(Mandatory=$true)][string]$Output,
 [Parameter(Mandatory=$true)][string]$Consultant,
 [Parameter(Mandatory=$true)][string]$Client
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Get-HashBytes {
 <# .SYNOPSIS Return SHA256 of bytes, disposing the provider; no writes. #>
 param([byte[]]$Bytes)
 $hash=[Security.Cryptography.SHA256]::Create()
 try { return ([BitConverter]::ToString($hash.ComputeHash($Bytes))).Replace('-','').ToLowerInvariant() }
 finally { $hash.Dispose() }
}

function Read-ZipBytes {
 <# .SYNOPSIS Read one template entry into memory; throw if missing. #>
 param($Archive,[string]$Name)
 $entry=$Archive.GetEntry($Name)
 if($null -eq $entry){throw "Missing template entry: $Name"}
 $stream=$entry.Open();$memory=New-Object IO.MemoryStream
 try {$stream.CopyTo($memory);return ,$memory.ToArray()}
 finally {$stream.Dispose();$memory.Dispose()}
}

function Write-Json {
 <# .SYNOPSIS Write UTF-8 JSON in the NEW private output; propagate I/O errors. #>
 param([string]$Path,$Value)
 [IO.File]::WriteAllText($Path,($Value | ConvertTo-Json -Depth 30),[Text.UTF8Encoding]::new($false))
}

if($TemplateSha256 -cnotmatch '^[a-f0-9]{64}$' -or
   (Get-FileHash -LiteralPath $Template -Algorithm SHA256).Hash.ToLowerInvariant() -cne $TemplateSha256){throw 'Template hash mismatch'}
if(Test-Path -LiteralPath $Output){throw 'Output must be a new directory'}
if(![IO.Path]::IsPathRooted($Output) -or ![IO.Path]::IsPathRooted($ReceiptRoot)){throw 'Absolute paths required'}
if($Output -match '[\\/]Belegtransfer[\\/]'){throw 'Output must be outside watched folders'}
$templateZip=[IO.Compression.ZipFile]::OpenRead($Template)
try {
 $mapping=[Text.Encoding]::UTF8.GetString((Read-ZipBytes $templateZip 'Belegzuordnung.json')) | ConvertFrom-Json
 $audit=[Text.Encoding]::UTF8.GetString((Read-ZipBytes $templateZip 'Validierung.json')) | ConvertFrom-Json
 $checks=[Text.Encoding]::UTF8.GetString((Read-ZipBytes $templateZip 'SHA256.json')) | ConvertFrom-Json
 if($audit.consultant_number -cne $Consultant -or $audit.client_number -cne $Client -or
    $audit.documents -ne 20 -or @($mapping).Count -ne 20){throw 'Wrong client or receipt count'}
 $xmlBytes=Read-ZipBytes $templateZip 'document.xml'
 $xmlSettings=New-Object Xml.XmlReaderSettings;$xmlSettings.DtdProcessing=[Xml.DtdProcessing]::Prohibit;$xmlSettings.XmlResolver=$null
 $xmlStream=New-Object IO.MemoryStream(,$xmlBytes);$reader=[Xml.XmlReader]::Create($xmlStream,$xmlSettings)
 $xml=New-Object Xml.XmlDocument;$xml.XmlResolver=$null
 try {$xml.Load($reader)}finally{$reader.Dispose();$xmlStream.Dispose()}
 $ns=New-Object Xml.XmlNamespaceManager($xml.NameTable);$ns.AddNamespace('d','http://xml.datev.de/bedi/tps/document/v06.0')
 if($xml.SelectSingleNode('/d:archive/d:header/d:consultantNumber',$ns).InnerText -cne $Consultant -or
    $xml.SelectSingleNode('/d:archive/d:header/d:clientNumber',$ns).InnerText -cne $Client){throw 'XML target mismatch'}
 $nodes=$xml.SelectNodes('/d:archive/d:content/d:document',$ns)
 if($nodes.Count -ne 20){throw 'Wrong XML document count'}
 $expected=@{};$receipts=@{}
 foreach($record in $mapping){
  if($record.file -match '(^[\\/]|\.\.|:)' -or $record.xml_file -cnotmatch '^[a-f0-9-]{36}\.(pdf|png)$'){throw 'Unsafe receipt path'}
  $bytes=[IO.File]::ReadAllBytes((Join-Path $ReceiptRoot $record.file))
  if((Get-HashBytes $bytes) -cne $record.sha256){throw ('Changed receipt: '+$record.file)}
  if($expected.ContainsKey($record.xml_file)){throw 'Duplicate mapped file'}
  $expected[$record.xml_file]=$record.sha256;$receipts[$record.xml_file]=$bytes
 }
 $seen=@{}
 foreach($node in $nodes){
  $file=$node.SelectSingleNode('d:extension',$ns).GetAttribute('name')
  if($node.GetAttribute('processID') -cne '2' -or !$expected.ContainsKey($file) -or $seen.ContainsKey($file) -or
     $node.GetAttribute('guid') -cne [IO.Path]::GetFileNameWithoutExtension($file)){throw 'XML receipt mapping mismatch'}
  $seen[$file]=$true
 }
 $null=New-Item -ItemType Directory -Path $Output
 foreach($entry in $templateZip.Entries){
  if($entry.FullName -ceq 'document.xml'){continue}
  if($entry.FullName -match '(^[\\/]|\.\.|:)' -or $entry.FullName.EndsWith('/')){throw 'Unsafe template entry'}
  $bytes=Read-ZipBytes $templateZip $entry.FullName
  if($entry.FullName -cne 'SHA256.json'){
   $check=$checks.PSObject.Properties[$entry.FullName]
   if($null -eq $check -or (Get-HashBytes $bytes) -cne $check.Value){throw 'Changed template entry'}
  }
  $path=Join-Path $Output $entry.FullName
  $null=New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($path)) -Force
  [IO.File]::WriteAllBytes($path,$bytes)
 }
 $transfer=Join-Path $Output ('Belegtransfer\DATEV_Belege_20_bis_'+$audit.as_of+'_XML.zip')
 $null=New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($transfer)) -Force
 $zip=[IO.Compression.ZipFile]::Open($transfer,[IO.Compression.ZipArchiveMode]::Create)
 try {
  $data=@{'document.xml'=$xmlBytes};foreach($key in $receipts.Keys){$data[$key]=$receipts[$key]}
  foreach($name in ($data.Keys | Sort-Object)){
   $entry=$zip.CreateEntry($name,[IO.Compression.CompressionLevel]::Optimal);$stream=$entry.Open()
   try {$bytes=$data[$name];$stream.Write($bytes,0,$bytes.Length)}finally{$stream.Dispose()}
  }
 }finally{$zip.Dispose()}
 $verify=[IO.Compression.ZipFile]::OpenRead($transfer)
 try {
  if($verify.Entries.Count -ne 21){throw 'Wrong output ZIP file count'}
  if((Get-HashBytes (Read-ZipBytes $verify 'document.xml')) -cne (Get-HashBytes $xmlBytes)){throw 'Output XML changed'}
  foreach($name in $expected.Keys){if((Get-HashBytes (Read-ZipBytes $verify $name)) -cne $expected[$name]){throw 'Output receipt changed'}}
 }finally{$verify.Dispose()}
 $archiveHash=(Get-FileHash -LiteralPath $transfer -Algorithm SHA256).Hash.ToLowerInvariant()
 $sourceArchiveHash=$audit.transfer_zip_sha256
 $audit.transfer_zip_sha256=$archiveHash
 $audit | Add-Member -NotePropertyName windows_repacked -NotePropertyValue $true
 $audit | Add-Member -NotePropertyName source_transfer_zip_sha256 -NotePropertyValue $sourceArchiveHash
 $audit | Add-Member -NotePropertyName xml_sha256 -NotePropertyValue (Get-HashBytes $xmlBytes)
 Write-Json (Join-Path $Output 'Validierung.json') $audit
 $updated=@{};Get-ChildItem -LiteralPath $Output -Recurse -File | Where-Object {$_.Name -cne 'SHA256.json'} | ForEach-Object {
  $name=$_.FullName.Substring($Output.TrimEnd('\').Length+1).Replace('\','/')
  $updated[$name]=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
 }
 Write-Json (Join-Path $Output 'SHA256.json') $updated
 $bundle=Join-Path ([IO.Path]::GetDirectoryName($Output)) 'DATEV_Neuanlage_bis_2026-09-30_KOMPLETT_WINDOWS.zip'
 if(Test-Path -LiteralPath $bundle){throw 'Windows bundle already exists'}
 [IO.Compression.ZipFile]::CreateFromDirectory($Output,$bundle,[IO.Compression.CompressionLevel]::Optimal,$false)
 [pscustomobject]@{status='prepared_not_uploaded';path=$Output;transfer_zip=$transfer;transfer_sha256=$archiveHash;
  bundle=$bundle;bundle_sha256=(Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash.ToLowerInvariant();
  documents=20;xml_bytes_preserved=$true;receipt_bytes_preserved=$true;target_verified=$false;datev_import_confirmed=$false} | ConvertTo-Json
}finally{$templateZip.Dispose()}
