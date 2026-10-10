# tools/cut_public.ps1 — rebuild the public single-commit repo from private HEAD.
#
# The public repo is an artefact, never a place to work: this script deletes and
# recreates it. Built from `git archive HEAD`, not from the filesystem, because a
# filesystem copy brought .env and data/raw/Connections.csv across on the first
# attempt and only .gitignore stood between a live key and a public repo.
#
# It refuses rather than repairs. Every check that failed or passed vacuously
# while the first cut was made is here, and each one is proven able to fire.

[CmdletBinding()]
param(
    [string]$Private  = "C:\dev\network-visualiser",
    [string]$Public   = "C:\dev\nv-public",
    [string]$Remote   = "https://github.com/amrxshariff/avian_v1.git",
    [Parameter(Mandatory)][string]$MessageFile,
    [switch]$Push
)

$ErrorActionPreference = "Stop"

function Fail($msg) { Write-Host "REFUSED: $msg" -ForegroundColor Red; exit 1 }

# PowerShell 5.1 does not stop on a failing native command, whatever
# $ErrorActionPreference says, so every git call that matters is checked.
function Git-Checked {
    git @args
    if ($LASTEXITCODE -ne 0) { Fail "git $($args -join ' ') exited $LASTEXITCODE" }
}

# Resolved now: the commit runs from inside $Public, where a relative path
# would point at nothing.
if (-not (Test-Path $MessageFile)) { Fail "no commit message file at $MessageFile" }
$MessageFile = (Resolve-Path $MessageFile).Path

# The one destructive step deletes $Public. Refuse unless it is unmistakably
# the public artefact: never the private repo or anything containing it, and,
# if it is already a repository, one whose origin is $Remote.
$privFull = [IO.Path]::GetFullPath($Private).TrimEnd('\')
$pubFull  = [IO.Path]::GetFullPath($Public).TrimEnd('\')
if ($pubFull -eq $privFull -or $privFull.StartsWith("$pubFull\")) {
    Fail "-Public ($pubFull) is, or contains, the private repo"
}
if (Test-Path (Join-Path $pubFull ".git")) {
    $existing = git -C $pubFull remote get-url origin 2>$null
    if ($existing -ne $Remote) { Fail "$pubFull has origin '$existing', not $Remote" }
}

# The force-push replaces whatever the remote holds, so refuse unless that is
# exactly the local public commit (D-82). A title edited in GitHub's web editor
# on the public repo was not in the private one, and the first cut built by this
# script erased it: the checks above compare against the LOCAL public copy, and
# that copy was stale. Asked of the remote itself, and the push below is leased
# on the same answer, so nothing published in between is overwritten either.
$remoteLine = git ls-remote $Remote refs/heads/main
if ($LASTEXITCODE -ne 0) { Fail "could not read $Remote (git ls-remote exited $LASTEXITCODE)" }
$remoteHead = if ($remoteLine) { ($remoteLine -split "\s+")[0] } else { "" }
if ($remoteHead) {
    $localHead = if (Test-Path (Join-Path $pubFull ".git")) { git -C $pubFull rev-parse HEAD 2>$null } else { "" }
    if ($localHead -ne $remoteHead) {
        Fail ("the public remote's main is $remoteHead, but the local public copy " +
              "is at '$localHead'. Something was published that is not in it, and " +
              "this cut would erase it. Bring that change into the private repo, " +
              "then fetch it into $pubFull before cutting.")
    }
}

# Prove the key scan can match before trusting an empty result. The sample is
# assembled at run time: written out whole, this script would ship it in the
# cut and the scan would refuse on itself every time.
$keyPattern = "sk-ant-[A-Za-z0-9_-]{20,}"
$sample = "sk-ant-" + ("A" * 24)
if (-not ($sample | Select-String -Pattern $keyPattern)) {
    Fail "the key scan cannot match a key - an empty result would prove nothing"
}

Set-Location $Private
# Untracked files are ignored here: the cut is `git archive HEAD`, so they
# cannot reach it. Uncommitted changes to tracked files would be silently left
# out, so those refuse.
if (git status --porcelain --untracked-files=no) { Fail "the private repo has uncommitted changes" }
$local = git log --oneline origin/main..HEAD
if ($local) { Fail "the private repo has unpushed commits:`n$local" }

# Scan what the cut will contain before deleting anything, so a refusal leaves
# the existing public tree untouched. The extracted tree is scanned again below.
$early = git grep -l -E $keyPattern HEAD -- .
if ($early) { Fail "possible API key in HEAD, before anything was deleted:`n$($early -join "`n")" }

$expected = @(git ls-files).Count
$source = git log -1 --format="%h %s"
Write-Host "private HEAD $source tracks $expected files"

# --- rebuild ---------------------------------------------------------------
$zip = Join-Path $env:TEMP "nv-public-cut.zip"
if (Test-Path $pubFull) { Remove-Item $pubFull -Recurse -Force }
Git-Checked archive --format=zip -o $zip HEAD
Expand-Archive $zip -DestinationPath $pubFull -Force
Remove-Item $zip

# --- refuse on anything the archive should not contain ----------------------
Set-Location $pubFull
$count = @(Get-ChildItem -Recurse -File -Force).Count
if ($count -ne $expected) { Fail "extracted $count files, expected $expected" }

foreach ($p in @(".env", "data\raw", "data\graph", "data\labels")) {
    if (Test-Path $p) { Fail "$p is present in the cut" }
}

$keys = Get-ChildItem -Recurse -File -Force | Select-String -Pattern $keyPattern
if ($keys) { Fail "possible API key:`n$($keys | Out-String)" }

# --- commit -----------------------------------------------------------------
Git-Checked init -q
Git-Checked branch -m main
Git-Checked remote add origin $Remote
Git-Checked add -A
$staged = @(git status --short).Count
if ($staged -ne $expected) { Fail "staged $staged files, expected $expected" }

Git-Checked commit -q -F $MessageFile
git log -1 --format="%h %s"

$lease = "--force-with-lease=main:$remoteHead"
if ($Push) {
    Git-Checked push $lease origin main
} else {
    Write-Host "`nNot pushed. Review, then:  git push $lease origin main" -ForegroundColor Yellow
}
