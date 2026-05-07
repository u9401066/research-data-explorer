# Session Cleanup - sessionEnd Hook (PowerShell)
# ENCODING: Forces UTF-8 output.
$ErrorActionPreference = "Stop"

[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

function Append-Utf8NoBomLine {
    param(
        [string]$Path,
        [string]$Line
    )
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::AppendAllText($Path, $Line + [Environment]::NewLine, $encoding)
}

function Clear-HookStateFile {
    param([string]$Path)
    try {
        if (Test-Path $Path -ErrorAction SilentlyContinue) {
            $archiveDir = Join-Path (Split-Path $Path -Parent) "_archive"
            if (-not (Test-Path $archiveDir)) {
                New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null
            }
            $stamp = Get-Date -Format "yyyyMMddTHHmmssfff"
            $leaf = Split-Path $Path -Leaf
            Move-Item -LiteralPath $Path -Destination (Join-Path $archiveDir "$stamp-$leaf") -Force
        }
    } catch {
    }
}

try {
    $rawInput = [Console]::In.ReadToEnd()
    $reason = "unknown"
    if ($rawInput -and $rawInput.Trim().Length -gt 0) {
        try {
            $inputJson = $rawInput | ConvertFrom-Json -ErrorAction Stop
            $reason = if ($inputJson.reason) { $inputJson.reason } else { "unknown" }
        } catch {
            # Malformed input - continue with defaults
        }
    }

    $stateDir = ".github/hooks/_state"
    if (Test-Path $stateDir) {
        # Log session end
        try {
            $logEntry = @{
                timestamp = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
                event     = "session_end"
                reason    = $reason
            }
            Append-Utf8NoBomLine -Path "$stateDir/search_audit.jsonl" -Line ($logEntry | ConvertTo-Json -Compress)
        } catch {
            # Audit log write failed - non-critical
        }

        # Archive state while clearing active nudges (keep audit log).
        Clear-HookStateFile -Path "$stateDir/last_search_eval.json"
        Clear-HookStateFile -Path "$stateDir/last_research_eval.json"
        Clear-HookStateFile -Path "$stateDir/pending_complexity.json"
    }
    exit 0
} catch {
    # Fail open - cleanup should never block
    exit 0
}
