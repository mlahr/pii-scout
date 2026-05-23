import os
import re

def natural_sort_key(s):
    """Key function for natural sorting (1, 2, 10 instead of 1, 10, 2)."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r'(\d+)', s)]

def collect_files(root_path):
    """
    Recursively collect all .txt files in the given root path.
    Returns a sorted list of relative paths (natural/numeric sort).
    """
    txt_files = []
    if not os.path.exists(root_path):
        return []

    for root, _, files in os.walk(root_path):
        for file in files:
            if file.endswith('.txt'):
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, root_path)
                txt_files.append(rel_path)

    # Natural sort (numeric order)
    txt_files.sort(key=natural_sort_key)
    return txt_files
