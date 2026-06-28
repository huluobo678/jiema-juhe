#!/bin/bash
set -e
echo "=== 云枢智联 部署脚本 ==="

# 1. 拉取最新代码
echo "[1/3] 拉取最新代码..."
git pull origin master

# 2. 确保数据库文件不被 Git 跟踪
echo "[2/3] 确保数据库文件不被 Git 跟踪..."
git rm --cached sms.db 2>/dev/null || true
git rm --cached database.db 2>/dev/null || true
git rm --cached data.db 2>/dev/null || true
git rm --cached _test_*.py 2>/dev/null || true
git rm --cached '*.pyc' 2>/dev/null || true

# 3. 重启服务
echo "[3/3] 重启服务..."
systemctl restart jiema

echo "=== 部署完成 ==="
