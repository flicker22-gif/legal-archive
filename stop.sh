#!/usr/bin/env bash
# 停止本项目的前端、后端、PostgreSQL（不影响同机其他项目）
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "▶ 停止 Next.js（端口 4730）…"
ps -eo pid,args | awk -v r="$ROOT" '
  /[n]ext/ && index($0, r"/frontend/") {print $1}
  /[n]pm run dev/ && index(ENVIRON["PWD"], r) {print $1}
' | xargs -r kill 2>/dev/null || true

echo "▶ 停止 FastAPI…"
ps -eo pid,args | awk -v r="$ROOT" '
  /[u]vicorn app\.main/ && index($0, r"/backend/") {print $1}
' | xargs -r kill 2>/dev/null || true

echo "▶ 停止 PostgreSQL…"
"$ROOT/tools/pgctl.sh" stop || true

echo "已全部停止。"
