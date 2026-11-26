"""Apply and verify a Windows owner-only ACL before writing research key bytes."""

import os
import subprocess
from pathlib import Path


def windows_private_key(path: Path, *, initialize: bool = False) -> None:
    kernel = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    script = """
$ErrorActionPreference = 'Stop'
$file = Get-Item -Force -LiteralPath $env:RDE_ACL_TARGET
if ($file.PSIsContainer -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) {exit 2}
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$acl = Get-Acl -LiteralPath $file.FullName
if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $sid.Value) {exit 2}
if ($env:RDE_ACL_INITIALIZE -eq '1') {
    if ($file.Length -ne 0) {exit 2}
    $acl.SetSecurityDescriptorSddlForm(('D:P(A;;FA;;;{0})' -f $sid.Value), [Security.AccessControl.AccessControlSections]::Access)
    Set-Acl -LiteralPath $file.FullName -AclObject $acl
    $acl = Get-Acl -LiteralPath $file.FullName
}
$rules = @($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
if (!$acl.AreAccessRulesProtected -or $rules.Count -ne 1) {exit 2}
if ($rules[0].IdentityReference.Value -ne $sid.Value -or $rules[0].AccessControlType -ne 'Allow') {exit 2}
"""
    result = subprocess.run(
        [str(kernel), "-NoProfile", "-NonInteractive", "-Command", script],
        env={
            **os.environ,
            "RDE_ACL_TARGET": str(path.resolve()),
            "RDE_ACL_INITIALIZE": "1" if initialize else "0",
        },
        capture_output=True,
        timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise ValueError("Research privacy key requires an owner-only Windows file ACL.")
