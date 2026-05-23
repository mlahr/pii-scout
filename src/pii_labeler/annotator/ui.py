from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QListWidget, QPlainTextEdit, QTableWidget, QTableWidgetItem,
    QLabel, QPushButton, QSplitter, QHeaderView, QFileDialog,
    QMessageBox, QLineEdit, QComboBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QAction, QKeySequence

class MainWindowUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PII Labeler")
        self.resize(1200, 800)
        
        # Central Widget
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        
        # Splitter for 3 panels
        self.splitter = QSplitter(Qt.Horizontal)
        self.main_layout.addWidget(self.splitter)
        
        # --- Left Panel: File List ---
        self.left_panel = QWidget()
        self.left_layout = QVBoxLayout(self.left_panel)
        
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All", "Unlabeled", "Labeled", "Skipped", "Unskipped"])
        self.left_layout.addWidget(QLabel("Filter:"))
        self.left_layout.addWidget(self.filter_combo)
        
        self.file_list = QListWidget()
        self.left_layout.addWidget(self.file_list)
        
        self.splitter.addWidget(self.left_panel)
        
        # --- Center Panel: Text Editor ---
        self.center_panel = QWidget()
        self.center_layout = QVBoxLayout(self.center_panel)
        
        self.info_label = QLabel("No file loaded")
        self.center_layout.addWidget(self.info_label)
        
        self.text_editor = QPlainTextEdit()
        self.text_editor.setReadOnly(True)
        self.text_editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        font = QFont("Courier New", 18)
        font.setStyleHint(QFont.Monospace)
        self.text_editor.setFont(font)
        self.center_layout.addWidget(self.text_editor)
        
        self.splitter.addWidget(self.center_panel)
        
        # --- Right Panel: Annotations ---
        self.right_panel = QWidget()
        self.right_layout = QVBoxLayout(self.right_panel)
        
        self.right_layout.addWidget(QLabel("Annotations"))
        
        # Suggestion Controls
        self.suggestion_layout = QHBoxLayout()
        self.accept_btn = QPushButton("Accept (Enter)")
        self.accept_all_btn = QPushButton("Accept All")
        self.suggestion_layout.addWidget(self.accept_btn)
        self.suggestion_layout.addWidget(self.accept_all_btn)
        self.right_layout.addLayout(self.suggestion_layout)
        
        self.annotations_table = QTableWidget()
        self.annotations_table.setColumnCount(4)
        self.annotations_table.setHorizontalHeaderLabels(["Type", "Start", "End", "Content"])
        self.annotations_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.annotations_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.annotations_table.setSelectionMode(QTableWidget.SingleSelection)
        self.right_layout.addWidget(self.annotations_table)
        
        self.delete_btn = QPushButton("Delete Selected (Del)")
        self.right_layout.addWidget(self.delete_btn)
        
        self.splitter.addWidget(self.right_panel)
        
        # Initial splitter sizes - more space for text editor
        self.splitter.setSizes([150, 750, 300])
        
        # --- Toolbar ---
        self.toolbar = self.addToolBar("Main")
        
        self.open_action = QAction("Open Folder... (Ctrl+O)", self)
        self.open_action.setShortcut(QKeySequence("Ctrl+O"))
        self.toolbar.addAction(self.open_action)
        
        self.save_action = QAction("Save (Ctrl+S)", self)
        self.save_action.setShortcut(QKeySequence("Ctrl+S"))
        self.toolbar.addAction(self.save_action)
        
        self.export_action = QAction("Export JSONL...", self)
        self.toolbar.addAction(self.export_action)
        
        self.toolbar.addSeparator()
        
        self.prev_action = QAction("Prev (Ctrl+P)", self)
        self.prev_action.setShortcut(QKeySequence("Ctrl+P"))
        self.toolbar.addAction(self.prev_action)
        
        self.next_action = QAction("Next (Ctrl+N)", self)
        self.next_action.setShortcut(QKeySequence("Ctrl+N"))
        self.toolbar.addAction(self.next_action)
        
        self.undo_action = QAction("Undo (Ctrl+Z)", self)
        self.undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        self.toolbar.addAction(self.undo_action)
        
        self.toolbar.addSeparator()
        self.progress_label = QLabel("0 / 0")
        self.toolbar.addWidget(self.progress_label)

    def show_error(self, message):
        QMessageBox.critical(self, "Error", message)
        
    def show_info(self, message):
        QMessageBox.information(self, "Info", message)

    def ask_yes_no(self, title, question):
        ret = QMessageBox.question(self, title, question, QMessageBox.Yes | QMessageBox.No)
        return ret == QMessageBox.Yes
