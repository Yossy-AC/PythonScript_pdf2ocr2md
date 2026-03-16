# PDF→Markdown変換システム（Gemini 2.5 Flash）- 開発ノート

## プロジェクト概要

大学入試問題PDFをMarkdown形式に自動変換するシステム。Gemini 2.5 Flashを使用したビジョンベースのOCR。

**主な特徴:**
- Gemini APIの直接呼び出し（ライブラリラッパーなし）
- トークン単価ベースの正確なコスト計算
- ファイル名からのメタデータ自動抽出
- 品質チェック機能（JSON検出・行数チェック・コードブロック検出）

## 技術スタック

| 項目 | 選択 | 理由 |
|---|---|---|
| LLM | Gemini 2.5 Flash | コスト・精度のバランス。lite版（$0.10/$0.40）より推奨 |
| PDF処理 | PyMuPDF (fitz) | 軽量・高速。スキャン判定用テキスト抽出のみに使用 |
| 言語 | Python 3.12+ | google-generativeai との互換性 |
| ログ | CSV (DictWriter) | シンプル・手動編集可能 |

## 重要な実装パターン

### 1. ファイル名からのメタデータ抽出

```python
def parse_filename(stem: str) -> tuple[str, str]:
    m = re.match(r'^(\d{4})(.+?)_問題', stem)
    if m:
        return m.group(1), m.group(2)
    return "", stem
```

**パターン:** `YYYY大学名（学部）_問題` → year, university を抽出

**用途:** Geminiプロンプト内の `{university}` `{year}` プレースホルダーに埋め込み。Geminiに推測させずに確実な値を渡す。

### 2. Geminiプロンプトのテンプレート化

`gemini_prompt.md` の FrontMatter は以下のように**プレースホルダーで埋め込む**：

```markdown
---
university: {university}
year: {year}
faculty: [学部・学科（不明な場合は空欄）]
---
```

`convert.py` 内で実行時に置換：

```python
filled_prompt = prompt.replace("{university}", university).replace("{year}", year)
markdown, in_tok, out_tok = convert_pdf_to_markdown(str(pdf_path), filled_prompt)
```

**理由:** Geminiに推測させない。ファイル名が唯一の信頼できるメタデータ源。

### 3. トークン使用量とコスト計算

```python
cost_usd = (in_tok * PRICE_INPUT_PER_1M + out_tok * PRICE_OUTPUT_PER_1M) / 1_000_000
cost_yen = cost_usd * USD_TO_JPY
```

**注意点:**
- `in_tok`, `out_tok` は `response.usage_metadata` から取得
- `getattr()` でフォールバック（APIの仕様変更に備える）
- 為替レート（`USD_TO_JPY`）は `config.py` で一元管理

### 4. 品質チェックの3層構造

```python
issues = []
if "OCR_LOW_CONFIDENCE" in markdown or "GRAPH: 要手動確認" in markdown or "IMAGE:" in markdown:
    issues.append("OCR/図表タグあり")

if (stripped.startswith("```json") or stripped.startswith("{") or stripped.startswith("[") or stripped.startswith("```")):
    issues.append("フォーマット異常(コードブロック)")

if line_count < MIN_OUTPUT_LINES:
    issues.append(f"行数不足({line_count}行)")

status = "要確認" if issues else "完了"
note = ", ".join(issues)
```

**いずれかに該当 → 「要確認」に昇格**

### 5. conversion_log.csv への通算コスト記録

```python
def write_log(filename: str, status: str, note: str = "", cost_yen: float = 0.0):
    writer.writerow({
        "cost_yen": f"{cost_yen:.4f}",  # 4桁精度で記録
    })
```

起動時に `load_log()` で過去コストを集計：

```python
total_cost = sum(float(row.get("cost_yen") or 0) for row in reader)
```

**重要:** CSV既存行には `cost_yen` 列がない場合がある。`getattr()` と `try/except` で対応。

## 設定の優先度

1. **コマンドラインパラメータ** （未実装、将来の拡張）
2. **環境変数** （`GEMINI_API_KEY`）
3. **config.py** （デフォルト設定）

## 今後のメンテナンス

### Gemini APIの仕様変更への対応

**想定される変更:**
- `usage_metadata` の構造変更 → `getattr()` でフォールバック
- 価格変更 → `config.py` の `PRICE_*` を更新
- モデル廃止 → `MODEL_NAME` を新モデルに変更

**テスト対象:**
- `response.usage_metadata` の存在確認
- 入力/出力トークン数の取得可否
- FrontMatter形式の保持確認

### プロンプト調整時の注意

`gemini_prompt.md` のコメント "5. 出力制限" に記載の規則を厳密に保持：
- コードブロック（` ``` `）で囲まない
- JSON形式での出力禁止
- `{university}` `{year}` は変数として保持

### ログ形式の変更

`conversion_log.csv` に列を追加する場合：
1. `write_log()` の `fieldnames` を更新
2. 既存行とのマッピング処理を `load_log()` に追加
3. README.md の仕様表を更新

**例:** "ページ数" 列を追加する場合

```python
def write_log(filename: str, status: str, note: str = "", cost_yen: float = 0.0, pages: int = 0):
    writer = csv.DictWriter(f, fieldnames=["datetime", "filename", "status", "note", "cost_yen", "pages"])
```

## トラブルシューティング記録

### 問題: gemini-2.0-flash 廃止（2026年6月）
**対応:** gemini-2.5-flash に移行。価格更新（$0.10/$0.40 → $0.30/$2.50）

### 問題: Gemini が JSON 形式で出力
**原因:** プロンプト指示がの遵守不足
**対応:** "コードブロック禁止" の指示を強化。品質チェックで検出

### 問題: 九州大で行数不足（27行）
**原因:** Gemini の出力トークン数不足か、中断
**対応:** MIN_OUTPUT_LINES のチェック追加

## CLIスクリプト

`tools/convert.py` にスタンドアロンCLI版がある（Web UI版 `app/main.py` とは独立）。
`app/main.py` は `from tools.convert import ...` で同じモジュールを参照する。

## テスト戦略

現在、自動テストなし（手動確認）。今後の検討項目：

1. **ユニットテスト**: `parse_filename()`, コスト計算
2. **統合テスト**: ダミーPDF + モック Gemini API
3. **回帰テスト**: 既知の問題ファイル（東北大、九州大）が改善したか確認

## ドキュメント

- **README.md**: ユーザー向け（セットアップ・使用方法）
- **このファイル**: 開発者向け（実装パターン・メンテナンス）
- **manual_Tom用.md**: 特定ユーザー向け（操作ガイド）

## 最近の変更（2026年3月）
- main.py: パストラバーサル強化（`urllib.parse.unquote()`デコード後チェック + `Path.resolve()`正規化）
- main.py: 認証ミドルウェア・ヘルスチェックを `yossy-portal-lib` 共有ライブラリに移行
