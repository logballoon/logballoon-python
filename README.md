# LogBalloon

Offline-first logging and operations SDK for desktop apps.

Buffer locally. Deliver reliably.

- Site: https://logballoon.github.io/logballoon-python/
- PyPI: https://pypi.org/project/logballoon/
- Repo: https://github.com/logballoon/logballoon-python

## Install

```bash
pip install logballoon
```

開発中（このリポジトリ）:

```bash
pip install -e .
```

## Quick start

```python
from logballoon import LogBalloon

lb = LogBalloon(
    app_name="FFT Analyzer",
    version="1.0.0",
    endpoint="http://127.0.0.1:8765",
)
lb.start()
lb.event("export_complete", {"rows": 120})
```

これだけで:

- `installation_id` の生成・保存
- 起動ログ送信
- 任意イベント送信
- 未捕捉例外のクラッシュ報告
- 通信失敗時の SQLite キュー退避と再送

を行います。**追加の依存パッケージは不要**です（Python 標準ライブラリのみ）。

## Demo

```bash
# 端末1: 受信サーバ
python examples/demo_server.py

# 端末2: クライアント
python examples/demo_client.py
```

オフライン動作の確認:

```bash
# サーバを止めている状態で実行 → キューに溜まる
python examples/demo_client.py

# サーバ起動後にもう一度実行 → 溜まった分も送られる
python examples/demo_server.py
python examples/demo_client.py
```

## API

| メソッド | 説明 |
|---|---|
| `start()` | 起動ログを enqueue し、バックグラウンド送信を開始 |
| `event(name, payload=None)` | 任意イベントを enqueue |
| `flush(timeout=None)` | 未送信キューを今すぐ送る |
| `stop(flush=True)` | 送信スレッドを停止 |

## Design

```
App → LogBalloon → SQLite queue → HTTP (urllib) → Server
                 ↖ retry on recovery ↗
```

## Requirements

- Python 3.10+
- Windows / Linux / macOS（ラズパイ含む）
