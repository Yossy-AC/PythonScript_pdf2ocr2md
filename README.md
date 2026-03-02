# PDF → Markdown 変換システム（Gemini 2.5 Flash）

大学入試問題PDFを構造化Markdown形式に自動変換するツール。Gemini APIのビジョン機能を利用したOCR変換です。

## 機能

- **PDFのMarkdown変換**: Gemini 2.5 Flashを使用した高精度OCR
- **予算管理**: トークン使用量の追跡と予算超過時の自動停止
- **品質チェック**: JSON出力・行数不足・コードブロック囲みの自動検出
- **ファイル名からの自動抽出**: `2025大阪大（外国語以外）_問題.pdf` → `university: 大阪大（外国語以外）`, `year: 2025`
- **冪等性**: `conversion_log.csv` に記録された「完了」ファイルは自動スキップ
- **コスト表示**: ファイル毎・セッション毎・通算の3段階でコスト表示

## セットアップ

### 必須環境
- Python 3.9以上
- Gemini API キー（Google Cloud）
- 予算設定（無料版の場合はクォータ制限あり）

### インストール

```bash
git clone <repository-url>
cd PythonScript_pdf2ocr2md

# 依存パッケージのインストール
pip install -r requirements.txt

# フォルダ作成（初回のみ）
mkdir -p input output
```

### 環境変数設定

```bash
# Windows
set GEMINI_API_KEY=your_api_key_here

# Mac/Linux
export GEMINI_API_KEY=your_api_key_here
```

## 使用方法

### 基本的な実行

```bash
python convert.py
```

**処理の流れ:**
1. `input/` フォルダ内のすべてのPDFをソート
2. `conversion_log.csv` の「完了」ファイルはスキップ
3. 各PDFを順番に処理
4. `output/` に `{stem}.md` を保存
5. `conversion_log.csv` に結果を追記

### 途中で止まった場合の再開

`conversion_log.csv` に「完了」と記録されたファイルは自動スキップされます。

```bash
python convert.py  # そのまま再実行するだけでOK
```

## ファイル構成

```
PythonScript_pdf2ocr2md/
├── convert.py              # メインスクリプト
├── config.py               # 設定（予算、価格、閾値）
├── gemini_prompt.md        # Geminiプロンプト
├── requirements.txt        # 依存パッケージ
├── input/                  # 変換対象PDFを置くフォルダ
├── output/                 # 変換後.mdの出力先
├── conversion_log.csv      # 処理ログ（実行時に自動生成）
└── README.md              # このファイル
```

## 設定（config.py）

| 項目 | デフォルト | 説明 |
|---|---|---|
| `MODEL_NAME` | `gemini-2.5-flash` | 使用するGeminiモデル |
| `BUDGET_YEN` | `1000` | 予算上限（円） |
| `USD_TO_JPY` | `150` | 為替レート（目安） |
| `PRICE_INPUT_PER_1M` | `0.30` | 入力トークン単価（$/1M） |
| `PRICE_OUTPUT_PER_1M` | `2.50` | 出力トークン単価（$/1M） |
| `MIN_OUTPUT_LINES` | `50` | 出力行数の最小値（未満なら「要確認」） |
| `MAX_RETRIES` | `3` | APIエラー時のリトライ回数 |
| `REQUEST_INTERVAL_SEC` | `3` | リクエスト間隔（秒） |

## 品質チェック

各ファイルは以下の3つの条件で自動チェック：

| 項目 | 検出内容 | ログ表示 |
|---|---|---|
| OCR/図表 | `OCR_LOW_CONFIDENCE`, `GRAPH: 要手動確認`, `IMAGE:` タグ | `OCR/図表タグあり` |
| フォーマット | JSONやコードブロック囲み（` ```json `, ` ``` ` など） | `フォーマット異常(コードブロック)` |
| 行数 | 出力が `MIN_OUTPUT_LINES` 未満 | `行数不足(xx行)` |

いずれかに該当 → **ステータス: 「要確認」**
すべてクリア → **ステータス: 「完了」**

## conversion_log.csv の仕様

| 列 | 説明 |
|---|---|
| `datetime` | 処理日時 |
| `filename` | PDFファイル名 |
| `status` | `完了` / `要確認` / `エラー` |
| `note` | 要確認理由またはエラーメッセージ |
| `cost_yen` | そのファイルの処理コスト（円） |

## コスト表示の見かた

実行中（各ファイル毎）:
```
  [COST] 今回: 2.40円 / 今回累計: 24.50円 / 通算: 124.50円 / 残: 875.50円
```

終了時:
```
[COST] 今回セッション: 24.50円 / 通算: 124.50円 / 予算残: 875.50円
```

**用語:**
- **今回**: 現在のファイル処理コスト
- **今回累計**: このセッション内の合計コスト
- **通算**: 過去セッションも含めた合計コスト（`conversion_log.csv` から計算）
- **残**: `BUDGET_YEN` - 通算コスト

## トラブルシューティング

### 「GEMINI_API_KEY が設定されていません」
環境変数が設定されていません。上記のセットアップ手順を確認してください。

### 「予算上限に達したため処理を停止」
`config.py` の `BUDGET_YEN` を増やすか、予算をリセットしてください。

### 「行数不足」が多い
`config.py` の `MIN_OUTPUT_LINES` を減らすか、プロンプト（`gemini_prompt.md`）を調整してください。

### JSON形式で出力されている
Geminiがプロンプト指示を無視しています。`gemini_prompt.md` の「コードブロック禁止」の指示を確認してください。

## 別PCへの移行

全ファイルをコピーして、環境変数とAPIキーを設定するだけで動作します：

```bash
# コピー対象
- convert.py
- config.py
- gemini_prompt.md
- requirements.txt

# コピー不要（実行時に自動生成）
- input/, output/ フォルダ
- conversion_log.csv
```

詳細は `manual_Tom用.md` を参照。

## ライセンス

MIT License（内部利用想定）

## 技術スタック

- **Python**: 3.14
- **Gemini API**: 2.5 Flash
- **PyMuPDF**: PDFのテキスト抽出（スキャン判定用）
