"""Render first-run screens without downloads, credentials or changes to real settings."""
import argparse
import os
import tempfile
from pathlib import Path


def render(output):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication

    from capri.config.defaults import DEFAULTS
    from capri.ui.setup_wizard import SetupWizard
    from capri.ui.theme import apply_theme
    app = QApplication.instance() or QApplication([])
    for font in ("segoeui.ttf", "segoeuib.ttf"):
        path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / font
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))
    apply_theme(app)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="capri_setup_preview_") as temporary:
        wizard = SetupWizard(DEFAULTS, base=temporary)
        wizard.show()
        app.processEvents()
        wizard.grab().save(str(output / "choose.png"))
        wizard.advance()
        app.processEvents()
        wizard.grab().save(str(output / "local.png"))
        wizard.previous()
        wizard.cloud.setChecked(True)
        wizard.advance()
        app.processEvents()
        wizard.grab().save(str(output / "api.png"))
        wizard.key.setText("preview-key-not-a-real-secret")
        wizard.advance()
        app.processEvents()
        wizard.grab().save(str(output / "ready.png"))
        wizard.close()
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    render(parser.parse_args().output)
