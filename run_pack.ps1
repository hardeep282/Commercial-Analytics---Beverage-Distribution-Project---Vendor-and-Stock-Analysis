

# Step 7 - run the monthly pack. Windows Task Scheduler runs this file once a month.
# It builds last month's pack and writes everything it prints to pack_output\run_log.txt,
# so a run that happened while nobody was watching can still be checked afterwards.

$project = $PSScriptRoot                                   # the folder this file is in
Set-Location $project
$python = Join-Path $project ".venv\Scripts\python.exe"   # the venv's Python: no activation needed
$log = Join-Path $project "pack_output\run_log.txt"
New-Item -ItemType Directory -Force -Path (Join-Path $project "pack_output") | Out-Null
$env:PYTHONIOENCODING = "utf-8"

"`r`n===== run started $(Get-Date -Format 'yyyy-MM-dd HH:mm') =====" | Out-File $log -Append -Encoding utf8
& $python -m monthly_pack.build_pack --previous-month 2>&1 | Out-File $log -Append -Encoding utf8
$code = $LASTEXITCODE
"===== run finished, exit code $code (0 = success) =====" | Out-File $log -Append -Encoding utf8
exit $code