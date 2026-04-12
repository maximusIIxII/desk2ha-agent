# Dell Peripheral USB Capture Script
# Run as Administrator!
#
# 1. Run this script in Admin PowerShell
# 2. Open DDPM, change a KB900/MS900 setting (DPI, Backlight)
# 3. Press Ctrl+C to stop
# 4. Open the .pcapng in Wireshark

$ErrorActionPreference = "Stop"

Write-Host "Dell Peripheral USB Capture" -ForegroundColor Cyan
Write-Host "==========================="
Write-Host ""

$usbpcap = "C:\Program Files\USBPcap\USBPcapCMD.exe"
if (-not (Test-Path $usbpcap)) {
    Write-Error "USBPcap not found at $usbpcap"
    exit 1
}

# Try all 5 filters, capture from all devices on each root hub
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$outDir = "C:\dev\dell-ha\dell-ha-agent\tools"

# Find which filter has the Dell Secure Link Receiver
# We'll capture on ALL filters simultaneously for 2 seconds to find the right one
Write-Host "Probing USB root hubs (USBPcap1-5)..."
$activeFilter = $null

for ($i = 1; $i -le 5; $i++) {
    $filter = "\\.\USBPcap$i"
    $testFile = "$outDir\probe_$i.pcap"

    try {
        $proc = Start-Process -FilePath $usbpcap `
            -ArgumentList "-d `"$filter`" -o `"$testFile`" -A --snaplen 65535" `
            -PassThru -NoNewWindow -ErrorAction Stop

        Start-Sleep -Seconds 2

        if (-not $proc.HasExited) {
            $proc.Kill()
            $proc.WaitForExit(3000)
        }

        if (Test-Path $testFile) {
            $size = (Get-Item $testFile).Length
            Write-Host "  USBPcap$i : $size bytes captured"
            if ($size -gt 100) {
                if ($null -eq $activeFilter -or $size -gt $bestSize) {
                    $activeFilter = $i
                    $bestSize = $size
                }
            }
            Remove-Item $testFile -ErrorAction SilentlyContinue
        }
    } catch {
        Write-Host "  USBPcap$i : error - $($_.Exception.Message)"
    }
}

if ($null -eq $activeFilter) {
    Write-Host ""
    Write-Host "No active USB traffic found on any filter." -ForegroundColor Yellow
    Write-Host "Trying USBPcap1 as default..."
    $activeFilter = 1
}

$filter = "\\.\USBPcap$activeFilter"
$outFile = "$outDir\dell_peripheral_$timestamp.pcap"

Write-Host ""
Write-Host "Capturing on $filter (most USB traffic)" -ForegroundColor Green
Write-Host "Output: $outFile"
Write-Host ""
Write-Host "NOW: Open DDPM and change a setting (KB900 Backlight, MS900 DPI)" -ForegroundColor Yellow
Write-Host "Press Ctrl+C when done."
Write-Host ""

& $usbpcap -d $filter -o $outFile -A --snaplen 65535
