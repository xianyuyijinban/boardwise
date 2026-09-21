# 013 batch-2: does the canvas contain marker-shaped red geometry?
# The marker rectangles are hollow boxes drawn around components, so they show up
# as long straight runs of red pixels. A schematic's own red parts (component
# bodies, pin stubs) do not. Counts red pixels that sit in a horizontal or
# vertical run of at least MinRun pixels.
param([Parameter(Mandatory=$true)][string]$File, [int]$MinRun = 25,
      [int]$R = 180, [int]$G = 80, [int]$B = 80)

Add-Type -AssemblyName System.Drawing
$img = [System.Drawing.Bitmap]::FromFile((Resolve-Path $File).Path)
$w = $img.Width; $h = $img.Height
$mask = New-Object 'bool[,]' $w, $h
for ($y = 0; $y -lt $h; $y++) {
  for ($x = 0; $x -lt $w; $x++) {
    $c = $img.GetPixel($x, $y)
    if ($c.R -ge $R -and $c.G -le $G -and $c.B -le $B) { $mask[$x, $y] = $true }
  }
}
$total = 0; $inRun = 0; $maxH = 0; $maxV = 0
for ($y = 0; $y -lt $h; $y++) {           # horizontal runs
  $run = 0
  for ($x = 0; $x -lt $w; $x++) {
    if ($mask[$x, $y]) { $run++; $total++ } else { if ($run -ge $MinRun) { $inRun += $run }; if ($run -gt $maxH) { $maxH = $run }; $run = 0 }
  }
  if ($run -ge $MinRun) { $inRun += $run }; if ($run -gt $maxH) { $maxH = $run }
}
for ($x = 0; $x -lt $w; $x++) {           # vertical runs
  $run = 0
  for ($y = 0; $y -lt $h; $y++) {
    if ($mask[$x, $y]) { $run++ } else { if ($run -ge $MinRun) { $inRun += $run }; if ($run -gt $maxV) { $maxV = $run }; $run = 0 }
  }
  if ($run -ge $MinRun) { $inRun += $run }; if ($run -gt $maxV) { $maxV = $run }
}
$img.Dispose()
Write-Output ("{0}: redTotal={1} redInLongRuns={2} maxHRun={3} maxVRun={4} (MinRun={5})" -f `
  (Split-Path -Leaf $File), $total, $inRun, $maxH, $maxV, $MinRun)
