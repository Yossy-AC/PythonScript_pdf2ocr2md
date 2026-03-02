# PDF → Markdown 変換スクリプト　セットアップ・運用マニュアル

---

## 作成ファイル一覧

```
project/
├── convert.py          ← メイン処理スクリプト
├── config.py           ← 設定ファイル（パス・モデル・リトライ数等）
├── requirements.txt    ← 必要ライブラリ一覧
├── gemini_prompt.md    ← Geminiへのプロンプト（別途作成済み）
├── input/              ← 変換対象PDFを置く（自動生成）
├── output/             ← 変換後.mdの出力先（自動生成）
└── conversion_log.csv  ← 処理ログ（自動生成）
```

---

## STEP 1｜プロジェクトフォルダの作成

VS Codeで作業フォルダを作成し、以下のファイルを配置する。

```
任意の場所/pdf_converter/
├── convert.py
├── config.py
├── requirements.txt
└── gemini_prompt.md    ← 別途作成済みのプロンプトファイル
```

VS Codeでフォルダを開く：  
`ファイル` → `フォルダを開く` → 上記フォルダを選択

---

## STEP 2｜Gemini APIキーの取得

1. [Google AI Studio](https://aistudio.google.com/) にアクセス
2. 左メニューの **「Get API key」** をクリック
3. **「Create API key」** → プロジェクトを選択 → APIキーをコピー

> ⚠️ APIキーはコード内に直接書かない。環境変数で管理する（次のSTEPで設定）。

---

## STEP 3｜環境変数の設定

### Windows（推奨：システム環境変数）

1. スタートメニューで「環境変数」と検索 → 「システム環境変数の編集」を開く
2. 「環境変数(N)...」をクリック
3. ユーザー環境変数の「新規(N)...」をクリック
4. 以下を入力してOK：
   - 変数名: `GEMINI_API_KEY`
   - 変数値: `取得したAPIキー`
5. VS Codeを**再起動**する（再起動しないと反映されない）

### 確認方法（VS Code ターミナル）

```powershell
echo $env:GEMINI_API_KEY
```

APIキーの文字列が表示されれば成功。

---

## STEP 4｜ライブラリのインストール

VS Codeのターミナルを開く（`Ctrl+@`）。

```bash
pip install -r requirements.txt
```

インストールされるライブラリ：
- `google-generativeai` — Gemini APIクライアント
- `PyMuPDF` — PDF読み込み・スキャン判定

---

## STEP 5｜PDFを配置して実行

### PDFの配置

```
project/
└── input/
    ├── 2026兵庫県立大（国際商経）.pdf
    ├── 2025京都大学（文系）.pdf
    └── ...
```

### 実行

```bash
python convert.py
```

### 実行中の表示例

```
[INFO] 対象ファイル数: 5件
--------------------------------------------------
[1/5] 2026兵庫県立大（国際商経）.pdf
  → 完了：output/2026兵庫県立大（国際商経）.md
[2/5] 2025京都大学（文系）.pdf
  → スキャンPDFと判定
  → 要確認：output/2025京都大学（文系）.md
[3/5] 2024大阪大学（外国語）.pdf
  → スキップ（処理済み）
--------------------------------------------------
[完了] 成功: 2件 / スキップ: 1件 / エラー: 0件
[INFO] ログ: conversion_log.csv
```

---

## STEP 6｜出力の確認

### 正常な出力例

```markdown
---
university: 兵庫県立大（国際商経）
faculty: 国際商経学部
year: 2026
exam_type: 前期
source_file: 2026兵庫県立大（国際商経）.pdf
---

# Question 1

## Instructions
次の英文を読み、設問に答えなさい。

## Text
The issue of *biodiversity*\*1 has become prominent...
<u>the environment is changing</u><!-- 下線部② -->

## Vocabulary
- \*1: biodiversity — 生物多様性
```

### 要確認タグの確認

以下のタグが含まれるファイルは `conversion_log.csv` で `要確認` と記録される。

| タグ | 意味 |
|---|---|
| `<!-- OCR_LOW_CONFIDENCE: ... -->` | 読み取り精度が低い箇所 |
| `<!-- GRAPH: 要手動確認 -->` | 図表の手動確認が必要 |
| `<!-- IMAGE: ここに絵がある -->` | 絵・写真の存在を示す |

---

## 途中で止まった場合の再開

`conversion_log.csv` に `完了` と記録されたファイルは自動的にスキップされる。

```bash
python convert.py  # そのまま再実行するだけでOK
```

---

## config.py のカスタマイズ

| 設定項目 | デフォルト | 変更理由の例 |
|---|---|---|
| `MODEL_NAME` | `gemini-2.0-flash` | 精度を上げたい場合は `gemini-1.5-pro` |
| `MAX_RETRIES` | `3` | エラーが多い場合は増やす |
| `RETRY_WAIT_SEC` | `10` | レート制限エラーが出る場合は増やす |
| `REQUEST_INTERVAL_SEC` | `3` | 連続処理の間隔 |

---

## コスト管理

Google AI Studioの使用量確認：  
[console.cloud.google.com](https://console.cloud.google.com/) → 「APIとサービス」→「割り当て」

**Gemini 2.0 Flash の目安コスト（100ファイル × 平均12ページ）：$3〜5**

---

## よくあるエラー

### `GEMINI_API_KEY が設定されていません`
→ STEP 3を再確認。VS Codeを再起動したか確認する。

### `google.api_core.exceptions.ResourceExhausted`
→ レート制限。`config.py` の `RETRY_WAIT_SEC` を `30` に増やして再実行。

### `ModuleNotFoundError: No module named 'fitz'`
→ PyMuPDFのインストール名に注意。`pip install PyMuPDF`（`fitz` ではない）。

### 出力MDが空または極端に短い
→ Geminiがプロンプトの最後の指示（「Markdownのみを出力」）に過剰反応している可能性。`gemini_prompt.md` の末尾を確認する。

---

*最終更新: 2026年3月*
