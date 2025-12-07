"""
ワンナイト人狼 Discord Bot

エントリーポイント。Discord Botの起動とコマンド定義を行う。
スラッシュコマンド（/onj）を使用。
"""

import os
import asyncio
from typing import Optional
from datetime import datetime
from dotenv import load_dotenv

import discord
from discord import app_commands
from discord.ext import commands

from config import (
    ROLE_CONFIG,
    MIN_PLAYERS,
    MAX_PLAYERS,
    MESSAGES,
    ROLE_DESCRIPTIONS,
    NIGHT_ACTION_TIMEOUT,
    DISCUSSION_TIME,
    VOTE_TIMEOUT,
)
from game.models import Role, GamePhase, GameState, Player
from game.logic import (
    setup_game,
    process_werewolf_night,
    process_seer_action,
    process_thief_action,
    register_vote,
    calculate_votes,
    determine_execution,
    determine_winner,
    get_winner_message,
    get_final_roles_message,
    get_execution_message,
    get_current_night_role,
    advance_night_phase,
    is_night_phase_complete,
)

# 環境変数の読み込み
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")  # テスト用サーバーのID（オプション）

if not TOKEN:
    raise ValueError("DISCORD_TOKEN が設定されていません。.env ファイルを確認してください。")


# =============================================================================
# Bot設定
# =============================================================================

intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# チャンネルごとのゲーム状態を管理
# channel_id -> GameState
games: dict[int, GameState] = {}


# =============================================================================
# ユーティリティ関数
# =============================================================================

def get_game(channel_id: int) -> Optional[GameState]:
    """チャンネルのゲーム状態を取得する。"""
    return games.get(channel_id)


def create_game(channel_id: int, host_id: int) -> GameState:
    """新しいゲームを作成する。"""
    state = GameState(channel_id=channel_id, host_id=host_id)
    games[channel_id] = state
    return state


def end_game(channel_id: int) -> None:
    """ゲームを終了し、状態を削除する。"""
    if channel_id in games:
        del games[channel_id]


async def send_role_dm(user: discord.User, player: Player) -> bool:
    """プレイヤーにDMで役職を通知する。"""
    try:
        role = player.initial_role
        description = ROLE_DESCRIPTIONS.get(role, "")
        message = MESSAGES["role_notification"].format(
            role=role.value,
            description=description
        )
        await user.send(message)
        return True
    except discord.Forbidden:
        return False


# =============================================================================
# スラッシュコマンドグループ
# =============================================================================

class OnenightCommands(app_commands.Group):
    """ワンナイト人狼のコマンドグループ"""
    
    def __init__(self):
        super().__init__(name="onj", description="ワンナイト人狼のコマンド")
    
    @app_commands.command(name="start", description="ゲームの参加者募集を開始する")
    async def start(self, interaction: discord.Interaction) -> None:
        """ゲームの募集を開始する。"""
        channel_id = interaction.channel_id
        
        if channel_id is None:
            await interaction.response.send_message("このチャンネルでは使用できません。", ephemeral=True)
            return
        
        # 既存のゲームがあるか確認
        existing_game = get_game(channel_id)
        if existing_game and existing_game.phase != GamePhase.ENDED:
            await interaction.response.send_message(
                MESSAGES["game_already_running"],
                ephemeral=True
            )
            return
        
        # 新しいゲームを作成
        game = create_game(channel_id, interaction.user.id)
        game.add_player(interaction.user.id, interaction.user.display_name)
        
        await interaction.response.send_message(
            f"🐺 **ワンナイト人狼** の参加者を募集中！\n"
            f"`/onj join` で参加してください。\n"
            f"現在の参加者: 1人 ({interaction.user.display_name})\n\n"
            f"参加者が {MIN_PLAYERS}〜{MAX_PLAYERS}人 になったら、\n"
            f"ホストは `/onj begin` でゲームを開始できます。"
        )
    
    @app_commands.command(name="join", description="ゲームに参加する")
    async def join(self, interaction: discord.Interaction) -> None:
        """ゲームに参加する。"""
        channel_id = interaction.channel_id
        
        if channel_id is None:
            await interaction.response.send_message("このチャンネルでは使用できません。", ephemeral=True)
            return
        
        game = get_game(channel_id)
        
        if game is None or game.phase != GamePhase.WAITING:
            await interaction.response.send_message(
                "⚠️ 現在参加募集中のゲームがありません。`/onj start` で開始してください。",
                ephemeral=True
            )
            return
        
        if game.player_count >= MAX_PLAYERS:
            await interaction.response.send_message(
                MESSAGES["too_many_players"].format(max=MAX_PLAYERS),
                ephemeral=True
            )
            return
        
        if not game.add_player(interaction.user.id, interaction.user.display_name):
            await interaction.response.send_message(
                MESSAGES["already_joined"],
                ephemeral=True
            )
            return
        
        player_names = ", ".join(p.username for p in game.player_list)
        await interaction.response.send_message(
            f"✅ {interaction.user.display_name} さんが参加しました！\n"
            f"現在の参加者: {game.player_count}人 ({player_names})"
        )
    
    @app_commands.command(name="leave", description="ゲームから離脱する")
    async def leave(self, interaction: discord.Interaction) -> None:
        """ゲームから離脱する。"""
        channel_id = interaction.channel_id
        
        if channel_id is None:
            await interaction.response.send_message("このチャンネルでは使用できません。", ephemeral=True)
            return
        
        game = get_game(channel_id)
        
        if game is None or game.phase != GamePhase.WAITING:
            await interaction.response.send_message(
                MESSAGES["wrong_phase"],
                ephemeral=True
            )
            return
        
        if not game.remove_player(interaction.user.id):
            await interaction.response.send_message(
                MESSAGES["not_in_game"],
                ephemeral=True
            )
            return
        
        # ホストが離脱した場合はゲームをキャンセル
        if interaction.user.id == game.host_id:
            end_game(channel_id)
            await interaction.response.send_message(
                "❌ ホストが離脱したため、ゲームがキャンセルされました。"
            )
            return
        
        player_names = ", ".join(p.username for p in game.player_list)
        await interaction.response.send_message(
            f"❌ {interaction.user.display_name} さんが離脱しました。\n"
            f"現在の参加者: {game.player_count}人 ({player_names})"
        )
    
    @app_commands.command(name="players", description="現在の参加者を表示する")
    async def players(self, interaction: discord.Interaction) -> None:
        """現在の参加者を表示する。"""
        channel_id = interaction.channel_id
        
        if channel_id is None:
            await interaction.response.send_message("このチャンネルでは使用できません。", ephemeral=True)
            return
        
        game = get_game(channel_id)
        
        if game is None:
            await interaction.response.send_message(
                "⚠️ このチャンネルでゲームは行われていません。",
                ephemeral=True
            )
            return
        
        player_list = "\n".join(
            f"• {p.username}" + (" (ホスト)" if p.user_id == game.host_id else "")
            for p in game.player_list
        )
        
        phase_names = {
            GamePhase.WAITING: "参加募集中",
            GamePhase.NIGHT: "夜フェーズ",
            GamePhase.DISCUSSION: "議論フェーズ",
            GamePhase.VOTING: "投票フェーズ",
            GamePhase.ENDED: "終了",
        }
        
        await interaction.response.send_message(
            f"📋 **参加者一覧** ({game.player_count}人)\n"
            f"フェーズ: {phase_names.get(game.phase, '不明')}\n\n"
            f"{player_list}",
            ephemeral=True
        )
    
    @app_commands.command(name="begin", description="ゲームを開始する（ホストのみ）")
    async def begin(self, interaction: discord.Interaction) -> None:
        """ゲームを開始する。"""
        channel_id = interaction.channel_id
        
        if channel_id is None:
            await interaction.response.send_message("このチャンネルでは使用できません。", ephemeral=True)
            return
        
        game = get_game(channel_id)
        
        if game is None or game.phase != GamePhase.WAITING:
            await interaction.response.send_message(
                MESSAGES["wrong_phase"],
                ephemeral=True
            )
            return
        
        if interaction.user.id != game.host_id:
            await interaction.response.send_message(
                MESSAGES["not_host"],
                ephemeral=True
            )
            return
        
        if game.player_count < MIN_PLAYERS:
            await interaction.response.send_message(
                MESSAGES["not_enough_players"].format(min=MIN_PLAYERS, current=game.player_count),
                ephemeral=True
            )
            return
        
        if game.player_count > MAX_PLAYERS:
            await interaction.response.send_message(
                MESSAGES["too_many_players"].format(max=MAX_PLAYERS),
                ephemeral=True
            )
            return
        
        # 役職構成を取得
        role_list = ROLE_CONFIG.get(game.player_count)
        if role_list is None:
            await interaction.response.send_message(
                f"⚠️ {game.player_count}人用の役職構成が定義されていません。",
                ephemeral=True
            )
            return
        
        # 役職構成を集計して表示用文字列を作成
        from collections import Counter
        role_counts = Counter(role.value for role in role_list)
        role_composition = "、".join(
            f"{role}×{count}" if count > 1 else role
            for role, count in role_counts.items()
        )
        
        await interaction.response.send_message(
            f"🌙 **ゲームを開始します！**\n\n"
            f"📋 **役職構成（{len(role_list)}枚）**\n"
            f"{role_composition}\n"
            f"（プレイヤー{game.player_count}人 + 中央カード2枚）\n\n"
            f"各プレイヤーにDMで役職を通知します..."
        )
        
        # ゲームをセットアップ
        setup_game(game, role_list)
        
        # 各プレイヤーにDMで役職を通知
        dm_failed: list[str] = []
        for player in game.player_list:
            user = bot.get_user(player.user_id)
            if user is None:
                try:
                    user = await bot.fetch_user(player.user_id)
                except discord.NotFound:
                    dm_failed.append(player.username)
                    continue
            
            success = await send_role_dm(user, player)
            if not success:
                dm_failed.append(player.username)
        
        if dm_failed:
            if interaction.channel:
                await interaction.channel.send(
                    f"⚠️ 以下のプレイヤーにDMを送信できませんでした: {', '.join(dm_failed)}\n"
                    f"DMを受け取れるよう設定を確認してください。"
                )
        
        # 夜フェーズを開始
        await start_night_phase(interaction.channel, game)
    
    async def vote_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """投票先のオートコンプリート（ゲーム参加者のみ表示）"""
        channel_id = interaction.channel_id
        if channel_id is None:
            return []
        
        game = get_game(channel_id)
        if game is None or game.phase != GamePhase.VOTING:
            return []
        
        # 自分以外のゲーム参加者をフィルタリング
        choices = []
        for player in game.player_list:
            if player.user_id == interaction.user.id:
                continue  # 自分自身は除外
            if current.lower() in player.username.lower():
                choices.append(
                    app_commands.Choice(name=player.username, value=str(player.user_id))
                )
        
        return choices[:25]  # Discord の上限は25件
    
    @app_commands.command(name="vote", description="プレイヤーに投票する")
    @app_commands.describe(player="投票先のプレイヤー")
    @app_commands.autocomplete(player=vote_autocomplete)
    async def vote(self, interaction: discord.Interaction, player: str) -> None:
        """プレイヤーに投票する。"""
        channel_id = interaction.channel_id
        
        if channel_id is None:
            await interaction.response.send_message("このチャンネルでは使用できません。", ephemeral=True)
            return
        
        game = get_game(channel_id)
        
        if game is None or game.phase != GamePhase.VOTING:
            await interaction.response.send_message(
                MESSAGES["wrong_phase"],
                ephemeral=True
            )
            return
        
        voter = game.get_player(interaction.user.id)
        if voter is None:
            await interaction.response.send_message(
                MESSAGES["not_in_game"],
                ephemeral=True
            )
            return
        
        if voter.vote_target_id is not None:
            await interaction.response.send_message(
                MESSAGES["already_voted"],
                ephemeral=True
            )
            return
        
        # player はユーザーIDの文字列
        try:
            target_id = int(player)
        except ValueError:
            # 名前で検索を試みる
            target = None
            for p in game.player_list:
                if p.username.lower() == player.lower():
                    target = p
                    break
            if target is None:
                await interaction.response.send_message(
                    MESSAGES["invalid_target"],
                    ephemeral=True
                )
                return
            target_id = target.user_id
        
        target = game.get_player(target_id)
        if target is None:
            await interaction.response.send_message(
                MESSAGES["invalid_target"],
                ephemeral=True
            )
            return
        
        if interaction.user.id == target_id:
            await interaction.response.send_message(
                MESSAGES["cannot_vote_self"],
                ephemeral=True
            )
            return
        
        if not register_vote(game, interaction.user.id, target_id):
            await interaction.response.send_message(
                "⚠️ 投票に失敗しました。",
                ephemeral=True
            )
            return
        
        await interaction.response.send_message(
            f"✅ {interaction.user.display_name} さんが **{target.username}** に投票しました。"
            f"（{game.voted_count()}/{game.player_count}）"
        )
        
        # 全員投票完了したら結果発表
        if game.all_voted():
            await end_voting_phase(interaction.channel, game)
    
    @app_commands.command(name="skip", description="誰も処刑しない（平和村）に投票する")
    async def skip(self, interaction: discord.Interaction) -> None:
        """平和村（誰も処刑しない）に投票する。"""
        channel_id = interaction.channel_id
        
        if channel_id is None:
            await interaction.response.send_message("このチャンネルでは使用できません。", ephemeral=True)
            return
        
        game = get_game(channel_id)
        
        if game is None or game.phase != GamePhase.VOTING:
            await interaction.response.send_message(
                MESSAGES["wrong_phase"],
                ephemeral=True
            )
            return
        
        voter = game.get_player(interaction.user.id)
        if voter is None:
            await interaction.response.send_message(
                MESSAGES["not_in_game"],
                ephemeral=True
            )
            return
        
        if voter.vote_target_id is not None:
            await interaction.response.send_message(
                MESSAGES["already_voted"],
                ephemeral=True
            )
            return
        
        # 平和村投票は vote_target_id を -1 に設定
        voter.vote_target_id = -1
        
        await interaction.response.send_message(
            f"🕊️ {interaction.user.display_name} さんが **平和村**（誰も処刑しない）に投票しました。"
            f"（{game.voted_count()}/{game.player_count}）"
        )
        
        # 全員投票完了したら結果発表
        if game.all_voted():
            await end_voting_phase(interaction.channel, game)
    
    @app_commands.command(name="cancel", description="ゲームをキャンセルする（ホストのみ）")
    async def cancel(self, interaction: discord.Interaction) -> None:
        """ゲームをキャンセルする。"""
        channel_id = interaction.channel_id
        
        if channel_id is None:
            await interaction.response.send_message("このチャンネルでは使用できません。", ephemeral=True)
            return
        
        game = get_game(channel_id)
        
        if game is None:
            await interaction.response.send_message(
                "⚠️ このチャンネルでゲームは行われていません。",
                ephemeral=True
            )
            return
        
        if interaction.user.id != game.host_id:
            await interaction.response.send_message(
                MESSAGES["not_host"],
                ephemeral=True
            )
            return
        
        end_game(channel_id)
        await interaction.response.send_message("❌ ゲームがキャンセルされました。")
    
    @app_commands.command(name="help", description="コマンド一覧と遊び方を表示する")
    async def help(self, interaction: discord.Interaction) -> None:
        """ヘルプを表示する。"""
        help_text = """🐺 **ワンナイト人狼 ヘルプ**

**【コマンド一覧】**
`/onj start` - ゲームの参加者募集を開始
`/onj join` - ゲームに参加
`/onj leave` - ゲームから離脱
`/onj players` - 参加者一覧を表示
`/onj begin` - ゲームを開始（ホストのみ）
`/onj vote <プレイヤー>` - プレイヤーに投票
`/onj skip` - 平和村（誰も処刑しない）に投票
`/onj cancel` - ゲームをキャンセル（ホストのみ）
`/onj help` - このヘルプを表示

**【遊び方】**
1️⃣ `/onj start` でゲームを開始し、参加者を募集
2️⃣ 参加者は `/onj join` で参加（3〜6人）
3️⃣ ホストが `/onj begin` でゲーム開始
4️⃣ 各プレイヤーにDMで役職が通知される
5️⃣ 夜フェーズ：役職に応じてDMで行動
6️⃣ 昼フェーズ：議論後、投票で処刑者を決定
7️⃣ 結果発表！

**【役職】**
🧑‍🌾 **村人** - 特殊能力なし
🐺 **人狼** - 仲間の人狼を確認できる
🔮 **占い師** - 他プレイヤー1人 or 中央カード2枚を見る
🦹 **怪盗** - 他プレイヤーとカードを交換
🎭 **吊り人** - 自分が処刑されれば単独勝利

**【勝利条件】**
• **村人陣営**: 人狼を1人以上処刑する
• **人狼陣営**: 人狼が処刑されない
• **吊り人**: 自分が処刑される（単独勝利）"""
        
        await interaction.response.send_message(help_text, ephemeral=True)


# コマンドグループをBotに追加
bot.tree.add_command(OnenightCommands())


# =============================================================================
# 夜フェーズ処理
# =============================================================================

async def start_night_phase(channel: discord.abc.Messageable, game: GameState) -> None:
    """夜フェーズを開始する。"""
    await channel.send(MESSAGES["night_start"])
    
    # 人狼の行動
    await process_werewolves(game)
    
    # 占い師の行動
    await process_seers(channel, game)
    
    # 怪盗の行動
    await process_thieves(channel, game)
    
    # 昼フェーズへ
    await start_day_phase(channel, game)


async def process_werewolves(game: GameState) -> None:
    """人狼の夜行動を処理する。"""
    result = process_werewolf_night(game)
    
    for user_id, other_wolves in result.items():
        user = bot.get_user(user_id)
        if user is None:
            try:
                user = await bot.fetch_user(user_id)
            except discord.NotFound:
                continue
        
        try:
            if other_wolves:
                partner_names = ", ".join(w.username for w in other_wolves)
                await user.send(f"🐺 他の人狼: **{partner_names}**")
            else:
                await user.send(MESSAGES["werewolf_alone"])
        except discord.Forbidden:
            pass
    
    advance_night_phase(game)


async def process_seers(channel: discord.abc.Messageable, game: GameState) -> None:
    """占い師の夜行動を処理する。"""
    seers = game.get_players_by_initial_role(Role.SEER)
    
    if not seers:
        advance_night_phase(game)
        return
    
    for seer in seers:
        user = bot.get_user(seer.user_id)
        if user is None:
            try:
                user = await bot.fetch_user(seer.user_id)
            except discord.NotFound:
                continue
        
        try:
            # 他プレイヤーのリストを作成
            other_players = [
                p for p in game.player_list 
                if p.user_id != seer.user_id
            ]
            player_list = "\n".join(
                f"• {p.username}" for p in other_players
            )
            
            await user.send(
                f"🔮 **占い師の行動**\n\n"
                f"以下のいずれかのコマンドをこのDMで入力してください：\n\n"
                f"**プレイヤーを占う場合:**\n"
                f"`!seer player プレイヤー名`\n"
                f"（対象プレイヤー: {', '.join(p.username for p in other_players)}）\n\n"
                f"**中央カード2枚を見る場合:**\n"
                f"`!seer center`\n\n"
                f"⏱️ {NIGHT_ACTION_TIMEOUT}秒以内に行動してください。"
            )
        except discord.Forbidden:
            pass
    
    # 占い師の入力を待つ
    await wait_for_seer_actions(game, seers)
    advance_night_phase(game)


async def wait_for_seer_actions(game: GameState, seers: list[Player]) -> None:
    """占い師の行動入力を待つ。"""
    
    def check(message: discord.Message) -> bool:
        if message.guild is not None:  # DMのみ
            return False
        if message.author.id not in [s.user_id for s in seers]:
            return False
        player = game.get_player(message.author.id)
        if player is None or player.has_acted:
            return False
        return message.content.startswith("!seer")
    
    pending_seers = {s.user_id for s in seers}
    end_time = asyncio.get_event_loop().time() + NIGHT_ACTION_TIMEOUT
    
    while pending_seers and asyncio.get_event_loop().time() < end_time:
        remaining = end_time - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        
        try:
            message = await bot.wait_for("message", check=check, timeout=remaining)
        except asyncio.TimeoutError:
            break
        
        seer = game.get_player(message.author.id)
        if seer is None:
            continue
        
        parts = message.content.split()
        if len(parts) < 2:
            await message.channel.send("⚠️ 無効なコマンドです。`!seer player 名前` または `!seer center` を使用してください。")
            continue
        
        action = parts[1].lower()
        
        if action == "center":
            result = process_seer_action(game, seer.user_id, view_center=True)
            if result:
                await message.channel.send(result)
                pending_seers.discard(seer.user_id)
            else:
                await message.channel.send("⚠️ 行動に失敗しました。")
        
        elif action == "player":
            if len(parts) < 3:
                await message.channel.send("⚠️ プレイヤー名を指定してください。")
                continue
            
            target_name = " ".join(parts[2:])
            target = None
            for p in game.player_list:
                if p.username.lower() == target_name.lower() or target_name.lower() in p.username.lower():
                    target = p
                    break
            
            if target is None:
                await message.channel.send(f"⚠️ プレイヤー '{target_name}' が見つかりません。")
                continue
            
            if target.user_id == seer.user_id:
                await message.channel.send("⚠️ 自分自身は占えません。")
                continue
            
            result = process_seer_action(game, seer.user_id, target_player_id=target.user_id)
            if result:
                await message.channel.send(result)
                pending_seers.discard(seer.user_id)
            else:
                await message.channel.send("⚠️ 行動に失敗しました。")
        
        else:
            await message.channel.send("⚠️ 無効なコマンドです。`!seer player 名前` または `!seer center` を使用してください。")
    
    # タイムアウトした占い師には何もしなかったことを通知
    for user_id in pending_seers:
        seer = game.get_player(user_id)
        if seer and not seer.has_acted:
            seer.has_acted = True
            user = bot.get_user(user_id)
            if user:
                try:
                    await user.send("⏱️ 時間切れです。何も行動しませんでした。")
                except discord.Forbidden:
                    pass


async def process_thieves(channel: discord.abc.Messageable, game: GameState) -> None:
    """怪盗の夜行動を処理する。"""
    thieves = game.get_players_by_initial_role(Role.THIEF)
    
    if not thieves:
        advance_night_phase(game)
        return
    
    for thief in thieves:
        user = bot.get_user(thief.user_id)
        if user is None:
            try:
                user = await bot.fetch_user(thief.user_id)
            except discord.NotFound:
                continue
        
        try:
            other_players = [
                p for p in game.player_list 
                if p.user_id != thief.user_id
            ]
            
            await user.send(
                f"🦹 **怪盗の行動**\n\n"
                f"以下のいずれかのコマンドをこのDMで入力してください：\n\n"
                f"**カードを交換する場合:**\n"
                f"`!thief プレイヤー名`\n"
                f"（対象プレイヤー: {', '.join(p.username for p in other_players)}）\n\n"
                f"**何もしない場合:**\n"
                f"`!thief skip`\n\n"
                f"⏱️ {NIGHT_ACTION_TIMEOUT}秒以内に行動してください。"
            )
        except discord.Forbidden:
            pass
    
    await wait_for_thief_actions(game, thieves)
    advance_night_phase(game)


async def wait_for_thief_actions(game: GameState, thieves: list[Player]) -> None:
    """怪盗の行動入力を待つ。"""
    
    def check(message: discord.Message) -> bool:
        if message.guild is not None:
            return False
        if message.author.id not in [t.user_id for t in thieves]:
            return False
        player = game.get_player(message.author.id)
        if player is None or player.has_acted:
            return False
        return message.content.startswith("!thief")
    
    pending_thieves = {t.user_id for t in thieves}
    end_time = asyncio.get_event_loop().time() + NIGHT_ACTION_TIMEOUT
    
    while pending_thieves and asyncio.get_event_loop().time() < end_time:
        remaining = end_time - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        
        try:
            message = await bot.wait_for("message", check=check, timeout=remaining)
        except asyncio.TimeoutError:
            break
        
        thief = game.get_player(message.author.id)
        if thief is None:
            continue
        
        parts = message.content.split()
        if len(parts) < 2:
            await message.channel.send("⚠️ 無効なコマンドです。`!thief プレイヤー名` または `!thief skip` を使用してください。")
            continue
        
        action = parts[1].lower()
        
        if action == "skip":
            process_thief_action(game, thief.user_id, target_id=None)
            await message.channel.send("🦹 何もしませんでした。あなたの役職は **怪盗** のままです。")
            pending_thieves.discard(thief.user_id)
        
        else:
            target_name = " ".join(parts[1:])
            target = None
            for p in game.player_list:
                if p.username.lower() == target_name.lower() or target_name.lower() in p.username.lower():
                    target = p
                    break
            
            if target is None:
                await message.channel.send(f"⚠️ プレイヤー '{target_name}' が見つかりません。")
                continue
            
            if target.user_id == thief.user_id:
                await message.channel.send("⚠️ 自分自身とは交換できません。")
                continue
            
            new_role = process_thief_action(game, thief.user_id, target_id=target.user_id)
            if new_role:
                await message.channel.send(
                    f"🦹 {target.username} とカードを交換しました！\n"
                    f"あなたの新しい役職は **{new_role.value}** です。"
                )
                pending_thieves.discard(thief.user_id)
            else:
                await message.channel.send("⚠️ 行動に失敗しました。")
    
    # タイムアウトした怪盗には何もしなかったことを通知
    for user_id in pending_thieves:
        thief = game.get_player(user_id)
        if thief and not thief.has_acted:
            process_thief_action(game, thief.user_id, target_id=None)
            user = bot.get_user(user_id)
            if user:
                try:
                    await user.send("⏱️ 時間切れです。何も行動しませんでした。")
                except discord.Forbidden:
                    pass


# =============================================================================
# 昼フェーズ処理
# =============================================================================

async def start_day_phase(channel: discord.abc.Messageable, game: GameState) -> None:
    """昼フェーズ（議論）を開始する。"""
    game.phase = GamePhase.DISCUSSION
    
    await channel.send(
        f"☀️ **朝になりました！**\n\n"
        f"これから {DISCUSSION_TIME}秒間 、自由に議論してください。\n"
        f"誰が人狼か、話し合いましょう！\n\n"
        f"議論終了後、投票フェーズに移ります。"
    )
    
    # 議論時間を待つ
    await asyncio.sleep(DISCUSSION_TIME)
    
    # 投票フェーズへ
    await start_voting_phase(channel, game)


async def start_voting_phase(channel: discord.abc.Messageable, game: GameState) -> None:
    """投票フェーズを開始する。"""
    game.phase = GamePhase.VOTING
    
    player_list = "\n".join(f"• {p.username}" for p in game.player_list)
    
    await channel.send(
        f"🗳️ **投票フェーズです！**\n\n"
        f"`/onj vote @プレイヤー` で投票してください。\n"
        f"`/onj skip` で **平和村**（誰も処刑しない）に投票できます。\n"
        f"※自分以外のプレイヤーに投票できます。\n\n"
        f"**参加者:**\n{player_list}\n\n"
        f"全員の投票が完了すると結果が発表されます。"
    )
    # 全員の投票を待つ（タイムアウトなし）


async def end_voting_phase(channel: discord.abc.Messageable, game: GameState) -> None:
    """投票フェーズを終了し、結果を発表する。"""
    if game.phase == GamePhase.ENDED:
        return  # 既に終了している
    
    game.phase = GamePhase.ENDED
    
    # 投票結果を集計
    vote_counts = calculate_votes(game)
    
    # 投票結果の表示
    vote_summary_lines = []
    for player in game.player_list:
        count = vote_counts.get(player.user_id, 0)
        vote_summary_lines.append(f"• {player.username}: {count}票")
    
    # 平和村への投票を表示
    peace_votes = vote_counts.get(-1, 0)
    if peace_votes > 0:
        vote_summary_lines.append(f"• 🕊️ 平和村（処刑なし）: {peace_votes}票")
    
    vote_summary = "\n".join(vote_summary_lines)
    
    await channel.send(
        f"📊 **投票結果**\n\n{vote_summary}"
    )
    
    # 処刑対象を決定
    executed = determine_execution(game)
    
    # 処刑結果を表示
    await channel.send(get_execution_message(game))
    
    # 勝敗を判定
    determine_winner(game)
    
    # 勝者を発表
    await channel.send(get_winner_message(game))
    
    # 最終役職を公開
    await channel.send(
        f"\n📋 **最終役職一覧**\n\n{get_final_roles_message(game)}"
    )
    
    # ゲームを終了
    channel_id = game.channel_id
    end_game(channel_id)
    
    await channel.send(
        "\n🎮 ゲームが終了しました！\n"
        "新しいゲームを始めるには `/onj start` を使用してください。"
    )


# =============================================================================
# イベントハンドラ
# =============================================================================

@bot.event
async def on_ready() -> None:
    """Bot起動時の処理。"""
    print(f"ワンナイト人狼Bot がログインしました: {bot.user}")
    
    # スラッシュコマンドを同期
    try:
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            
            # ギルドのコマンドを一度クリアしてから再登録
            bot.tree.clear_commands(guild=guild)
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            print(f"ギルド {GUILD_ID} にコマンドを同期しました: {len(synced)}個")
            
            # グローバルコマンドをクリア（重複防止）
            bot.tree.clear_commands(guild=None)
            await bot.tree.sync()
            print("グローバルコマンドをクリアしました")
        else:
            # グローバルに同期（反映に最大1時間かかる）
            synced = await bot.tree.sync()
            print(f"グローバルにコマンドを同期しました: {len(synced)}個")
    except Exception as e:
        print(f"コマンド同期エラー: {e}")


@bot.event
async def on_message(message: discord.Message) -> None:
    """メッセージ受信時の処理（プレフィックスコマンド用）。"""
    if message.author.bot:
        return
    
    await bot.process_commands(message)


# =============================================================================
# メイン
# =============================================================================

def main() -> None:
    """Botを起動する。"""
    bot.run(TOKEN)


if __name__ == "__main__":
    main()

