#!/bin/bash
set -e

echo "Checking for Ollama..."
if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is not installed. Install it from https://ollama.com/download and run this script again."
  exit 1
fi

echo "Pulling Qwen3 14B (about 23 GB)..."
ollama pull qwen3:14b

echo "Testing Qwen3 14B..."
ollama run qwen3:14b 'Return only this JSON: {"status":"ok"}'

echo "Qwen3 14B planner is ready."
