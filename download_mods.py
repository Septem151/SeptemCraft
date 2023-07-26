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

    @property
    def version(self) -> str:
        """
        Extracts the version string from the jar name
        """
        mod_str = self.jar_name.removesuffix(".jar")
        mod_arr = mod_str.split("-", 1)
        sep_is_space = len(mod_arr) < 2
        if sep_is_space:
            mod_arr = mod_arr[0].rsplit(" ", 1)
            mod_str = "".join(mod_arr[1:])
        mod_str = "".join(mod_arr[1:])
        if sep_is_space:
            return mod_str
        invalid_prefixes = (
            "all-",
            "1.7.10",
            "-",
            "/",
            " ",
            "V1.7.10",
            "v1.7.10",
            "[1.7.10]",
            "mc1.7.10",
            "MC1.7.10",
        )
        while mod_str.startswith(invalid_prefixes):
            for invalid_prefix in invalid_prefixes:
                mod_str = mod_str.removeprefix(invalid_prefix)
        return mod_str

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
    """
    Dependency Interface for dependencies that have a publicly accessible URL
    """

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


class TableBuilder:
    """
    Utility builder class to build markdown tables
    """

    def __init__(self) -> None:
        self._headers: list[str] = []
        self._rows: list[list[str]] = []

    def add_header(self, header: str) -> "TableBuilder":
        """
        Adds a header to the table if it doesn't already exist
        """
        if "header" not in self._headers:
            self._headers.append(header)
        return self

    def add_headers(self, headers: list[str]) -> "TableBuilder":
        """
        Add multiple headers to the table if they don't already exist
        """
        for header in headers:
            self.add_header(header)
        return self

    def add_row(self, row: list[str]) -> "TableBuilder":
        """
        Add a row to the table
        """
        self._rows.append(row)
        return self

    def sort_rows(self, header: str) -> "TableBuilder":
        """
        Sorts the rows in a table based on a given header
        """
        if header not in self._headers:
            return self
        index = self._headers.index(header)
        self._rows.sort(key=lambda row: row[index].lower())
        return self

    def build(self) -> str:
        """
        Builds the resulting table. Rows with more columns than headers
        are truncated
        """
        result = ""
        for header_column, header in enumerate(self._headers):
            first = header_column == 0
            last = header_column == len(self._headers) - 1
            space_before = "" if first else " "
            space_after = "" if last else " |"
            newline = "\n" if last else ""
            result = f"{result}{space_before}{header}{space_after}{newline}"
        result = result + "".join(["---|"] * len(self._headers))[:-1] + "\n"
        for row in self._rows:
            for value_index, value in enumerate(row):
                if value_index >= len(self._headers):
                    break
                first = value_index == 0
                last = value_index == len(self._headers) - 1
                space_before = "" if first else " "
                space_after = "" if last else " |"
                newline = "\n" if last else ""
                result = f"{result}{space_before}{value}{space_after}{newline}"
        return result


def generate_dependencies_list(filepath: Path, mods: list[Dependency]) -> bool:
    """
    Generates a table of dependencies and writes them to a file
    """
    tablebuilder = TableBuilder().add_headers(
        ["\\#", "Mod Name", "Version", "Link To Mod"]
    )
    mods.sort(
        key=lambda mod: mod.url.rsplit("/", 1)[1].lower()
        if isinstance(mod, URLDependency)
        else mod.jar_name.removesuffix(".jar").lower()
    )
    for mod_index, mod in enumerate(mods):
        if isinstance(mod, URLDependency):
            tablebuilder.add_row(
                [
                    str(mod_index + 1),
                    mod.url.rsplit("/", 1)[1],
                    mod.version,
                    f"[{mod.source.upper()}]({mod.url})",
                ]
            )
        elif isinstance(mod, LocalDependency):
            tablebuilder.add_row(
                [
                    str(mod_index + 1),
                    mod.jar_name.removesuffix(".jar"),
                    mod.version,
                    f"[{mod.source.upper()}]({mod.path})",
                ]
            )
    with filepath.open("w", encoding="UTF-8") as file:
        file.write(f"Dependencies:\n\n{tablebuilder.build()}")
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
    mod_list.sort(key=lambda mod: mod.jar_name.lower())
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
