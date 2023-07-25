#!/usr/bin/env python3

"""
Downloads mods from CurseForge and GitHub using a special json schema.
"""
import json
import os
import shutil
from abc import ABC, abstractmethod
from enum import Enum, StrEnum, auto
from pathlib import Path
from typing import Any

import requests


class ModType(StrEnum):
    """Enum for valid "source" parameters in the JSON schema"""

    GITHUB = auto()
    CURSEFORGE = auto()
    LOCAL = auto()
    UNKNOWN = auto()


class DownloadStatus(Enum):
    """Enum containing statuses for a dependency's download"""

    MISSING = auto()
    SKIPPED = auto()
    SUCCESS = auto()
    ERROR = auto()


class Dependency(ABC):
    """Base Dependency interface"""

    @property
    @abstractmethod
    def headers(self) -> dict[str, Any]:
        """
        Default headers for HTTP requests
        MUST BE IMPLEMENTED BY CLASSES
        """
        return {"Accept": "application/json"}

    @property
    @abstractmethod
    def source(self) -> ModType:
        """
        Source value for dependency
        MUST BE IMPLEMENTED BY CLASSES
        """
        return ModType.UNKNOWN

    @property
    @abstractmethod
    def jar_name(self) -> str:
        """
        Jar name for dependency
        MUST BE IMPLEMENTED BY CLASSES
        """

    @abstractmethod
    def download(self, local_path: Path) -> DownloadStatus:
        """
        Default check to see if mod already exists.
        Downloads the file to local_path.
        MUST BE IMPLEMENTED BY CLASS
        """
        mod_path = local_path / self.jar_name
        if mod_path.exists():
            print(f"Skipping download of {self.source} mod, file exists at {mod_path}")
            return DownloadStatus.SKIPPED
        print(f"Downloading {self.source} mod to {mod_path}")
        return DownloadStatus.MISSING

    @abstractmethod
    def to_json(self) -> dict[str, Any]:
        """
        Returns a JSON representation of the dependency.
        MUST BE IMPLEMENTED BY CLASS
        """
        return {"source": self.source, "data": {}}


class GitHubDependency(Dependency):
    """
    JSON Schema:
    {
        "source": "github",
        "data": {
            "url": string,
            "author": string,
            "repo": string,
            "asset": integer,
            "jar_name": string
        }
    }
    """

    api_key: str = os.getenv("GH_TOKEN", "")
    api_base_url: str = "https://api.github.com"

    def __init__(self, url: str, repo_info: str, asset: int, jar_name: str) -> None:
        self.url = url
        self.author, self.repo = repo_info.split("/", 1)
        self.asset = asset
        self._jar_name = jar_name

    @property
    def headers(self) -> dict[str, Any]:
        return super().headers | {"Authorization": f"Bearer {self.api_key}"}

    @property
    def source(self) -> ModType:
        return ModType.GITHUB

    @property
    def jar_name(self) -> str:
        return self._jar_name

    def download(self, local_path: Path) -> DownloadStatus:
        status = super().download(local_path)
        if status == DownloadStatus.SKIPPED:
            return status
        mod_path = local_path / self._jar_name
        asset_url = (
            f"{self.api_base_url}/repos/{self.author}/{self.repo}"
            "/releases/assets/{self.asset}"
        )
        asset_request = requests.get(
            asset_url,
            timeout=5,
            headers=self.headers | {"Accept": "application/octet-stream"},
        )
        if asset_request.status_code != 200:
            print(f"Download of {self._jar_name} failed! ({asset_url})")
            return DownloadStatus.ERROR
        with mod_path.open("wb") as mod_file:
            mod_file.write(asset_request.content)
        return DownloadStatus.SUCCESS

    def to_json(self) -> dict[str, Any]:
        return super().to_json() | {
            "data": {
                "url": self.url,
                "author": self.author,
                "repo": self.repo,
                "asset": self.asset,
                "jar_name": self._jar_name,
            }
        }


class CurseForgeDependency(Dependency):
    """
    JSON schema:
    {
        "source": "curseforge",
        "data": {
            "url": "string",
            "project": integer,
            "file": integer,
            "jar_name": string
        }
    }
    """

    api_key: str = os.getenv("CURSEFORGE_TOKEN", "")
    api_base_url: str = "https://api.curseforge.com/v1"

    def __init__(self, url: str, project: int, file: int, jar_name: str) -> None:
        self.url = url
        self.project = project
        self.file = file
        self._jar_name = jar_name

    @property
    def headers(self) -> dict[str, Any]:
        return super().headers | {"x-api-key": self.api_key}

    @property
    def source(self) -> ModType:
        return ModType.CURSEFORGE

    @property
    def jar_name(self) -> str:
        return self._jar_name

    def download(self, local_path: Path) -> DownloadStatus:
        status = super().download(local_path)
        if status == DownloadStatus.SKIPPED:
            return status
        mod_path = local_path / self._jar_name
        asset_url = (
            f"{self.api_base_url}/mods/{self.project}/files/{self.file}/download-url"
        )
        asset_request = requests.get(
            asset_url,
            timeout=5,
            headers=self.headers,
        )
        if asset_request.status_code != 200:
            print(f"Download of {self.project} failed! ({asset_url})")
            return DownloadStatus.ERROR
        asset_url = asset_request.json()["data"]
        asset_request = requests.get(
            asset_url,
            timeout=5,
            headers=self.headers | {"Accept": "application/java-archive"},
        )
        if asset_request.status_code != 200:
            print(f"Download of {self.project} failed! ({asset_url})")
            return DownloadStatus.ERROR
        with mod_path.open("wb") as mod_file:
            mod_file.write(asset_request.content)
        return DownloadStatus.SUCCESS

    def to_json(self) -> dict[str, Any]:
        return super().to_json() | {
            "data": {
                "url": self.url,
                "project": self.project,
                "file": self.file,
                "jar_name": self.jar_name,
            }
        }


class LocalDependency(Dependency):
    """
    JSON Schema:
    {
        "source": "local",
        "data": {
            "path": string,
            "jar_name": string
        }
    }
    """

    def __init__(self, path: str, jar_name: str) -> None:
        self.path = path
        self._jar_name = jar_name

    @property
    def headers(self) -> dict[str, Any]:
        return super().headers

    @property
    def source(self) -> ModType:
        return ModType.LOCAL

    @property
    def jar_name(self) -> str:
        return self._jar_name

    def download(self, local_path: Path) -> DownloadStatus:
        status = super().download(local_path)
        if status == DownloadStatus.SKIPPED:
            return status
        from_path = (Path(__file__).resolve().parent / self.path).absolute()
        to_path = (local_path / self.jar_name).absolute()
        shutil.copy(from_path, to_path)
        return DownloadStatus.SUCCESS

    def to_json(self) -> dict[str, Any]:
        return super().to_json() | {
            "data": {
                "path": self.path,
                "jar_name": self.jar_name,
            }
        }


def dependency_from_json(json_data: dict[str, Any]) -> Dependency:
    """
    Factory method to create dependency objects from JSON schema
    """
    source: str = json_data.get("source", ModType.UNKNOWN)
    data: dict[str, Any] = json_data.get("data", {})
    if source == ModType.GITHUB:
        return GitHubDependency(
            data["url"],
            data["repo_name"],
            data["asset"],
            data["jar_name"],
        )
    if source == ModType.CURSEFORGE:
        return CurseForgeDependency(
            data["url"],
            data["project"],
            data["file"],
            data["jar_name"],
        )
    if source == ModType.LOCAL:
        return LocalDependency(data["path"], data["jar_name"])
    raise RuntimeError(f"unknown source for mod: {source}")


def main() -> None:
    """
    Main program entrypoint, loops through each mod
    in the modlist.json file and downloads each dependency to the
    mods/ folder as needed.
    """
    download_directory = Path(__file__).resolve().parent / "mods"
    if not download_directory.exists():
        download_directory.mkdir(parents=True)
    mod_list: list[dict[str, Any]] = json.load(
        (Path(__file__).resolve().parent / "modlist.json").open("r", encoding="UTF-8")
    )
    success_count = 0
    skip_count = 0
    error_count = 0
    for mod_json in mod_list:
        mod = dependency_from_json(mod_json)
        result = mod.download(download_directory)
        if result == DownloadStatus.SUCCESS:
            success_count += 1
        elif result == DownloadStatus.SKIPPED:
            skip_count += 1
        elif result == DownloadStatus.ERROR:
            error_count += 1
    print(f"Mods Installed: {success_count}")
    print(f"Mods Skipped: {skip_count}")
    print(f"Errors: {error_count}")


if __name__ == "__main__":
    main()
