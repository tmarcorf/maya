from __future__ import annotations

import asyncio
import configparser
import difflib
import logging
import os
import re
import shutil
import subprocess
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from livekit.agents import ToolError, function_tool, llm

from ..config import AppsSettings

logger = logging.getLogger("maya.apps")


class AppLaunchError(Exception):
    pass


def _normalize(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.casefold()).strip()


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class DesktopEntry:
    desktop_id: str
    path: Path
    name: str
    generic_name: str
    terminal: bool
    search_terms: tuple[str, ...]


class AppLauncher(Protocol):
    def launch(self, entry: DesktopEntry) -> None: ...


CommandRunner = Callable[[list[str], float], None]
WhichFn = Callable[[str], str | None]


def _default_runner(command: list[str], timeout_seconds: float) -> None:
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise AppLaunchError(str(exc)) from exc

    try:
        returncode = process.wait(timeout=min(timeout_seconds, 1.0))
    except subprocess.TimeoutExpired:
        return

    if returncode != 0:
        raise AppLaunchError(f"launch exited with {returncode}")


class DesktopAppLauncher:
    def __init__(
        self,
        *,
        timeout_seconds: float,
        runner: CommandRunner | None = None,
        which: WhichFn = shutil.which,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._runner = runner or _default_runner
        self._which = which

    def launch(self, entry: DesktopEntry) -> None:
        errors: list[str] = []

        if self._which("gio"):
            try:
                self._runner(
                    ["gio", "launch", str(entry.path)],
                    self._timeout_seconds,
                )
                return
            except AppLaunchError as exc:
                errors.append(f"gio: {exc}")

        if self._which("gtk-launch"):
            try:
                self._runner(
                    ["gtk-launch", entry.desktop_id.removesuffix(".desktop")],
                    self._timeout_seconds,
                )
                return
            except AppLaunchError as exc:
                errors.append(f"gtk-launch: {exc}")

        detail = "; ".join(errors) or "neither gio nor gtk-launch is available"
        raise AppLaunchError(detail)


def _get(parser: configparser.RawConfigParser, key: str) -> str:
    try:
        return parser.get("Desktop Entry", key, fallback="") or ""
    except configparser.Error:
        return ""


def _parse_desktop(path: Path) -> DesktopEntry | None:
    parser = configparser.RawConfigParser(strict=False, interpolation=None)
    try:
        loaded = parser.read(path, encoding="utf-8")
    except (OSError, UnicodeDecodeError, configparser.Error):
        return None

    if not loaded or not parser.has_section("Desktop Entry"):
        return None

    entry_type = _get(parser, "Type").strip() or "Application"
    if entry_type != "Application":
        return None
    if _as_bool(_get(parser, "NoDisplay")) or _as_bool(_get(parser, "Hidden")):
        return None

    name = " ".join(_get(parser, "Name").split()).strip()
    if not name:
        return None

    generic_name = " ".join(_get(parser, "GenericName").split()).strip()
    localized = [
        name,
        generic_name,
        _get(parser, "Name[pt_BR]"),
        _get(parser, "Name[pt]"),
        _get(parser, "GenericName[pt_BR]"),
        _get(parser, "GenericName[pt]"),
        _get(parser, "Name[en]"),
        _get(parser, "GenericName[en]"),
    ]
    keywords: list[str] = []
    for raw in (_get(parser, "Keywords"), _get(parser, "Keywords[pt_BR]")):
        keywords.extend(part for part in raw.split(";") if part.strip())

    terms = {_normalize(value) for value in [*localized, path.name, path.stem, *keywords]}
    terms.discard("")

    return DesktopEntry(
        desktop_id=path.name,
        path=path,
        name=name,
        generic_name=generic_name,
        terminal=_as_bool(_get(parser, "Terminal")),
        search_terms=tuple(sorted(terms)),
    )


class AppIndex:
    def __init__(self, entries: Iterable[DesktopEntry]) -> None:
        self._entries = tuple(entries)

    @classmethod
    def from_dirs(cls, dirs: Iterable[Path]) -> AppIndex:
        entries: list[DesktopEntry] = []
        seen: set[str] = set()
        for directory in dirs:
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.desktop")):
                if path.name in seen:
                    continue
                entry = _parse_desktop(path)
                if entry is None:
                    continue
                seen.add(entry.desktop_id)
                entries.append(entry)
        return cls(entries)

    @classmethod
    def from_default_dirs(cls) -> AppIndex:
        data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
        dirs = [data_home / "applications"]
        dirs.extend(Path(raw) / "applications" for raw in data_dirs.split(":") if raw.strip())
        dirs.extend(
            [
                Path.home() / ".local/share/flatpak/exports/share/applications",
                Path("/var/lib/flatpak/exports/share/applications"),
            ]
        )

        unique_dirs: list[Path] = []
        seen_dirs: set[Path] = set()
        for directory in dirs:
            if directory not in seen_dirs:
                seen_dirs.add(directory)
                unique_dirs.append(directory)
        return cls.from_dirs(unique_dirs)

    @property
    def entries(self) -> tuple[DesktopEntry, ...]:
        return self._entries

    def resolve(self, query: str) -> DesktopEntry:
        cleaned = " ".join(query.split()).strip()
        if not cleaned:
            raise ToolError("Diga qual programa você quer abrir.")
        if "/" in cleaned or "\\" in cleaned:
            raise ToolError("Use o nome do programa, não um caminho.")

        normalized = _normalize(cleaned)
        if not normalized:
            raise ToolError("Não encontrei esse programa.")

        compact = normalized.replace(" ", "")

        exact = [
            entry
            for entry in self._entries
            if normalized in entry.search_terms
            or any(compact == term.replace(" ", "") for term in entry.search_terms)
        ]
        if match := self._unique(exact):
            return match

        if len(normalized) >= 2:
            partial = [
                entry
                for entry in self._entries
                if any(
                    normalized in term or compact in term.replace(" ", "")
                    for term in entry.search_terms
                )
            ]
            if match := self._unique(partial):
                return match

        raise ToolError("Não encontrei esse programa. Use find_apps para procurar o nome exato.")

    def find(self, query: str, limit: int = 10) -> list[DesktopEntry]:
        cleaned = " ".join(query.split()).strip()
        if not cleaned:
            return sorted(self._entries, key=lambda entry: entry.name)

        normalized = _normalize(cleaned)
        if not normalized:
            return []
        compact = normalized.replace(" ", "")

        scored: list[tuple[float, DesktopEntry]] = []
        for entry in self._entries:
            best = 0.0
            for term in entry.search_terms:
                if normalized == term or compact == term.replace(" ", ""):
                    best = max(best, 100.0)
                elif normalized in term or compact in term.replace(" ", ""):
                    best = max(best, 80.0)
                else:
                    best = max(
                        best,
                        difflib.SequenceMatcher(None, normalized, term).ratio() * 60,
                    )
            if best >= 36:
                scored.append((best, entry))

        scored.sort(key=lambda item: (-item[0], item[1].name))
        results: list[DesktopEntry] = []
        seen: set[str] = set()
        for _, entry in scored:
            if entry.desktop_id in seen:
                continue
            seen.add(entry.desktop_id)
            results.append(entry)
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _unique(entries: list[DesktopEntry]) -> DesktopEntry | None:
        unique: list[DesktopEntry] = []
        seen: set[str] = set()
        for entry in entries:
            if entry.desktop_id in seen:
                continue
            seen.add(entry.desktop_id)
            unique.append(entry)

        if len(unique) == 1:
            return unique[0]
        if len(unique) > 1:
            options = ", ".join(f"{entry.name} ({entry.desktop_id})" for entry in unique[:5])
            raise ToolError(f"Encontrei mais de um app: {options}. Diga qual.")
        return None


async def open_app(index: AppIndex, launcher: AppLauncher, app_name: str) -> dict[str, Any]:
    entry = index.resolve(app_name)
    try:
        await asyncio.to_thread(launcher.launch, entry)
    except AppLaunchError as exc:
        logger.warning("failed to launch %s: %s", entry.desktop_id, exc)
        raise ToolError("Não consegui abrir esse programa agora.") from exc

    logger.info("opened app desktop_id=%s", entry.desktop_id)
    return {
        "app": entry.name,
        "desktop_id": entry.desktop_id,
        "launched": True,
    }


def build_find_apps_tool(index: AppIndex) -> llm.Tool:
    @function_tool(name="find_apps")
    async def find_apps(query: str = "") -> dict[str, Any]:
        """Search the installed applications available on this computer.

        Use this when the user's app name may be translated or vague, or when
        open_app cannot find the name. Then call open_app with the exact name or
        desktop_id returned here. An empty query lists a sample of installed apps.
        """
        matches = index.find(query, limit=10)
        return {
            "query": query,
            "apps": [
                {
                    "name": entry.name,
                    "desktop_id": entry.desktop_id,
                    "generic_name": entry.generic_name or None,
                }
                for entry in matches
            ],
        }

    return find_apps


def build_app_tools(
    settings: AppsSettings,
    index: AppIndex | None = None,
    launcher: AppLauncher | None = None,
) -> list[llm.Tool]:
    app_index = index or AppIndex.from_default_dirs()
    return [
        build_find_apps_tool(app_index),
        build_open_app_tool(settings, index=app_index, launcher=launcher),
    ]


def build_open_app_tool(
    settings: AppsSettings,
    index: AppIndex | None = None,
    launcher: AppLauncher | None = None,
) -> llm.Tool:
    app_index = index or AppIndex.from_default_dirs()
    app_launcher = launcher or DesktopAppLauncher(timeout_seconds=settings.launch_timeout_seconds)

    @function_tool(name="open_app")
    async def open_app_tool(app: str) -> dict[str, Any]:
        """Open an installed application by name.

        Use only when the user explicitly asks to open or launch a program, such
        as "open Firefox" or "abre o Spotify". Pass only the application name;
        never pass command-line flags, paths or URLs. If the name is not found,
        use find_apps first.
        """
        return await open_app(app_index, app_launcher, app)

    return open_app_tool
