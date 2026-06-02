#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$VideoRoot = if ($env:VIDEO_ROOT) { $env:VIDEO_ROOT } else { "e:\CCTV Footage" }
$StoreId = if ($env:STORE_ID) { $env:STORE_ID } else { "STORE_BLR_002" }
$Output = if ($env:OUTPUT) { $env:OUTPUT } else { Join-Path $Root "data\generated_events.jsonl" }
$IngestUrl = if ($env:INGEST_URL) { $env:INGEST_URL } else { "http://localhost:8000" }
$FrameStride = if ($env:FRAME_STRIDE) { $env:FRAME_STRIDE } else { "5" }

python (Join-Path $Root "scripts\prepare_pos.py")
$detectArgs = @(
    (Join-Path $Root "pipeline\detect.py"),
    "--store-id", $StoreId,
    "--video-root", $VideoRoot,
    "--layout", (Join-Path $Root "data\store_layout.json"),
    "--output", $Output,
    "--frame-stride", $FrameStride,
    "--ingest-url", $IngestUrl
)
if ($env:FAST_MODE -eq "1") { $detectArgs += "--fast" }
python @detectArgs
Write-Host "Pipeline complete. Events written to $Output"
