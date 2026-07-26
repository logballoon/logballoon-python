# 仕様メモ: 連絡先プロンプト（Contact Prompt）

ステータス: **実装済み（0.1.8: フレームワーク非依存 Contact API 公開）**  
対象バージョン: **0.1.8**  
最終更新: 2026-07-26

---

## 1. 目的

LogBalloon の差別化として、開発者が **任意で** エンドユーザーから連絡先（メール）を集められるようにする。

- クラッシュや運用上の問題があったときに、開発者から連絡できる
- `installation_id` だけでは「誰か」が分からないギャップを埋める

コアの思想は変えない:

- オフライン優先・依存ゼロ・静かに運ぶ
- **import しただけでは UI は出ない**（明示オプトイン）

---

## 2. やらないこと（Non-goals）

| やらない | 理由 |
|---|---|
| import だけで自動ポップアップ | 信頼を損なう / シンプル思想と矛盾 |
| 全フレームワーク自動検知 | メンテ地獄・バージョン地獄 |
| メール必須（スキップ不可） | 配布アプリで嫌がられる |
| コアへの重い UI 依存 | `pip install logballoon` の軽さを守る |
| マーケティング同意の一般基盤 | 連絡用の最小機能に絞る |

---

## 3. オプトイン API（案）

```python
from logballoon import LogBalloon

lb = LogBalloon(app_name="...", version="...", endpoint="...")
lb.start()

# 欲しいアプリだけ明示。これ無しでは連絡先機能は動かない。
lb.enable_contact_prompt(
    ui="tk",              # MVP は "tk" のみ
    on=("startup",),      # 決定: MVP は startup のみ（crash は Phase F）
    skip_days=14,         # 決定: デフォルト 14 日
    message=None,         # 省略時はデフォルト文言
)
```

デフォルト値（決定）:

| 引数 | デフォルト |
|---|---|
| `on` | `("startup",)` |
| `skip_days` | `14` |
| `ui` | 必須指定（推測しない） |

原則:

- `enable_contact_prompt` を呼ばない限り、状態ファイルも UI も触らない
- UI 実装が無い `ui` 値は明確にエラー（黙って無視しない）
- Web / GUI 系は公開 Contact API を使って各アプリが UI を実装する

---

## 3.1 フレームワーク非依存 API（実装済み）

Tk / Qt / Web といった UI 層から、次の公開 API だけを使う。
全送信は `POST /user` に集約し、フレームワーク別プロトコルは作らない。

```python
if lb.should_prompt_contact():
    state = lb.contact_state()

lb.submit_contact("user@example.com")  # register / update を自動選択
lb.confirm_contact()                   # confirm
lb.skip_contact()                      # ローカルのみ、送信なし
lb.defer_contact()                     # メール維持、送信なし
```

| メソッド | ローカル状態 | キュー |
|---|---|---|
| `contact_state()` | 読み取り | なし |
| `should_prompt_contact()` | 読み取り | なし |
| `submit_contact()` | メール保存・静穏期間更新 | `user` register/update |
| `confirm_contact()` | 確認日時・静穏期間更新 | `user` confirm |
| `skip_contact()` | skipped・静穏期間更新 | なし |
| `defer_contact()` | メール維持・静穏期間更新 | なし |

方針:

- UI コンポーネントは原則として各アプリが作る
- SDK は各 UI フレームワークを自動検知しない
- Qt / Streamlit / Flask / FastAPI / Django の公式アダプタは、具体的な要望が出るまで作らない
- 組み込み Tk も、この公開 API を呼ぶだけの薄いアダプタとする

---

## 4. 状態機械

永続状態（アプリ data 配下、`installation_id` と同じ世界）:

| 状態 | 意味 |
|---|---|
| `unset` | 未登録・未スキップ（初期） |
| `registered` | メール保存済み |
| `skipped` | ユーザーがスキップした |

### フロー

```
unset
  ├─ 入力して送信     → registered（サーバへ POST /user）
  └─ スキップ         → skipped（skip_until = now + skip_days）

registered
  └─ 確認ダイアログ「このメールで連絡してよい？」
        ├─ Yes（OK）           → registered 維持 + skip_until = now + skip_days
                                 + POST /user action=confirm
        ├─ 変更                → 入力ダイアログへ → registered 更新 + POST /user
                                 + skip_until = now + skip_days
        └─ 今回は出さない      → 次回表示を skip_days 後まで延期
                                 （registered は維持。メールは消さない）

skipped
  └─ now < skip_until  → 出さない
     now >= skip_until → unset と同様の初回ダイアログを再提示
```

### UX 方針（合意）

- **毎回フル入力はしない**
- 登録済みなら **確認ダイアログ**（Yes / 変更 / 今回は出さない）
- **OK / 登録 / スキップ / 今回は出さない** のいずれも `skip_days`（デフォルト 14）静かにする
- 静穏期間後に再度確認する（毎起動は出さない）

---

## 5. トリガー

| トリガー | 挙動案 |
|---|---|
| `startup` | **MVP 対象。** `start()` 後、メインスレッドでプロンプト可能なら出す（Tk は呼び出し側スレッド注意） |
| `crash` | **MVP 対象外（Phase F）。** 未捕捉例外フック内での UI は壊れやすい |

### 決定: MVP は `startup` のみ

理由:

- crash フック内のモーダル UI は壊れやすい（プロセス終了直前・別スレッド・再入）
- クラッシュ処理が UI で失敗すると、本来のクラッシュ報告まで巻き添えになる

crash を後で足すときの前提（Phase F）:

- クラッシュ時にダイアログを出すのではなく、**「次回起動時に聞く」フラグ**を立てて即 return する方式を基本にする
- クラッシュ直後に重い UI を必須にしない

---

## 6. 永続化

場所: 既存の per-app data dir（例: `.../logballoon/<app>/contact.json`）

例:

```json
{
  "status": "registered",
  "email": "user@example.com",
  "updated_at": 1784692408.12,
  "last_confirmed_at": 1784692408.12,
  "skip_until": null,
  "consent_version": 1
}
```

ルール:

- メールはローカルに保持し、次回は確認だけ
- 変更時は上書き + サーバ再送
- アンインストール相当で data dir を消すと状態も消える（installation_id と同じ寿命）

---

## 7. プロトコル: `POST /user`

認証は既存どおり任意（`api_key` / `headers`）。

### リクエスト（案）

```json
{
  "app": "logballoon_test_app",
  "version": "1.0.0",
  "sdk_version": "0.1.8",
  "installation_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "email": "user@example.com",
  "action": "register",
  "consent_version": 1,
  "timestamp": 1784692408.12
}
```

| フィールド | 必須 | 説明 |
|---|---|---|
| envelope 系 | yes | 他エンドポイントと同様 |
| `email` | yes（confirm も送る） | ユーザー入力。confirm 時もローカル保持値を同梱 |
| `action` | yes | `register` / `update` / `confirm` |
| `consent_version` | yes | 文言・ポリシー改定時に上げる。ローカルにも保存 |

### 決定: `/user` も offline queue に載せる

- kind=`user` で startup / event / crash と同じ配送経路
- オフラインでもローカル状態は先に更新し、配送はキューが担う（ブランクでも動く）
- `confirm` もサーバへ送る（ローカル完結にしない）。サーバは保存を省略して監査ログだけでもよい

### 決定: メール検証は緩め

- MVP: 空でない・空白除去後に `@` を1つ以上含む、程度
- 厳密な RFC チェックや MX 確認はしない（間違えても仕方ない）

### サーバ側

- デモサーバに `/user` を追加
- FastAPI サンプルにも同じルートを載せる（別タスク）

---

## 8. UI（MVP）

| 項目 | MVP |
|---|---|
| 実装 | Tkinter（stdlib） |
| 配布 | **コア同梱＋遅延 import**（`logballoon.ui.tk`）。pip extras にはしない |
| 文言 | デフォルトは OS UI 言語（en / ja / zh）を自動判定。`message=` で本文のみ上書き可。`lang=` で明示指定可 |
| 多言語 | MVP は en / ja / zh。未知ロケールは en |

### 決定: Tk は extras にしない

理由:

- `tkinter` は **pip でインストールできない**（stdlib 同梱 or OS パッケージ）。`logballoon[tk]` を作っても中身が空になり、「入れたのに動かない」を生むだけ
- 遅延 import なら、`ui="tk"` を指定しない限りコアは Tk を一切触らない → 依存ゼロの体感は変わらない

代わりにやること:

- `logballoon/ui/tk.py` を作り、`enable_contact_prompt(ui="tk")` の中でだけ import
- `ImportError` 時は分かりやすく案内（Linux 例: `sudo apt install python3-tk`）
- 外部 UI の extras は具体的な要望が Issue で出るまで追加しない

デフォルト文言（案・日本語アプリ向けは呼び出し側で上書き推奨）:

> Something went wrong sometimes — may we keep an email to contact you?  
> We only use it when we need to reach you about this app.

必須 UI 要素:

1. 初回: email 入力 / 送信 / スキップ
2. 登録済み: 表示中メール / OK / 変更 / 今回は出さない

---

## 9. プライバシー・同意

- プロンプト本文で「何に使うか」を一文で示す（開発者が `message` で責任を持つ）
- SDK はメールを第三者 SaaS に送らない（セルフホスト endpoint のみ）
- ログイベントの payload にメールを勝手に混ぜない（`/user` 専用）

### 決定: `consent_version` 再確認は「ルールは決めるが MVP では動かさない」

| 段階 | 挙動 |
|---|---|
| MVP | `consent_version` をローカル保存＋`/user` に載せるだけ。バージョン差での再プロンプトはしない |
| 後続 | `stored.consent_version < configured` なら、登録済みでも **確認ダイアログ**を出す（再入力は不要。メールは維持）。Yes で version 更新 + `action=confirm` をキュー |

理由:

- ほとんどのアプリは文言をほぼ変えない → MVP で毎回気にする必要がない
- フィールドと将来ルールだけ先に決めておけば、実装を足すだけで済む
- いきなり強制再確認すると、アップデート直後に急にダイアログが増えてうるさい

`enable_contact_prompt(..., consent_version=1)` を引数に持ち、デフォルト `1`。

---

## 10. フェーズ分割

| Phase | 内容 | 依存 |
|---|---|---|
| **A** | 仕様確定・本メモ更新 | — |
| **B** | `POST /user` + offline queue kind + ローカル `contact.json` API（UI なし） | 認証ヘッダ（済） |
| **C** | `enable_contact_prompt(ui="tk")` + 確認/スキップ間隔（startup のみ） | B |
| **D** | デモサーバ `/user`、README、protocol 更新 | B/C |
| **E** | FastAPI 受信サンプル（疎通用） | D と独立でも可 |
| **F** | crash トリガー（次回起動フラグ方式） | C の運用後 |

連絡先 UI 本体より先に **B（運ぶ仕組み）** を固めると、シンプル思想を壊しにくい。

---

## 11. 決定済み / 未決

決定済み（2026-07-26）:

- [x] MVP トリガーは **`startup` のみ**（crash は Phase F）
- [x] `skip_days` デフォルトは **14**
- [x] Tk は **コア同梱＋遅延 import**。extras にはしない（pip で入らないため）
- [x] crash を足すときは **「次回起動フラグ」方式**を基本とする
- [x] `/user` は **offline queue（kind=user）**。confirm も含めサーバへ送る。オフラインでもローカル先更新
- [x] メール検証は **緩め**（空でない + `@` 含む程度）
- [x] `consent_version` は保存・送信する。**再確認ロジックは後続**（差分検知 → 確認ダイアログ、再入力なし）

未決: なし（仕様メモとしてはここまでで実装に入れる）

---

## 12. 一言まとめ

> 連絡先は「勝手に出る機能」ではなく、開発者が明示有効化する **任意の同意付きコンタクト収集**。  
> UX は初回入力 → 以降は確認 1 回、拒否・延期は 14 日スキップ。  
> `/user` も他と同じくキューで運ぶ。メール検証は緩め。consent_version は保存のみ（再確認は後続）。  
> MVP は startup のみ。先に `/user` と永続化、UI は Tk（コア同梱・遅延 import）の明示呼び出しから。
