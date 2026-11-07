# Local LLM Chat Application - TASK

**対象仕様書:** `specification.md` Version 1.2  
**目的:** 仕様書に定義された初期バージョンを、段階的に実装・検証して完成させる  
**進め方:** 各フェーズで「実装 → テスト → 完了判定」を行い、完了条件を満たしてから次のフェーズへ進む

---

## 0. 開発ルール

### 0.1 基本ルール

- 仕様書 Version 1.2 を実装上の基準とする。
- 仕様書にない機能を独断で追加しない。必要になった場合は、実装前に仕様を更新する。
- 各フェーズは、実装だけでなく、そのフェーズに対応するテストまで完了して初めて完了とする。
- 主機能は、機能単位のテストケースを作成してからテストを実行する。
- テストが失敗した場合は原因を修正し、関連テストを再実行する。
- 既存機能に影響する変更を行った場合は、関連する回帰テストも実行する。
- テストを実行できない場合は、理由・未確認事項・手動確認手順を記録し、合格扱いにしない。
- 実行環境に依存する値（実行ファイル、モデルファイル、ポート等）は `config.yaml` に集約する。
- llama-server のCLI/API仕様は、実際に使用するビルドで確認してから実装する。

### 0.2 フェーズ完了の定義

各フェーズの完了時に、以下をすべて満たすこと。

1. フェーズ内の実装タスクが完了している。
2. フェーズ内のテストケースが作成されている。
3. テストがすべて合格している。
4. 失敗したテストがある場合、修正後に再実行して合格している。
5. 既存機能への回帰がないことを確認している。
6. 起動方法・テスト方法・既知の制約が必要に応じてドキュメント化されている。

### 0.3 テストの種類

| 種類 | 目的 | 例 |
|---|---|---|
| 単体テスト | 関数・クラス単位の動作確認 | 直近5ターンの抽出、設定値の検証 |
| APIテスト | HTTP APIの入出力確認 | 不正なリクエストに400を返す |
| コンポーネントテスト | 外部依存を含む機能単位の確認 | Pythonからllama-serverへの接続 |
| 結合テスト | 複数コンポーネント間の連携確認 | GoからPythonを経由した推論 |
| E2Eテスト | ブラウザ操作を含む全体動作確認 | UIから送信して回答が表示される |
| 手動テスト | 実機・実モデルでの確認 | 設定モデルの起動・推論・停止 |

### 0.4 テスト実装方針

- Go: `go test ./...` を基本とし、HTTP APIは `httptest` 等を利用して検証する。
- Python: `pytest` を基本とし、外部プロセス・HTTP通信はモック可能な構造にする。
- Frontend: ブラウザでの手動確認を最低限実施する。必要に応じてJavaScriptの単体テストやブラウザ自動テストを追加する。
- llama-server: 単体テストではプロセス起動・HTTP応答をモックし、実モデルを使うテストは別途手動／統合テストとして実施する。
- 実モデルを使用するテストでは、使用したモデルID、llama.cppのバージョン、実行環境を記録する。

---

# Phase 1. プロジェクト初期構築

## 目的

Go + Echo、Python + FastAPI、Frontend の最小構成を作り、それぞれを独立して起動できる状態にする。

## 実装タスク

- [x] 仕様書に従ってディレクトリ構成を作成する。
- [x] Go module を初期化する。
- [x] Echo v5 を導入する。
- [x] Python仮想環境（.venv）を作成する。
- [x] FastAPI、Uvicorn、Pydantic、YAML読み込み用ライブラリ等の依存関係を定義する。
- [x] `requirements.txt` を作成する。
- [x] `frontend/index.html`、`style.css`、`app.js` の空の初期ファイルを作成する。
- [x] Goサーバーの起動処理を実装する。
- [x] Python FastAPIサーバーの起動処理を実装する。
- [x] Go側に仮のヘルスチェックAPIを用意する。
- [x] Python側に `/health` APIを用意する。
- [x] 開発環境での起動手順をREADME等に記載する。

## テストケース

| ID | 内容 | 期待結果 | 結果 |
|---|---|---|---|
| P1-T01 | Goの依存関係を取得する | エラーなく完了する | 合格 |
| P1-T02 | `go test ./...` を実行する | コンパイルエラーなく完了する | 合格 |
| P1-T03 | Goサーバーを起動する | 指定ポートで待ち受ける | 合格（127.0.0.1:8000） |
| P1-T04 | GoのヘルスチェックAPIを呼び出す | 正常なHTTPレスポンスが返る | 合格 |
| P1-T05 | Python依存関係をインストールする | エラーなく完了する | 合格（Python 3.11） |
| P1-T06 | FastAPIサーバーを起動する | 指定ポートで待ち受ける | 合格（127.0.0.1:8001） |
| P1-T07 | Pythonの `/health` を呼び出す | 正常なJSONレスポンスが返る | 合格 |
| P1-T08 | Frontendをブラウザで開く | HTML/CSS/JSの読み込みエラーがない | 合格 |

## 完了条件

- [x] GoサーバーとPythonサーバーを個別に起動できる。
- [x] 両方のヘルスチェックが成功する。
- [x] Go/Pythonの基本テストが合格する。

---

# Phase 2. 設定ファイルの実装

## 目的

ルートの `config.yaml` をPython側で読み込み、設定値とモデル定義を検証できるようにする。

## 実装タスク

- [x] 仕様書の構造に沿って `config.yaml` を作成する。
- [x] Python側に設定クラスを定義する。
- [x] YAML読み込み処理を実装する。
- [x] 必須設定項目の存在チェックを実装する。
- [x] ポート番号・タイムアウト値等の値域チェックを実装する。
- [x] llama-server実行ファイルの存在チェックを実装する。
- [x] 登録された各GGUFファイルの存在チェックを実装する。
- [x] `models.default` が `models.available` に存在するか検証する。
- [x] 相対パスはアプリケーションルートを基準に解決する。
- [x] 絶対パスはそのまま扱う。
- [x] 設定エラー時は、どの項目に問題があるか分かるエラーを返す。

## テストケース

| ID | 内容 | 期待結果 | 結果 |
|---|---|---|---|
| P2-T01 | 正常なYAMLを読み込む | 全設定値を正しく取得できる | 合格 |
| P2-T02 | 必須項目を削除したYAMLを読み込む | 起動時に設定エラーとなる | 合格 |
| P2-T03 | 不正なポート番号を指定する | 設定エラーとなる | 合格 |
| P2-T04 | 不正なタイムアウト値を指定する | 設定エラーとなる | 合格 |
| P2-T05 | 存在しないllama-server実行ファイルを指定する | 設定エラーとなる | 合格 |
| P2-T06 | 存在しないGGUFパスを指定する | 設定エラーとなる | 合格 |
| P2-T07 | 存在しないモデルIDをdefaultに指定する | 設定エラーとなる | 合格 |
| P2-T08 | 相対パスを指定する | アプリケーションルート基準で解決される | 合格 |
| P2-T09 | 絶対パスを指定する | 指定した絶対パスとして扱われる | 合格 |
| P2-T10 | 複数モデルを定義する | 全モデルをモデルID付きで取得できる | 合格 |
| P2-T11 | FastAPIの起動ライフサイクルで設定を読み込む | 検証済み設定がアプリに設定される | 合格 |

テスト実行: `python -m pytest inference\tests -q`（12 passed）。Go回帰テスト `go test ./...` も合格。

## 完了条件

- [x] 正常な設定ファイルを読み込める。
- [x] 不正な設定を起動前に検出できる。
- [x] 設定値とパス解決に関するテストがすべて合格する。

> 注意: `src/config.yaml` の実行ファイル・モデルパスは配置場所の例です。実際のファイルに合わせて設定するまでは、仕様どおりAPIの起動時に設定エラーとなります。

---

# Phase 3. GoのデータモデルとSession Store

## 目的

会話メッセージ、セッション、メモリ上のSession Storeを実装する。

## 実装タスク

- [x] `Message` 構造体を実装する。
- [x] `Session` 構造体を実装する。
- [x] Session IDをUUID等の推測困難な値で生成する。
- [x] Session Storeを実装する。
- [x] セッションの新規作成・取得・更新・削除を実装する。
- [x] StoreへのアクセスをMutexで保護する。
- [x] セッション有効期限を管理する。
- [x] 期限切れセッションを削除する仕組みを実装する。
- [x] 同一セッションの同時処理を制御できるようにする。
- [x] 推論処理中にStore全体のMutexを保持し続けない構造にする。

## テストケース

| ID | 内容 | 期待結果 | 結果 |
|---|---|---|---|
| P3-T01 | 新規セッションを作成する | 一意なSession IDが発行される | 合格 |
| P3-T02 | Session IDでセッションを取得する | 作成したセッションを取得できる | 合格 |
| P3-T03 | 存在しないSession IDを取得する | 未存在として扱われる | 合格 |
| P3-T04 | セッションのHistoryを更新する | 更新内容が保持される | 合格 |
| P3-T05 | セッションを削除する | Storeから削除される | 合格 |
| P3-T06 | 有効期限内のセッションを取得する | 取得できる | 合格 |
| P3-T07 | 期限切れセッションを取得する | 期限切れとして削除・無効化される | 合格 |
| P3-T08 | 複数セッションを並行して操作する | データ破損や競合が発生しない | 合格（race detector含む） |
| P3-T09 | 同一セッションを同時に操作する | 定義した排他制御が機能する | 合格 |

セッションのアイドル有効期限は30分とし、取得・更新時に延長する。取得時および新規作成時に期限切れを削除する。

## 完了条件

- [x] セッションのCRUDが正常に動作する。
- [x] セッション有効期限が機能する。
- [x] 並行アクセスのテストが合格する。

---

# Phase 4. 会話履歴管理とチャット処理の基礎

## 目的

直近5ターンの抽出、履歴更新ルール、System Prompt管理を実装する。

## 実装タスク

- [x] 完了済みのUser / Assistantペアを1ターンとして扱う。
- [x] 保存する全履歴と、推論に渡す直近5ターンを分離する。
- [x] 直近5ターンの抽出処理を実装する。
- [x] 現在のユーザー入力は既存Historyと分けて扱う。
- [x] 推論成功時にUserとAssistantの両メッセージをHistoryへ追加する。
- [x] 推論失敗時はHistoryを更新しない仕様を実装する。
- [x] System PromptをSession単位で保持・更新する。
- [x] Reset時はHistoryのみを初期化し、System Promptは保持する。

## テストケース

| ID | 内容 | 期待結果 |
|---|---|---|
| P4-T01 | Historyが空の状態で直近ターンを取得する | 空配列が返る |
| P4-T02 | 1ターンだけ保存されている | 1ターン分が返る |
| P4-T03 | 5ターン保存されている | 5ターン分・最大10メッセージが返る |
| P4-T04 | 6ターン保存されている | 最新5ターンのみ返る |
| P4-T05 | UserとAssistantが揃っていない末尾データがある | 未完了ペアを直近の完了ターンとして数えない |
| P4-T06 | 現在の入力を履歴抽出に渡さず推論入力として扱う | 現在の入力が履歴に重複しない |
| P4-T07 | 推論成功を模擬する | UserとAssistantが順番に追加される |
| P4-T08 | 推論失敗を模擬する | Historyが変更されない |
| P4-T09 | Resetを実行する | Historyは空になりSystem Promptは維持される |
| P4-T10 | System Promptを更新する | 対象Sessionの値だけが更新される |

テスト実行: `go test ./...` および `go test -race ./...` は合格。

## 完了条件

- [x] 直近5ターンの抽出が仕様どおりに動作する。
- [x] 推論成功／失敗によるHistory更新ルールが守られる。
- [x] System PromptとResetのテストが合格する。

---

# Phase 5. Python Prompt Builder と Output Schema

## 目的

Goから渡されたSystem Prompt、会話履歴、現在の入力からプロンプトを生成し、LLM出力をPydanticで検証できるようにする。

## 実装タスク

- [x] `OutputSchema` をPydanticで定義する。
- [x] `text: str` を必須フィールドとする。
- [x] 余分なフィールドを拒否する設定にする。
- [x] PydanticからJSON Schemaを生成できるようにする。
- [x] Prompt Builderを実装する。
- [x] System Promptを先頭に配置する。
- [x] 会話履歴を参考に文脈を維持する指示を含める。
- [x] Historyを `[User]` / `[Assistant]` 形式で配置する。
- [x] 最後に `## ユーザーの入力` と現在の入力を配置する。
- [x] Historyが空の場合は会話履歴部分を省略する。
- [x] LLMのJSON文字列をPydanticで検証する。
- [x] 不正JSON・スキーマ不一致を明確なエラーとして扱う。

## テストケース

| ID | 内容 | 期待結果 |
|---|---|---|
| P5-T01 | System Prompt、History、User Inputを渡す | 指定順序でプロンプトが生成される |
| P5-T02 | Historyが空の状態で生成する | 会話履歴部分を省略する |
| P5-T03 | Historyに複数ターンを渡す | User / Assistantの順序を維持する |
| P5-T04 | 現在のUser Inputを渡す | プロンプト末尾のユーザー入力欄に配置される |
| P5-T05 | 正常な `{"text":"hello"}` を検証する | OutputSchemaとして検証成功 |
| P5-T06 | `text` が欠落したJSONを検証する | 検証エラー |
| P5-T07 | `text` が文字列以外のJSONを検証する | 検証エラー |
| P5-T08 | 余分なキーを含むJSONを検証する | 検証エラー |
| P5-T09 | JSONとして不正な文字列を検証する | パース／検証エラー |
| P5-T10 | PydanticからJSON Schemaを生成する | `text` 必須・追加プロパティ禁止のSchemaになる |

テスト実行: `python -m pytest inference\tests -q`（22 passed。Phase 2の回帰テストを含む）。`go test ./...` も合格。

## 完了条件

- [x] プロンプト形式が仕様書どおりに生成される。
- [x] OutputSchemaが正常系・異常系を判定できる。
- [x] Prompt BuilderとSchemaのテストがすべて合格する。

---

# Phase 6. llama-server クライアントの実装

## 目的

Pythonからllama-serverのOpenAI互換APIを呼び出し、JSON SchemaによるStructured Outputを要求できるようにする。

> このフェーズの開始前に、使用するllama.cppビルドのCLIオプション、ヘルスチェックAPI、Chat Completions API、Structured Outputのリクエスト形式を確認する。

## 実装タスク

- [x] 使用するllama.cppのバージョン／ビルドを記録する（version 10066、commit `86a9c79f8`）。
- [x] `llama-server` の起動オプションを確認する（`--gpu-layers`、`--flash-attn`、`--ctx-size`、`--port`、`--jinja` を確認）。
- [x] ヘルスチェック用エンドポイントを実ビルドで確認する（`/health` が成功）。
- [x] OpenAI互換Chat Completions APIのリクエスト形式を実モデルで確認する。
- [x] JSON Schema指定のサポート状況と正しい形式を実モデルで確認する。
- [x] `server.py` の `LlamaServerManager.chat_completion()` を使用する。
- [x] `/v1/chat/completions` へHTTP POSTする。
- [x] 会話メッセージをpayloadとして送る。
- [x] Pydantic由来のJSON Schemaを `response_format` に指定する。
- [x] HTTPタイムアウトを設定する（chat completionは60秒）。
- [x] HTTPエラーを `LlamaServerError` として扱う。
- [x] クライアント接続エラー・タイムアウト・不正レスポンスを `LlamaServerError` として扱う。
- [x] 応答から生成テキストを取り出し、OutputSchemaで検証する。

## テストケース

| ID | 内容 | 期待結果 | 結果 |
|---|---|---|---|
| P6-T01 | ローカルHTTPサーバーへChat Completions payloadを実送信する | 応答をOutputSchema検証後の辞書として取得できる | 合格 |
| P6-T02 | 受信したHTTP payloadを検査する | messages、生成パラメーター、JSON Schema指定が正しい | 合格 |
| P6-T03 | payload送信前のhealth確認を検査する | GET `/health` の後にPOSTし、health失敗時はPOSTしない | 合格 |
| P6-T04 | Chat CompletionsがHTTPエラーを返す | `LlamaServerError` となる | 合格 |
| P6-T05 | llama-serverに接続できない | `LlamaServerError` となる | 合格（接続エラーをモック） |
| P6-T06 | HTTPタイムアウトが発生する | `LlamaServerError` となる | 合格（タイムアウトをモック） |
| P6-T07 | 応答JSONが不正、または応答形式が不正 | `LlamaServerError` となる | 合格 |
| P6-T08 | LLMのcontentがスキーマ不一致 | Pydantic検証エラーとなる | 合格 |
| P6-T09 | 実際のllama-serverへ接続する | ヘルスチェックと推論が成功する | 合格（Gemma 4 12B） |
| P6-T10 | 実モデルでStructured Outputを要求する | `{"text":"..."}` 形式の出力を取得・検証できる | 合格（`{"text":"Hello."}`） |

テスト実行: `python -m pytest inference\tests\test_server.py -q`（9 passed）、`python -m pytest inference\tests -q`（46 passed）、変更したPythonファイルの `py_compile`（成功）。

> 実ビルド version 10066 / commit `86a9c79f8` でhealth、Chat Completions、Structured Outputを実機確認した。プロセスの起動・停止は `server.py` の `LlamaServerManager` が保持するProcessオブジェクトだけを対象にする。

## 完了条件

- [x] ローカルHTTPサーバーを使ったpayload・health順序テストが合格する。
- [x] 実際のllama-serverでヘルスチェックが成功する。
- [x] 実モデルによるStructured Outputの生成とPydantic検証が成功する。
- [x] 使用ビルドで非対応のオプション／APIがないことを確認する。

---

# Phase 7. llama-server プロセス管理

## 目的

Python起動時に `config.yaml` のdefaultモデルをロードし、llama-serverを安全に停止できるようにする。利用モデルを変更する場合は `config.yaml` を編集してPythonを再起動する。

## 実装タスク

### 7.1 プロセス管理

- [x] `server.py` の `LlamaServerManager` にプロセス管理を実装する。
- [x] モデル定義から起動引数リストを生成する。
- [x] `subprocess.Popen` に引数リストを渡して起動する。
- [x] `shell=True` やシェル文字列による起動を使用しない。
- [x] `Popen` のProcessオブジェクトを保持する。
- [x] stdout / stderrを破棄し、表示しない。
- [x] 起動後、HTTPヘルスチェックをポーリングする。
- [x] `startup_timeout` を超えた場合は起動失敗にする。
- [x] 停止時は `shutdown_timeout` の範囲で終了を待つ。
- [x] タイムアウト時は強制終了する。
- [x] Python終了時に管理中のllama-serverを停止する。
- [x] プロセスの異常終了を検知し、状態を更新する。

### 7.2 状態管理

- [x] `stopped` / `starting` / `ready` / `stopping` / `error` を管理する。
- [x] 現在のモデルIDを管理する。
- [x] 状態を一元管理する。

## テストケース

### プロセス管理テスト

| ID | 内容 | 期待結果 | 結果 |
|---|---|---|---|
| P7-T01 | 起動引数を生成する | 設定値が正しい引数リストになる | 合格 |
| P7-T02 | パス等に空白がある設定で引数を生成する | 引数が分割・破損せずに渡される | 合格 |
| P7-T03 | 正常起動をモックする | Processを保持し `ready` になる | 合格 |
| P7-T04 | 起動後もヘルスチェックが成功しない | startup_timeout後に `error` になる | 合格 |
| P7-T05 | 起動直後にプロセスが終了する | 起動失敗として検知する | 合格 |
| P7-T06 | 正常停止する | プロセス終了後に `stopped` になる | 合格 |
| P7-T07 | 停止がタイムアウトする | 強制終了される | 合格 |
| P7-T08 | Python終了処理を実行する | 管理中のプロセスが停止される | 合格 |
| P7-T09 | プロセスが外部要因で終了する | 状態が `error` 等に更新される | 合格 |

### 設定モデルの起動テスト

| ID | 内容 | 期待結果 | 結果 |
|---|---|---|---|
| P7-T10 | defaultモデルで起動する | `config.yaml` のdefault IDのモデルでreadyになる | 合格 |
| P7-T11 | defaultモデルを設定変更する | 次回起動時に変更後のモデルが選ばれる | 合格 |
| P7-T12 | 起動中にstartを重複要求する | 2つ目のllama-serverを起動しない | 合格 |
| P7-T13 | 推論中に停止を要求する | 推論完了後に停止し、新規推論を受け付けない | 合格 |

テスト実行: `python -m pytest inference\tests -q`（46 passed）、変更したPythonファイルの `py_compile`（成功）。実機では設定済みモデル `gemma-4-12b` の起動、health、Structured Output、停止を確認済み。

## 完了条件

- [x] 起動・停止・異常終了検知が機能する。
- [x] ヘルスチェックで起動完了を判定する。
- [x] 同時に管理するllama-serverが1プロセスに制限される。
- [x] defaultモデル起動の正常系・異常系テストが合格する。
- [x] 実機で設定モデルの起動・health・停止を確認する。

---

# Phase 8. Python Inference API

## 目的

FastAPIから現在のモデル状態と推論機能を提供する。

## 実装タスク

- [x] `GET /health` を実装する。
- [x] `GET /models/current` を実装する。
- [x] `POST /generate` を実装する。
- [x] APIリクエスト／レスポンス用のPydanticモデルを定義する。
- [x] 起動時に設定読み込み・検証を行う。
- [x] 起動時にdefaultモデルをロードする。
- [x] generateではPrompt Builder、llama-serverクライアント、OutputSchema検証を順番に実行する。
- [x] モデル状態が `ready` でない場合は推論を拒否する。
- [x] 推論中の停止要求を安全に処理する。
- [x] FastAPI終了時にllama-serverを停止する。
- [x] エラーを適切なHTTPステータスとJSON形式で返す。

## テストケース

| ID | 内容 | 期待結果 |
|---|---|---|
| P8-T01 | `/health` を呼び出す | Python APIとモデル状態を取得できる | 合格 |
| P8-T02 | `/models/current` を呼び出す | 現在のモデルIDと状態が返る | 合格 |
| P8-T03 | 正常なgenerateリクエストを送る | `{"text":"..."}` が返る | 合格 |
| P8-T04 | 必須項目が欠けたgenerateを送る | 422等の入力エラーとなる | 合格 |
| P8-T05 | モデルがreadyでない状態でgenerateする | 推論が拒否される | 合格 |
| P8-T06 | llama-serverが推論エラーを返す | APIが適切なエラーを返す | 合格 |
| P8-T07 | Pydantic検証に失敗する | 不正出力を正常レスポンスとして返さない | 合格 |
| P8-T08 | FastAPIを終了する | 管理中のllama-serverが停止する | 合格 |

- [x] Python Inference APIの全エンドポイントが動作する。
- [x] APIテストがすべて合格する。

テスト実行: `python -m pytest inference\tests -q`（53 passed）。
実機確認: 設定モデル `gemma-4-12b` で `/health` と `/models/current` が成功し、`POST /generate` から `{"text":"Hello!"}` を取得。

## 完了条件

- [x] Python Inference APIの全エンドポイントが動作する。
- [x] APIテストがすべて合格する。
- [x] 実モデルを使ったgenerateが成功する。

---

# Phase 9. Go Backend API と Python接続

## 目的

Goをアプリケーションの窓口とし、Session管理とPython Inference APIへの接続を実装する。

## 実装タスク

### 9.1 Python API Client

- [x] `service/inference_client.go` を実装する。
- [x] Python APIのベースURLを環境変数 `INFERENCE_API_URL` で設定可能にする。
- [x] HTTPタイムアウトを設定する（90秒）。
- [x] `/generate` を呼び出す。
- [x] `/models/current` を呼び出す。
- [x] 接続エラー・タイムアウト・不正レスポンスを区別して扱う。

### 9.2 Session / Chat API

- [x] `POST /api/session` で有効なCookieのセッションを再利用し、Cookieがない・無効・期限切れの場合は新規Sessionを発行する。
- [x] Session IDをHttpOnly Cookieだけで受け渡し、レスポンス本文には含めない。
- [x] セッションを扱うAPIはSession Storeに存在するCookieのセッションだけを受け付け、未発行・期限切れの場合は401を返す。
- [x] Session IDをURLパス・クエリ・リクエスト本文から受け付けない。
- [x] `POST /api/chat` を実装する。
- [x] `GET /api/history` を実装する。
- [x] `POST /api/reset` を実装する。
- [x] `PUT /api/system-prompt` を実装する。
- [x] 同一セッションからの同時送信を制御する。
- [x] 推論成功時のみHistoryを更新する。

### 9.3 Model Status API

- [x] `GET /api/models/current` を実装する。
- [x] Python側のエラーをGo APIの適切なHTTPステータスへ変換する。

## テストケース

### Python API Client

| ID | 内容 | 期待結果 | 結果 |
|---|---|---|---|
| P9-T01 | Python `/generate` の正常応答をモックする | Goが応答内容を取得できる | 合格 |
| P9-T02 | Python APIが接続拒否する | 接続エラーとして扱う | 合格 |
| P9-T03 | Python APIがタイムアウトする | タイムアウトとして扱う | 合格 |
| P9-T04 | Python APIが不正JSONを返す | 不正レスポンスとして扱う | 合格 |
| P9-T05 | Python APIがHTTPエラーを返す | エラー情報を失わずに扱う | 合格 |

### Go API

| ID | 内容 | 期待結果 |
|---|---|---|
| P9-T06 | Cookieなしで `POST /api/session` を呼ぶ | 新規Sessionを発行し、IDはHttpOnly Cookieだけに設定される | 合格 |
| P9-T07 | `/api/chat` に正常なmessageを送る | Pythonの応答が返る | 合格 |
| P9-T08 | `/api/chat` に空messageを送る | 400エラーとなる | 合格 |
| P9-T09 | `/api/history` を呼ぶ | SessionのHistoryが返る | 合格 |
| P9-T10 | `/api/reset` を呼ぶ | Historyが空になりSystem Promptは維持される | 合格 |
| P9-T11 | `/api/system-prompt` を更新する | SessionのSystem Promptが更新される | 合格 |
| P9-T12 | `/api/models/current` を呼ぶ | 現在のモデル状態が返る | 合格 |
| P9-T13 | Python接続失敗中に `/api/chat` を呼ぶ | 502相当のエラーとなりHistoryは更新されない | 合格 |
| P9-T14 | 同一Sessionから同時にchatを送る | 同時処理が制御される | 合格（race detector含む） |
| P9-T15 | 異なるSessionからchatを送る | Session間でHistoryが混在しない | 合格 |
| P9-T16 | ブラウザCookieを確認する | Session IDにHttpOnlyが設定されている | 合格 |
| P9-T17 | 有効なCookieで `POST /api/session` を呼ぶ | 同じSessionを再利用する | 合格 |
| P9-T18 | 未知のCookieで `POST /api/session` を呼ぶ | 新しいSession IDのCookieを発行する | 合格 |
| P9-T19 | Cookieなし・未知・期限切れで状態APIを呼ぶ | 401となり、新規Sessionは作成されない | 合格 |

テスト実行: `go test -race ./...`、`go vet ./...` が合格。

## 完了条件

- [x] Go APIが仕様書の全エンドポイントを提供する。
- [x] GoからPythonへの通信が正常に動作する。
- [x] セッション分離・Cookie・履歴更新ルールがテストで確認される。
- [x] APIテストがすべて合格する。

---

# Phase 10. Frontend UI

## 目的

ブラウザ上で現在のモデル状態を表示し、System Prompt編集、チャット、履歴リセットができるUIを実装する。

## 実装タスク

- [x] `index.html` に画面構造を作成する。
- [x] `style.css` で基本レイアウトを作成する。
- [x] 現在のモデル名・状態表示を作成する。
- [x] System Prompt編集欄を作成する。
- [x] Chat History表示エリアを作成する。
- [x] メッセージ入力欄とSendボタンを作成する。
- [x] Resetボタンを作成する。
- [x] JavaScriptからGo APIを呼び出す処理を実装する。
- [x] ページ読み込み時に現在のモデル・Historyを取得する。
- [x] System Promptの更新処理を実装する。
- [x] チャット送信と応答表示を実装する。
- [x] Enterキーで送信できるようにする。
- [x] 送信中は二重送信を防止する。
- [x] Reset後にHistory表示を更新する。
- [x] ローディング表示とエラーメッセージ表示を実装する。
- [x] ユーザー入力・LLM出力をHTMLとして直接挿入せず、安全にテキスト表示する。

- [x] Go Backendから同一オリジンでFrontendを配信する。

## テストケース

| ID | 内容 | 期待結果 | 結果 |
|---|---|---|---|
| P10-T01 | ページを開く | チャット画面が表示される | 合格 |
| P10-T02 | 現在のモデル情報を取得する | モデル名と状態が表示される | 合格 |
| P10-T03 | Historyを取得する | 既存メッセージが画面に表示される | 合格 |
| P10-T04 | System Promptを編集して保存する | API更新が成功し、以降の送信に反映される | 合格 |
| P10-T05 | メッセージを送信する | UserとAssistantのメッセージが表示される | 合格 |
| P10-T06 | Enterキーを押す | メッセージが送信される | 合格 |
| P10-T07 | 送信中にSendを連続クリックする | 二重送信されない | 合格（リクエスト1件） |
| P10-T08 | Resetを押す | History表示が消える | 合格 |
| P10-T09 | APIエラーを発生させる | エラーメッセージが表示される | 合格 |
| P10-T10 | ユーザー入力にHTMLタグ文字列を含める | HTMLとして実行されず文字列として表示される | 合格 |
| P10-T11 | ブラウザを再読み込みする | 同じCookieのSessionでHistoryを再取得できる | 合格 |

検証: `go test -race ./...` 合格。ブラウザーでモックPython APIを使い、P10-T01〜P10-T11を確認。

## 完了条件

- [x] 仕様書に記載されたUI要素がすべて存在する。
- [x] UIから全Go APIを利用できる。
- [x] ローディング・エラー・操作無効化が機能する。
- [x] Frontendテストケースがすべて合格する。

---

# Phase 11. 全体結合テスト

## 目的

Frontend → Go → Python → llama-server の全経路を接続し、実モデルを使ってアプリケーション全体が動作することを確認する。

## 事前準備

- [x] `config.yaml` に実際のllama-server実行ファイルを設定する。
- [x] 少なくとも1つの利用可能なGGUFモデルを登録する。
- [x] 使用するllama.cppのバージョンを記録する: `10066 (86a9c79f8)` (MSVC 19.28.29337.0, x64)
- [x] PythonとGoの起動手順を確認する。

## 結合テストケース

| ID | 内容 | 期待結果 | 実施結果 |
|---|---|---|---|
| P11-T01 | Pythonサーバーを起動する | configを読み込みdefaultモデルがreadyになる | 合格 |
| P11-T02 | Goサーバーを起動する | APIが待ち受け状態になる | 合格 |
| P11-T03 | ブラウザで画面を開く | モデル・状態・Historyが表示される | 合格 |
| P11-T04 | 初回メッセージを送信する | 実モデルから回答が返る | 合格 |
| P11-T05 | 2回目のメッセージを送信する | 直前の会話を踏まえた応答が生成される | 合格 |
| P11-T06 | System Promptを変更して送信する | 変更後のSystem Promptが推論に反映される | 合格 |
| P11-T07 | 6ターン以上会話する | 保存Historyは維持され、推論入力は直近5ターンに制限される | 合格 |
| P11-T08 | Resetを実行する | Historyだけが消え、System Promptは残る | 合格 |
| P11-T09 | llama-serverを停止させる | 異常状態が検知され、推論失敗がUIに表示される | 合格 |
| P11-T10 | Pythonサーバーを終了する | 管理中のllama-serverも停止する | 合格 |
| P11-T11 | Goサーバーを再起動する | メモリ上のSessionは消失し、新規Sessionとして開始する | 合格 |
| P11-T12 | ブラウザを再読み込みする | 有効なCookieがあれば同じSessionのHistoryを取得できる | 合格 |

P11-T07ではブラウザ上で6ターン分のHistoryが維持されることを確認し、`go test ./service`で直近5ターンへの制限を確認した。P11-T06は初回にモデルの不正な生成形式による502が発生したが、同じ条件での再試行とその後の会話は成功した。

## 完了条件

- [x] 実モデルでチャットができる。
- [x] System Promptが反映される。
- [x] 直近5ターンの履歴制限が機能する。
- [x] 異常時に適切なエラーが表示される。
- [x] 全体結合テストがすべて合格する。

---

# Phase 12. 受け入れテスト・完成確認

## 目的

初期バージョンの実装範囲を満たしていることを、利用者視点で最終確認する。

## 受け入れテストケース

| ID | シナリオ | 合格条件 | 実施結果 |
|---|---|---|---|
| AT-01 | アプリケーションを起動する | Pythonがdefaultモデルをロードし、Go APIとUIが利用可能になる | 合格 |
| AT-02 | ブラウザから会話する | 入力した内容に対してLLMの回答が表示される | 合格 |
| AT-03 | System Promptを変更する | 変更内容が次回以降の推論に使われる | 合格 |
| AT-04 | 会話を継続する | 過去の会話を文脈として利用する | 合格 |
| AT-05 | 5ターンを超えて会話する | LLMには直近5ターンだけが渡される | 合格 |
| AT-06 | 会話履歴をリセットする | Historyが消え、System Promptは保持される | 合格 |
| AT-07 | 推論サーバーに異常を発生させる | 状態が反映され、推論エラーが利用者に通知される | 合格 |
| AT-08 | アプリケーションを終了する | llama-serverプロセスが残存しない | 合格 |
| AT-09 | アプリケーションを再起動する | Sessionはメモリ管理の仕様どおり初期化される | 合格 |

Phase 11の実モデルを使った全体結合テスト結果を受け入れ確認に使用した。Goは`go test -race ./...`と`go vet ./...`、Pythonは`.venv\Scripts\python.exe -m pytest`を実行し、Goの全テストとPythonの53テストが合格した。PythonのテストではStarlette TestClientのhttpx利用に関する非推奨警告が1件出たが、テストはすべて成功した。

## 最終チェックリスト

### 機能

- [x] 1つのチャット画面がある。
- [x] Session管理ができる。
- [x] System PromptをUIから編集できる。
- [x] 会話履歴をメモリに保持できる。
- [x] LLMに直近5ターンを渡せる。
- [x] Python FastAPIでInference APIを提供できる。
- [x] Pythonがllama-serverを起動・停止できる。
- [x] `config.yaml` でdefaultモデルを指定でき、変更後の再起動で反映される。
- [x] llama-server経由でLLM推論できる。
- [x] JSON SchemaによるStructured Outputを利用できる。
- [x] Pydanticで生成結果を検証できる。
- [x] 会話履歴をリセットできる。
- [x] 推論サーバーの状態を表示できる。

### 非機能

- [x] Session StoreがMutexで保護されている。
- [x] 同一Sessionからの同時送信が制御される。
- [x] HTTP通信にタイムアウトが設定されている。
- [x] Session ID CookieにHttpOnlyが設定されている。
- [x] ユーザー入力・LLM出力が安全にテキスト表示される。
- [x] Python APIとllama-serverが原則localhostにバインドされている。
- [x] llama-server起動にシェル文字列を使用していない。
- [x] サーバー終了時にllama-serverプロセスが停止する。

### リリース判定

- [x] 全フェーズの完了条件を満たしている。
- [x] 全単体テスト・APIテストが合格している。
- [x] 全体結合テストが合格している。
- [x] 受け入れテストが合格している。
- [x] 未解決の重大な不具合がない。
- [x] 起動方法・設定方法・テスト方法が記載されている。

---

# 初期バージョンの対象外

以下は初期バージョンでは実装しない。実装タスクに追加しないこと。

- ユーザー認証
- データベース
- 複数モデルの同時ロード
- ストリーミング生成
- Temperature等の生成パラメータUI設定
- 会話履歴の永続化
- 複数チャットルーム
- ファイルアップロード
- UIからのモデル定義追加・編集

# 実装時の注意事項

- llama.cppのバージョンによってCLIオプション、ヘルスチェック方法、Structured Outputの形式が異なる可能性がある。Phase 6の開始時に実環境で確認する。
- `Popen`でプロセスを起動しただけではreadyと判定しない。HTTPヘルスチェックが成功して初めてreadyとする。
- 使用モデルは起動時に `config.yaml` のdefault設定から決定し、変更後はPythonを再起動する。
- Historyの5ターンは、完了済みのUser / Assistantペアを単位に数える。
- 推論失敗時はUser MessageもHistoryへ追加しない。
- Cookieの有効期限とサーバー側Sessionの有効期限を整合させる。
