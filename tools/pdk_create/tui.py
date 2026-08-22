"""Textual TUI for interactive PDK plugin scaffolding."""

from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Footer, Header, Input, Label, Select

from .generate import PluginSpec, Preset
from .paths import validate_plugin_parent
from .session import InteractiveOutcome
from .validators import validate_functions, validate_plugin_id


class OverwriteModal(ModalScreen[bool]):
    """Dismiss with True if the user confirms overwriting a non-empty directory."""

    def compose(self) -> ComposeResult:
        yield Label(
            "Plugin directory already exists and is not empty.\nOverwrite everything in it?",
        )
        with Horizontal(classes="dialog_buttons"):
            yield Button("Yes", variant="error", id="yes")
            yield Button("No", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yes":
            self.dismiss(True)
        else:
            self.dismiss(False)


class PdkCreateApp(App[InteractiveOutcome | None]):
    """Collect plugin root path, metadata, optional post-install, then scaffold."""

    TITLE = "PyDeck PDK plugin creator"
    CSS = """
    PdkCreateApp {
        layout: vertical;
        height: 100%;
    }
    #middle {
        layout: vertical;
        height: 1fr;
        min-height: 10;
        width: 100%;
    }
    VerticalScroll {
        height: 1fr;
        min-height: 8;
        width: 100%;
        border: tall $primary;
        padding: 0 1;
    }
    Label {
        margin-top: 1;
    }
    Input {
        width: 100%;
    }
    Select {
        width: 100%;
    }
    Checkbox {
        margin-top: 1;
    }
    #create {
        margin: 1;
        width: 100%;
        height: auto;
    }
    Horizontal.dialog_buttons {
        layout: horizontal;
        height: auto;
        margin-top: 1;
    }
    Horizontal.dialog_buttons Button {
        margin-right: 2;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(
        self,
        *,
        pre_resolved_plugin_parent: Path | None,
        detected_candidate: Path | None,
    ) -> None:
        super().__init__()
        self._pre = pre_resolved_plugin_parent
        self._detected = detected_candidate

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="middle"):
            with VerticalScroll():
                yield Label("Plugin root (directory that contains RDNN plugin folders)")
                initial_root = ""
                if self._pre is not None:
                    initial_root = str(self._pre)
                elif self._detected is not None:
                    initial_root = str(self._detected)
                yield Input(initial_root, placeholder="e.g. ~/.local/share/pydeck/plugin", id="plugins_parent")
                yield Label("RDNN plugin id (install folder name)")
                yield Input("no.pydeck.my_plugin", id="plugin_id")
                yield Label("Display name")
                yield Input("My Plugin", id="name")
                yield Label("Description")
                yield Input("PDK demo plugin", id="description")
                yield Label("Author")
                yield Input("You", id="author")
                yield Label("Version")
                yield Input("0.1.0", id="version")
                yield Label("Function ids (comma-separated, snake_case)")
                yield Input("main", id="functions")
                yield Label("Preset")
                yield Select(
                    [("static", "static"), ("counter", "counter")],
                    value="static",
                    id="preset",
                    allow_blank=False,
                )
                yield Label("min_pydeck_version")
                yield Input("1.1.0", id="min_pydeck")
                yield Checkbox(
                    "Include post-install script (scripts/setup.sh + manifest post_install_script)",
                    id="post_install",
                )
            yield Button("Create plugin", variant="primary", id="create")
        yield Footer()

    def action_cancel(self) -> None:
        self.exit(None, return_code=1)

    @on(Button.Pressed, "#create")
    async def on_create_pressed(self) -> None:
        plugins_raw = self.query_one("#plugins_parent", Input).value.strip()
        try:
            plugins_dir = validate_plugin_parent(Path(plugins_raw))
        except FileNotFoundError as e:
            self.notify(str(e), severity="error", timeout=12)
            return

        pid_raw = self.query_one("#plugin_id", Input).value.strip() or "no.pydeck.my_plugin"
        try:
            slug = validate_plugin_id(pid_raw)
        except ValueError as e:
            self.notify(str(e), severity="error", timeout=12)
            return

        name = self.query_one("#name", Input).value.strip() or "My Plugin"
        description = self.query_one("#description", Input).value.strip() or "PDK demo plugin"
        author = self.query_one("#author", Input).value.strip() or "You"
        version = self.query_one("#version", Input).value.strip() or "0.1.0"
        functions_raw = self.query_one("#functions", Input).value.strip() or "main"
        try:
            functions = validate_functions(functions_raw)
        except ValueError as e:
            self.notify(str(e), severity="error", timeout=12)
            return

        preset_w = self.query_one("#preset", Select)
        raw_preset = preset_w.value
        preset_val: Preset = "counter" if raw_preset == "counter" else "static"

        min_pv = self.query_one("#min_pydeck", Input).value.strip() or "1.1.0"
        post_install = self.query_one("#post_install", Checkbox).value

        spec = PluginSpec(
            slug=slug,
            name=name,
            description=description,
            author=author,
            version=version,
            functions=functions,
            preset=preset_val,
            min_pydeck_version=min_pv,
            include_post_install_script=post_install,
        )

        plugin_root = plugins_dir / spec.slug
        force = False
        if plugin_root.exists() and any(plugin_root.iterdir()):
            confirmed = await self.push_screen_wait(OverwriteModal())
            if not confirmed:
                self.notify("Aborted.", severity="information")
                return
            force = True

        self.exit(
            InteractiveOutcome(plugins_dir=plugins_dir, spec=spec, force=force),
            return_code=0,
        )


def run_interactive_tui(
    *,
    pre_resolved_plugin_parent: Path | None,
    detected_candidate: Path | None,
) -> InteractiveOutcome | None:
    """Run the Textual wizard; returns None if the user cancels or closes the app."""
    app = PdkCreateApp(
        pre_resolved_plugin_parent=pre_resolved_plugin_parent,
        detected_candidate=detected_candidate,
    )
    return app.run()
