# 013 batch-2 window capture helper: grab the EasyEDA Pro window (the canvas the
# bridge's export.screenshot cannot deliver on this host — it returns one cached,
# blank frame). Read-only: it only reads pixels from the screen.
param([string]$Out = "outputs/013_win_capture.png", [int]$TargetPid = 0, [string]$Mode = "print")

Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class W {
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

if ($TargetPid -eq 0) {
  $TargetPid = (Get-Process lceda-pro | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1).Id
}
$p = Get-Process -Id $TargetPid
$h = $p.MainWindowHandle
Write-Output "pid=$TargetPid handle=$h title=$($p.MainWindowTitle)"
$r = New-Object W+RECT
[void][W]::GetWindowRect($h, [ref]$r)
$w = $r.Right - $r.Left; $ht = $r.Bottom - $r.Top
Write-Output "rect=$($r.Left),$($r.Top) size=${w}x${ht} iconic=$([W]::IsIconic($h))"

$bmp = New-Object System.Drawing.Bitmap($w, $ht)
$g = [System.Drawing.Graphics]::FromImage($bmp)
if ($Mode -eq "screen") {
  $g.CopyFromScreen($r.Left, $r.Top, 0, 0, (New-Object System.Drawing.Size($w, $ht)))
} else {
  $dc = $g.GetHdc()
  # 2 = PW_RENDERFULLCONTENT (needed for GPU-composited Chromium/Electron windows)
  [void][W]::PrintWindow($h, $dc, 2)
  $g.ReleaseHdc($dc)
}
$g.Dispose()
$bmp.Save((Resolve-Path -LiteralPath (Split-Path -Parent $Out)).Path + "\" + (Split-Path -Leaf $Out),
          [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()

# non-white pixel count, so "blank" is a measurement, not an opinion
$img = [System.Drawing.Image]::FromFile((Resolve-Path -LiteralPath $Out).Path)
$b2 = New-Object System.Drawing.Bitmap($img)
$nonWhite = 0
for ($y = 0; $y -lt $b2.Height; $y += 4) {
  for ($x = 0; $x -lt $b2.Width; $x += 4) {
    $c = $b2.GetPixel($x, $y)
    if ($c.R -lt 240 -or $c.G -lt 240 -or $c.B -lt 240) { $nonWhite++ }
  }
}
$b2.Dispose(); $img.Dispose()
Write-Output "saved=$Out size=$((Get-Item $Out).Length) nonWhiteSamples=$nonWhite"
