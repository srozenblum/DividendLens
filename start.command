#!/bin/bash
cd "$(dirname "$0")"

echo "Setting up environment..."

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate

pip install -r requirements.txt --quiet

echo "Starting server..."
uvicorn main:app --host 127.0.0.1 --port 8000 --reload &

sleep 2

open http://localhost:8000

echo "Server running at http://localhost:8000"
echo "Press Ctrl+C to stop."

wait