# 🐺 ワンナイト人狼 Discord Bot

Discord上で3〜6人向けのワンナイト人狼風ゲームを遊べるBotです。

## 特徴

- **プレイ人数**: 3〜6人
- **中央カード**: 2枚
- **対応役職**: 村人、人狼、占い師、怪盗、吊り人（Tanner）
- **スラッシュコマンド対応**: Discord の `/` コマンドで操作

## 🎮 役職説明

| 役職 | 陣営 | 夜の行動 | 勝利条件 |
|------|------|----------|----------|
| 村人 | 村人 | なし | 人狼を1人以上処刑する |
| 人狼 | 人狼 | 他の人狼を確認 | 人狼が1人も処刑されない |
| 占い師 | 村人 | 他プレイヤー1人 or 中央2枚を見る | 人狼を1人以上処刑する |
| 怪盗 | 村人 | 他プレイヤーとカードを交換 | 交換後の陣営で判定 |
| 吊り人 | 吊り人 | なし | 自分が処刑される |

## 📦 環境構築

### 必要要件

- Python 3.11 以上
- [uv](https://github.com/astral-sh/uv) パッケージマネージャー

### 1. リポジトリのクローン

```bash
git clone <repository-url>
cd onj
```

### 2. 仮想環境の作成と有効化

```bash
# 仮想環境を作成
uv venv .venv

# 有効化 (macOS / Linux)
source .venv/bin/activate

# 有効化 (Windows PowerShell)
.venv\Scripts\Activate.ps1

# 有効化 (Windows コマンドプロンプト)
.venv\Scripts\activate.bat
```

### 3. 依存パッケージのインストール

```bash
uv pip install discord.py python-dotenv
```

### 4. 環境変数の設定

```bash
cp .env.example .env
```

`.env` ファイルを編集し、Discord Botのトークンを設定します：

```
DISCORD_TOKEN=your_bot_token_here
GUILD_ID=your_server_id_here
```

**GUILD_ID の取得方法：**
1. Discordの「ユーザー設定」→「詳細設定」→「開発者モード」を ON にする
2. テストしたいサーバーを右クリック →「サーバーIDをコピー」

※ `GUILD_ID` を設定すると、そのサーバーにのみコマンドが即座に反映されます。設定しない場合はグローバル同期（反映に最大1時間）になります。

## 🤖 Discord Botの準備

1. [Discord Developer Portal](https://discord.com/developers/applications) にアクセス
2. 「New Application」でアプリケーションを作成
3. 「Bot」タブでBotを作成し、トークンをコピー
4. **⚠️ 重要：Privileged Gateway Intents を有効にする**
   - 「Bot」タブの下部にある「Privileged Gateway Intents」セクションで以下を **ON** にする：
     - ✅ **SERVER MEMBERS INTENT**
     - ✅ **MESSAGE CONTENT INTENT**
5. 「OAuth2」→「URL Generator」で以下の権限を選択:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Send Messages`, `Send Messages in Threads`, `Embed Links`, `Read Message History`
6. 生成されたURLでBotをサーバーに招待

## 🚀 Botの起動

```bash
python bot.py
```

起動成功時、コンソールに以下のようなメッセージが表示されます：

```
ワンナイト人狼Bot がログインしました: BotName#1234
スラッシュコマンドを同期しました
```

## 📖 遊び方

### ゲームの流れ

1. **ゲーム開始**: `/onj start` で募集フェーズを開始
2. **参加**: `/onj join` でプレイヤーが参加
3. **ゲーム開始**: `/onj begin` でゲームを開始（3〜6人必要）
4. **夜フェーズ**: 各役職がDMで行動を選択
5. **昼フェーズ**: 議論後、`/onj vote @プレイヤー` で投票
6. **結果発表**: 処刑結果と勝敗が発表される

### コマンド一覧

| コマンド | 説明 |
|----------|------|
| `/onj start` | ゲームの募集を開始する |
| `/onj join` | ゲームに参加する |
| `/onj leave` | ゲームから離脱する |
| `/onj players` | 現在の参加者を表示する |
| `/onj begin` | ゲームを開始する（ホストのみ） |
| `/onj vote @player` | プレイヤーに投票する |
| `/onj cancel` | ゲームをキャンセルする（ホストのみ） |

### 夜フェーズの行動（DMで操作）

- **占い師**: `!seer player @プレイヤー` または `!seer center` で行動
- **怪盗**: `!thief @プレイヤー` で行動

## 🎯 役職構成（人数別）

| 人数 | 役職構成 |
|------|----------|
| 3人 | 村人, 人狼, 占い師, 怪盗, 吊り人 |
| 4人 | 村人×2, 人狼, 占い師, 怪盗, 吊り人 |
| 5人 | 村人×2, 人狼×2, 占い師, 怪盗, 吊り人 |
| 6人 | 村人×3, 人狼×2, 占い師, 怪盗, 吊り人 |

## 🔧 トラブルシューティング

### スラッシュコマンドが表示されない

- Botを一度サーバーから削除し、再度招待してみてください
- コマンドの同期には最大1時間かかる場合があります

### DMが届かない

- プライバシー設定で「サーバーメンバーからのダイレクトメッセージを許可する」が有効になっているか確認してください

## 📄 ライセンス

MIT License

