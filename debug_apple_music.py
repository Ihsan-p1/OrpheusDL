import subprocess
import sys

def main():
    # Test AAC download (no wrapper needed)
    cmd = [sys.executable, "orpheus.py", "luckysearch", "applemusic", "track", "4batz act ii date @ 8"]
    print(f"Running: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    
    print("--- RETURN CODE ---")
    print(result.returncode)
    
    print("\n--- STDOUT (tail) ---")
    # Print last 50 lines of stdout
    lines = result.stdout.strip().split('\n')
    print('\n'.join(lines[-50:]))
    
    print("\n--- STDERR (tail) ---")
    lines = result.stderr.strip().split('\n')
    print('\n'.join(lines[-30:]))

if __name__ == "__main__":
    main()
