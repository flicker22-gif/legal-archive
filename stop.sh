#!/usr/bin/env bash
# 停止本项目的前端、后端、PostgreSQL（不影响同机其他项目）
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "▶ 停止 Next.js（端口 4730）…"
# next-server 命令行不含项目路径，按工作目录是否为本项目 frontend 定位，
# 避免误杀同机其他项目
for pid in $(pgrep -f "next-server|next (dev|start)" 2>/dev/null); do
  cwd=$(readlink "/proc/$pid/cwd" 2>/dev/null || true)
  case "$cwd" in
    "$ROOT/frontend") kill "$pid" 2>/dev/null || true;;
  esac
done
# 同时停止 npm/sh 包装进程（按端口）
for pid in $(pgrep -f "next (dev|start).*4730" 2>/dev/null); do kill "$pid" 2>/dev/null || true; done

echo "▶ 停止 FastAPI…"
ps -eo pid,args | awk -v r="$ROOT" '
  /[u]vicorn app\.main/ && index($0, r"/backend/") {print $1}
' | xargs -r kill 2>/dev/null || true

echo "▶ 停止 PostgreSQL…"
"$ROOT/tools/pgctl.sh" stop || true

echo "已全部停止。"
