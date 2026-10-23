#!/bin/bash
# Double-click to launch Jana in your browser.
cd "$(dirname "$0")"
if ! curl -s http://127.0.0.1:11434/api/version >/dev/null; then
  echo "Starting Ollama…"; (ollama serve >/dev/null 2>&1 &); sleep 2
fi
[ -d node_modules ] || npm install
node server.js
