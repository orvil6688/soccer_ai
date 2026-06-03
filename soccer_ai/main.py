"""板塊四：主流程編排 + 失敗分流（架構 A：OddsPapi 主源）。

失敗分流雙軌：
  - 致命（金鑰缺）→ 記錄後中斷（exit 1）。
  - 部分（單場錯/盤口對不上）→ 下游 log，不阻斷。

Phase 1（架構 A）：走勢拉取 + 六錨點推導。
Phase 2：D+1 賽果回填（/v4/settlements）+ CLV 自算。Phase 3：selector/analyzer/Discord。
"""
from __future__ import annotations

import argparse
import logging
import sys

from . import config, movement, oddspapi_client


def _setup_logging() -> None:
    tag = f"{config.TEST_TAG} " if config.is_test_mode() else ""
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s {tag}%(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="世界盃盤口分析系統 主流程（OddsPapi）")
    parser.add_argument("--test", action="store_true", help="測試模式：讀寫 data/test/、產出壓 🧪")
    parser.add_argument(
        "--mode", choices=["movement", "backtest"], default="movement",
        help="movement=走勢拉取+六錨點（Phase 1）；backtest=賽果回填+CLV（Phase 2）",
    )
    parser.add_argument(
        "--bookmaker", default=config.BOOKMAKER_PRIMARY,
        help=f"主抓 bookmaker（預設 {config.BOOKMAKER_PRIMARY}）",
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
        config.require_key("ODDSPAPI_API_KEY")
    except RuntimeError as e:
        log.error("致命中斷：%s", e)
        return 1

    # --- 額度狀態（不計額度的 /account）---
    acct = oddspapi_client.get_account()
    if acct is None:
        log.warning("無法取得 OddsPapi 用量狀態")
    else:
        log.info("OddsPapi 用量：已用 %d / 上限 %d（剩餘 %d, plan=%s）",
                 acct["request_count"], acct["request_limit"], acct["remaining"], acct["plan"])
        if acct["remaining"] <= config.REQUEST_ALERT_REMAINING:
            log.warning("額度告急：剩餘 %d（門檻 %d）", acct["remaining"], config.REQUEST_ALERT_REMAINING)

    if args.mode == "movement":
        stats = movement.scan(bookmaker=args.bookmaker)
        log.info("走勢完成：%s", stats)
    elif args.mode == "backtest":
        # TODO(Phase 2): backtest.run_backfill() — /v4/settlements 取賽果 + CLV 自算
        log.error("backtest 模式尚未實作（Phase 2），本次不執行")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
