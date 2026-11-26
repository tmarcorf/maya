from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from livekit.agents import ToolError

from maya_agent.config import AppsSettings
from maya_agent.tools.apps import (
    AppIndex,
    AppLaunchError,
    DesktopAppLauncher,
    build_app_tools,
    build_find_apps_tool,
    open_app,
)


def _write_desktop(
    directory: Path,
    filename: str,
    *,
    name: str,
    generic: str = "",
    terminal: bool = False,
    no_display: bool = False,
    hidden: bool = False,
    localized_name: str = "",
    keywords: str = "",
) -> Path:
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={name}",
    ]
    if generic:
        lines.append(f"GenericName={generic}")
    if localized_name:
        lines.append(f"Name[pt_BR]={localized_name}")
    if keywords:
        lines.append(f"Keywords={keywords}")
    if terminal:
        lines.append("Terminal=true")
    if no_display:
        lines.append("NoDisplay=true")
    if hidden:
        lines.append("Hidden=true")
    path = directory / filename
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def app_index(tmp_path: Path) -> AppIndex:
    _write_desktop(
        tmp_path,
        "firefox.desktop",
        name="Firefox",
        generic="Web Browser",
        localized_name="Navegador Firefox",
        keywords="internet;web;",
    )
    _write_desktop(tmp_path, "spotify.desktop", name="Spotify", generic="Music Player")
    _write_desktop(tmp_path, "hidden.desktop", name="Hidden App", no_display=True)
    _write_desktop(tmp_path, "terminal.desktop", name="Terminal", terminal=True)
    return AppIndex.from_dirs([tmp_path])


def test_index_skips_hidden_and_no_display_entries(app_index: AppIndex) -> None:
    ids = {entry.desktop_id for entry in app_index.entries}

    assert "hidden.desktop" not in ids
    assert "terminal.desktop" in ids


@pytest.mark.parametrize(
    ("query", "desktop_id"),
    [
        ("Firefox", "firefox.desktop"),
        ("firefox", "firefox.desktop"),
        ("firefox.desktop", "firefox.desktop"),
        ("Navegador", "firefox.desktop"),
        ("web browser", "firefox.desktop"),
        ("fire", "firefox.desktop"),
        ("Spotify", "spotify.desktop"),
        ("music player", "spotify.desktop"),
        ("term", "terminal.desktop"),
    ],
)
def test_index_resolves_names_aliases_and_substrings(
    app_index: AppIndex, query: str, desktop_id: str
) -> None:
    assert app_index.resolve(query).desktop_id == desktop_id


def test_index_resolves_compact_aliases(tmp_path: Path) -> None:
    _write_desktop(
        tmp_path,
        "vscode.desktop",
        name="Visual Studio Code",
        generic="Code Editor",
        keywords="vscode;code;",
    )
    index = AppIndex.from_dirs([tmp_path])

    assert index.resolve("VS Code").desktop_id == "vscode.desktop"


def test_index_does_not_guess_unrelated_apps(app_index: AppIndex) -> None:
    with pytest.raises(ToolError, match="Não encontrei"):
        app_index.resolve("firefx")


def test_index_reports_ambiguous_names(tmp_path: Path) -> None:
    _write_desktop(tmp_path, "code.desktop", name="Code", generic="Editor")
    _write_desktop(tmp_path, "vscode.desktop", name="Code", generic="Editor")
    index = AppIndex.from_dirs([tmp_path])

    with pytest.raises(ToolError, match="mais de um app"):
        index.resolve("code")


def test_index_finds_translated_names_without_launching(tmp_path: Path) -> None:
    _write_desktop(tmp_path, "org.gnome.Calculator.desktop", name="Calculator")
    index = AppIndex.from_dirs([tmp_path])

    matches = index.find("calculadora")

    assert [entry.name for entry in matches][:1] == ["Calculator"]


def test_index_find_without_query_lists_visible_apps(app_index: AppIndex) -> None:
    names = [entry.name for entry in app_index.find("")]

    assert names == sorted(names)
    assert "Firefox" in names
    assert "Hidden App" not in names


@pytest.mark.asyncio
async def test_find_apps_tool_returns_source_of_truth(tmp_path: Path) -> None:
    _write_desktop(tmp_path, "org.gnome.Calculator.desktop", name="Calculator")
    index = AppIndex.from_dirs([tmp_path])
    tool = build_find_apps_tool(index)

    result = await tool(query="calculadora")

    assert result["query"] == "calculadora"
    assert result["apps"] == [
        {
            "name": "Calculator",
            "desktop_id": "org.gnome.Calculator.desktop",
            "generic_name": None,
        }
    ]


def test_build_app_tools_exposes_find_and_open(tmp_path: Path) -> None:
    _write_desktop(tmp_path, "firefox.desktop", name="Firefox")
    index = AppIndex.from_dirs([tmp_path])
    settings = AppsSettings(enabled=True, launch_timeout_seconds=5)

    class FakeLauncher:
        def launch(self, entry) -> None:
            pass

    tools = build_app_tools(settings, index=index, launcher=FakeLauncher())

    assert [tool.info.name for tool in tools] == ["find_apps", "open_app"]


def test_index_rejects_unknown_app(app_index: AppIndex) -> None:
    with pytest.raises(ToolError, match="Não encontrei"):
        app_index.resolve("Photoshop")


def test_index_rejects_paths(app_index: AppIndex) -> None:
    with pytest.raises(ToolError, match="não um caminho"):
        app_index.resolve("/usr/bin/firefox")


class FakeLauncher:
    def __init__(self, error: Exception | None = None) -> None:
        self.entries = []
        self.error = error

    def launch(self, entry) -> None:
        self.entries.append(entry)
        if self.error is not None:
            raise self.error


@pytest.mark.asyncio
async def test_open_app_resolves_and_launches(app_index: AppIndex) -> None:
    launcher = FakeLauncher()

    result = await open_app(app_index, launcher, "navegador")

    assert result == {
        "app": "Firefox",
        "desktop_id": "firefox.desktop",
        "launched": True,
    }
    assert [entry.desktop_id for entry in launcher.entries] == ["firefox.desktop"]


@pytest.mark.asyncio
async def test_open_app_wraps_launch_failure(app_index: AppIndex) -> None:
    launcher = FakeLauncher(error=AppLaunchError("boom"))

    with pytest.raises(ToolError, match="Não consegui abrir"):
        await open_app(app_index, launcher, "Spotify")


def test_launcher_prefers_gio_and_uses_exact_desktop_path(tmp_path: Path) -> None:
    path = _write_desktop(tmp_path, "firefox.desktop", name="Firefox")
    entry = AppIndex.from_dirs([tmp_path]).resolve("firefox")
    commands: list[list[str]] = []

    def runner(command: list[str], timeout: float) -> None:
        commands.append(command)

    launcher = DesktopAppLauncher(
        timeout_seconds=5,
        runner=runner,
        which=lambda name: f"/usr/bin/{name}",
    )

    launcher.launch(entry)

    assert commands == [["gio", "launch", str(path)]]


def test_launcher_falls_back_to_gtk_launch(tmp_path: Path) -> None:
    _write_desktop(tmp_path, "firefox.desktop", name="Firefox")
    entry = AppIndex.from_dirs([tmp_path]).resolve("firefox")
    commands: list[list[str]] = []

    def which(name: str) -> str | None:
        return "/usr/bin/gtk-launch" if name == "gtk-launch" else None

    def runner(command: list[str], timeout: float) -> None:
        commands.append(command)

    launcher = DesktopAppLauncher(
        timeout_seconds=5,
        runner=runner,
        which=which,
    )

    launcher.launch(entry)

    assert commands == [["gtk-launch", "firefox"]]


def test_launcher_reports_failure_when_both_commands_fail(tmp_path: Path) -> None:
    _write_desktop(tmp_path, "firefox.desktop", name="Firefox")
    entry = AppIndex.from_dirs([tmp_path]).resolve("firefox")

    def runner(command: list[str], timeout: float) -> None:
        raise AppLaunchError("failed")

    launcher = DesktopAppLauncher(
        timeout_seconds=5,
        runner=runner,
        which=lambda name: f"/usr/bin/{name}",
    )

    with pytest.raises(AppLaunchError, match="gio"):
        launcher.launch(entry)


def test_default_runner_does_not_capture_child_output(monkeypatch, tmp_path: Path) -> None:
    _write_desktop(tmp_path, "firefox.desktop", name="Firefox")
    entry = AppIndex.from_dirs([tmp_path]).resolve("firefox")
    seen: dict[str, object] = {}

    class FakeProcess:
        def __init__(self, command, **kwargs) -> None:
            seen["command"] = command
            seen.update(kwargs)

        def wait(self, timeout: float) -> int:
            return 0

    monkeypatch.setattr("maya_agent.tools.apps.subprocess.Popen", FakeProcess)
    launcher = DesktopAppLauncher(
        timeout_seconds=5,
        which=lambda name: f"/usr/bin/{name}",
    )

    launcher.launch(entry)

    assert seen["stdin"] is subprocess.DEVNULL
    assert seen["stdout"] is subprocess.DEVNULL
    assert seen["stderr"] is subprocess.DEVNULL
    assert seen["start_new_session"] is True
