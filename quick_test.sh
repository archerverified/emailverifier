#!/bin/bash
# Quick Test Script for Lead Validator (Mac/Linux)
# Run this after cloning the repo to verify everything works

echo "========================================"
echo "Lead Validator - Quick Test Script"
echo "========================================"
echo ""

# Check if we're in the right directory
if [ ! -f "backend/app.py" ]; then
    echo "[ERROR] Please run this script from the project root directory"
    exit 1
fi

echo "[1/5] Checking Python installation..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version)
    echo "      Found: $PYTHON_VERSION"
else
    echo "[ERROR] Python not found. Please install Python 3.8+"
    exit 1
fi

echo "[2/5] Setting up virtual environment..."
if [ ! -d "backend/venv" ]; then
    cd backend
    python3 -m venv venv
    cd ..
    echo "      Created virtual environment"
else
    echo "      Virtual environment already exists"
fi

echo "[3/5] Installing dependencies..."
cd backend
source venv/bin/activate
pip install -q -r requirements.txt
if [ $? -eq 0 ]; then
    echo "      Dependencies installed"
else
    echo "[ERROR] Failed to install dependencies"
    exit 1
fi

echo "[4/5] Running test suite..."
export VALIDATOR_MODE=mock
export TESTING=1
TEST_OUTPUT=$(pytest -v --tb=short 2>&1)
if [ $? -eq 0 ]; then
    PASSED_COUNT=$(echo "$TEST_OUTPUT" | grep -oP '\d+ passed' | grep -oP '\d+')
    echo "      All $PASSED_COUNT tests passed!"
else
    echo "[ERROR] Some tests failed"
    echo "$TEST_OUTPUT"
    exit 1
fi

echo "[5/5] Running smoke test..."
cd ..
python3 scripts/smoke_test.py
if [ $? -eq 0 ]; then
    echo "      Smoke test passed!"
else
    echo "[ERROR] Smoke test failed"
    exit 1
fi

echo ""
echo "========================================"
echo "SUCCESS! All tests passed!"
echo "========================================"
echo ""
echo "Next steps:"
echo "  1. Start backend:  cd backend; source venv/bin/activate; python3 app.py"
echo "  2. Open browser:   http://localhost:5050"
echo "  3. Upload CSV:     Drag Fortune500leads.csv to the drop zone"
echo ""
echo "OR use Docker:"
echo "  docker compose up --build"
echo ""
echo "For detailed testing guide, see TESTING_GUIDE.md"
