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
    def download(self, mod_dir: Path) -> DownloadStatus:
        """
        Default check to see if mod already exists.
        Downloads the file to local_path.
        MUST BE IMPLEMENTED BY CLASS
        """
        mod_path = mod_dir / self.jar_name
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


class URLDependency(Dependency):
    @property
    @abstractmethod
    def url(self) -> str:
        """
        URL for dependency
        MUST BE IMPLEMENTED BY CLASSES
        """


class GitHubDependency(URLDependency):
    """
    {
        "source": "github",
        "data": {
            "url": string,
            "tag": string,
            "filename": string
        }
    }
    """

    api_key: str = os.getenv("GH_TOKEN", "")
    api_base_url: str = "https://api.github.com"

    def __init__(self, url: str, tag: str, filename: str) -> None:
        self._url = url
        self.tag = tag
        self.filename = filename
        self.owner, self.repo = self.url.removesuffix(".git").rsplit("/", 2)[-2:]

    @property
    def url(self) -> str:
        return self._url

    @property
    def headers(self) -> dict[str, Any]:
        return super().headers | {"Authorization": f"Bearer {self.api_key}"}

    @property
    def source(self) -> ModType:
        return ModType.GITHUB

    @property
    def jar_name(self) -> str:
        return self.filename

    def download(self, mod_dir: Path) -> DownloadStatus:
        status = super().download(mod_dir)
        if status == DownloadStatus.SKIPPED:
            return status
        mod_path = mod_dir / self.filename
        asset_url = f"{self.api_base_url}/repos/{self.owner}/{self.repo}/releases/tags/{self.tag}"
        asset_request = requests.get(
            asset_url,
            timeout=5,
            headers=self.headers | {"Accept": "application/vnd.github+json"},
        )
        if asset_request.status_code != 200:
            print(f"Download of {self.filename} failed! ({asset_url})")
            return DownloadStatus.ERROR
        assets: list[dict[str, Any]] = asset_request.json()["assets"]
        for asset in assets:
            partname: str = asset["name"]
            if partname != self.filename:
                continue
            asset_url = (
                f"{self.api_base_url}/repos/{self.owner}/{self.repo}"
                f"/releases/assets/{asset['id']}"
            )
            asset_request = requests.get(
                asset_url,
                headers=self.headers | {"Accept": "application/octet-stream"},
                timeout=5,
            )
            if asset_request.status_code != 200:
                print(f"Download of {self.filename} failed! ({asset_url})")
                return DownloadStatus.ERROR
            with mod_path.open("wb") as mod_file:
                mod_file.write(asset_request.content)
        return DownloadStatus.SUCCESS

    def to_json(self) -> dict[str, Any]:
        return super().to_json() | {
            "data": {
                "url": self.url,
                "tag": self.tag,
                "filename": self.filename,
            }
        }


class CurseForgeDependency(URLDependency):
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
        self._url = url
        self.project = project
        self.file = file
        self._jar_name = jar_name

    @property
    def url(self) -> str:
        return self._url

    @property
    def headers(self) -> dict[str, Any]:
        return super().headers | {"x-api-key": self.api_key}

    @property
    def source(self) -> ModType:
        return ModType.CURSEFORGE

    @property
    def jar_name(self) -> str:
        return self._jar_name

    def download(self, mod_dir: Path) -> DownloadStatus:
        status = super().download(mod_dir)
        if status == DownloadStatus.SKIPPED:
            return status
        mod_path = mod_dir / self._jar_name
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

    def download(self, mod_dir: Path) -> DownloadStatus:
        status = super().download(mod_dir)
        if status == DownloadStatus.SKIPPED:
            return status
        from_path = (Path(__file__).resolve().parent / self.path).absolute()
        to_path = (mod_dir / self.jar_name).absolute()
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
            data["tag"],
            data["filename"],
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


def generate_dependencies_list(filepath: Path, mods: list[Dependency]) -> bool:
    deplist: str = "Dependencies:\n\n"
    for mod in mods:
        if isinstance(mod, URLDependency):
            deplist += f"- [{mod.jar_name}]({mod.url})\n"
    with filepath.open("w", encoding="UTF-8") as file:
        file.write(deplist)
    return True


def main() -> None:
    """
    Main program entrypoint, loops through each mod
    in the modlist.json file and downloads each dependency to the
    mods/ folder as needed.
    """
    modlist_path = Path(__file__).resolve().parent / "modlist.json"
    deplist_path = Path(__file__).resolve().parent / "DEPENDENCIES.md"
    download_directory = Path(__file__).resolve().parent / "mods"
    if not download_directory.exists():
        download_directory.mkdir(parents=True, exist_ok=True)
    (download_directory / "1.7.10").mkdir(exist_ok=True)
    mod_list: list[Dependency] = [
        dependency_from_json(mod)
        for mod in json.load((modlist_path).open("r", encoding="UTF-8"))
    ]
    success_count = 0
    skip_count = 0
    error_count = 0
    for mod in mod_list:
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
    if os.getenv("CI") is None and generate_dependencies_list(deplist_path, mod_list):
        print(f"Dependency list generated at {deplist_path}")


if __name__ == "__main__":
    main()
