#!/bin/bash
cd /docker/clone-remaining-test-fixes-682060

echo "=== COMMAND 1 ==="
python3 tests/test_stream.py 2>&1
echo "EXIT_CODE:$?"

echo "=== COMMAND 2 ==="
python3 tests/test_embeddings.py 2>&1
echo "EXIT_CODE:$?"

echo "=== COMMAND 3 ==="
python3 tests/test_point_id.py 2>&1
echo "EXIT_CODE:$?"
