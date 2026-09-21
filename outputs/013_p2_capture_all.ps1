# 013 batch-2: capture every top-level window of the editor process, fast (no
# pixel scan — that is 013_p2_redscan.ps1's job). Used right after a marker call,
# because export.screenshot on this host returns one cached blank frame.
param([string]$Prefix = "outputs/013_cap", [string]$ProcName = "lceda-pro")

Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class CapW {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [StructLayout(LayoutKind.Sequential)] public struct R { public int L,T,Ri,B; }
}
"@

$pids = (Get-Process $ProcName -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
if (-not $pids) { Write-Output "no process named $ProcName"; exit 1 }

$found = New-Object System.Collections.ArrayList
$cb = [CapW+EnumProc]{
  param($h, $l)
  $pid2 = 0
  [void][CapW]::GetWindowThreadProcessId($h, [ref]$pid2)
  if ($pids -contains [int]$pid2) { [void]$found.Add([pscustomobject]@{ h = $h; vis = [CapW]::IsWindowVisible($h) }) }
  return $true
}
[void][CapW]::EnumWindows($cb, [IntPtr]::Zero)

$i = 0
foreach ($item in $found) {
  $i++
  $h = $item.h
  $r = New-Object CapW+R
  [void][CapW]::GetWindowRect([IntPtr]$h, [ref]$r)
  $w = $r.Ri - $r.L; $ht = $r.B - $r.T
  if ($w -le 0 -or $ht -le 0) { continue }
  $sb = New-Object System.Text.StringBuilder 512
  [void][CapW]::GetWindowText([IntPtr]$h, $sb, 512)
  $b = New-Object System.Drawing.Bitmap($w, $ht)
  $g = [System.Drawing.Graphics]::FromImage($b)
  $dc = $g.GetHdc()
  [void][CapW]::PrintWindow([IntPtr]$h, $dc, 2)
  $g.ReleaseHdc($dc); $g.Dispose()
  $path = Join-Path (Get-Location) "$Prefix$i.png"
  $b.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
  $b.Dispose()
  Write-Output "$path hwnd=$h vis=$($item.vis) size=${w}x${ht} title=[$($sb.ToString())]"
}
