# 013 batch-2: enumerate every top-level window of the editor process and capture
# each one. EasyEDA Pro can show documents in their own windows, so the main
# window (Start Page) is not necessarily where the schematic canvas lives.
param([int]$TargetPid = 5240, [string]$Prefix = "outputs/013_win_")

Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class W2 {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

$list = New-Object System.Collections.ArrayList
$cb = [W2+EnumProc]{
  param($h, $l)
  $pid2 = 0
  [void][W2]::GetWindowThreadProcessId($h, [ref]$pid2)
  if ($pid2 -eq $TargetPid) {
    $n = [W2]::GetWindowTextLength($h)
    $sb = New-Object System.Text.StringBuilder ($n + 2)
    [void][W2]::GetWindowText($h, $sb, $sb.Capacity)
    $r = New-Object W2+RECT
    [void][W2]::GetWindowRect($h, [ref]$r)
    [void]$list.Add([pscustomobject]@{
      hwnd = $h; title = $sb.ToString(); vis = [W2]::IsWindowVisible($h)
      iconic = [W2]::IsIconic($h); w = $r.Right - $r.Left; hgt = $r.Bottom - $r.Top
      left = $r.Left; top = $r.Top
    })
  }
  return $true
}
[void][W2]::EnumWindows($cb, [IntPtr]::Zero)

$i = 0
foreach ($w in $list) {
  $i++
  $tag = "$Prefix$i.png"
  $line = "win#$i hwnd=$($w.hwnd) vis=$($w.vis) iconic=$($w.iconic) size=$($w.w)x$($w.hgt) title=[$($w.title)]"
  if ($w.w -le 0 -or $w.hgt -le 0) { Write-Output "$line -> skipped"; continue }
  $bmp = New-Object System.Drawing.Bitmap($w.w, $w.hgt)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $dc = $g.GetHdc()
  [void][W2]::PrintWindow($w.hwnd, $dc, 2)
  $g.ReleaseHdc($dc); $g.Dispose()
  $bmp.Save((Join-Path (Get-Location) $tag), [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()
  $img = [System.Drawing.Bitmap]::FromFile((Join-Path (Get-Location) $tag))
  $nonWhite = 0
  for ($y = 0; $y -lt $img.Height; $y += 4) {
    for ($x = 0; $x -lt $img.Width; $x += 4) {
      $c = $img.GetPixel($x, $y)
      if ($c.R -lt 240 -or $c.G -lt 240 -or $c.B -lt 240) { $nonWhite++ }
    }
  }
  $img.Dispose()
  Write-Output "$line -> $tag nonWhite=$nonWhite"
}
