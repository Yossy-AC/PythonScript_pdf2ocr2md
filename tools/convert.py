#!/usr/bin/env python3
# convert.py
# PDF → Markdown 変換スクリプト（Gemini 2.0 Flash使用）
# 使用方法: python convert.py

import os
import re
import sys
import csv
import time
import pathlib
import datetime

import fitz  # PyMuPDF
from google import genai
from google.genai import types

from config import (
    GEMINI_API_KEY,
    MODEL_NAME,
    INPUT_DIR,
    OUTPUT_DIR,
    PROMPT_FILE,
    LOG_FILE,
    MAX_RETRIES,
    RETRY_WAIT_SEC,
    REQUEST_INTERVAL_SEC,
    BUDGET_YEN,
    USD_TO_JPY,
    PRICE_INPUT_PER_1M,
    PRICE_OUTPUT_PER_1M,
    MIN_OUTPUT_LINES,
)

_client: genai.Client | None = None

# =============================================
# 初期化
# =============================================
def init():
    """APIキーの確認とフォルダの作成"""
    if not GEMINI_API_KEY:
        print("[ERROR] 環境変数 GEMINI_API_KEY が設定されていません。")
        print("  設定方法: set GEMINI_API_KEY=your_api_key_here  (Windows)")
        print("  設定方法: export GEMINI_API_KEY=your_api_key_here  (Mac/Linux)")
        sys.exit(1)

    global _client
    _client = genai.Client(api_key=GEMINI_API_KEY)
    pathlib.Path(OUTPUT_DIR).mkdir(exist_ok=True)
    pathlib.Path(INPUT_DIR).mkdir(exist_ok=True)


def load_prompt() -> str:
    """プロンプトファイルを読み込む"""
    if not pathlib.Path(PROMPT_FILE).exists():
        print(f"[ERROR] プロンプトファイルが見つかりません: {PROMPT_FILE}")
        sys.exit(1)
    with open(PROMPT_FILE, encoding="utf-8") as f:
        return f.read()


# =============================================
# ログ管理
# =============================================
def load_log() -> tuple[set, float]:
    """処理済みファイル名のセットと通算コスト（円）を返す"""
    processed = set()
    total_cost = 0.0
    if pathlib.Path(LOG_FILE).exists():
        with open(LOG_FILE, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("status") == "完了":
                    processed.add(row["filename"])
                try:
                    total_cost += float(row.get("cost_yen") or 0)
                except ValueError:
                    pass
    return processed, total_cost


def write_log(filename: str, status: str, note: str = "", cost_yen: float = 0.0):
    """ログに1行追記する"""
    file_exists = pathlib.Path(LOG_FILE).exists()
    with open(LOG_FILE, encoding="utf-8", newline="", mode="a") as f:
        writer = csv.DictWriter(f, fieldnames=["datetime", "filename", "status", "note", "cost_yen"])
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "datetime": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "filename": filename,
            "status": status,
            "note": note,
            "cost_yen": f"{cost_yen:.4f}",
        })


# =============================================
# PDF処理
# =============================================
def is_scanned_pdf(pdf_path: str, threshold: int = 100) -> bool:
    """PDFがスキャン由来かどうかを判定する"""
    doc = fitz.open(pdf_path)
    total_chars = sum(len(page.get_text()) for page in doc)
    doc.close()
    return total_chars < threshold


# =============================================
# ファイル名パース
# =============================================
def parse_filename(stem: str) -> tuple[str, str]:
    """ファイル名から year と university を抽出する
    例: '2025大阪大（外国語以外）_問題' → ('2025', '大阪大（外国語以外）')
    """
    m = re.match(r'^(\d{4})(.+?)_問題', stem)
    if m:
        return m.group(1), m.group(2)
    return "", stem


# =============================================
# Gemini API呼び出し
# =============================================
def convert_pdf_to_markdown(pdf_path: str, prompt: str) -> tuple[str, int, int]:
    """PDFをGemini APIに投げてMarkdownとトークン使用量を返す

    Returns:
        tuple: (markdown_text, input_tokens, output_tokens)
    """
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = _client.models.generate_content(
                model=MODEL_NAME,
                contents=[
                    types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                    prompt,
                ],
                config=types.GenerateContentConfig(
                    http_options=types.HttpOptions(timeout=300_000),  # 5分
                ),
            )
            usage = response.usage_metadata
            input_tokens = getattr(usage, "prompt_token_count", 0) or 0
            output_tokens = getattr(usage, "candidates_token_count", 0) or 0
            return response.text, input_tokens, output_tokens

        except Exception as e:
            print(f"  [WARNING] APIエラー（試行 {attempt}/{MAX_RETRIES}）: {e}")
            if attempt < MAX_RETRIES:
                print(f"  {RETRY_WAIT_SEC}秒後にリトライします...")
                time.sleep(RETRY_WAIT_SEC)
            else:
                raise


# =============================================
# メイン処理
# =============================================
def main():
    init()
    prompt = load_prompt()
    processed, past_cost_yen = load_log()

    pdf_files = sorted(pathlib.Path(INPUT_DIR).glob("*.pdf"))
    if not pdf_files:
        print(f"[INFO] {INPUT_DIR}/ フォルダにPDFファイルが見つかりません。")
        return

    total = len(pdf_files)
    skipped = 0
    success = 0
    failed = 0
    session_cost_yen = 0.0
    budget_exceeded = False

    print(f"[INFO] 対象ファイル数: {total}件 / 予算: {BUDGET_YEN}円 / 通算使用済み: {past_cost_yen:.2f}円")
    print("-" * 50)

    for i, pdf_path in enumerate(pdf_files, 1):
        filename = pdf_path.name
        output_path = pathlib.Path(OUTPUT_DIR) / (pdf_path.stem + ".md")

        print(f"[{i}/{total}] {filename}")

        # 処理済みスキップ
        if filename in processed:
            print("  → スキップ（処理済み）")
            skipped += 1
            continue

        # スキャン判定（情報表示のみ、Geminiが対応するため処理は変わらない）
        scanned = is_scanned_pdf(str(pdf_path))
        if scanned:
            print("  → スキャンPDFと判定")

        # 変換実行
        try:
            year, university = parse_filename(pdf_path.stem)
            filled_prompt = prompt.replace("{university}", university).replace("{year}", year)
            markdown, in_tok, out_tok = convert_pdf_to_markdown(str(pdf_path), filled_prompt)

            # コスト計算
            cost_usd = (in_tok * PRICE_INPUT_PER_1M + out_tok * PRICE_OUTPUT_PER_1M) / 1_000_000
            cost_yen = cost_usd * USD_TO_JPY
            session_cost_yen += cost_yen
            total_cost_yen = past_cost_yen + session_cost_yen
            remaining = BUDGET_YEN - total_cost_yen
            print(f"  [COST] 今回: {cost_yen:.2f}円 / 今回累計: {session_cost_yen:.2f}円 / 通算: {total_cost_yen:.2f}円 / 残: {remaining:.2f}円")

            # 品質チェック
            issues = []
            if "OCR_LOW_CONFIDENCE" in markdown or "GRAPH: 要手動確認" in markdown or "IMAGE:" in markdown:
                issues.append("OCR/図表タグあり")

            stripped = markdown.strip()
            if (stripped.startswith("```json") or stripped.startswith("{") or
                    stripped.startswith("[") or stripped.startswith("```")):
                issues.append("フォーマット異常(コードブロック)")

            line_count = len(stripped.splitlines())
            if line_count < MIN_OUTPUT_LINES:
                issues.append(f"行数不足({line_count}行)")

            status = "要確認" if issues else "完了"
            note = ", ".join(issues)

            # ファイル保存
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(markdown)

            write_log(filename, status, note, cost_yen)
            print(f"  → {status}：{output_path}")
            success += 1

            # 予算チェック
            if total_cost_yen >= BUDGET_YEN:
                print(f"\n[STOP] 予算上限 {BUDGET_YEN}円 に達したため処理を停止します（通算: {total_cost_yen:.2f}円）")
                budget_exceeded = True
                break

        except Exception as e:
            write_log(filename, "エラー", str(e))
            print(f"  → [ERROR] {e}")
            failed += 1

        # リクエスト間隔
        if i < total:
            time.sleep(REQUEST_INTERVAL_SEC)

    # サマリ
    print("-" * 50)
    total_cost_yen = past_cost_yen + session_cost_yen
    print(f"[完了] 成功: {success}件 / 要確認含む / スキップ: {skipped}件 / エラー: {failed}件")
    print(f"[COST] 今回セッション: {session_cost_yen:.2f}円 / 通算: {total_cost_yen:.2f}円 / 予算残: {BUDGET_YEN - total_cost_yen:.2f}円")
    if budget_exceeded:
        print(f"[STOP] 予算超過により未処理ファイルがあります")
    print(f"[INFO] ログ: {LOG_FILE}")


if __name__ == "__main__":
    main()
