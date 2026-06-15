#!/bin/sh
# 容器入口:按固定间隔循环跑一轮 fapiao,单轮异常不退出容器。
set -eu

INTERVAL="${RUN_INTERVAL:-1800}"
echo "[fapiao] 启动,轮询间隔 ${INTERVAL}s(改 RUN_INTERVAL 可调整)"

while true; do
  echo "[fapiao] $(date '+%F %T') 开始一轮"
  python -m fapiao run || echo "[fapiao] 本轮异常,已跳过,等待下一轮"
  echo "[fapiao] 休眠 ${INTERVAL}s"
  sleep "${INTERVAL}"
done
