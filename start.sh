#!/usr/bin/env bash
# 一键启动：PostgreSQL + FastAPI(8000) + Next.js(4730)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "▶ 启动 PostgreSQL (端口 55432)…"
"$ROOT/tools/pgctl.sh" start || true

echo "▶ 启动 FastAPI 后端 (端口 8000)…"
mkdir -p "$ROOT/run"
if ! curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
  (cd "$ROOT/backend" && setsid nohup .venv/bin/uvicorn app.main:app \
      --host 127.0.0.1 --port 8000 \
      > "$ROOT/run/backend.log" 2>&1 < /dev/null &)
fi

echo "▶ 启动 Next.js 前端 (端口 4730)…"
if ! curl -sf http://127.0.0.1:4730 >/dev/null 2>&1; then
  (cd "$ROOT/frontend" && setsid nohup npm run dev \
      > "$ROOT/run/frontend.log" 2>&1 < /dev/null &)
fi

# 等待后端就绪
for i in $(seq 1 30); do
  curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1 && break
  sleep 1
done

cat <<EOF

============================================================
  案件归档检索系统已启动：
    前端页面 : http://localhost:4730
    后端 API : http://localhost:8000  （文档 /docs）
    PostgreSQL: 127.0.0.1:55432  库名/用户 archive
  日志目录  : $ROOT/run/
  停止服务  : $ROOT/stop.sh
============================================================
EOF
