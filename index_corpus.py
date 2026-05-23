import argparse
import hashlib
import json
import os
import signal
import time
import typing
from concurrent.futures import TimeoutError

import fitz  # PyMuPDF
from pebble import ProcessPool
from tqdm import tqdm

# Size buckets configuration
SIZE_BUCKETS = {
    "tiny": 200 * 1024,  # < 200 KB
    "normal": 5 * 1024 * 1024,  # < 5 MB
    # huge is > 5 MB
}

def get_file_hash(path: str) -> str:
    """Computes SHA1 hash of the file content."""
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        stat = os.stat(path)
        identity = f"{path}{stat.st_size}{stat.st_mtime}"
        return hashlib.sha1(identity.encode('utf-8')).hexdigest()

def compute_size_bucket(size_bytes: int) -> str:
    if size_bytes < SIZE_BUCKETS["tiny"]:
        return "tiny"
    elif size_bytes < SIZE_BUCKETS["normal"]:
        return "normal"
    else:
        return "huge"

def analyze_pdf(path: str, max_pages_probe: int) -> typing.Dict[str, typing.Any]:
    start_time = time.time()
    result = {
        "path": os.path.abspath(path),
        "bytes": 0,
        "mtime_epoch": 0,
        "size_bucket": "normal",
        "page_count": None,
        "producer": None,
        "creator": None,
        "has_text_ops": False,
        "image_xobject_count": 0,
        "large_image_count": 0,
        "likely_scanned": False,
        "scan_score": 0.0,
        "errors": [],
        "processing_time_seconds": 0.0
    }

    try:
        stat = os.stat(path)
        result["bytes"] = stat.st_size
        result["mtime_epoch"] = stat.st_mtime
        result["size_bucket"] = compute_size_bucket(stat.st_size)
    except OSError as e:
        result["errors"].append(f"Stat error: {str(e)}")
        result["pdf_id"] = hashlib.sha1(path.encode('utf-8')).hexdigest()
        result["processing_time_seconds"] = time.time() - start_time
        return result

    try:
        result["pdf_id"] = get_file_hash(path)
    except Exception as e:
        result["errors"].append(f"Hash error: {str(e)}")
        result["pdf_id"] = hashlib.sha1(f"{path}{stat.st_size}{stat.st_mtime}".encode('utf-8')).hexdigest()

    doc = None
    try:
        # We perform the open inside the StderrCapture block in worker, 
        # but analyze_pdf itself needs to be safe.
        doc = fitz.open(path)
        result["page_count"] = doc.page_count
        result["producer"] = doc.metadata.get("producer")
        result["creator"] = doc.metadata.get("creator")
        
        text_ops_found = False
        image_count = 0
        large_image_count = 0
        
        pages_to_check = min(doc.page_count, max_pages_probe)
        
        for i in range(pages_to_check):
            page = doc.load_page(i)
            text = page.get_text("text")
            if text and text.strip():
                text_ops_found = True
            
            images = page.get_images()
            image_count += len(images)
            for img in images:
                w, h = img[2], img[3]
                if w * h > 1_000_000:
                    large_image_count += 1
        
        result["has_text_ops"] = text_ops_found
        result["image_xobject_count"] = image_count
        result["large_image_count"] = large_image_count
        
        score = 0.0
        if not text_ops_found:
            score += 0.6
        if image_count > 0 and not text_ops_found:
            score += 0.3
        if large_image_count > 0 and not text_ops_found:
            score += 0.1
        if text_ops_found:
             score = 0.0 
        else:
             if result["page_count"] > 0:
                 avg_bytes = result["bytes"] / result["page_count"]
                 if avg_bytes > 500_000:
                     score += 0.1

        result["scan_score"] = min(1.0, max(0.0, score))
        result["likely_scanned"] = result["scan_score"] >= 0.7

    except Exception as e:
        result["errors"].append(f"PDF processing error: {str(e)}")
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass
            
    result["processing_time_seconds"] = time.time() - start_time
    return result

class ListLog:
    """Captures fitz logs to a list."""
    def __init__(self):
        self.lines = []
    def write(self, msg):
        self.lines.append(msg)
    def flush(self):
        pass

def worker(args):
    path, max_pages = args
    
    # Disable default console logging (stderr)
    if hasattr(fitz.TOOLS, "mupdf_display_errors"):
        fitz.TOOLS.mupdf_display_errors(False)
    
    def handler(signum, frame):
        raise TimeoutError("Processing timed out")
    
    signal.signal(signal.SIGALRM, handler)
    signal.alarm(20)
    
    log_sink = ListLog()
    result = None
    
    try:
        # Redirect fitz errors to our sink
        try:
            fitz.set_log(stream=log_sink)
        except Exception:
            pass # If set_log fails, we just don't capture C-logs
            
        try:
            result = analyze_pdf(path, max_pages)
        except TimeoutError:
            raise
        except Exception as e:
            if isinstance(e, TimeoutError):
                raise
            result = {
                "path": os.path.abspath(path),
                "errors": [f"Unexpected error: {str(e)}"],
                "pdf_id": None
            }

    except TimeoutError:
         result = {
            "path": os.path.abspath(path),
            "bytes": 0,
            "mtime_epoch": 0,
            "size_bucket": "normal",
            "page_count": None,
            "producer": None,
            "creator": None,
            "has_text_ops": False,
            "image_xobject_count": 0,
            "large_image_count": 0,
            "likely_scanned": False,
            "scan_score": 0.0,
            "errors": ["Timeout triggered during processing"]
         }
    except Exception as e:
         result = {
            "path": os.path.abspath(path),
            "errors": [f"Worker unhandled exception: {str(e)}"],
             "pdf_id": None
         }
    finally:
        signal.alarm(0)
    
    # reset log? not strictly necessary as process will likely reuse or die
    
    if log_sink.lines:
        if "errors" not in result:
            result["errors"] = []
        # Filter and add
        clean_logs = [l.strip() for l in log_sink.lines if l.strip()]
        result["errors"].extend(clean_logs)
            
    return result

def main():
    parser = argparse.ArgumentParser(description="Index PDF corpus metadata.")
    parser.add_argument("--root", required=True, help="Root directory to scan")
    parser.add_argument("--out", required=True, help="Output output file")
    parser.add_argument("--workers", type=int, default=8, help="Number of workers")
    parser.add_argument("--resume", action="store_true", help="Resume from existing output")
    parser.add_argument("--max-pages-probe", type=int, default=3, help="Pages to probe for heuristics")
    
    args = parser.parse_args()
    
    existing_paths = set()
    open_mode = "w"
    
    if args.resume and os.path.exists(args.out):
        print(f"Resuming from {args.out}...")
        open_mode = "a"
        try:
            with open(args.out, "r") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        existing_paths.add(record["path"])
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            print(f"Error reading existing file: {e}")
            
    print(f"Scanning for PDFs in {args.root}...")
    pdf_files = []
    for root, dirs, files in os.walk(args.root):
        for file in files:
            if file.lower().endswith(".pdf"):
                full_path = os.path.abspath(os.path.join(root, file))
                if full_path not in existing_paths:
                    pdf_files.append(full_path)
    
    print(f"Found {len(pdf_files)} new PDFs to index.")
    
    if not pdf_files:
        return

    total = len(pdf_files)
    tasks = [(p, args.max_pages_probe) for p in pdf_files]
    
    with open(args.out, open_mode) as f_out:
        with ProcessPool(max_workers=args.workers) as pool:
            futures = []
            for t in tasks:
                 futures.append(pool.schedule(worker, args=(t,), timeout=20))
            
            pbar = tqdm(enumerate(futures), total=total, unit="pdf", desc="Indexing") 
            for i, future in pbar:
                path = tasks[i][0]
                result = None
                try:
                    # Check if result is ready within 1 second
                    try:
                         # Attempt to get result quickly
                         result = future.result(timeout=1.0)
                    except TimeoutError:
                        # If detecting timeout but task not done, it means it's running long
                        if not future.done():
                             # Show slow file
                             short_name = os.path.basename(path)
                             if len(short_name) > 30:
                                 short_name = short_name[:27] + "..."
                             pbar.set_description(f"Slow: {short_name}")
                             
                             # Wait for actual completion
                             result = future.result()
                             
                             # Reset description
                             pbar.set_description("Indexing")
                        else:
                             # Task is done and raised TimeoutError (Hard Kill from pebble)
                             raise
                            
                except TimeoutError:
                    result = {
                        "path": path, "pdf_id": None, "errors": ["Timeout (Hard Kill)"],
                        "bytes": 0, "mtime_epoch": 0, "size_bucket": "normal",
                        "page_count": None, "likely_scanned": False, "scan_score": 0.0,
                        "producer": None, "creator": None, "has_text_ops": False, 
                        "image_xobject_count":0, "large_image_count": 0
                    }
                except Exception as e:
                     result = {
                        "path": path, "pdf_id": None, "errors": [f"Process Error: {str(e)}"],
                        "bytes": 0, "mtime_epoch": 0, "size_bucket": "normal",
                         "page_count": None, "likely_scanned": False, "scan_score": 0.0,
                         "producer": None, "creator": None, "has_text_ops": False,
                         "image_xobject_count":0, "large_image_count": 0
                     }
                
                if result:
                    f_out.write(json.dumps(result) + "\n")
                    f_out.flush() # flush regularly
            pbar.close()
                
    print(f"\nDone. Indexed {total} files.")

if __name__ == "__main__":
    main()
