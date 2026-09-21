# 013 batch-2: pixel-difference between two grabs of the same editor window, so
# "the mark changed the canvas" is a measurement. Reports how many pixels differ,
# how many of those are red on the B side (a marker), and the bounding boxes.
param([Parameter(Mandatory=$true)][string]$A, [Parameter(Mandatory=$true)][string]$B,
      [int]$Tol = 12)

Add-Type -AssemblyName System.Drawing
$ia = [System.Drawing.Bitmap]::FromFile((Resolve-Path $A).Path)
$ib = [System.Drawing.Bitmap]::FromFile((Resolve-Path $B).Path)
if ($ia.Width -ne $ib.Width -or $ia.Height -ne $ib.Height) {
  Write-Output "size mismatch: $($ia.Width)x$($ia.Height) vs $($ib.Width)x$($ib.Height)"; exit 1
}
$diff = 0; $redOnB = 0; $minX = 999999; $minY = 999999; $maxX = -1; $maxY = -1
for ($y = 0; $y -lt $ia.Height; $y++) {
  for ($x = 0; $x -lt $ia.Width; $x++) {
    $ca = $ia.GetPixel($x, $y); $cb = $ib.GetPixel($x, $y)
    if ([Math]::Abs($ca.R - $cb.R) -gt $Tol -or [Math]::Abs($ca.G - $cb.G) -gt $Tol -or
        [Math]::Abs($ca.B - $cb.B) -gt $Tol) {
      $diff++
      if ($x -lt $minX) { $minX = $x }; if ($x -gt $maxX) { $maxX = $x }
      if ($y -lt $minY) { $minY = $y }; if ($y -gt $maxY) { $maxY = $y }
      if ($cb.R -ge 180 -and $cb.G -le 90 -and $cb.B -le 90) { $redOnB++ }
    }
  }
}
$ia.Dispose(); $ib.Dispose()
$box = if ($diff) { "$minX,$minY - $maxX,$maxY" } else { "-" }
Write-Output "A=$A B=$B diffPixels=$diff redOnB=$redOnB bbox=$box"
