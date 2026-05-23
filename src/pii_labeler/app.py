#!/usr/bin/env python3

import sys
from PySide6.QtWidgets import QApplication
from annotator.controller import AnnotatorController

def main():
    app = QApplication(sys.argv)
    controller = AnnotatorController()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
