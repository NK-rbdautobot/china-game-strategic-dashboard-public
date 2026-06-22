#!/usr/bin/env python3
"""Canonicalize the dashboard's casual broad genre and subgenres.

Business rule from Peter Lee:
- The `캐주얼` broad genre may only contain these subgenres:
  방치, 경쟁/파티, 타워디펜스, 아케이드, 러닝, 로그라이크
- Existing `파티게임` labels are not a canonical subgenre anymore. Party/social
  casual games become `캐주얼 / 경쟁/파티`; non-casual false positives are moved
  to their better broad genre.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS = ROOT / "docs" / "downloads"
INDEX = ROOT / "docs" / "index.html"
FINAL_DB = DOWNLOADS / "china_game_final_strategic_genre_db.csv"
DASH_ROWS = DOWNLOADS / "china_game_dashboard_rows.csv"
SUB_SUMMARY = DOWNLOADS / "china_game_subcategory_summary.csv"
CASUAL_AUDIT = DOWNLOADS / "casual_subgenre_reclassification_audit.csv"

CASUAL_SUBS = ["방치", "경쟁/파티", "타워디펜스", "아케이드", "러닝", "로그라이크"]

# App-specific decisions for titles that were previously bucketed as `파티게임`
# under 스포츠/레이싱 even though that subgenre should not exist in the new model.
OVERRIDES = {
    "1544884479": ("캐주얼", "경쟁/파티", "오리지널 소셜 파티/UGC 경쟁 게임"),  # 蛋仔派对
    "1632344522": ("캐주얼", "경쟁/파티", "소셜 파티/UGC 경쟁 게임"),  # 元梦之星
    "1593603378": ("스포츠/레이싱", "스포츠", "NBA 라이선스 농구 스포츠 게임"),  # 全明星街球派对
    "1326730621": ("캐주얼", "경쟁/파티", "캐주얼 배틀로얄/멀티 경쟁 파티 성격"),  # 香肠派对
    "1300107673": ("음악/댄스", "리듬 탭", "걸즈 밴드 리듬 게임"),  # 梦想协奏曲！少女乐团派对！
    "6475333544": ("캐주얼", "경쟁/파티", "협동 요리 파티 게임"),  # 暴吵萌厨
    "1471085940": ("캐주얼", "경쟁/파티", "보드/추리 기반 멀티 파티 게임"),  # 推理学院
    "1596540193": ("슈팅", "슈팅", "전술 슈팅/TPS 성격이 강함"),  # 卡拉彼丘
    "6478924760": ("캐주얼", "경쟁/파티", "동물 캐릭터 기반 캐주얼 아레나 경쟁"),  # 动物王者
    "6448866237": ("수집형 게임", "수집/육성 카드", "신화 캐릭터 수집형 RPG/카드"),  # 众神派对
    "1636463825": ("캐주얼", "경쟁/파티", "소셜 시뮬레이션/파티 커뮤니티 게임"),  # 皮卡堂之梦想起源
}

# Keep current casual titles inside the six allowed subgenres, but repair labels
# if old names reappear in future generated files.
SUB_NORMALIZE = {
    "파티게임": "경쟁/파티",
    "라이트 경쟁": "경쟁/파티",
    "캐주얼 경쟁": "경쟁/파티",
    "캐주얼 슈팅": "아케이드",
}
BIG_NORMALIZE = {
    "FPS/TPS": "슈팅",
    "경기/스포츠·레이싱": "스포츠/레이싱",
    "애니메이션": "애니메이션/IP",
    "보드/체스/마작": "카지노",
    "카드게임": "수집형 게임",
}


def app_id_from_row(row: pd.Series) -> str:
    for col in ("App_ID", "App ID", "Qimai_App_ID"):
        if col in row.index and pd.notna(row[col]):
            s = str(row[col]).strip()
            if s.endswith(".0"):
                s = s[:-2]
            return s
    return ""


def apply_to_dataframe(df: pd.DataFrame, *, final_db: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.copy()
    changed_rows = []
    for idx, row in df.iterrows():
        app_id = app_id_from_row(row)
        old_big = str(row.get("战略大品类Tag", ""))
        old_sub = str(row.get("战略细分品类Tag", ""))
        big = BIG_NORMALIZE.get(old_big, old_big)
        sub = SUB_NORMALIZE.get(old_sub, old_sub)
        reason = "기존 캐주얼 세부분류 6종 유지/정규화"

        if app_id in OVERRIDES:
            big, sub, reason = OVERRIDES[app_id]
        elif big == "캐주얼":
            if sub not in CASUAL_SUBS:
                # Last-resort deterministic fallback for future stray labels.
                text = " ".join(str(row.get(c, "")) for c in row.index)
                if any(k in text for k in ["塔防", "守塔", "保卫", "Kingdom Rush", "植物大战僵尸"]):
                    sub = "타워디펜스"
                    reason = "키워드 기반 캐주얼/타워디펜스 정규화"
                elif any(k.lower() in text.lower() for k in ["roguelike", "肉鸽", "随机", "弓箭", "元气骑士", "弹壳"]):
                    sub = "로그라이크"
                    reason = "키워드 기반 캐주얼/로그라이크 정규화"
                elif any(k in text for k in ["跑酷", "跑", "러닝", "酷跑", "地铁跑酷"]):
                    sub = "러닝"
                    reason = "키워드 기반 캐주얼/러닝 정규화"
                elif any(k in text for k in ["放置", "挂机", "Idle", "AFK", "방치"]):
                    sub = "방치"
                    reason = "키워드 기반 캐주얼/방치 정규화"
                elif any(k in text for k in ["派对", "乱斗", "多人", "竞技", "社交", "聚会", "협동"]):
                    sub = "경쟁/파티"
                    reason = "키워드 기반 캐주얼/경쟁·파티 정규화"
                else:
                    sub = "아케이드"
                    reason = "기타 캐주얼 액션/클리커/미니게임 → 아케이드"

        # Write canonical fields.
        if "战略大品类Tag" in df.columns:
            df.at[idx, "战略大品类Tag"] = big
        if "战略细分品类Tag" in df.columns:
            df.at[idx, "战略细分品类Tag"] = sub
        if "전략대분류_KO" in df.columns:
            df.at[idx, "전략대분류_KO"] = big
        if "전략세부분류_KO" in df.columns:
            df.at[idx, "전략세부분류_KO"] = sub
        if final_db and (old_big != big or old_sub != sub) and "战略Tag_判定依据" in df.columns:
            df.at[idx, "战略Tag_判定依据"] = f"캐주얼 세부분류 재정리: {reason}"

        if old_big != big or old_sub != sub or big == "캐주얼":
            changed_rows.append({
                "App_ID": app_id,
                "게임명": row.get("Qimai_중국_게임명", row.get("게임명_중문", row.get("App Name", ""))),
                "기존_대분류": old_big,
                "기존_세부분류": old_sub,
                "최종_대분류": big,
                "최종_세부분류": sub,
                "판정근거": reason,
            })
    return df, pd.DataFrame(changed_rows)


def recompute_summaries(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    gross_krw = "Gross_KRW_원_12개월"
    gross_eok = "Gross_KRW_억원_12개월"
    gross_usd = "Gross_USD_12개월"
    name = "게임명_중문"
    broad = "战略大品类Tag"
    sub = "战略细分品类Tag"

    def reps(g: pd.DataFrame) -> str:
        return ", ".join(g.sort_values(gross_krw, ascending=False)[name].astype(str).head(8))

    big_records = []
    for b, g in rows.groupby(broad, dropna=False):
        big_records.append({
            "战略大品类Tag": b,
            "전략대분류_KO": b,
            "게임수": int(len(g)),
            gross_krw: float(g[gross_krw].sum()),
            gross_eok: float(g[gross_eok].sum()),
            gross_usd: float(g[gross_usd].sum()),
            "대표게임": reps(g),
        })
    big_df = pd.DataFrame(big_records).sort_values(gross_krw, ascending=False).reset_index(drop=True)
    big_df.insert(0, "순위", list(range(1, len(big_df) + 1)))

    sub_records = []
    for keys, g in rows.groupby([broad, sub], dropna=False):
        b, s = keys
        sub_records.append({
            "战略大品类Tag": b,
            "战略细分品类Tag": s,
            "전략대분류_KO": b,
            "전략세부분류_KO": s,
            "게임수": int(len(g)),
            gross_krw: float(g[gross_krw].sum()),
            gross_eok: float(g[gross_eok].sum()),
            gross_usd: float(g[gross_usd].sum()),
            "대표게임": reps(g),
        })
    sub_df = pd.DataFrame(sub_records).sort_values(gross_krw, ascending=False).reset_index(drop=True)
    return big_df, sub_df


def json_safe(value):
    """Convert pandas/numpy NaN values to JSON null for browser JSON.parse."""
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def replace_json_script(source: str, script_id: str, obj) -> str:
    payload = json.dumps(json_safe(obj), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    pattern = rf'(<script id="{script_id}" type="application/json">)(.*?)(</script>)'
    return re.sub(pattern, rf'\1{payload}\3', source, flags=re.S)


def update_index(rows: pd.DataFrame, big_df: pd.DataFrame, sub_df: pd.DataFrame) -> None:
    s = INDEX.read_text(encoding="utf-8")
    s = replace_json_script(s, "data", rows.to_dict(orient="records"))
    s = replace_json_script(s, "bigData", big_df.to_dict(orient="records"))
    s = replace_json_script(s, "subData", sub_df.to_dict(orient="records"))
    # Runtime guard: browser-local/Supabase stale edits should not reintroduce `파티게임`.
    if "'파티게임':'경쟁/파티'" not in s:
        s = s.replace("'라이트 경쟁':'경쟁/파티'", "'라이트 경쟁':'경쟁/파티','파티게임':'경쟁/파티'")
    INDEX.write_text(s, encoding="utf-8")


def main() -> None:
    final = pd.read_csv(FINAL_DB)
    dash = pd.read_csv(DASH_ROWS)

    final2, audit_final = apply_to_dataframe(final, final_db=True)
    dash2, audit_dash = apply_to_dataframe(dash, final_db=False)

    big_df, sub_df = recompute_summaries(dash2)

    final2.to_csv(FINAL_DB, index=False)
    dash2.to_csv(DASH_ROWS, index=False)
    sub_df.to_csv(SUB_SUMMARY, index=False)

    audit = pd.concat([audit_dash, audit_final], ignore_index=True)
    audit = audit.drop_duplicates(subset=["App_ID", "최종_대분류", "최종_세부분류"]).sort_values(["최종_대분류", "최종_세부분류", "게임명"])
    # The audit is intentionally focused on the final casual set plus rows moved out of old `파티게임`.
    audit.to_csv(CASUAL_AUDIT, index=False)

    update_index(dash2, big_df, sub_df)

    # Validate the contract.
    casual_subs = sorted(dash2.loc[dash2["战略大品类Tag"].eq("캐주얼"), "战略细分品类Tag"].unique())
    assert set(casual_subs) <= set(CASUAL_SUBS), casual_subs
    assert "파티게임" not in set(dash2["战略细分品类Tag"].astype(str)), "파티게임 remains in dashboard rows"

    src = INDEX.read_text(encoding="utf-8")
    for sid in ["data", "bigData", "subData", "cityData", "chinaMapData"]:
        m = re.search(rf'<script id="{sid}" type="application/json">(.*?)</script>', src, re.S)
        assert m, sid
        json.loads(html.unescape(m.group(1)))

    print("casual_subs", casual_subs)
    print("casual_count", int(dash2["战略大品类Tag"].eq("캐주얼").sum()))
    print("audit", CASUAL_AUDIT)


if __name__ == "__main__":
    main()
