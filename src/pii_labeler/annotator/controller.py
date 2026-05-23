import os
from PySide6.QtWidgets import QFileDialog, QTableWidgetItem
from PySide6.QtCore import Qt, QTimer, QObject, Signal, QUrl
from PySide6.QtGui import QAction, QKeySequence, QTextCursor, QDesktopServices

from .model import AnnotationModel
from .ui import MainWindowUI
from .utils import collect_files
# Import existing detection logic
import sys
from pathlib import Path
repo_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(repo_root / "src"))
sys.path.insert(0, str(repo_root))
from pii_detect import detect_pii, load_models 


class AnnotatorController(QObject):
    def __init__(self):
        super().__init__()
        self.model = AnnotationModel()
        self.view = MainWindowUI()
        
        self.current_file_index = -1
        self.autosave_timer = QTimer()
        self.autosave_timer.timeout.connect(self.on_autosave)
        self.autosave_timer.start(5000) # 5 seconds
        
        # Undo stack: simple list of (rel_path, list_of_entities) tuples
        self.undo_stack = [] 
        
        self.setup_connections()
        self.setup_hotkeys()
        
        # Load NLP models
        print("Loading NLP models... this might take a moment.")
        try:
             # Create dummy args object
             class Args:
                 models = "fast" # Use fast model by default for GUI responsivness? Or accurate? Plan didn't specify.
                 # Let's check pii_detect defaults: accurate. 
                 # Let's stick with "accurate" (trf) if user has it, or "fast" (lg).
                 # To be safe and quick for dev: let's use what's available or default.
            
             class MockArgs:
                 models = "accurate" # Default
                 
             self.models = load_models(MockArgs())
             print("Models loaded.")
        except Exception as e:
            print(f"Error loading models: {e}")
            self.models = []

        self.view.show()

    def setup_connections(self):
        self.view.open_action.triggered.connect(self.open_folder_dialog)
        self.view.save_action.triggered.connect(self.save_data)
        self.view.export_action.triggered.connect(self.export_data)
        self.view.prev_action.triggered.connect(self.prev_file)
        self.view.next_action.triggered.connect(self.next_file)
        self.view.undo_action.triggered.connect(self.undo_action)
        
        self.view.accept_btn.clicked.connect(self.accept_selected_suggestion)
        self.view.accept_all_btn.clicked.connect(self.accept_all_suggestions)
        
        self.view.file_list.currentRowChanged.connect(self.on_file_selected)
        self.view.delete_btn.clicked.connect(self.delete_selected_annotation)
        self.view.filter_combo.currentIndexChanged.connect(self.refresh_file_list)

    def setup_hotkeys(self):
        # Hotkeys for labels
        self.hotkeys = {
            'P': 'PERSON',
            'L': 'LOCATION',
            'A': 'ADDRESS',
            'S': 'SSN',
            'T': 'PHONE_NUMBER',
            'C': 'ACCOUNT_NUMBER',
            'B': 'BIRTHDATE',
            'D': 'DATE',
            'E': 'EMAIL'
        }

        for key, label in self.hotkeys.items():
            action = QAction(self.view)
            action.setShortcut(QKeySequence(key))
            action.setShortcutContext(Qt.WindowShortcut)
            # Lambda capture issue: default argument fixes it
            action.triggered.connect(lambda checked=False, l=label: self.add_label_from_selection(l))
            self.view.addAction(action)

        # Delete hotkey
        del_action = QAction(self.view)
        del_action.setShortcut(QKeySequence(Qt.Key_Delete))
        del_action.setShortcutContext(Qt.WindowShortcut)
        del_action.triggered.connect(self.delete_selected_annotation)
        self.view.addAction(del_action)

        # Backspace sometimes acts as delete on mac
        backspace_action = QAction(self.view)
        backspace_action.setShortcut(QKeySequence(Qt.Key_Backspace))
        backspace_action.setShortcutContext(Qt.WindowShortcut)
        backspace_action.triggered.connect(self.delete_selected_annotation)
        self.view.addAction(backspace_action)

        # Skip PDF hotkey
        skip_action = QAction(self.view)
        skip_action.setShortcut(QKeySequence('K'))
        skip_action.setShortcutContext(Qt.WindowShortcut)
        skip_action.triggered.connect(self.toggle_skip_current_pdf)
        self.view.addAction(skip_action)

        # Mark as reviewed (no PII) hotkey
        reviewed_action = QAction(self.view)
        reviewed_action.setShortcut(QKeySequence('R'))
        reviewed_action.setShortcutContext(Qt.WindowShortcut)
        reviewed_action.triggered.connect(self.toggle_reviewed_current_file)
        self.view.addAction(reviewed_action)

        # Accept Suggestion Hotkey (Enter)
        accept_action = QAction(self.view)
        accept_action.setShortcut(QKeySequence(Qt.Key_Return))
        accept_action.setShortcutContext(Qt.WindowShortcut)
        accept_action.triggered.connect(self.accept_selected_suggestion)
        self.view.addAction(accept_action)
        
        # Enter on numpad too
        accept_action2 = QAction(self.view)
        accept_action2.setShortcut(QKeySequence(Qt.Key_Enter))
        accept_action2.setShortcutContext(Qt.WindowShortcut)
        accept_action2.triggered.connect(self.accept_selected_suggestion)
        self.view.addAction(accept_action2)

        # Accept All Hotkey (Shift+Enter)
        accept_all_action = QAction(self.view)
        accept_all_action.setShortcut(QKeySequence("Shift+Return"))
        accept_all_action.setShortcutContext(Qt.WindowShortcut)
        accept_all_action.triggered.connect(self.accept_all_suggestions)
        self.view.addAction(accept_all_action)

        # Open PDF hotkey
        open_pdf_action = QAction(self.view)
        open_pdf_action.setShortcut(QKeySequence('O'))
        open_pdf_action.setShortcutContext(Qt.WindowShortcut)
        open_pdf_action.triggered.connect(self.open_current_pdf)
        self.view.addAction(open_pdf_action)

    def open_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self.view, "Open Folder")
        if folder:
            self.load_folder(folder)

    def load_folder(self, folder):
        self.model.load_root_dir(folder)
        last_file = None

        # Verify autosave
        has_autosave, saved_last_file = self.model.load_autosave()
        if has_autosave:
            if self.view.ask_yes_no("Autosave Found", "Autosave file found. Restore?"):
                last_file = saved_last_file
            else:
                self.model.data_store = {}  # Reset if user says no

        self.all_files = collect_files(folder)
        self.refresh_file_list()

        if self.all_files:
            # Jump to last file if available
            if last_file and last_file in self.display_files:
                row = self.display_files.index(last_file)
                self.view.file_list.setCurrentRow(row)
            else:
                self.view.file_list.setCurrentRow(0)
        else:
            self.view.show_info("No .txt files found in selected directory.")

    def refresh_file_list(self):
        filter_mode = self.view.filter_combo.currentText()
        self.view.file_list.clear()  # This triggers on_file_selected(-1)

        self.display_files = []

        # Compute stats inline to avoid double iteration
        pdfs = set()
        done_count = 0
        skipped_count = 0

        for f in self.all_files:
            is_labeled = self.model.is_file_labeled(f)
            is_skipped = self.model.is_file_skipped(f)
            is_reviewed = self.model.is_file_reviewed(f)

            # Collect stats during iteration
            parts = f.split(os.sep)
            if parts:
                pdfs.add(parts[0])
            if is_skipped:
                skipped_count += 1
            elif is_labeled:
                done_count += 1

            if filter_mode == "All":
                should_show = True
            elif filter_mode == "Labeled":
                should_show = is_labeled
            elif filter_mode == "Unlabeled":
                should_show = not is_labeled and not is_skipped
            elif filter_mode == "Skipped":
                should_show = is_skipped
            elif filter_mode == "Unskipped":
                should_show = not is_skipped
            else:
                should_show = True

            if should_show:
                if is_skipped:
                    display_name = f"[SKIP] {f}"
                elif is_reviewed:
                    display_name = f"[OK] {f}"
                elif is_labeled:
                    display_name = f"[DONE] {f}"
                else:
                    display_name = f
                self.view.file_list.addItem(display_name)
                self.display_files.append(f)

        # Pass pre-computed stats to avoid second iteration
        stats = {
            'pdfs': len(pdfs),
            'done': done_count,
            'todo': len(self.all_files) - done_count - skipped_count,
            'skipped': skipped_count
        }
        self.update_progress(stats)

    def on_file_selected(self, row):
        if row < 0 or row >= len(self.display_files):
            return
        
        rel_path = self.display_files[row]
        self.current_rel_path = rel_path
        
        data = self.model.load_file_content(rel_path)
        
        # Auto-suggestion logic
        if 'suggestions' not in data or not data.get('suggestions_generated', False):
             # check if we have suggestions list initiated in model (it should be)
             # Run detection if not already present or generated
             if not data['suggestions'] and not data.get('suggestions_generated'):
                 # Avoid blocking UI too much? It's synchronous.
                 # For now, run it.
                 try:
                     text = data['text']
                     # detect_pii returns (merged_entities, stats)
                     detected, _ = detect_pii(text, self.models, min_score=0.4) # Reasonable threshold
                     
                     # Filter out items that overlap with existing manual entities?
                     # Requirement: "auto-label is manually accepted ... manual and auto never mixed up".
                     # We store them in 'suggestions'. Overlap check is good UX but not strict requirement.
                     # Let's just store all detected as suggestions.
                     
                     data['suggestions'] = detected
                     data['suggestions_generated'] = True
                 except Exception as e:
                     print(f"Detection failed for {rel_path}: {e}")

        self.view.text_editor.setPlainText(data['text'])
        self.update_info_label()
        self.refresh_annotation_table()
        self.update_progress()
        
        # Save on navigation (as per requirement)
        self.on_autosave()

    def refresh_annotation_table(self):
        if not hasattr(self, 'current_rel_path'):
            return
        
        self.view.annotations_table.setRowCount(0)
        entities = self.model.data_store[self.current_rel_path]['entities']
        suggestions = self.model.data_store[self.current_rel_path].get('suggestions', [])
        text = self.model.data_store[self.current_rel_path]['text']
        
        total_rows = len(entities) + len(suggestions)
        self.view.annotations_table.setRowCount(total_rows)
        
        # Add Manual Entities
        for i, ent in enumerate(entities):
            self.util_add_table_row(i, ent, text, is_suggestion=False)
            
        # Add Suggestions
        for j, sug in enumerate(suggestions):
            row_idx = len(entities) + j
            self.util_add_table_row(row_idx, sug, text, is_suggestion=True)
            
        self.highlight_annotations()

    def highlight_annotations(self):
        from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
        from PySide6.QtWidgets import QPlainTextEdit, QTextEdit
        
        if not hasattr(self, 'current_rel_path'): return
        
        entities = self.model.data_store[self.current_rel_path]['entities']
        suggestions = self.model.data_store[self.current_rel_path].get('suggestions', [])
        
        selections = []
        
        # Manual Entities - Green
        fmt_entity = QTextCharFormat()
        fmt_entity.setBackground(QColor(144, 238, 144)) # Light green
        fmt_entity.setForeground(QColor(0, 0, 0))
        
        for ent in entities:
             sel = QTextEdit.ExtraSelection()
             sel.format = fmt_entity
             cursor = self.view.text_editor.textCursor()
             cursor.setPosition(ent['start'])
             cursor.setPosition(ent['end'], QTextCursor.KeepAnchor)
             sel.cursor = cursor
             selections.append(sel)
             
        # Suggestions - Light Blue
        fmt_sug = QTextCharFormat()
        fmt_sug.setBackground(QColor(200, 200, 255)) # Light blue
        fmt_sug.setForeground(QColor(0, 0, 100))
        # Maybe distinct style?
        
        for sug in suggestions:
             sel = QTextEdit.ExtraSelection()
             sel.format = fmt_sug
             cursor = self.view.text_editor.textCursor()
             cursor.setPosition(sug['start'])
             cursor.setPosition(sug['end'], QTextCursor.KeepAnchor)
             sel.cursor = cursor
             selections.append(sel)
             
        self.view.text_editor.setExtraSelections(selections)

    def util_add_table_row(self, row, ent, text, is_suggestion):
        from PySide6.QtGui import QColor, QFont
        
        type_item = QTableWidgetItem(ent['type'])
        start_item = QTableWidgetItem(str(ent['start']))
        end_item = QTableWidgetItem(str(ent['end']))
        
        content = text[ent['start']:ent['end']]
        content_item = QTableWidgetItem(content)
        
        if is_suggestion:
             # Style for suggestion
             color = QColor(0, 0, 255) # Blue text
             font = QFont()
             font.setItalic(True)
             
             type_item.setForeground(color)
             type_item.setFont(font)
             type_item.setText(f"{ent['type']} (?)") # Visual cue
             
             start_item.setForeground(color)
             end_item.setForeground(color)
             content_item.setForeground(color)
        
        self.view.annotations_table.setItem(row, 0, type_item)
        self.view.annotations_table.setItem(row, 1, start_item)
        self.view.annotations_table.setItem(row, 2, end_item)
        self.view.annotations_table.setItem(row, 3, content_item)

    def get_suggestion_index(self, table_row):
        # Helper to map table row to suggestion index
        # Table has [Entities... | Suggestions...]
        if not hasattr(self, 'current_rel_path'): return -1
        entities = self.model.data_store[self.current_rel_path]['entities']
        if table_row < len(entities):
            return -1 # It's a manual entity
        return table_row - len(entities)

    def accept_selected_suggestion(self):
        row = self.view.annotations_table.currentRow()
        if row < 0: return
        
        sug_idx = self.get_suggestion_index(row)
        if sug_idx == -1: return # Not a suggestion
        
        self.push_undo_state()
        
        path = self.current_rel_path
        suggestions = self.model.data_store[path]['suggestions']
        
        if 0 <= sug_idx < len(suggestions):
            sug = suggestions.pop(sug_idx)
            self.model.add_annotation(path, sug['start'], sug['end'], sug['type'])
            self.refresh_annotation_table()
            self.update_current_file_status()
            # Select the newly created entity (which is at the end of entities list, but list is sorted by start)
            # Simpler to just refresh.
            
    def reject_selected_suggestion(self):
        row = self.view.annotations_table.currentRow()
        if row < 0: return
        
        sug_idx = self.get_suggestion_index(row)
        # If it's -1, it's a manual entity, so use delete logic?
        # User wants "Reject" -> Delete.
        # But we have existing delete functionality.
        # Let's check logic: "Reject" usually means "Remove suggestion".
        
        if sug_idx == -1:
            # It's manual entity -> Delete it
            self.delete_selected_annotation()
            return

        self.push_undo_state()
        path = self.current_rel_path
        suggestions = self.model.data_store[path]['suggestions']
        if 0 <= sug_idx < len(suggestions):
            suggestions.pop(sug_idx)
            self.refresh_annotation_table()
            self.update_current_file_status()

    def accept_all_suggestions(self):
        if not hasattr(self, 'current_rel_path'): return
        path = self.current_rel_path
        suggestions = self.model.data_store[path]['suggestions']
        
        if not suggestions: return
        
        self.push_undo_state()
        
        # Move all
        while suggestions:
            sug = suggestions.pop(0)
            self.model.add_annotation(path, sug['start'], sug['end'], sug['type'])

        self.refresh_annotation_table()
        self.update_current_file_status()

    def reject_all_suggestions(self):
        # Optional: clear all suggestions ?
        # Not explicitly requested but good to have.
        pass


    def add_label_from_selection(self, label):
        if not hasattr(self, 'current_rel_path'):
            return

        cursor = self.view.text_editor.textCursor()
        if not cursor.hasSelection():
            return
            
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        text = self.view.text_editor.toPlainText()
        
        # Trim whitespace from selection
        selected_text = text[start:end]
        
        l_trim = 0
        while l_trim < len(selected_text) and selected_text[l_trim].isspace():
            l_trim += 1
            
        r_trim = 0
        while r_trim < len(selected_text) and selected_text[-(r_trim+1)].isspace():
            r_trim += 1
            
        actual_start = start + l_trim
        actual_end = end - r_trim
        
        if actual_start >= actual_end:
            return  # Empty after trim
            
        # Push to undo stack before modifying
        self.push_undo_state()
        
        self.model.add_annotation(self.current_rel_path, actual_start, actual_end, label)
        self.refresh_annotation_table()
        self.update_current_file_status()

        # Clear selection? Usually better to keep or clear?
        # Let's clear to indicate done
        cursor.clearSelection()
        self.view.text_editor.setTextCursor(cursor)

    def delete_selected_annotation(self):
        row = self.view.annotations_table.currentRow()
        if row < 0: return # Nothing selected
        
        sug_idx = self.get_suggestion_index(row)
        if sug_idx != -1:
            # It is a suggestion -> Reject
            self.reject_selected_suggestion()
            return
            
        # It is a manual entity -> Delete
        if row >= 0:
            self.push_undo_state()
            self.model.remove_annotation(self.current_rel_path, row)
            self.refresh_annotation_table()
            self.update_current_file_status()

    def push_undo_state(self):
        if not hasattr(self, 'current_rel_path'):
            return
        # Deep copy current entities for this file
        current_entities = [dict(e) for e in self.model.data_store[self.current_rel_path]['entities']]
        self.undo_stack.append((self.current_rel_path, current_entities))
        # Limit stack size? 
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)

    def undo_action(self):
        if not self.undo_stack:
            return
        
        # Pop
        path, entities = self.undo_stack.pop()
        
        # If we are not on the same file, maybe switch?
        # Requirement says "single-level is OK for MVP".
        # Let's check if path matches current. If not, it might be confusing.
        # But global undo is often expected. 
        # For simplicity, if path != current, we just update the model but don't force switch unless we want to.
        # But if we don't switch, the user doesn't see the undo.
        # Let's simple Check:
        
        if path in self.model.data_store:
             self.model.data_store[path]['entities'] = entities
             if hasattr(self, 'current_rel_path') and self.current_rel_path == path:
                 self.refresh_annotation_table()
                 self.update_current_file_status()
             elif hasattr(self, 'current_rel_path') and self.current_rel_path != path:
                 # Switch to that file to show undo?
                 # Maybe too intrusive if accidental undo.
                 # Let's just update model and stats.
                 self.update_progress()

    def next_file(self):
        row = self.view.file_list.currentRow()
        if row < 0 or row >= len(self.display_files):
            return

        current_path = self.display_files[row]
        current_prefix = self.model.get_file_prefix(current_path)

        # Mark current paragraph as processed
        self.model.mark_paragraph_processed(current_path)

        # Update current file's status before moving (defer stats update)
        self.update_current_file_status(update_stats=False)

        # Find next non-skipped file
        next_row = None
        for i in range(row + 1, len(self.display_files)):
            if not self.model.is_file_skipped(self.display_files[i]):
                next_row = i
                break

        # If moving to a different PDF, mark the old one as reviewed
        if next_row is not None:
            next_path = self.display_files[next_row]
            next_prefix = self.model.get_file_prefix(next_path)
            if next_prefix != current_prefix:
                # Auto-mark the PDF we're leaving as reviewed
                if current_prefix not in self.model.reviewed_files:
                    self.model.reviewed_files.add(current_prefix)
                    # Update all files from this PDF to show [OK] (defer stats)
                    self._update_pdf_status(current_prefix, update_stats=False)
            self.view.file_list.setCurrentRow(next_row)

        # Update stats once at the end
        self.update_progress()

    def prev_file(self):
        row = self.view.file_list.currentRow()
        # Find previous non-skipped file
        for i in range(row - 1, -1, -1):
            if not self.model.is_file_skipped(self.display_files[i]):
                self.view.file_list.setCurrentRow(i)
                return

    def update_progress(self, stats=None):
        current = self.view.file_list.currentRow() + 1
        total = self.view.file_list.count()

        # Use pre-computed stats if provided, otherwise calculate
        if stats is None:
            stats = self.calculate_stats()
        self.view.progress_label.setText(
            f"{current}/{total} | "
            f"PDFs: {stats['pdfs']} | "
            f"Done: {stats['done']} | "
            f"Todo: {stats['todo']} | "
            f"Skipped: {stats['skipped']}"
        )

    def update_current_file_status(self, update_stats=True):
        """Update the current file's status indicator in sidebar and optionally refresh stats."""
        if not hasattr(self, 'current_rel_path'):
            return

        row = self.view.file_list.currentRow()
        if row < 0 or row >= len(self.display_files):
            return

        f = self.current_rel_path
        is_labeled = self.model.is_file_labeled(f)
        is_skipped = self.model.is_file_skipped(f)
        is_reviewed = self.model.is_file_reviewed(f)

        # Build display name with status
        if is_skipped:
            display_name = f"[SKIP] {f}"
        elif is_reviewed:
            display_name = f"[OK] {f}"
        elif is_labeled:
            display_name = f"[DONE] {f}"
        else:
            display_name = f

        # Update just this item's text
        self.view.file_list.item(row).setText(display_name)

        # Update progress stats
        if update_stats:
            self.update_progress()

    def _update_pdf_status(self, pdf_prefix, update_stats=True):
        """Update status for all files belonging to a PDF prefix."""
        for i, f in enumerate(self.display_files):
            if self.model.get_file_prefix(f) == pdf_prefix:
                is_labeled = self.model.is_file_labeled(f)
                is_skipped = self.model.is_file_skipped(f)
                is_reviewed = self.model.is_file_reviewed(f)

                if is_skipped:
                    display_name = f"[SKIP] {f}"
                elif is_reviewed:
                    display_name = f"[OK] {f}"
                elif is_labeled:
                    display_name = f"[DONE] {f}"
                else:
                    display_name = f

                self.view.file_list.item(i).setText(display_name)

        if update_stats:
            self.update_progress()

    def calculate_stats(self):
        if not hasattr(self, 'all_files'):
            return {'pdfs': 0, 'done': 0, 'todo': 0, 'skipped': 0}

        pdfs = set()
        done_count = 0
        skipped_count = 0

        for f in self.all_files:
            parts = f.split(os.sep)
            if len(parts) >= 1:
                pdfs.add(parts[0])

            is_skipped = self.model.is_file_skipped(f)
            is_done = self.model.is_paragraph_done(f)

            if is_skipped:
                skipped_count += 1
            elif is_done:
                done_count += 1

        todo_count = len(self.all_files) - done_count - skipped_count

        return {
            'pdfs': len(pdfs),
            'done': done_count,
            'todo': todo_count,
            'skipped': skipped_count
        }

    def toggle_skip_current_pdf(self):
        if not hasattr(self, 'current_rel_path'):
            return
        current_path = self.current_rel_path
        is_skipped = self.model.toggle_skip_file(current_path)
        self.refresh_file_list()
        # Re-select the current file
        if current_path in self.display_files:
            row = self.display_files.index(current_path)
            self.view.file_list.setCurrentRow(row)
        self.update_info_label()
        self.on_autosave()

    def toggle_reviewed_current_file(self):
        if not hasattr(self, 'current_rel_path'):
            return
        current_path = self.current_rel_path
        self.model.toggle_reviewed_file(current_path)
        self.refresh_file_list()
        # Re-select the current file
        if current_path in self.display_files:
            row = self.display_files.index(current_path)
            self.view.file_list.setCurrentRow(row)
        self.update_info_label()
        self.on_autosave()

    def open_current_pdf(self):
        if not hasattr(self, 'current_rel_path') or not self.model.root_dir:
            return
        prefix = self.model.get_file_prefix(self.current_rel_path)
        pdf_path = os.path.join(self.model.root_dir, 'pdfs', f'{prefix}.pdf')
        if os.path.exists(pdf_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(pdf_path))
        else:
            self.view.show_info(f"PDF not found: {pdf_path}")

    def update_info_label(self):
        if not hasattr(self, 'current_rel_path'):
            return
        rel_path = self.current_rel_path
        data = self.model.data_store.get(rel_path, {})
        text_len = len(data.get('text', ''))
        prefix = self.model.get_file_prefix(rel_path)
        status = ""
        if self.model.is_file_skipped(rel_path):
            status = " [SKIPPED]"
        elif self.model.is_file_reviewed(rel_path):
            status = " [REVIEWED - No PII]"
        self.view.info_label.setText(f"File: {rel_path} (Len: {text_len}){status}")

    def on_autosave(self):
        current_file = getattr(self, 'current_rel_path', None)
        self.model.save_autosave(current_file)

    def save_data(self):
        current_file = getattr(self, 'current_rel_path', None)
        self.model.save_autosave(current_file)
        self.view.show_info("Saved to autosave file.")

    def export_data(self):
        # Validation first
        issues = self.model.validate_all()
        if issues:
            msg = "Validation failed:\n" + "\n".join(issues[:10])
            if len(issues) > 10:
                msg += f"\n...and {len(issues)-10} more."
            self.view.show_error(msg)
            return

        path, _ = QFileDialog.getSaveFileName(self.view, "Export JSONL", self.model.root_dir or "", "JSONL (*.jsonl)")
        if path:
            self.model.export_jsonl(path)
            self.view.show_info(f"Exported to {path}")
