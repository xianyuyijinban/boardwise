# 013 batch-2: screen-grab the editor windows. PrintWindow (and the bridge's own
# export.screenshot) both hand back cached frames on this host — byte-identical
# before and after a marker call — so the only way to see the canvas is to raise
# each editor window and grab the screen under it.
#
# The raise is a z-order change only, and the window that had the foreground is
# restored afterwards. Nothing in the project is touched.
param([string]$Prefix = "outputs/013_scr", [string]$ProcName = "lceda-pro")

Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class ScrW {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [StructLayout(LayoutKind.Sequential)] public struct R { public int L,T,Ri,B; }
}
"@

$pids = (Get-Process $ProcName -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
if (-not $pids) { Write-Output "no process named $ProcName"; exit 1 }

$found = New-Object System.Collections.ArrayList
$cb = [ScrW+EnumProc]{
  param($h, $l)
  $pid2 = 0
  [void][ScrW]::GetWindowThreadProcessId($h, [ref]$pid2)
  if ($pids -contains [int]$pid2) {
    $r = New-Object ScrW+R
    [void][ScrW]::GetWindowRect($h, [ref]$r)
    $w = $r.Ri - $r.L; $ht = $r.B - $r.T
    if ([ScrW]::IsWindowVisible($h) -and $w -gt 200 -and $ht -gt 200) {
      [void]$found.Add([pscustomobject]@{ h = $h; w = $w; ht = $ht; l = $r.L; t = $r.T })
    }
  }
  return $true
}
[void][ScrW]::EnumWindows($cb, [IntPtr]::Zero)

$prev = [ScrW]::GetForegroundWindow()
$i = 0
foreach ($item in $found) {
  $i++
  [void][ScrW]::ShowWindow([IntPtr]$item.h, 9)   # SW_RESTORE
  [void][ScrW]::SetWindowPos([IntPtr]$item.h, [IntPtr]::Zero, 0, 0, 0, 0, 0x43)  # NOMOVE|NOSIZE|SHOWWINDOW|NOACTIVATE? keep simple below
  [void][ScrW]::BringWindowToTop([IntPtr]$item.h)
  [void][ScrW]::SetForegroundWindow([IntPtr]$item.h)
  Start-Sleep -Milliseconds 900
  $r = New-Object ScrW+R
  [void][ScrW]::GetWindowRect([IntPtr]$item.h, [ref]$r)
  $w = $r.Ri - $r.L; $ht = $r.B - $r.T
  $b = New-Object System.Drawing.Bitmap($w, $ht)
  $g = [System.Drawing.Graphics]::FromImage($b)
  $g.CopyFromScreen($r.L, $r.T, 0, 0, (New-Object System.Drawing.Size($w, $ht)))
  $g.Dispose()
  $sb = New-Object System.Text.StringBuilder 512
  [void][ScrW]::GetWindowText([IntPtr]$item.h, $sb, 512)
  $path = Join-Path (Get-Location) "$Prefix$i.png"
  $b.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
  $b.Dispose()
  # non-white samples, so "this grab is blank" is measured
  $img = [System.Drawing.Bitmap]::FromFile($path)
  $nw = 0
  for ($y = 0; $y -lt $img.Height; $y += 6) {
    for ($x = 0; $x -lt $img.Width; $x += 6) {
      $c = $img.GetPixel($x, $y)
      if ($c.R -lt 240 -or $c.G -lt 240 -or $c.B -lt 240) { $nw++ }
    }
  }
  $img.Dispose()
  Write-Output "$path hwnd=$($item.h) size=${w}x${ht} nonWhite=$nw title=[$($sb.ToString())]"
}
if ($prev -ne [IntPtr]::Zero) { [void][ScrW]::SetForegroundWindow($prev) }
Write-Output "restored foreground=$prev"
