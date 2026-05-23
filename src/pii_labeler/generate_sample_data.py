import os

def create_sample_data(root="sample_data"):
    if os.path.exists(root):
        print(f"Directory {root} already exists.")
        return

    os.makedirs(root)

    structure = {
        "file1": {
            "page1": [
                "This is the first paragraph. My name is John Doe.",
                "I live in New York City.",
                "Contact me at 555-0199."
            ],
            "page2": [
                "Another page here.",
                "My SSN is 000-00-0000 (fake)."
            ]
        },
        "file2": {
            "page1": [
                "Just some random text without PII.",
                "Or maybe a date like January 1, 2020."
            ]
        }
    }

    for file_name, pages in structure.items():
        for page_name, paragraphs in pages.items():
            path = os.path.join(root, file_name, page_name)
            os.makedirs(path, exist_ok=True)
            for i, p_text in enumerate(paragraphs):
                p_path = os.path.join(path, f"p{i}.txt")
                with open(p_path, 'w', encoding='utf-8') as f:
                    f.write(p_text)

    print(f"Sample data created in {root}")

if __name__ == "__main__":
    create_sample_data()
