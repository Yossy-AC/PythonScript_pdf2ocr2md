"""
PDF→Markdown 変換 Web アプリ
FastAPI + htmx + Gemini 2.5 Flash
変換はブロッキング処理なので asyncio.to_thread() で実行
"""
from __future__ import annotations

import asyncio
import csv
import os
import pathlib
import sys
import tempfile
from pathlib import Path

from google import genai
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.templating import Jinja2Templates

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# config.py の相対パス（input/, output/, conversion_log.csv）を解決
os.chdir(PROJECT_ROOT)

from config import (
    GEMINI_API_KEY,
    LOG_FILE,
    MIN_OUTPUT_LINES,
    OUTPUT_DIR,
    PRICE_INPUT_PER_1M,
    PRICE_OUTPUT_PER_1M,
    PROMPT_FILE,
    USD_TO_JPY,
)
from convert import (
    convert_pdf_to_markdown,
    is_scanned_pdf,
    load_log,
    parse_filename,
    write_log,
)

OUTPUT_PATH = PROJECT_ROOT / OUTPUT_DIR
OUTPUT_PATH.mkdir(exist_ok=True)
(PROJECT_ROOT / "input").mkdir(exist_ok=True)

templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))

app = FastAPI(title="PDF→Markdown変換")


@app.middleware("http")
async def portal_auth(request: Request, call_next):
    if os.environ.get("BEHIND_PORTAL") == "true" and request.headers.get("X-Portal-Role"):
        return await call_next(request)
    return await call_next(request)


def _load_log_entries(limit: int = 10) -> list[dict]:
    """conversion_log.csv から最新 N 件を返す"""
    log_path = pathlib.Path(LOG_FILE)
    if not log_path.exists():
        return []
    with open(log_path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return list(reversed(rows))[:limit]


def _convert_sync(pdf_bytes: bytes, filename: str, prompt: str) -> dict:
    """同期変換処理。asyncio.to_thread() から呼び出す"""
    stem = pathlib.Path(filename).stem
    year, university = parse_filename(stem)
    filled_prompt = prompt.replace("{university}", university).replace("{year}", year)

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        tmp.write(pdf_bytes)
        tmp.close()
        scanned = is_scanned_pdf(tmp.name)
        markdown, in_tok, out_tok = convert_pdf_to_markdown(tmp.name, filled_prompt)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    # コスト計算
    cost_usd = (in_tok * PRICE_INPUT_PER_1M + out_tok * PRICE_OUTPUT_PER_1M) / 1_000_000
    cost_yen = cost_usd * USD_TO_JPY

    # 品質チェック
    issues = []
    if any(t in markdown for t in ["OCR_LOW_CONFIDENCE", "GRAPH: 要手動確認", "IMAGE:"]):
        issues.append("OCR/図表タグあり")
    stripped = markdown.strip()
    if stripped.startswith(("```json", "{", "[", "```")):
        issues.append("フォーマット異常(コードブロック)")
    line_count = len(stripped.splitlines())
    if line_count < MIN_OUTPUT_LINES:
        issues.append(f"行数不足({line_count}行)")

    status = "要確認" if issues else "完了"
    note = ", ".join(issues)

    # 保存
    md_path = OUTPUT_PATH / (stem + ".md")
    md_path.write_text(markdown, encoding="utf-8")
    write_log(filename, status, note, cost_yen)

    return {
        "status": status,
        "note": note,
        "cost_yen": cost_yen,
        "in_tok": in_tok,
        "out_tok": out_tok,
        "line_count": line_count,
        "md_filename": stem + ".md",
        "scanned": scanned,
    }


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    _, total_cost = load_log()
    log_entries = _load_log_entries()
    api_ok = bool(GEMINI_API_KEY)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "log_entries": log_entries,
        "total_cost": f"{total_cost:.2f}",
        "api_ok": api_ok,
    })


@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, file: UploadFile = File(...)):
    if not GEMINI_API_KEY:
        return templates.TemplateResponse("result.html", {
            "request": request,
            "error": "GEMINI_API_KEY が設定されていません。環境変数を確認してください。",
        })

    filename = file.filename or "unknown.pdf"
    if not filename.lower().endswith(".pdf"):
        return templates.TemplateResponse("result.html", {
            "request": request,
            "error": "PDFファイルのみ受け付けています",
        })

    prompt_path = PROJECT_ROOT / PROMPT_FILE
    if not prompt_path.exists():
        return templates.TemplateResponse("result.html", {
            "request": request,
            "error": f"プロンプトファイルが見つかりません: {PROMPT_FILE}",
        })

    pdf_bytes = await file.read()
    MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB
    if len(pdf_bytes) > MAX_UPLOAD_SIZE:
        return templates.TemplateResponse("result.html", {
            "request": request,
            "error": f"ファイルサイズが上限（50MB）を超えています",
        })
    prompt = prompt_path.read_text(encoding="utf-8")

    # convert.py の _client を初期化（Web UI 経由の場合）
    import convert
    if convert._client is None:
        convert._client = genai.Client(api_key=GEMINI_API_KEY)

    try:
        result = await asyncio.to_thread(_convert_sync, pdf_bytes, filename, prompt)
    except Exception as e:
        write_log(filename, "エラー", str(e))
        return templates.TemplateResponse("result.html", {
            "request": request,
            "error": f"変換エラー: {e}",
        })

    return templates.TemplateResponse("result.html", {
        "request": request,
        "filename": filename,
        "status": result["status"],
        "note": result["note"],
        "cost_yen": f"{result['cost_yen']:.2f}",
        "in_tok": result["in_tok"],
        "out_tok": result["out_tok"],
        "line_count": result["line_count"],
        "md_filename": result["md_filename"],
        "scanned": result["scanned"],
    })


@app.get("/download/{filename}")
async def download(filename: str):
    # パストラバーサル防止
    if any(c in filename for c in ("/", "\\", "..")):
        return Response("Invalid filename", status_code=400)
    md_path = OUTPUT_PATH / filename
    if not md_path.exists() or md_path.suffix != ".md":
        return Response("ファイルが見つかりません", status_code=404)
    return FileResponse(
        path=str(md_path),
        filename=filename,
        media_type="text/markdown; charset=utf-8",
    )
