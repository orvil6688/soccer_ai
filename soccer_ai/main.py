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

from . import analyzer, backtest, config, movement, oddspapi_client, selector, storage


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
        "--mode", choices=["movement", "backtest", "select"], default="movement",
        help="movement=走勢+軌跡；backtest=賽果回填+CLV；select=選注→analyzer→存推薦（閉環）",
    )
    parser.add_argument(
        "--bookmaker", default=config.BOOKMAKER_PRIMARY,
        help=f"主抓 bookmaker（預設 {config.BOOKMAKER_PRIMARY}）",
    )
    parser.add_argument(
        "--date", default=None,
        help="backtest 回填日期 YYYY-MM-DD（UTC+8；預設前一日）",
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
        stats = movement.scan()  # 雙 book（config.MOVEMENT_BOOKMAKERS）
        log.info("走勢完成：%s", stats)
    elif args.mode == "backtest":
        m = backtest.run_backfill(date_local=args.date, bookmaker=args.bookmaker)
        log.info("回測完成：%s", {k: v for k, v in m.items() if k != "breakdown"})
    elif args.mode == "select":
        _run_select(log)

    return 0


def _run_select(log) -> None:
    """#5 編排：selector→analyzer→存推薦（閉環接 backtest）。逐 pick 隔離、部分失敗不阻斷。"""
    picks = selector.select()
    stored = ai_ok = 0
    reasons: dict = {}
    for pick in picks:
        fid = pick.get("fixtureId")
        try:
            record = storage.load_fixture_movement(fid) or {}
            date = config.local_date(pick["kickoff_utc"])          # 存撈共用 UTC+8 歸檔
            prior = storage.find_recommendation(date, fid, pick["market"], pick["side"])
            # produced_at_local：CLV 基準，首見凍結、重跑不更新
            pick["produced_at_local"] = (prior or {}).get("produced_at_local") or config.now_local().isoformat()
            prior_ai = (prior or {}).get("ai")
            pick["ai"] = analyzer.analyze(pick, record, prior_ai)  # 內含 C 快取；ai.produced_at 隨 hash 更新
            storage.append_recommendation(pick, date_local=date)   # (fixtureId,market,side) upsert
            stored += 1
            if pick["ai"].get("available"):
                ai_ok += 1
            else:
                r = pick["ai"].get("reason")
                reasons[r] = reasons.get(r, 0) + 1
        except Exception as e:  # 單筆失敗不阻斷其餘
            log.warning("select 單筆失敗 fixture=%s：%s", fid, e)
    log.info("選注完成：picks %d / 已存 %d / ai可用 %d / ai未用 %s", len(picks), stored, ai_ok, reasons)


if __name__ == "__main__":
    sys.exit(main())
