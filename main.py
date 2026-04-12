"""AA Laser Studio — entry point."""

import sys

from PySide6.QtWidgets import QApplication

from aa_laser.app import App, _apply_dark_palette

if __name__ == "__main__":
    app = QApplication(sys.argv)
    _apply_dark_palette(app)
    window = App()
    window.show()
    sys.exit(app.exec())
