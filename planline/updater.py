"""Verify and stage GitHub release updates for the Planline desktop app."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from . import __version__

REPOSITORY = "marlucool/floorplan-digitizer"
RELEASES_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
INSTALLER_NAME = "Planline-Setup.exe"
CHECKSUMS_NAME = "checksums.txt"
MAX_INSTALLER_BYTES = 500 * 1024 * 1024


class UpdateError(RuntimeError):
    """An update could not be checked, verified or staged."""


def _version_key(value: str) -> tuple[int, ...]:
    match = re.fullmatch(r"v?(\d+(?:\.\d+){1,3})", value.strip(), re.IGNORECASE)
    if not match:
        raise UpdateError(f"Unsupported Planline release version: {value}")
    return tuple(int(part) for part in match.group(1).split("."))


def _is_release_asset_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urllib.parse.urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.netloc.lower() == "github.com"
        and parsed.path.startswith(f"/{REPOSITORY}/releases/download/")
        and not parsed.query
        and not parsed.fragment
    )


def _read_url(url: str, *, limit: int = 2 * 1024 * 1024) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"Planline/{__version__}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > limit:
                raise UpdateError("The GitHub response is larger than expected.")
            data = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and url == RELEASES_API:
            raise UpdateError("No stable Planline release has been published yet.") from exc
        raise UpdateError(f"GitHub returned HTTP {exc.code} while checking for updates.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Could not reach GitHub: {exc}") from exc
    if len(data) > limit:
        raise UpdateError("The GitHub response is larger than expected.")
    return data


def _asset_map(release: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        return {}
    return {
        item.get("name"): item
        for item in assets
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }


def _release_version(tag_name: str) -> str:
    prefix = "planline-v"
    if not tag_name.lower().startswith(prefix):
        raise UpdateError("The latest GitHub release does not use a Planline version tag.")
    version = tag_name[len(prefix):]
    _version_key(version)
    return version


def fetch_latest_release() -> dict[str, Any]:
    """Fetch latest stable release metadata, omitting executable URLs from the UI."""
    try:
        release = json.loads(_read_url(RELEASES_API))
    except json.JSONDecodeError as exc:
        raise UpdateError("GitHub returned invalid release metadata.") from exc
    if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
        raise UpdateError("GitHub did not return a stable Planline release.")

    latest_version = _release_version(str(release.get("tag_name", "")))
    assets = _asset_map(release)
    installer = assets.get(INSTALLER_NAME)
    checksums = assets.get(CHECKSUMS_NAME)
    asset_urls_ready = (
        _is_release_asset_url(installer.get("browser_download_url") if installer else None)
        and _is_release_asset_url(checksums.get("browser_download_url") if checksums else None)
    )
    available = _version_key(latest_version) > _version_key(__version__)

    return {
        "status": "update_available" if available else "up_to_date",
        "current_version": __version__,
        "latest_version": latest_version,
        "update_available": available,
        "install_available": bool(available and asset_urls_ready),
        "release_url": release.get("html_url"),
        "release_notes": str(release.get("body") or "")[:20000],
        "published_at": release.get("published_at"),
        "installer_size": installer.get("size") if installer else None,
        "message": (
            "A verified installer is available."
            if available and asset_urls_ready
            else "A newer release exists, but its installer or checksum manifest is missing."
            if available
            else "Planline is up to date."
        ),
    }


def check_for_updates() -> dict[str, Any]:
    try:
        return fetch_latest_release()
    except UpdateError as exc:
        if str(exc) == "No stable Planline release has been published yet.":
            return {
                "status": "no_release",
                "current_version": __version__,
                "latest_version": None,
                "update_available": False,
                "install_available": False,
                "release_url": f"https://github.com/{REPOSITORY}/releases",
                "release_notes": "",
                "published_at": None,
                "installer_size": None,
                "message": str(exc),
            }
        raise


def _checksum_for_installer(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="strict")
    pattern = re.compile(
        rf"^([0-9a-fA-F]{{64}})\s+\*?{re.escape(INSTALLER_NAME)}\s*$",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        raise UpdateError("The release checksum manifest does not contain Planline-Setup.exe.")
    return match.group(1).lower()


def _download_asset(url: str, destination: Path) -> str:
    if not _is_release_asset_url(url):
        raise UpdateError("GitHub returned an unexpected installer download URL.")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"Planline/{__version__}", "Accept": "application/octet-stream"},
    )
    digest = hashlib.sha256()
    total = 0
    temp_path = destination.with_suffix(destination.suffix + ".part")
    try:
        with urllib.request.urlopen(request, timeout=90) as response, temp_path.open("wb") as output:
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_INSTALLER_BYTES:
                raise UpdateError("The installer is larger than the permitted download limit.")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_INSTALLER_BYTES:
                    raise UpdateError("The installer exceeded the permitted download limit.")
                digest.update(chunk)
                output.write(chunk)
        if total < 1_000_000:
            raise UpdateError("The downloaded installer is unexpectedly small.")
        os.replace(temp_path, destination)
        return digest.hexdigest()
    except UpdateError:
        temp_path.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        temp_path.unlink(missing_ok=True)
        raise UpdateError(f"The installer download failed: {exc}") from exc


def _powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _build_update_script(installer_path: Path, install_directory: str, parent_pid: int) -> str:
    installer = _powershell_literal(str(installer_path))
    install_dir = _powershell_literal(install_directory)
    return f"""$ErrorActionPreference = 'Stop'
$planlineParentPid = {int(parent_pid)}
$installerPath = {installer}
$installDirectory = {install_dir}
try {{
    Wait-Process -Id $planlineParentPid -Timeout 300 -ErrorAction Stop
}} catch {{
    if (Get-Process -Id $planlineParentPid -ErrorAction SilentlyContinue) {{
        exit 42
    }}
}}
$arguments = @('--update-install', '--install-path', ('"' + $installDirectory + '"'))
$setup = Start-Process -FilePath $installerPath -ArgumentList $arguments -PassThru -Wait
exit $setup.ExitCode
"""


def stage_and_launch_update() -> dict[str, str]:
    """Download, checksum-verify and hand off the installer after Planline exits."""
    if os.name != "nt":
        raise UpdateError("Automatic installation is available in the Windows desktop build.")
    install_directory = os.environ.get("PLANLINE_INSTALL_DIR")
    parent_pid_text = os.environ.get("PLANLINE_LAUNCHER_PID")
    if not install_directory or not parent_pid_text:
        raise UpdateError("Planline could not identify its installed launcher. Open the installed desktop app to update.")
    try:
        parent_pid = int(parent_pid_text)
    except ValueError as exc:
        raise UpdateError("Planline's launcher process ID is invalid.") from exc
    if parent_pid <= 0:
        raise UpdateError("Planline's launcher process ID is invalid.")

    release = fetch_latest_release()
    if not release["update_available"] or not release["install_available"]:
        raise UpdateError(release["message"])
    release_data = json.loads(_read_url(RELEASES_API))
    assets = _asset_map(release_data)
    installer = assets.get(INSTALLER_NAME) or {}
    checksums = assets.get(CHECKSUMS_NAME) or {}
    installer_url = installer.get("browser_download_url")
    checksums_url = checksums.get("browser_download_url")
    if not _is_release_asset_url(installer_url) or not _is_release_asset_url(checksums_url):
        raise UpdateError("The latest release does not contain valid update assets.")

    expected_digest = _checksum_for_installer(_read_url(checksums_url))
    data_root = Path(os.environ.get("PLANLINE_DATA_DIR") or (
        Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Planline"
    ))
    update_directory = data_root / "updates" / release["latest_version"]
    update_directory.mkdir(parents=True, exist_ok=True)
    installer_path = update_directory / INSTALLER_NAME
    actual_digest = _download_asset(installer_url, installer_path)
    if not hmac.compare_digest(actual_digest, expected_digest):
        installer_path.unlink(missing_ok=True)
        raise UpdateError("The installer SHA-256 checksum did not match GitHub's release manifest.")

    script_path = update_directory / "install-update.ps1"
    script_path.write_text(
        _build_update_script(installer_path, install_directory, parent_pid),
        encoding="utf-8",
    )
    powershell = (
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    )
    if not powershell.is_file():
        raise UpdateError("Windows PowerShell could not be found; the installer is downloaded but not started.")
    try:
        subprocess.Popen(
            [
                str(powershell), "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", str(script_path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    except OSError as exc:
        raise UpdateError(f"The update was downloaded but could not be launched: {exc}") from exc

    return {
        "status": "launching",
        "version": release["latest_version"],
        "message": "The verified update is ready. Planline will close and install it automatically.",
    }
