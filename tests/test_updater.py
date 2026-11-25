from __future__ import annotations

import json
from pathlib import Path

import pytest

from planline import updater


def release(version: str = "0.1.2") -> dict:
    base = "https://github.com/marlucool/floorplan-digitizer/releases/download/planline-v" + version
    return {
        "tag_name": "planline-v" + version,
        "draft": False,
        "prerelease": False,
        "html_url": "https://github.com/marlucool/floorplan-digitizer/releases/tag/planline-v" + version,
        "published_at": "2026-11-25T00:00:00Z",
        "body": "Update notes",
        "assets": [
            {"name": "Planline-Setup.exe", "browser_download_url": base + "/Planline-Setup.exe", "size": 12_000_000},
            {"name": "checksums.txt", "browser_download_url": base + "/checksums.txt", "size": 100},
        ],
    }


def test_release_check_detects_newer_verified_installer(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps(release()).encode("utf-8")
    monkeypatch.setattr(updater, "_read_url", lambda _url, **_kwargs: payload)
    result = updater.fetch_latest_release()
    assert result["status"] == "update_available"
    assert result["current_version"] == updater.__version__
    assert result["latest_version"] == "0.1.2"
    assert result["install_available"] is True
    assert result["release_notes"] == "Update notes"


def test_release_check_does_not_offer_same_or_older_version(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps(release(updater.__version__)).encode("utf-8")
    monkeypatch.setattr(updater, "_read_url", lambda _url, **_kwargs: payload)
    assert updater.fetch_latest_release()["status"] == "up_to_date"


def test_release_without_checksum_asset_cannot_be_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    data = release()
    data["assets"] = data["assets"][:1]
    payload = json.dumps(data).encode("utf-8")
    monkeypatch.setattr(updater, "_read_url", lambda _url, **_kwargs: payload)
    result = updater.fetch_latest_release()
    assert result["update_available"] is True
    assert result["install_available"] is False


def test_no_release_is_a_non_error_settings_state(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(_url: str, **_kwargs: object) -> bytes:
        raise updater.UpdateError("No stable Planline release has been published yet.")
    monkeypatch.setattr(updater, "_read_url", missing)
    result = updater.check_for_updates()
    assert result["status"] == "no_release"
    assert result["update_available"] is False


def test_checksum_parser_requires_the_exact_installer_filename() -> None:
    digest = "a" * 64
    assert updater._checksum_for_installer(f"{digest}  Planline-Setup.exe\n".encode()) == digest
    with pytest.raises(updater.UpdateError):
        updater._checksum_for_installer(f"{digest}  other.exe\n".encode())


def test_asset_url_is_limited_to_this_repository_release_downloads() -> None:
    assert updater._is_release_asset_url(
        "https://github.com/marlucool/floorplan-digitizer/releases/download/planline-v0.1.2/Planline-Setup.exe"
    )
    assert not updater._is_release_asset_url("https://example.com/Planline-Setup.exe")
    assert not updater._is_release_asset_url(
        "https://github.com/other/repository/releases/download/planline-v0.1.2/Planline-Setup.exe"
    )


def test_update_script_waits_for_app_and_uses_escaped_paths(tmp_path: Path) -> None:
    script = updater._build_update_script(
        tmp_path / "Planline-Setup.exe",
        r"C:\Users\Test O'Brien\AppData\Local\Programs\Planline",
        1234,
    )
    assert "$planlineParentPid = 1234" in script
    assert "Wait-Process -Id $planlineParentPid" in script
    assert "O''Brien" in script
    assert "--update-install" in script
