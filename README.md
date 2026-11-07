# ローカルLLMチャット
GoとPythonの連携を学習することを目的として開発した、ローカルLLM向けのチャットアプリケーションです。

Go（Echo）をバックエンドのAPIおよびセッション管理に、Python（FastAPI）をLLM推論処理および推論サーバーの管理に使用しています。LLMの推論には llama.cpp の llama-server を利用し、設定ファイルからモデルを指定・切り替えられる構成にしています。

主な機能は以下のとおりです。
- GoとPython間のHTTP API連携
- llama-serverのプロセス起動・停止管理
- 設定ファイルによるモデル管理・切り替え
- セッション単位の会話履歴管理
- System Promptの編集
- 直近5ターンの会話履歴を利用したLLM推論
- JSON SchemaによるStructured OutputとPydanticを用いた出力検証

GoとPythonそれぞれの役割を分離し、API設計、プロセス管理、セッション管理、LLM推論処理などの実装を通じて、複数言語を組み合わせたアプリケーション開発を学ぶことを目的としています。

## 開発環境
各サービスは `src` ディレクトリを基準に、それぞれ別のターミナルで起動します。

### Goバックエンド

```powershell
Set-Location backend
go mod download
go run .
```

バックエンドは `http://127.0.0.1:8000` で待ち受けます。次のコマンドでヘルスチェックできます。

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

バックエンドのテストは次のコマンドで実行します。

```powershell
go test ./...
```

Session Storeのセッションは、アクセス・更新がない状態が30分続くと期限切れになります。取得・更新のたびに期限が延長されます。

### Python推論API

初回のみ、仮想環境を作成して依存関係をインストールします。テストも実行する場合は開発用依存関係をインストールしてください。

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

起動前に、ルートの `config.yaml` で `llama_server.executable` と各モデルの `path` を実際に配置したファイルに合わせてください。相対パスは `src` を基準に解決され、指定ファイルが存在しない場合は起動時に項目名付きのエラーになります。

APIを起動します。ホストとポートは `config.yaml` の `server` 設定が使われます。

```powershell
.\.venv\Scripts\python.exe -m inference.main
```

次のコマンドでヘルスチェックできます。

```powershell
Invoke-RestMethod http://127.0.0.1:8001/health
```

Python側の設定テストは次のコマンドで実行します。

```powershell
.\.venv\Scripts\python.exe -m pytest inference\tests
```

### フロントエンド

Goバックエンドを起動すると、フロントエンドも同じオリジンで配信されます。ブラウザーで次のURLを開きます。

```text
http://127.0.0.1:8000/
```

同一オリジンで配信するため、セッションCookieをそのままGo APIに送信できます。
