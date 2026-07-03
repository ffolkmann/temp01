#!/bin/bash
cd /docker/clone-root-hardcode-682060

echo "=== TEST 1: test_stats.py ==="
python3 tests/test_stats.py 2>&1
echo "EXIT_CODE_1=$?"

echo ""
echo "=== TEST 2: test_embed.py ==="
python3 tests/test_embed.py 2>&1
echo "EXIT_CODE_2=$?"

echo ""
echo "=== TEST 3: test_order_status.py ==="
python3 tests/test_order_status.py 2>&1
echo "EXIT_CODE_3=$?"

echo ""
echo "=== TEST 4: test_sync_parity.py ==="
python3 tests/test_sync_parity.py 2>&1
echo "EXIT_CODE_4=$?"

echo ""
echo "=== TEST 5: test_sync.py ==="
python3 tests/test_sync.py 2>&1
echo "EXIT_CODE_5=$?"

echo ""
echo "=== ALL TESTS DONE ==="
