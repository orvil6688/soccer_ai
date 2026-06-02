"""板塊四：主流程編排 + 失敗分流。

失敗分流雙軌（§1.2 / CLAUDE.md）：
  - 致命失敗（金鑰缺 / 額度盡）→ 記錄後中斷（exit 1）。
  - 部分失敗（單場錯 / 盤口對不上）→ 已於下游 log，不阻斷。

Phase 1 範圍：三窗口快照掃描。
Phase 2：D+1 賽果回填（backtest）。Phase 3：selector/analyzer/Discord 推播。
（下列分支以明確 TODO 標記預留，禁止裸 pass 吞掉流程。）
"""
from __future__ import annotations

import argparse
import logging
import sys

from . import api_client, config, snapshot


def _setup_logging() -> None:
    tag = f"{config.TEST_TAG} " if config.is_test_mode() else ""
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s {tag}%(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="世界盃盤口分析系統 主流程")
    parser.add_argument(
        "--test", action="store_true",
        help="測試模式：讀寫重定向至 data/test/，產出壓 🧪 標記",
    )
    parser.add_argument(
        "--mode", choices=["snapshot", "backtest"], default="snapshot",
        help="snapshot=三窗口快照掃描（Phase 1）；backtest=D+1 賽果回填（Phase 2）",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    if args.test:
        config.set_test_mode(True)
    _setup_logging()
    log = logging.getLogger("main")
    log.info("啟動 mode=%s test_mode=%s data_dir=%s", args.mode, config.is_test_mode(), config.data_dir())

    # --- 致命前置：金鑰缺失即中斷 ---
    try:
        config.require_key("API_FOOTBALL_KEY")
    except RuntimeError as e:
        log.error("致命中斷：%s", e)
        return 1

    # --- 取當前額度（供生存法則判定）---
    status = api_client.get_status()
    if status is None:
        log.warning("無法取得 API 用量狀態，依回應標頭動態判定額度")
    else:
        log.info("API 用量：已用 %d / 上限 %d（剩餘 %d）", status["used"], status["limit"], status["remaining"])
        if api_client.quota_exhausted():
            log.error("致命中斷：API 額度已達告警門檻（剩餘 %d）", status["remaining"])
            return 1

    if args.mode == "snapshot":
        stats = snapshot.run_snapshot_scan()
        log.info("快照完成：%s", {k: v for k, v in stats.items() if k != "details"})
    elif args.mode == "backtest":
        # TODO(Phase 2): 接 backtest.run_backfill() — D+1 抓前日 90min 賽果 + CLV 命中率
        log.error("backtest 模式尚未實作（Phase 2），本次不執行")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
