#!/usr/bin/env python3
"""Comprehensive SQLite database integrity validation for Polily."""

import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone

DB_PATH = "data/polily.db"

OK = "\u2705"
WARN = "\u26a0\ufe0f"
FAIL = "\u274c"


def sep(title: str) -> str:
    return f"\n{'='*70}\n  {title}\n{'='*70}"


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def section_table_structure(conn: sqlite3.Connection):
    print(sep("1. 表结构完整性"))

    # List all tables
    tables = [
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'"
        ).fetchall()
    ]
    print(f"\n  数据库中的表: {', '.join(sorted(tables))}")

    # Row counts
    print(f"\n  {'表名':<25s} {'行数':>10s}")
    print(f"  {'-'*25} {'-'*10}")
    total_rows = 0
    for t in sorted(tables):
        cnt = conn.execute(f"SELECT count(*) FROM [{t}]").fetchone()[0]
        total_rows += cnt
        print(f"  {t:<25s} {cnt:>10,d}")
    print(f"  {'TOTAL':<25s} {total_rows:>10,d}")

    # Check expected tables
    expected = {
        "events",
        "markets",
        "event_monitors",
        "notifications",
        "scan_logs",
        "analyses",
        "movement_log",
        "positions",
        "wallet",
        "wallet_transactions",
    }
    present = set(tables)
    missing = expected - present
    extra = present - expected
    if missing:
        print(f"\n  {FAIL} 缺少核心表: {', '.join(missing)}")
    else:
        print(f"\n  {OK} 8张核心表全部存在")
    # Note: the spec says "analysis_versions" but actual table is "analyses"
    if "analyses" in present and "analysis_versions" not in present:
        print(f"  {WARN} 注意: 表名为 'analyses' 而非 'analysis_versions' (schema差异)")
    if extra:
        print(f"  额外的表: {', '.join(extra)}")


def section_events(conn: sqlite3.Connection):
    print(sep("2. Events 表"))

    events = conn.execute("SELECT * FROM events").fetchall()
    n = len(events)
    print(f"\n  总行数: {n}")

    # Required fields
    for field in ["event_id", "title", "structure_score", "tier"]:
        nulls = sum(1 for e in events if e[field] is None)
        if nulls == 0:
            print(f"  {OK} {field}: 全部非NULL")
        else:
            print(f"  {FAIL} {field}: {nulls}/{n} 行为NULL ({nulls/n*100:.1f}%)")

    # Duplicate event_id
    ids = [e["event_id"] for e in events if e["event_id"]]
    dupes = [eid for eid, cnt in Counter(ids).items() if cnt > 1]
    if dupes:
        print(f"  {FAIL} 重复 event_id: {len(dupes)} 个 — {dupes[:5]}")
    else:
        print(f"  {OK} event_id 无重复")

    # structure_score range
    scores = [e["structure_score"] for e in events if e["structure_score"] is not None]
    if scores:
        lo, hi = min(scores), max(scores)
        out_of_range = [s for s in scores if s < 0 or s > 100]
        print(f"  structure_score 范围: [{lo:.1f}, {hi:.1f}]")
        if out_of_range:
            print(f"  {FAIL} {len(out_of_range)} 个 score 超出 [0,100]")
        else:
            print(f"  {OK} 所有 score 在 [0,100] 范围内")

    # tier distribution
    tier_dist = Counter(e["tier"] for e in events)
    print(f"\n  tier 分布:")
    for t, c in tier_dist.most_common():
        print(f"    {str(t):<20s} {c:>6d} ({c/n*100:.1f}%)")

    # closed distribution
    closed_dist = Counter(e["closed"] for e in events)
    print(f"\n  closed 分布:")
    for c_val, cnt in closed_dist.most_common():
        print(f"    closed={str(c_val):<10s} {cnt:>6d} ({cnt/n*100:.1f}%)")

    # end_date
    has_end = sum(1 for e in events if e["end_date"])
    print(f"\n  有 end_date: {has_end}/{n} ({has_end/n*100:.1f}%)")
    no_end = n - has_end
    if no_end > 0:
        print(f"  {WARN} {no_end} 个 event 无 end_date")
    else:
        print(f"  {OK} 所有 event 都有 end_date")

    # description
    has_desc = sum(1 for e in events if e["description"])
    print(f"  有 description: {has_desc}/{n} ({has_desc/n*100:.1f}%)")

    # market_type distribution
    mt_dist = Counter(e["market_type"] for e in events)
    print(f"\n  market_type 分布:")
    for mt, c in mt_dist.most_common():
        print(f"    {str(mt):<20s} {c:>6d} ({c/n*100:.1f}%)")


def section_markets(conn: sqlite3.Connection):
    print(sep("3. Markets 表"))

    markets = conn.execute("SELECT * FROM markets").fetchall()
    n = len(markets)
    print(f"\n  总行数: {n}")

    # Required fields
    for field in ["market_id", "event_id", "question"]:
        nulls = sum(1 for m in markets if m[field] is None)
        if nulls == 0:
            print(f"  {OK} {field}: 全部非NULL")
        else:
            print(f"  {FAIL} {field}: {nulls}/{n} 行为NULL ({nulls/n*100:.1f}%)")

    # Duplicate market_id
    ids = [m["market_id"] for m in markets if m["market_id"]]
    dupes = [mid for mid, cnt in Counter(ids).items() if cnt > 1]
    if dupes:
        print(f"  {FAIL} 重复 market_id: {len(dupes)} 个")
    else:
        print(f"  {OK} market_id 无重复")

    # Foreign key integrity
    event_ids_in_events = set(
        r["event_id"]
        for r in conn.execute("SELECT event_id FROM events").fetchall()
    )
    orphan_markets = [
        m["market_id"]
        for m in markets
        if m["event_id"] not in event_ids_in_events
    ]
    if orphan_markets:
        print(f"  {FAIL} 孤儿 market (event_id 不在 events 表): {len(orphan_markets)} 个")
        for om in orphan_markets[:5]:
            print(f"    - {om}")
    else:
        print(f"  {OK} 外键完整性: 所有 market.event_id 都存在于 events 表")

    # yes_price range
    prices = [m["yes_price"] for m in markets if m["yes_price"] is not None]
    if prices:
        lo, hi = min(prices), max(prices)
        out = [p for p in prices if p < 0 or p > 1]
        print(f"\n  yes_price 范围: [{lo:.4f}, {hi:.4f}], 有值: {len(prices)}/{n}")
        if out:
            print(f"  {FAIL} {len(out)} 个 yes_price 超出 [0,1]")
        else:
            print(f"  {OK} 所有 yes_price 在 [0,1] 范围内")
    else:
        print(f"  {WARN} 没有 yes_price 数据")

    # volume > 0
    has_vol = sum(1 for m in markets if m["volume"] and m["volume"] > 0)
    print(f"  volume > 0: {has_vol}/{n} ({has_vol/n*100:.1f}%)")

    # structure_score
    has_ss = sum(1 for m in markets if m["structure_score"] is not None)
    print(f"  有 structure_score: {has_ss}/{n} ({has_ss/n*100:.1f}%)")

    # score_breakdown
    has_sb = 0
    bad_json = 0
    dimension_ok = 0
    dimension_fail = 0
    expected_dims = {"liquidity", "verifiability", "probability", "time", "friction"}
    net_edge_present = 0
    for m in markets:
        sb = m["score_breakdown"]
        if sb:
            has_sb += 1
            try:
                parsed = json.loads(sb)
                keys = set(parsed.keys())
                if expected_dims.issubset(keys):
                    dimension_ok += 1
                else:
                    dimension_fail += 1
                if "net_edge" in keys:
                    net_edge_present += 1
            except (json.JSONDecodeError, TypeError):
                bad_json += 1
    print(f"  有 score_breakdown: {has_sb}/{n} ({has_sb/n*100:.1f}%)")
    if bad_json:
        print(f"  {FAIL} score_breakdown JSON 解析失败: {bad_json} 个")
    else:
        print(f"  {OK} score_breakdown JSON 全部可解析")
    if dimension_fail:
        print(
            f"  {WARN} score_breakdown 缺少核心维度: {dimension_fail}/{has_sb}"
        )
    elif has_sb > 0:
        print(
            f"  {OK} score_breakdown 核心5维度完整: {dimension_ok}/{has_sb}"
        )
    print(f"  score_breakdown 含 net_edge: {net_edge_present}/{has_sb}")

    # clob_token_id_yes
    has_clob = sum(1 for m in markets if m["clob_token_id_yes"])
    print(f"\n  有 clob_token_id_yes: {has_clob}/{n} ({has_clob/n*100:.1f}%)")

    # best_bid / best_ask
    has_bid = sum(1 for m in markets if m["best_bid"] is not None)
    has_ask = sum(1 for m in markets if m["best_ask"] is not None)
    print(f"  有 best_bid: {has_bid}/{n} ({has_bid/n*100:.1f}%)")
    print(f"  有 best_ask: {has_ask}/{n} ({has_ask/n*100:.1f}%)")

    # bid_depth / ask_depth
    has_bd = sum(1 for m in markets if m["bid_depth"] is not None)
    has_ad = sum(1 for m in markets if m["ask_depth"] is not None)
    print(f"  有 bid_depth: {has_bd}/{n} ({has_bd/n*100:.1f}%)")
    print(f"  有 ask_depth: {has_ad}/{n} ({has_ad/n*100:.1f}%)")

    # market_type — markets table doesn't have market_type directly,
    # so we join with events to get it
    # Actually, let's check if markets has a market_type column
    cols = [c["name"] for c in conn.execute("PRAGMA table_info(markets)").fetchall()]
    if "market_type" in cols:
        mt_dist = Counter(m["market_type"] for m in markets)
        print(f"\n  market_type 分布 (markets表):")
        for mt, c in mt_dist.most_common():
            print(f"    {str(mt):<20s} {c:>6d} ({c/n*100:.1f}%)")
    else:
        # Use event-level market_type
        print(f"\n  (markets表无 market_type 列，使用 events 表关联)")
        rows = conn.execute("""
            SELECT e.market_type, count(*) as cnt
            FROM markets m JOIN events e ON m.event_id = e.event_id
            GROUP BY e.market_type
            ORDER BY cnt DESC
        """).fetchall()
        print(f"  market_type 分布 (via events):")
        for r in rows:
            print(f"    {str(r['market_type']):<20s} {r['cnt']:>6d}")

    # closed distribution
    closed_dist = Counter(m["closed"] for m in markets)
    print(f"\n  closed 分布:")
    for c_val, cnt in closed_dist.most_common():
        print(f"    closed={str(c_val):<10s} {cnt:>6d} ({cnt/n*100:.1f}%)")


def section_consistency(conn: sqlite3.Connection):
    print(sep("4. 数据一致性"))

    # market_count vs actual
    print("\n  --- event.market_count vs 实际 market 数量 ---")
    rows = conn.execute("""
        SELECT e.event_id, e.title, e.market_count,
               (SELECT count(*) FROM markets m WHERE m.event_id = e.event_id) as actual_count
        FROM events e
    """).fetchall()
    mismatches = [(r["event_id"], r["title"][:40], r["market_count"], r["actual_count"])
                  for r in rows if r["market_count"] != r["actual_count"]]
    if mismatches:
        print(f"  {FAIL} market_count 不匹配: {len(mismatches)} 个 event")
        for eid, title, expected, actual in mismatches[:10]:
            print(f"    {eid[:12]}.. {title:<40s} expected={expected} actual={actual}")
        if len(mismatches) > 10:
            print(f"    ... 还有 {len(mismatches)-10} 个")
    else:
        print(f"  {OK} 所有 event.market_count 与实际 market 数量一致")

    # event structure_score vs max sub-market score
    print("\n  --- event.structure_score vs sub-market 最高 score ---")
    rows = conn.execute("""
        SELECT e.event_id, e.structure_score as event_score,
               max(m.structure_score) as max_market_score,
               count(m.market_id) as mkt_cnt
        FROM events e
        LEFT JOIN markets m ON m.event_id = e.event_id
        WHERE e.structure_score IS NOT NULL
        GROUP BY e.event_id
    """).fetchall()
    score_diffs = []
    for r in rows:
        if r["max_market_score"] is not None and r["event_score"] is not None:
            diff = abs(r["event_score"] - r["max_market_score"])
            if diff > 0.01:
                score_diffs.append((r["event_id"], r["event_score"], r["max_market_score"], diff))
    if score_diffs:
        print(f"  {WARN} event_score != max(market_score): {len(score_diffs)} 个")
        for eid, es, ms, d in sorted(score_diffs, key=lambda x: -x[3])[:10]:
            print(f"    {eid[:12]}..  event={es:.1f}  max_market={ms:.1f}  diff={d:.1f}")
    else:
        print(f"  {OK} event.structure_score 与 max(market.structure_score) 一致")

    # yes_price + no_price ~ 1.0
    print("\n  --- yes_price + no_price ≈ 1.0 ---")
    rows = conn.execute("""
        SELECT market_id, question, yes_price, no_price
        FROM markets
        WHERE yes_price IS NOT NULL AND no_price IS NOT NULL
    """).fetchall()
    bad_sum = []
    for r in rows:
        s = r["yes_price"] + r["no_price"]
        if abs(s - 1.0) > 0.05:
            bad_sum.append((r["market_id"], r["question"][:40], r["yes_price"], r["no_price"], s))
    print(f"  有 yes+no price 的 market: {len(rows)}")
    if bad_sum:
        print(f"  {FAIL} yes_price + no_price 偏差 > 0.05: {len(bad_sum)} 个")
        for mid, q, yp, np, s in bad_sum[:10]:
            print(f"    {mid[:12]}.. {q:<40s} yes={yp:.3f} no={np:.3f} sum={s:.3f}")
    else:
        print(f"  {OK} 所有 yes+no price 之和偏差 < 0.05")

    # Sums distribution
    if rows:
        sums = [r["yes_price"] + r["no_price"] for r in rows]
        print(f"  sum 统计: min={min(sums):.4f} max={max(sums):.4f} avg={sum(sums)/len(sums):.4f}")

    # best_bid <= yes_price <= best_ask
    print("\n  --- best_bid <= yes_price <= best_ask ---")
    rows = conn.execute("""
        SELECT market_id, question, yes_price, best_bid, best_ask
        FROM markets
        WHERE yes_price IS NOT NULL AND best_bid IS NOT NULL AND best_ask IS NOT NULL
    """).fetchall()
    price_violations = []
    for r in rows:
        yp, bb, ba = r["yes_price"], r["best_bid"], r["best_ask"]
        if bb > yp + 0.001 or yp > ba + 0.001:
            price_violations.append((r["market_id"], r["question"][:40], bb, yp, ba))
    print(f"  有 bid/ask/price 的 market: {len(rows)}")
    if price_violations:
        print(f"  {WARN} 价格不满足 bid <= price <= ask: {len(price_violations)} 个")
        for mid, q, bb, yp, ba in price_violations[:10]:
            print(f"    {mid[:12]}.. {q:<40s} bid={bb:.3f} price={yp:.3f} ask={ba:.3f}")
    elif rows:
        print(f"  {OK} 所有价格满足 bid <= price <= ask")
    else:
        print(f"  {WARN} 没有同时有 bid/ask/price 的 market")

    # Crypto net_edge check
    print("\n  --- crypto market net_edge 检查 ---")
    crypto_rows = conn.execute("""
        SELECT m.market_id, m.score_breakdown, e.market_type
        FROM markets m JOIN events e ON m.event_id = e.event_id
        WHERE m.score_breakdown IS NOT NULL
    """).fetchall()
    crypto_no_edge = 0
    crypto_has_edge = 0
    noncrypto_nonzero_edge = 0
    noncrypto_total = 0
    parse_errors = 0
    for r in crypto_rows:
        try:
            sb = json.loads(r["score_breakdown"])
        except (json.JSONDecodeError, TypeError):
            parse_errors += 1
            continue
        mt = r["market_type"]
        ne = sb.get("net_edge", 0)
        if mt == "crypto":
            if ne and ne != 0:
                crypto_has_edge += 1
            else:
                crypto_no_edge += 1
        else:
            noncrypto_total += 1
            if ne and ne != 0:
                noncrypto_nonzero_edge += 1
    print(f"  crypto market 有 net_edge: {crypto_has_edge}, 无 net_edge: {crypto_no_edge}")
    if noncrypto_nonzero_edge:
        print(f"  {WARN} non-crypto market 有非零 net_edge: {noncrypto_nonzero_edge}/{noncrypto_total}")
    else:
        print(f"  {OK} non-crypto market net_edge 均为 0 或不存在 ({noncrypto_total} 个)")


def section_quality(conn: sqlite3.Connection):
    print(sep("5. 数据质量"))

    events = conn.execute("SELECT * FROM events").fetchall()
    markets = conn.execute("SELECT * FROM markets").fetchall()
    n_e = len(events)
    n_m = len(markets)

    # NULL stats for key fields
    print("\n  --- Events 关键字段 NULL 统计 ---")
    event_fields = [
        "event_id", "title", "structure_score", "tier",
        "market_type", "volume", "liquidity", "end_date"
    ]
    for f in event_fields:
        nulls = sum(1 for e in events if e[f] is None)
        pct = nulls / n_e * 100 if n_e else 0
        marker = OK if nulls == 0 else (WARN if pct < 20 else FAIL)
        print(f"  {marker} {f:<25s} NULL: {nulls:>5d}/{n_e} ({pct:.1f}%)")

    print(f"\n  --- Markets 关键字段 NULL 统计 ---")
    market_fields = [
        "market_id", "event_id", "question", "yes_price", "no_price",
        "structure_score", "score_breakdown", "best_bid", "best_ask",
        "volume", "liquidity", "clob_token_id_yes", "bid_depth", "ask_depth"
    ]
    for f in market_fields:
        nulls = sum(1 for m in markets if m[f] is None)
        pct = nulls / n_m * 100 if n_m else 0
        marker = OK if nulls == 0 else (WARN if pct < 20 else FAIL)
        print(f"  {marker} {f:<25s} NULL: {nulls:>5d}/{n_m} ({pct:.1f}%)")

    # structure_score = 0
    zero_score_events = sum(1 for e in events if e["structure_score"] == 0)
    zero_score_markets = sum(1 for m in markets if m["structure_score"] == 0)
    print(f"\n  structure_score = 0: events={zero_score_events}, markets={zero_score_markets}")
    if zero_score_events or zero_score_markets:
        print(f"  {WARN} 有 score=0 的记录，可能是未评分")

    # Expired but not closed
    print("\n  --- 过期但未关闭 ---")
    now_iso = datetime.now(timezone.utc).isoformat()
    expired_open_events = conn.execute("""
        SELECT count(*) FROM events
        WHERE end_date IS NOT NULL AND end_date < ? AND closed = 0
    """, (now_iso,)).fetchone()[0]
    expired_open_markets = conn.execute("""
        SELECT count(*) FROM markets
        WHERE end_date IS NOT NULL AND end_date < ? AND closed = 0
    """, (now_iso,)).fetchone()[0]
    if expired_open_events:
        print(f"  {WARN} 过期但 closed=0 的 event: {expired_open_events}")
    else:
        print(f"  {OK} 没有过期但未关闭的 event")
    if expired_open_markets:
        print(f"  {WARN} 过期但 closed=0 的 market: {expired_open_markets}")
    else:
        print(f"  {OK} 没有过期但未关闭的 market")

    # score_breakdown parse failures (comprehensive)
    bad_json = 0
    for m in markets:
        sb = m["score_breakdown"]
        if sb:
            try:
                json.loads(sb)
            except (json.JSONDecodeError, TypeError):
                bad_json += 1
    if bad_json:
        print(f"\n  {FAIL} score_breakdown JSON 解析失败: {bad_json} 个")
    else:
        print(f"\n  {OK} 所有 score_breakdown JSON 格式正确")


def section_other_tables(conn: sqlite3.Connection):
    print(sep("6. 其他表"))

    # event_monitors
    print("\n  --- event_monitors ---")
    total_mon = conn.execute("SELECT count(*) FROM event_monitors").fetchone()[0]
    active_mon = conn.execute(
        "SELECT count(*) FROM event_monitors WHERE auto_monitor = 1"
    ).fetchone()[0]
    has_next = conn.execute(
        "SELECT count(*) FROM event_monitors WHERE next_check_at IS NOT NULL"
    ).fetchone()[0]
    print(f"  总记录: {total_mon}")
    print(f"  auto_monitor=1 (活跃监控): {active_mon}")
    print(f"  有 next_check_at: {has_next}")
    # Check orphan monitors
    orphan_mon = conn.execute("""
        SELECT count(*) FROM event_monitors em
        WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.event_id = em.event_id)
    """).fetchone()[0]
    if orphan_mon:
        print(f"  {WARN} 孤儿监控 (event_id 不在 events 表): {orphan_mon}")
    else:
        print(f"  {OK} 监控外键完整")

    # scan_logs
    print("\n  --- scan_logs ---")
    total_scans = conn.execute("SELECT count(*) FROM scan_logs").fetchone()[0]
    print(f"  总记录: {total_scans}")
    if total_scans > 0:
        status_dist = conn.execute(
            "SELECT status, count(*) as cnt FROM scan_logs GROUP BY status ORDER BY cnt DESC"
        ).fetchall()
        for r in status_dist:
            print(f"    status={r['status']:<15s} {r['cnt']:>5d}")

        recent = conn.execute(
            "SELECT scan_id, type, started_at, finished_at, status, total_markets, research_count, watchlist_count, filtered_count "
            "FROM scan_logs ORDER BY started_at DESC LIMIT 3"
        ).fetchall()
        print(f"\n  最近3条扫描记录:")
        for r in recent:
            print(
                f"    {r['started_at'][:19]} type={r['type']:<10s} status={r['status']:<10s} "
                f"total={r['total_markets']} R={r['research_count']} W={r['watchlist_count']} F={r['filtered_count']}"
            )

    # analyses
    print("\n  --- analyses ---")
    total_analyses = conn.execute("SELECT count(*) FROM analyses").fetchone()[0]
    print(f"  总记录: {total_analyses}")
    if total_analyses > 0:
        trigger_dist = conn.execute(
            "SELECT trigger_source, count(*) as cnt FROM analyses GROUP BY trigger_source ORDER BY cnt DESC"
        ).fetchall()
        for r in trigger_dist:
            print(f"    trigger_source={r['trigger_source']:<15s} {r['cnt']:>5d}")
        # Version stats
        max_ver = conn.execute("SELECT max(version) FROM analyses").fetchone()[0]
        avg_ver = conn.execute("SELECT avg(version) FROM analyses").fetchone()[0]
        print(f"  版本统计: max={max_ver}, avg={avg_ver:.1f}")

    # movement_log
    print("\n  --- movement_log ---")
    total_mvt = conn.execute("SELECT count(*) FROM movement_log").fetchone()[0]
    print(f"  总记录: {total_mvt}")
    if total_mvt > 0:
        label_dist = conn.execute(
            "SELECT label, count(*) as cnt FROM movement_log GROUP BY label ORDER BY cnt DESC"
        ).fetchall()
        for r in label_dist:
            print(f"    label={r['label']:<20s} {r['cnt']:>5d}")
        triggered = conn.execute(
            "SELECT count(*) FROM movement_log WHERE triggered_analysis = 1"
        ).fetchone()[0]
        print(f"  触发分析: {triggered}/{total_mvt}")

    # positions (v0.6.0)
    print("\n  --- positions ---")
    total_pos = conn.execute("SELECT count(*) FROM positions").fetchone()[0]
    print(f"  活跃持仓: {total_pos}")
    if total_pos > 0:
        side_dist = conn.execute(
            "SELECT side, count(*) as cnt FROM positions GROUP BY side ORDER BY cnt DESC"
        ).fetchall()
        for r in side_dist:
            print(f"    side={r['side']:<5s} {r['cnt']:>5d}")

    # wallet_transactions (v0.6.0 ledger)
    print("\n  --- wallet_transactions ---")
    total_tx = conn.execute("SELECT count(*) FROM wallet_transactions").fetchone()[0]
    print(f"  总记录: {total_tx}")
    if total_tx > 0:
        type_dist = conn.execute(
            "SELECT type, count(*) as cnt FROM wallet_transactions GROUP BY type ORDER BY cnt DESC"
        ).fetchall()
        for r in type_dist:
            print(f"    type={r['type']:<10s} {r['cnt']:>5d}")

    # notifications
    print("\n  --- notifications ---")
    total_notif = conn.execute("SELECT count(*) FROM notifications").fetchone()[0]
    print(f"  总记录: {total_notif}")
    if total_notif > 0:
        unread = conn.execute(
            "SELECT count(*) FROM notifications WHERE is_read = 0"
        ).fetchone()[0]
        print(f"  未读: {unread}/{total_notif}")


def section_summary(conn: sqlite3.Connection):
    print(sep("7. 综合摘要"))

    n_events = conn.execute("SELECT count(*) FROM events").fetchone()[0]
    n_markets = conn.execute("SELECT count(*) FROM markets").fetchone()[0]
    n_research = conn.execute(
        "SELECT count(*) FROM events WHERE tier='research'"
    ).fetchone()[0]
    n_watchlist = conn.execute(
        "SELECT count(*) FROM events WHERE tier='watchlist'"
    ).fetchone()[0]
    n_filtered = conn.execute(
        "SELECT count(*) FROM events WHERE tier='filtered'"
    ).fetchone()[0]
    avg_score = conn.execute(
        "SELECT avg(structure_score) FROM events WHERE structure_score IS NOT NULL"
    ).fetchone()[0]
    avg_market_score = conn.execute(
        "SELECT avg(structure_score) FROM markets WHERE structure_score IS NOT NULL"
    ).fetchone()[0]

    print(f"""
  Events:  {n_events}
  Markets: {n_markets}
  比例:    {n_markets/n_events:.1f} markets/event

  Tier 分布:
    research:  {n_research:>5d} ({n_research/n_events*100:.1f}%)
    watchlist: {n_watchlist:>5d} ({n_watchlist/n_events*100:.1f}%)
    filtered:  {n_filtered:>5d} ({n_filtered/n_events*100:.1f}%)

  平均 structure_score:
    events:  {avg_score:.1f}
    markets: {avg_market_score:.1f}
""")


def main():
    print(f"\n{'#'*70}")
    print(f"  Polily 数据库完整性验证报告")
    print(f"  数据库: {DB_PATH}")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*70}")

    conn = connect()

    # SQLite integrity check
    result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if result == "ok":
        print(f"\n{OK} SQLite PRAGMA integrity_check: OK")
    else:
        print(f"\n{FAIL} SQLite PRAGMA integrity_check: {result}")

    section_table_structure(conn)
    section_events(conn)
    section_markets(conn)
    section_consistency(conn)
    section_quality(conn)
    section_other_tables(conn)
    section_summary(conn)

    conn.close()
    print(f"\n{'='*70}")
    print(f"  验证完成")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
