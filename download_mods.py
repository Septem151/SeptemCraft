#!/usr/bin/env python3

import json
import os
import shutil
from abc import ABC, abstractmethod
from enum import Enum, StrEnum, auto
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests


class ModType(StrEnum):
    GITHUB = auto()
    CURSEFORGE = auto()
    LOCAL = auto()
    UNKNOWN = auto()


class DownloadStatus(Enum):
    MISSING = auto()
    SKIPPED = auto()
    SUCCESS = auto()
    ERROR = auto()


class Dependency(ABC):
    @property
    @abstractmethod
    def headers(self) -> dict[str, Any]:
        return {"Accept": "application/json"}

    @property
    @abstractmethod
    def source(self) -> ModType:
        return ModType.UNKNOWN

    @property
    @abstractmethod
    def jar_name(self) -> str:
        pass

    @abstractmethod
    def download(self, local_path: Path) -> DownloadStatus:
        mod_path = local_path / self.jar_name
        if mod_path.exists():
            print(f"Skipping download of {self.source} mod, file exists at {mod_path}")
            return DownloadStatus.SKIPPED
        print(f"Downloading {self.source} mod to {mod_path}")
        return DownloadStatus.MISSING

    @abstractmethod
    def to_json(self) -> dict[str, Any]:
        return {"source": self.source, "data": {}}


class GitHubDependency(Dependency):
    api_key: str = os.getenv("GH_TOKEN", "")
    api_base_url: str = "https://api.github.com"

    def __init__(
        self, url: str, author: str, repo: str, asset: int, jar_name: str
    ) -> None:
        self.url = url
        self.author = author
        self.repo = repo
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
        asset_url = f"{self.api_base_url}/repos/{self.author}/{self.repo}/releases/assets/{self.asset}"
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


class DependencyFactory:
    @staticmethod
    def from_json(json_data: dict[str, Any]) -> Dependency | None:
        source: str = json_data.get("source", ModType.UNKNOWN)
        data: dict[str, Any] = json_data.get("data", {})
        if source == ModType.GITHUB:
            return GitHubDependency(
                data["url"],
                data["author"],
                data["repo"],
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
        return None


def main() -> None:
    download_directory = Path(__file__).resolve().parent / "mods"
    if not download_directory.exists():
        download_directory.mkdir(parents=True)
    mod_list: list[str] = json.load(
        (Path(__file__).resolve().parent / "modlist.json").open("r", encoding="UTF-8")
    )
    success_count = 0
    skip_count = 0
    error_count = 0
    for mod_json in mod_list:
        mod = DependencyFactory.from_json(mod_json)
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
