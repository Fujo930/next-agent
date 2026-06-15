"""Test regex patterns from compress.py for bugs."""
import re

print("=== Test 1: \\d vs \\\\d in raw strings ===")
m1 = re.search(r"\d+", "42 lines")
m2 = re.search(r"\\d+", "42 lines")
print("  r'\\d+' matches:", m1)
print("  r'\\\\d+' matches:", m2)

print()
print("=== Test 2: \\w vs \\\\w in raw strings ===")
m3 = re.search(r"\w+", "hello.py")
m4 = re.search(r"\\w+", "hello.py")
print("  r'\\w+' matches:", m3)
print("  r'\\\\w+' matches:", m4)

print()
print("=== Test 3: \\. vs \\\\. in raw strings ===")
m5 = re.search(r"\.", "file.py")
m6 = re.search(r"\\.", "file.py")
print("  r'\\.' matches:", m5)
print("  r'\\\\.' matches:", m6)

print()
print("=== Test 4: Counts regex from compress.py line 119 ===")
pat_counts = r"(\\d+)\\s*(lines?|files?|entries?|matches?)"
print("  Buggy pattern:", repr(pat_counts))
m = re.search(pat_counts, "42 lines, 3 files")
print("    with '42 lines':", m)

pat_ok = r"(\d+)\s*(lines?|files?|entries?|matches?)"
print("  Correct pattern:", repr(pat_ok))
m = re.search(pat_ok, "42 lines, 3 files")
print("    with '42 lines':", m)

print()
print("=== Test 5: exit.code regex from line 122 ===")
pat_exit = r"exit.code.*?(\d+)"
print("  Pattern:", repr(pat_exit))
m = re.search(pat_exit, "Process finished with exit code 0", re.IGNORECASE)
print("    match on 'exit code 0':", m)
m = re.search(pat_exit, "exit_code: 123", re.IGNORECASE)
print("    match on 'exit_code: 123':", m)
m = re.search(pat_exit, "exit-code: 42", re.IGNORECASE)
print("    match on 'exit-code: 42':", m)
