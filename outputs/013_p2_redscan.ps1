# 013 batch-2: find the review markers (#FF0000 by default) in a captured
# window image — the marker API takes shapes, not text, so "is it on screen"
# has to be measured in pixels. Read-only.
param([Parameter(Mandatory=$true)][string[]]$Files, [int]$R = 200, [int]$G = 70, [int]$B = 70)

Add-Type -AssemblyName System.Drawing
foreach ($f in $Files) {
  if (-not (Test-Path $f)) { Write-Output "$f -> missing"; continue }
  $img = [System.Drawing.Bitmap]::FromFile((Resolve-Path $f).Path)
  $count = 0; $minX = 999999; $minY = 999999; $maxX = -1; $maxY = -1
  for ($y = 0; $y -lt $img.Height; $y++) {
    for ($x = 0; $x -lt $img.Width; $x++) {
      $c = $img.GetPixel($x, $y)
      if ($c.R -ge $R -and $c.G -le $G -and $c.B -le $B) {
        $count++
        if ($x -lt $minX) { $minX = $x }; if ($x -gt $maxX) { $maxX = $x }
        if ($y -lt $minY) { $minY = $y }; if ($y -gt $maxY) { $maxY = $y }
      }
    }
  }
  $box = if ($count) { "$minX,$minY - $maxX,$maxY" } else { "-" }
  Write-Output ("{0}: size={1}x{2} redPixels={3} bbox={4}" -f $f, $img.Width, $img.Height, $count, $box)
  $img.Dispose()
}
