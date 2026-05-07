#!/bin/bash
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
  echo "Setting up virtual environment..."
  python3 -m venv venv
  venv/bin/pip install -r requirements.txt
fi

source venv/bin/activate

(sleep 2 && open http://localhost:8000) &

echo "Server running at http://localhost:8000"
echo "Press Ctrl+C to stop."
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
