import sys
import os

def test_headless():
    # 1. Test Utils
    print("Testing Utils...")
    # Generate data first
    import generate_sample_data
    generate_sample_data.create_sample_data("sample_data")
    
    from annotator.utils import collect_files
    files = collect_files("sample_data")
    if not files:
        print("FAIL: No files found in sample_data")
        sys.exit(1)
    print(f"Found {len(files)} files.")
    
    # 2. Test Model (Pure Python)
    print("Testing Model...")
    from annotator.model import AnnotationModel
    model = AnnotationModel()
    model.load_root_dir("sample_data")
    
    first_file = files[0]
    data = model.load_file_content(first_file)
    if 'text' not in data:
        print("FAIL: 'text' missing in loaded data")
        sys.exit(1)
        
    print(f"Content length: {len(data['text'])}")
    
    # Add validation
    model.add_annotation(first_file, 0, 5, "TEST")
    # Duplicate check
    model.add_annotation(first_file, 0, 5, "TEST")
    if len(model.data_store[first_file]['entities']) != 1:
        print("FAIL: Duplicate prevention failed")
        sys.exit(1)
    
    # Remove
    model.remove_annotation(first_file, 0)
    if len(model.data_store[first_file]['entities']) != 0:
        print("FAIL: Removal failed")
        sys.exit(1)
        
    # Re-add for export test
    model.add_annotation(first_file, 10, 15, "TEST_EXPORT")
    
    # Export
    issues = model.validate_all()
    if issues:
        print(f"FAIL: Unexpected validation issues: {issues}")
        sys.exit(1)
        
    model.export_jsonl("test_export.jsonl")
    if not os.path.exists("test_export.jsonl"):
        print("FAIL: Export file not created")
        sys.exit(1)
        
    with open("test_export.jsonl", 'r') as f:
        content = f.read()
        if "TEST_EXPORT" not in content:
             print("FAIL: Export content missing annotation")
             sys.exit(1)
    
    # 3. Test Controller Imports (Optional)
    print("Testing Imports...")
    try:
        from PySide6.QtWidgets import QApplication
        from annotator.controller import AnnotatorController
        print("PySide6 available - Imports OK")
    except ImportError:
        print("PySide6 not found - Skipping Controller tests (Expected in headless env)")
    
    print("Verification Passed (Core Logic).")

if __name__ == "__main__":
    try:
        test_headless()
    except Exception as e:
        print(f"Test failed with exception: {e}")
        sys.exit(1)
