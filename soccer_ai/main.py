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

from . import analyzer, backtest, config, movement, notifier, oddspapi_client, scheduler, selector, storage


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
        "--mode", choices=["movement", "backtest", "select", "tick"], default="movement",
        help="movement=全掃走勢(每小時)；backtest=賽果回填+CLV；select=選注→analyzer→存推薦；"
             "tick=逐場事件驅動(每場 t30m 觸發 movement+select，event_pipeline 用、與 movement 並行)",
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
    elif args.mode == "tick":
        stats = scheduler.run_tick(select_fn=lambda: _run_select(log))   # 逐場事件驅動；select 流程注入避循環匯入
        log.info("tick 完成：%s", stats)

    return 0


def _run_observations(log, observations: list) -> None:
    """觀察場（無 pick）：analyzer 解讀 → 存 observations 檔（**不進 recommendations、不推 Discord**）。

    選注唯一依據仍是 edge；觀察場只「顯示走勢 + AI 解讀」，不產生任何 pick。逐場隔離、失敗不阻斷。
    """
    stored = ai_ok = 0
    for obs in observations:
        fid = obs.get("fixtureId")
        try:
            date = config.local_date(obs["kickoff_utc"])
            prior = storage.find_observation(date, fid) or {}
            ai = analyzer.analyze_observation(obs, prior.get("ai"))  # 唯讀加法；含快取
            rec = {  # 精簡存檔：無 pick 欄，剝除 trajectory（細節頁讀走勢檔）
                "fixtureId": fid, "home": obs.get("home"), "away": obs.get("away"),
                "kickoff_utc": obs.get("kickoff_utc"), "kickoff_local": obs.get("kickoff_local"),
                "reason": obs.get("reason"),
                "produced_at_local": prior.get("produced_at_local") or config.now_local().isoformat(),
                "ai": ai,
            }
            storage.append_observation(rec, date_local=date)
            stored += 1
            ai_ok += 1 if ai.get("available") else 0
        except Exception as e:  # 單場失敗不阻斷
            log.warning("觀察場單場失敗 fixture=%s：%s", fid, e)
    log.info("觀察場完成：%d 場 / ai 可用 %d（無 pick、不推 Discord）", stored, ai_ok)


def _run_select(log) -> None:
    """#5 編排：selector→analyzer→存推薦→#4 notifier 推播。逐 pick 隔離、部分失敗不阻斷。"""
    bundle = selector.select_and_observe()
    picks = bundle["picks"]
    stored = ai_ok = 0
    reasons: dict = {}
    to_notify: list = []
    for pick in picks:
        fid = pick.get("fixtureId")
        try:
            record = storage.load_fixture_movement(fid) or {}
            date = config.local_date(pick["kickoff_utc"])          # 存撈共用 UTC+8 歸檔
            prior = storage.find_recommendation(date, fid, pick["market"], pick["side"]) or {}
            # produced_at_local：CLV 基準，首見凍結、重跑不更新
            pick["produced_at_local"] = prior.get("produced_at_local") or config.now_local().isoformat()
            pick["ai"] = analyzer.analyze(pick, record, prior.get("ai"))  # 含 C 快取；ai.produced_at 隨 hash
            # 帶入既有去重狀態(供 notifier.should_notify 比對)
            for k in ("notified_hash", "notified_at", "notified_ai_available"):
                if k in prior:
                    pick[k] = prior[k]
            storage.append_recommendation(pick, date_local=date)   # (fixtureId,market,side) upsert
            stored += 1
            if pick["ai"].get("available"):
                ai_ok += 1
            else:
                reasons[pick["ai"].get("reason")] = reasons.get(pick["ai"].get("reason"), 0) + 1
            if notifier.should_notify(pick):
                to_notify.append(pick)
        except Exception as e:  # 單筆失敗不阻斷其餘
            log.warning("select 單筆失敗 fixture=%s：%s", fid, e)
    nstats = notifier.notify_batch(to_notify)   # 整輪彙總一則多 embed（成功回寫 notified_*）
    log.info("選注完成：picks %d / 已存 %d / ai可用 %d / ai未用 %s / 推播 %s",
             len(picks), stored, ai_ok, reasons, nstats)
    _run_observations(log, bundle["observations"])   # 觀察場：解讀+存檔，不推 Discord


if __name__ == "__main__":
    sys.exit(main())
