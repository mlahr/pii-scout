import json
import os
import shutil
from collections import defaultdict

class AnnotationModel:
    def __init__(self):
        self.root_dir = None
        self.file_list = []  # List of relative paths
        self.data_store = {} # relative_path -> {'text': str, 'entities': list}
        self.skipped_files = set()  # Set of skipped file prefixes (PDF ids)
        self.reviewed_files = set()  # Set of reviewed file prefixes (PDF ids)
        self.processed_paragraphs = set()  # Set of individually processed paragraphs
        self.autosave_filename = ".annotations.autosave.json"

    def load_root_dir(self, root_dir):
        self.root_dir = root_dir
        self.data_store = {}
        self.skipped_files = set()
        self.reviewed_files = set()
        self.processed_paragraphs = set()

    def get_file_prefix(self, rel_path):
        """Get the PDF id (first directory component) from a relative path."""
        parts = rel_path.split(os.sep)
        return parts[0] if parts else rel_path

    def is_file_skipped(self, rel_path):
        """Check if a file belongs to a skipped PDF."""
        prefix = self.get_file_prefix(rel_path)
        return prefix in self.skipped_files

    def toggle_skip_file(self, rel_path):
        """Toggle skip status for the PDF containing this file. Returns new status."""
        prefix = self.get_file_prefix(rel_path)
        if prefix in self.skipped_files:
            self.skipped_files.discard(prefix)
            return False
        else:
            self.skipped_files.add(prefix)
            return True

    def is_file_reviewed(self, rel_path):
        """Check if a file belongs to a reviewed PDF."""
        prefix = self.get_file_prefix(rel_path)
        return prefix in self.reviewed_files

    def toggle_reviewed_file(self, rel_path):
        """Toggle reviewed status for the PDF containing this file. Returns new status."""
        prefix = self.get_file_prefix(rel_path)
        if prefix in self.reviewed_files:
            self.reviewed_files.discard(prefix)
            return False
        else:
            self.reviewed_files.add(prefix)
            return True

    def mark_paragraph_processed(self, rel_path):
        """Mark a paragraph as processed."""
        self.processed_paragraphs.add(rel_path)

    def is_paragraph_processed(self, rel_path):
        """Check if a paragraph has been individually processed."""
        return rel_path in self.processed_paragraphs

    def is_paragraph_done(self, rel_path):
        """Check if a paragraph is done (has entities OR processed OR in reviewed PDF)."""
        has_entities = rel_path in self.data_store and bool(self.data_store[rel_path]['entities'])
        return has_entities or self.is_paragraph_processed(rel_path) or self.is_file_reviewed(rel_path)

    def is_file_labeled(self, rel_path):
        """Check if a file is labeled (has entities OR processed OR in reviewed PDF)."""
        return self.is_paragraph_done(rel_path)

    def get_full_path(self, rel_path):
        if not self.root_dir:
            return None
        return os.path.join(self.root_dir, rel_path)

    def load_file_content(self, rel_path):
        """Loads text content from disk if not already in memory."""
        if rel_path not in self.data_store:
            full_path = self.get_full_path(rel_path)
            if full_path and os.path.exists(full_path):
                with open(full_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                # Normalize: replace newlines with spaces, collapse multiple spaces
                text = ' '.join(text.split())
                self.data_store[rel_path] = {'text': text, 'entities': [], 'suggestions': []}
            else:
                 self.data_store[rel_path] = {'text': "", 'entities': [], 'suggestions': []}
        # Ensure suggestions key exists for legacy loaded data
        if 'suggestions' not in self.data_store[rel_path]:
            self.data_store[rel_path]['suggestions'] = []
        return self.data_store[rel_path]

    def add_annotation(self, rel_path, start, end, label):
        if rel_path not in self.data_store:
            return # Should not happen if loaded
        
        entities = self.data_store[rel_path]['entities']
        # Prevent duplicates
        for e in entities:
            if e['start'] == start and e['end'] == end and e['type'] == label:
                return

        entities.append({'type': label, 'start': start, 'end': end})
        # Keep sorted by start time for convenience
        entities.sort(key=lambda x: x['start'])

    def remove_annotation(self, rel_path, index):
        if rel_path in self.data_store and 0 <= index < len(self.data_store[rel_path]['entities']):
            self.data_store[rel_path]['entities'].pop(index)

    def save_autosave(self, current_file=None):
        if not self.root_dir:
            return

        path = os.path.join(self.root_dir, self.autosave_filename)
        # We only need to save entries that have entities to save space/time,
        # or we can save everything. Let's save everything that has been loaded/touched.
        # Actually, for "Restore", we probably want to save the whole dirty state.

        annotations = {
            k: v for k, v in self.data_store.items() if v['entities'] or v.get('suggestions') # Save if entities OR suggestions exist
            # Or if we want to support labeling "Nothing here", we might need to track "visited".
            # Requirement says: "Stores annotations...".
            # If we strictly valid-only, we might lose "I checked this and it has nothing".
            # But for MVP, saving items with entities is safe.
        }

        save_data = {
            "_meta": {"last_file": current_file},
            "annotations": annotations,
            "skipped_files": list(self.skipped_files),
            "reviewed_files": list(self.reviewed_files),
            "processed_paragraphs": list(self.processed_paragraphs)
        }

        # Serialize
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, indent=2)
        except Exception as e:
            print(f"Autosave failed: {e}")

    def load_autosave(self):
        """
        Load autosave data.
        Returns (success: bool, last_file: str or None)
        """
        if not self.root_dir:
            return False, None

        path = os.path.join(self.root_dir, self.autosave_filename)
        if not os.path.exists(path):
            return False, None

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Handle new format with _meta
            if "_meta" in data and "annotations" in data:
                last_file = data["_meta"].get("last_file")
                self.data_store = data["annotations"]
                self.skipped_files = set(data.get("skipped_files", []))
                self.reviewed_files = set(data.get("reviewed_files", []))
                self.processed_paragraphs = set(data.get("processed_paragraphs", []))
            else:
                # Legacy format: data is {rel_path: {text, entities}}
                last_file = None
                self.data_store = data
                self.skipped_files = set()
                self.reviewed_files = set()
                self.processed_paragraphs = set()

            return True, last_file
        except:
            return False, None

    def export_jsonl(self, output_path):
        """
        Exports valid paragraphs to JSONL.
        """
        issues = []
        
        with open(output_path, 'w', encoding='utf-8') as f:
            for rel_path, data in self.data_store.items():
                if not data['entities']:
                    continue # specific requirement: "gold_paragraphs.jsonl ... containing ... entities"
                             # Usually gold data might contain negatives too. 
                             # But let's include if it has entities. 
                             # Wait, user said "Treats each PARAGRAPH.txt as one annotation item."
                             # Maybe we should export ALL items, even empty ones?
                             # "Gold labeling" usually implies positive samples or all verified samples.
                             # Let's export all items that we know about (loaded) or maybe all files?
                             # Requirement: "Exports a gold_paragraphs.jsonl file ... containing id, path, text, entities."
                             # If we only export what we touched, we might miss the "False" negatives (files with no PII).
                             # But `data_store` only has loaded files.
                             # If the user opened the folder and went through all files, they are in data_store.
                             # Let's iterate over ALL discovered files (passed from controller) if possible, 
                             # or just export what is in data_store. 
                             # Let's export what is in data_store for now, assuming the user went through them.
                             # OR better: The model should preferably know about all files.
                             
                # Validations
                text = data['text']
                for i, ent in enumerate(data['entities']):
                    start, end = ent['start'], ent['end']
                    if not (0 <= start < end <= len(text)):
                        issues.append(f"{rel_path}: Entity {i} out of bounds")
                    elif not text[start:end].strip(): # "text[start:end] not empty" - technically strict empty check or whitespace?
                         # "Trim leading/trailing whitespace of selection automatically" implies stored entities span non-whitespace?
                         # Requirement says "text[start:end] not empty".
                         if len(text[start:end]) == 0:
                             issues.append(f"{rel_path}: Entity {i} is empty")

                record = {
                    "id": rel_path, # derived from relative path
                    "path": rel_path,
                    "text": text,
                    "entities": data['entities']
                    # Suggestions are STRICTLY EXCLUDED
                }
                f.write(json.dumps(record) + "\n")
                
        # Wait, validation should BLOCK export.
        # So we should validate first.
        return issues
        
    def validate_all(self):
        issues = []
        for rel_path, data in self.data_store.items():
            text = data['text']
            for i, ent in enumerate(data['entities']):
                start, end = ent['start'], ent['end']
                if not (0 <= start < end <= len(text)):
                    issues.append(f"{rel_path}: Entity '{ent['type']}' indices [{start}:{end}] out of bounds (len={len(text)})")
                    continue
                
                chunk = text[start:end]
                if not chunk:
                    issues.append(f"{rel_path}: Entity '{ent['type']}' at [{start}:{end}] is empty")
        return issues

    def plain_export(self, output_path):
        # Assumes validation passed
        with open(output_path, 'w', encoding='utf-8') as f:
            sorted_paths = sorted(self.data_store.keys()) # Deterministic export
            for rel_path in sorted_paths:
                data = self.data_store[rel_path]
                # If entities list is empty, do we export? 
                # "gold_paragraphs.jsonl ... containing id, path, text, entities"
                # It's better to export everything we have loaded/touched.
                
                record = {
                    "id": rel_path,
                    "path": rel_path,
                    "text": data['text'],
                    "entities": data['entities']
                }
                f.write(json.dumps(record) + "\n")
