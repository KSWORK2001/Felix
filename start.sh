#!/bin/bash

echo "Starting Felix Backend..."
gnome-terminal -- bash -c "cd backend && python -m uvicorn main:app --host 127.0.0.1 --port 8000; exec bash" &

echo "Starting Next.js Frontend..."
gnome-terminal -- bash -c "cd frontend/felix-front && npm run dev -- --hostname 127.0.0.1 --port 3000; exec bash" &

echo "Waiting for frontend to be ready..."
while ! curl -s http://127.0.0.1:3000 > /dev/null; do
  sleep 2
done

echo "Starting Electron Overlay..."
gnome-terminal -- bash -c "cd frontend/felix-front && npm run overlay:electron; exec bash" &

echo "All services started."
