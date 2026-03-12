from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.core.logging import configure_logging
from app.desktop.window import MainWindow


def main() -> int:
    configure_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("Local Whisper Transcriber")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
