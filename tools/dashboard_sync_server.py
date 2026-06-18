# -*- coding: utf-8 -*-
"""Local edit-sync server for the China game strategic genre dashboard.

Run:
  python3 dashboard_sync_server.py
Then open:
  http://127.0.0.1:8765/

The static dashboard can display from file://, but browser pages cannot write to
local CSV/XLSX/SQLite files directly. This tiny localhost server is the bridge:
when a genre select box changes, the dashboard POSTs the change here and this
script updates the canonical DB files in place.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

import pandas as pd

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "qimai_developer_genre_archive_2025-01_2026-05" / "launch_12m_revenue_st_priority"
SRC_CSV = BASE / "중국게임_최종_DB_전략장르태그_추가.csv"
SRC_XLSX = BASE / "중국게임_최종_DB_전략장르태그_추가.xlsx"
SQLITE = BASE / "중국게임_1000개_ST우선출시일_12개월_iOS매출_DB.sqlite"
HTML = BASE / "중국게임_최종_DB_전략장르_매출대시보드_WEB.html"
BUILDER = ROOT / "build_strategic_web_dashboard.py"
BACKUP_DIR = BASE / "dashboard_sync_backups"
HOST = "0.0.0.0"
PORT = 8765
OUT_DASH_CSV = BASE / "중국게임_최종_DB_전략장르_웹대시보드용_전체.csv"
OUT_BIG_CSV = BASE / "중국게임_최종_DB_전략대분류_매출요약.csv"
OUT_SUB_CSV = BASE / "중국게임_최종_DB_전략세부분류_매출요약.csv"

TAG_COLS = ["战略大品类Tag", "战略细分品类Tag", "전략대분류_KO", "전략세부분류_KO"]
TABLES_TO_UPDATE = ["launch_12m_revenue_games", "strategic_tag_review_needed"]


def app_id_text(v) -> str:
    s = "" if pd.isna(v) else str(v).strip()
    return s[:-2] if s.endswith(".0") else s


def load_source() -> pd.DataFrame:
    return pd.read_csv(SRC_CSV, encoding="utf-8-sig")


def tag_maps(df: pd.DataFrame):
    big_map: dict[str, str] = {}
    sub_map: dict[tuple[str, str], str] = {}
    for _, row in df.iterrows():
        big = str(row.get("战略大品类Tag", "") or "").strip()
        sub = str(row.get("战略细分品类Tag", "") or "").strip()
        big_ko = str(row.get("전략대분류_KO", "") or "").strip()
        sub_ko = str(row.get("전략세부분류_KO", "") or "").strip()
        if big and big_ko and big not in big_map:
            big_map[big] = big_ko
        if big and sub and sub_ko and (big, sub) not in sub_map:
            sub_map[(big, sub)] = sub_ko
    return big_map, sub_map


def backup_once_per_run() -> None:
    marker = BACKUP_DIR / ".backup_done_this_server_run"
    if marker.exists():
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    for p in [SRC_CSV, SRC_XLSX, SQLITE]:
        if p.exists():
            shutil.copy2(p, BACKUP_DIR / f"{p.stem}.before_dashboard_sync_{ts}{p.suffix}")
    marker.write_text(ts, encoding="utf-8")


def write_xlsx(df: pd.DataFrame) -> None:
    # Keep a clean one-sheet workbook in sync with the canonical CSV. If Excel has
    # the file open, this may fail; the CSV/SQLite update is still authoritative.
    try:
        df.to_excel(SRC_XLSX, index=False, engine="openpyxl")
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] XLSX sync skipped: {exc}", file=sys.stderr)


def update_sqlite(app_id: str, big: str, sub: str, big_ko: str, sub_ko: str) -> dict:
    if not SQLITE.exists():
        return {"updated_tables": {}, "warning": "SQLite file not found"}
    con = sqlite3.connect(SQLITE)
    cur = con.cursor()
    updated: dict[str, int] = {}
    try:
        for table in TABLES_TO_UPDATE:
            exists = cur.execute(
                "select 1 from sqlite_master where type='table' and name=?", (table,)
            ).fetchone()
            if not exists:
                continue
            cols = {r[1] for r in cur.execute(f'pragma table_info("{table}")')}
            if not set(TAG_COLS).issubset(cols) or "App ID" not in cols:
                continue
            cur.execute(
                f'''update "{table}" set
                    "战略大品类Tag"=?,
                    "战略细分品类Tag"=?,
                    "전략대분류_KO"=?,
                    "전략세부분류_KO"=?
                   where cast("App ID" as text)=?''',
                (big, sub, big_ko, sub_ko, app_id),
            )
            updated[table] = cur.rowcount
        con.commit()
    finally:
        con.close()
    return {"updated_tables": updated}


def rebuild_outputs() -> dict:
    if not BUILDER.exists():
        return {"rebuilt": False, "warning": "builder script not found"}
    proc = subprocess.run(
        [sys.executable, str(BUILDER)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=120,
    )
    if proc.returncode != 0:
        return {"rebuilt": False, "error": proc.stderr[-2000:] or proc.stdout[-2000:]}
    try:
        return {"rebuilt": True, "builder": json.loads(proc.stdout)}
    except Exception:
        return {"rebuilt": True, "builder_stdout": proc.stdout[-1000:]}


def read_dashboard_state() -> dict:
    """Return current generated dashboard payload for live multi-user polling."""
    # Ensure derived CSVs exist and are fresh enough after manual edits.
    if not OUT_DASH_CSV.exists() or OUT_DASH_CSV.stat().st_mtime < SRC_CSV.stat().st_mtime:
        rebuild_outputs()
    data = pd.read_csv(OUT_DASH_CSV, encoding="utf-8-sig").fillna("").to_dict("records")
    big = pd.read_csv(OUT_BIG_CSV, encoding="utf-8-sig").fillna("").to_dict("records") if OUT_BIG_CSV.exists() else []
    sub = pd.read_csv(OUT_SUB_CSV, encoding="utf-8-sig").fillna("").to_dict("records") if OUT_SUB_CSV.exists() else []
    version = max(p.stat().st_mtime_ns for p in [SRC_CSV, OUT_DASH_CSV, OUT_BIG_CSV, OUT_SUB_CSV] if p.exists())
    return {"ok": True, "version": version, "data": data, "big": big, "sub": sub}


def update_genre(payload: dict) -> dict:
    app_id = app_id_text(payload.get("app_id") or payload.get("key"))
    big = str(payload.get("big") or "").strip()
    sub = str(payload.get("sub") or "").strip()
    if not app_id or not big or not sub:
        raise ValueError("app_id, big, sub are required")

    backup_once_per_run()
    df = load_source()
    big_map, sub_map = tag_maps(df)
    if big not in big_map:
        raise ValueError(f"unknown big category: {big}")
    if (big, sub) not in sub_map:
        raise ValueError(f"unknown subcategory for {big}: {sub}")
    big_ko, sub_ko = big_map[big], sub_map[(big, sub)]

    ids = df["App ID"].map(app_id_text)
    mask = ids == app_id
    if not bool(mask.any()):
        raise ValueError(f"App ID not found in source CSV: {app_id}")

    old = df.loc[mask, TAG_COLS].iloc[0].to_dict()
    df.loc[mask, "战略大品类Tag"] = big
    df.loc[mask, "战略细分品类Tag"] = sub
    df.loc[mask, "전략대분류_KO"] = big_ko
    df.loc[mask, "전략세부분류_KO"] = sub_ko
    if "战略Tag_判定依据" in df.columns:
        df.loc[mask, "战略Tag_判定依据"] = "dashboard_manual_edit"
    if "战略Tag_置信度" in df.columns:
        df.loc[mask, "战略Tag_置信度"] = "manual"

    df.to_csv(SRC_CSV, index=False, encoding="utf-8-sig")
    write_xlsx(df)
    sqlite_result = update_sqlite(app_id, big, sub, big_ko, sub_ko)
    rebuild_result = rebuild_outputs()

    return {
        "ok": True,
        "app_id": app_id,
        "updated_rows_csv": int(mask.sum()),
        "old": old,
        "new": {
            "战略大品类Tag": big,
            "战略细分品类Tag": sub,
            "전략대분류_KO": big_ko,
            "전략세부분류_KO": sub_ko,
        },
        **sqlite_result,
        **rebuild_result,
    }


class Handler(SimpleHTTPRequestHandler):
    server_version = "ChinaGameDashboardSync/1.0"

    def translate_path(self, path: str) -> str:
        path = unquote(path.split("?", 1)[0].split("#", 1)[0])
        if path in ("", "/"):
            return str(HTML)
        rel = path.lstrip("/")
        # Allow direct serving of generated artifacts under BASE and scripts under ROOT.
        candidate = (BASE / rel).resolve()
        if str(candidate).startswith(str(BASE.resolve())) and candidate.exists():
            return str(candidate)
        candidate = (ROOT / rel).resolve()
        if str(candidate).startswith(str(ROOT.resolve())) and candidate.exists():
            return str(candidate)
        return str(HTML)

    def _json(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):  # noqa: N802
        self._json(200, {"ok": True})

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/api/status"):
            self._json(200, {"ok": True, "csv": str(SRC_CSV), "sqlite": str(SQLITE), "html": str(HTML)})
            return
        if self.path.startswith("/api/state"):
            try:
                self._json(200, read_dashboard_state())
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return
        return super().do_GET()

    def do_POST(self):  # noqa: N802
        if not self.path.startswith("/api/update-genre"):
            self._json(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            result = update_genre(payload)
            self._json(200, result)
        except Exception as exc:  # noqa: BLE001
            self._json(400, {"ok": False, "error": str(exc)})


def main() -> None:
    if not SRC_CSV.exists() or not HTML.exists():
        raise SystemExit(f"Missing dashboard files under {BASE}")
    print(f"Dashboard sync server running: http://127.0.0.1:{PORT}/")
    print(f"LAN/team URL: http://<this-mac-ip>:{PORT}/  (same network or tunnel required)")
    print(f"Canonical CSV: {SRC_CSV}")
    print(f"Canonical SQLite: {SQLITE}")
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
