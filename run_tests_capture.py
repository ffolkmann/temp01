"""Runner: executes the three test scripts and writes their complete output to a log file."""
import subprocess
import sys
import os

os.chdir("/docker/clone-remaining-test-fixes-682060")

commands = [
    ("COMMAND 1: test_stream.py", [sys.executable, "tests/test_stream.py"]),
    ("COMMAND 2: test_embeddings.py", [sys.executable, "tests/test_embeddings.py"]),
    ("COMMAND 3: test_point_id.py", [sys.executable, "tests/test_point_id.py"]),
]

lines = []
for label, cmd in commands:
    lines.append(f"=== {label} ===")
    result = subprocess.run(cmd, capture_output=True, text=True,
                            cwd="/docker/clone-remaining-test-fixes-682060")
    combined = result.stdout
    if result.stderr:
        combined = combined + result.stderr
    lines.append(combined.rstrip("\n"))
    lines.append(f"EXIT_CODE: {result.returncode}")
    lines.append("")

output = "\n".join(lines)
with open("/docker/clone-remaining-test-fixes-682060/test_output.log", "w") as f:
    f.write(output)

print(output)
