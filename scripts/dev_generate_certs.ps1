param(
    [string]$OutDir = "certs",
    [int]$ValidDays = 825,
    [string]$CaCommonName = "mqtt_test-dev-ca",
    [string[]]$MosquittoDnsNames = @("mosquitto", "localhost"),
    [string[]]$MosquittoIpAddresses = @("163.143.136.103"),
    [string[]]$WebDnsNames = @("localhost"),
    [string[]]$WebIpAddresses = @("163.143.136.103"),
    [switch]$ReuseCa,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

function Write-PemFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Type,
        [Parameter(Mandatory = $true)][byte[]]$DerBytes
    )
    $b64 = [System.Convert]::ToBase64String($DerBytes)
    $lines = New-Object System.Collections.Generic.List[string]
    for ($i = 0; $i -lt $b64.Length; $i += 64) {
        $len = [Math]::Min(64, $b64.Length - $i)
        $lines.Add($b64.Substring($i, $len))
    }
    $pem = @(
        "-----BEGIN $Type-----"
        $lines
        "-----END $Type-----"
        ""
    ) -join "`n"
    Set-Content -Path $Path -Value $pem -Encoding ascii -NoNewline
}

function New-SerialNumber {
    param([int]$Length = 16)
    $serial = New-Object byte[] $Length
    (New-Object System.Random).NextBytes($serial)
    return $serial
}

function Ensure-EmptyFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType File -Path $Path -Force | Out-Null
        return
    }
    if (-not $Force) {
        throw "File already exists: $Path (use -Force to overwrite)"
    }
}

function Read-PemDerBytes {
    param(
        [Parameter(Mandatory = $true)][string]$Path
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "File not found: $Path"
    }
    $raw = Get-Content -LiteralPath $Path -Raw
    $b64 = ($raw -split "`r?`n" | Where-Object { $_ -and ($_ -notmatch "^-----") } | ForEach-Object { $_.Trim() }) -join ""
    if (-not $b64) {
        throw "Invalid PEM file (no base64 payload): $Path"
    }
    try {
        $bytes = [System.Convert]::FromBase64String($b64)
    } catch {
        throw "Invalid PEM base64 in file: $Path"
    }
    return ,$bytes
}

function Get-LocalIpv4Addresses {
    $ips = @()
    try {
        $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { $_.IPAddress -and $_.IPAddress -ne "127.0.0.1" } |
            Select-Object -ExpandProperty IPAddress
    } catch {
        try {
            $configs = Get-CimInstance Win32_NetworkAdapterConfiguration -ErrorAction Stop |
                Where-Object { $_.IPEnabled -eq $true -and $_.IPAddress }
            foreach ($cfg in $configs) {
                foreach ($ip in $cfg.IPAddress) {
                    if ($ip -match "^(\\d{1,3}\\.){3}\\d{1,3}$" -and $ip -ne "127.0.0.1") {
                        $ips += $ip
                    }
                }
            }
        } catch {
            $ips = @()
        }
    }
    return @($ips | ForEach-Object { "$_".Trim() } | Where-Object { $_ } | Sort-Object -Unique)
}

New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

$caCrtPath = Join-Path $OutDir "ca.crt"
$caKeyPath = Join-Path $OutDir "ca.key"
$mosCrtPath = Join-Path $OutDir "mosquitto.crt"
$mosKeyPath = Join-Path $OutDir "mosquitto.key"
$webCrtPath = Join-Path $OutDir "web.crt"
$webKeyPath = Join-Path $OutDir "web.key"

$reuseExistingCa = $ReuseCa -and (Test-Path -LiteralPath $caCrtPath) -and (Test-Path -LiteralPath $caKeyPath)
if ($ReuseCa -and -not $reuseExistingCa) {
    Write-Host "[warn] -ReuseCa set but CA files not found; falling back to generating a new CA."
}

if ($reuseExistingCa) {
    @($mosCrtPath, $mosKeyPath, $webCrtPath, $webKeyPath) | ForEach-Object { Ensure-EmptyFile $_ }
} else {
    @($caCrtPath, $caKeyPath, $mosCrtPath, $mosKeyPath, $webCrtPath, $webKeyPath) | ForEach-Object { Ensure-EmptyFile $_ }
}

$hash = [System.Security.Cryptography.HashAlgorithmName]::SHA256
$pad = [System.Security.Cryptography.RSASignaturePadding]::Pkcs1
$notBefore = [System.DateTimeOffset]::UtcNow.AddMinutes(-5)
$notAfter = $notBefore.AddDays($ValidDays)

# ---------------- CA
$caSigGen = $null
if ($reuseExistingCa) {
    $caCertDer = Read-PemDerBytes -Path $caCrtPath
    $caCert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 -ArgumentList (, $caCertDer)

    $caKeyDer = Read-PemDerBytes -Path $caKeyPath
    $caCngKey = [System.Security.Cryptography.CngKey]::Import($caKeyDer, [System.Security.Cryptography.CngKeyBlobFormat]::Pkcs8PrivateBlob)
    $caKey = New-Object System.Security.Cryptography.RSACng -ArgumentList $caCngKey

    $caSigGen = [System.Security.Cryptography.X509Certificates.X509SignatureGenerator]::CreateForRSA($caKey, $pad)
} else {
    $caKey = New-Object System.Security.Cryptography.RSACng 4096
    $caReq = New-Object System.Security.Cryptography.X509Certificates.CertificateRequest("CN=$CaCommonName", $caKey, $hash, $pad)
    $caReq.CertificateExtensions.Add((New-Object System.Security.Cryptography.X509Certificates.X509BasicConstraintsExtension($true, $false, 0, $true))) | Out-Null
    $caFlags = [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyCertSign -bor [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::CrlSign
    $caReq.CertificateExtensions.Add((New-Object System.Security.Cryptography.X509Certificates.X509KeyUsageExtension($caFlags, $true))) | Out-Null
    $caReq.CertificateExtensions.Add((New-Object System.Security.Cryptography.X509Certificates.X509SubjectKeyIdentifierExtension($caReq.PublicKey, $false))) | Out-Null
    $caCert = $caReq.CreateSelfSigned($notBefore, $notAfter)

    Write-PemFile -Path $caCrtPath -Type "CERTIFICATE" -DerBytes ($caCert.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Cert))
    Write-PemFile -Path $caKeyPath -Type "PRIVATE KEY" -DerBytes ($caKey.Key.Export([System.Security.Cryptography.CngKeyBlobFormat]::Pkcs8PrivateBlob))
}

# ---------------- Mosquitto (server)
$mosKey = New-Object System.Security.Cryptography.RSACng 2048
$mosReq = New-Object System.Security.Cryptography.X509Certificates.CertificateRequest("CN=mosquitto", $mosKey, $hash, $pad)
$mosSan = New-Object System.Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder
foreach ($name in ($MosquittoDnsNames | Where-Object { $_ -and $_.Trim() })) {
    $mosSan.AddDnsName($name.Trim())
}
$mosIps = @($MosquittoIpAddresses + (Get-LocalIpv4Addresses)) | ForEach-Object { "$_".Trim() } | Where-Object { $_ } | Sort-Object -Unique
if ("127.0.0.1" -notin $mosIps) { $mosIps += "127.0.0.1" }
foreach ($ip in $mosIps) {
    try {
        $mosSan.AddIpAddress([System.Net.IPAddress]::Parse($ip.Trim()))
    } catch {
        throw "Invalid IP address in -MosquittoIpAddresses: $ip"
    }
}
$mosReq.CertificateExtensions.Add($mosSan.Build($false)) | Out-Null
$mosReq.CertificateExtensions.Add((New-Object System.Security.Cryptography.X509Certificates.X509BasicConstraintsExtension($false, $false, 0, $false))) | Out-Null
$mosFlags = [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::DigitalSignature -bor [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyEncipherment
$mosReq.CertificateExtensions.Add((New-Object System.Security.Cryptography.X509Certificates.X509KeyUsageExtension($mosFlags, $true))) | Out-Null
$mosEku = New-Object System.Security.Cryptography.OidCollection
$mosEku.Add((New-Object System.Security.Cryptography.Oid("1.3.6.1.5.5.7.3.1"))) | Out-Null # Server Authentication
$mosEku.Add((New-Object System.Security.Cryptography.Oid("1.3.6.1.5.5.7.3.2"))) | Out-Null # Client Authentication (dev: allow reusing same cert/key for mTLS)
$mosReq.CertificateExtensions.Add((New-Object System.Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension($mosEku, $true))) | Out-Null
$mosReq.CertificateExtensions.Add((New-Object System.Security.Cryptography.X509Certificates.X509SubjectKeyIdentifierExtension($mosReq.PublicKey, $false))) | Out-Null
$mosCert = if ($reuseExistingCa) {
    $mosReq.Create($caCert.SubjectName, $caSigGen, $notBefore, $notAfter, (New-SerialNumber))
} else {
    $mosReq.Create($caCert, $notBefore, $notAfter, (New-SerialNumber))
}

Write-PemFile -Path $mosCrtPath -Type "CERTIFICATE" -DerBytes ($mosCert.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Cert))
Write-PemFile -Path $mosKeyPath -Type "PRIVATE KEY" -DerBytes ($mosKey.Key.Export([System.Security.Cryptography.CngKeyBlobFormat]::Pkcs8PrivateBlob))

# ---------------- Web (server)
$webKey = New-Object System.Security.Cryptography.RSACng 2048
$webReq = New-Object System.Security.Cryptography.X509Certificates.CertificateRequest("CN=localhost", $webKey, $hash, $pad)
$webSan = New-Object System.Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder
foreach ($name in ($WebDnsNames | Where-Object { $_ -and $_.Trim() })) {
    $webSan.AddDnsName($name.Trim())
}
$webIps = @($WebIpAddresses + (Get-LocalIpv4Addresses)) | ForEach-Object { "$_".Trim() } | Where-Object { $_ } | Sort-Object -Unique
if ("127.0.0.1" -notin $webIps) { $webIps += "127.0.0.1" }
foreach ($ip in $webIps) {
    try {
        $webSan.AddIpAddress([System.Net.IPAddress]::Parse($ip.Trim()))
    } catch {
        throw "Invalid IP address in -WebIpAddresses: $ip"
    }
}
$webReq.CertificateExtensions.Add($webSan.Build($false)) | Out-Null
$webReq.CertificateExtensions.Add((New-Object System.Security.Cryptography.X509Certificates.X509BasicConstraintsExtension($false, $false, 0, $false))) | Out-Null
$webFlags = [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::DigitalSignature -bor [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyEncipherment
$webReq.CertificateExtensions.Add((New-Object System.Security.Cryptography.X509Certificates.X509KeyUsageExtension($webFlags, $true))) | Out-Null
$webEku = New-Object System.Security.Cryptography.OidCollection
$webEku.Add((New-Object System.Security.Cryptography.Oid("1.3.6.1.5.5.7.3.1"))) | Out-Null # Server Authentication
$webReq.CertificateExtensions.Add((New-Object System.Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension($webEku, $true))) | Out-Null
$webReq.CertificateExtensions.Add((New-Object System.Security.Cryptography.X509Certificates.X509SubjectKeyIdentifierExtension($webReq.PublicKey, $false))) | Out-Null
$webCert = if ($reuseExistingCa) {
    $webReq.Create($caCert.SubjectName, $caSigGen, $notBefore, $notAfter, (New-SerialNumber))
} else {
    $webReq.Create($caCert, $notBefore, $notAfter, (New-SerialNumber))
}

Write-PemFile -Path $webCrtPath -Type "CERTIFICATE" -DerBytes ($webCert.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Cert))
Write-PemFile -Path $webKeyPath -Type "PRIVATE KEY" -DerBytes ($webKey.Key.Export([System.Security.Cryptography.CngKeyBlobFormat]::Pkcs8PrivateBlob))

Write-Host "[ok] generated dev certs under: $OutDir"
if ($reuseExistingCa) {
    Write-Host " - CA:       (reused) $caCrtPath"
} else {
    Write-Host " - CA:       $caCrtPath"
}
Write-Host " - Mosquitto:$mosCrtPath"
Write-Host " - Web:      $webCrtPath"
