"""
ゲームロジック

役職ごとの夜アクション処理、勝敗判定などを実装する。
Discord依存のコードは含めず、純粋なゲームロジックのみを記述する。
"""

import random
from typing import Optional
from game.models import (
    Role,
    Team,
    GamePhase,
    GameState,
    Player,
    NightAction,
    NightActionType,
    get_team,
)


# =============================================================================
# 夜の行動順序
# =============================================================================
# ワンナイト人狼の標準的な行動順序
# 人狼 → 占い師 → 怪盗 の順
NIGHT_ACTION_ORDER: list[Role] = [
    Role.WEREWOLF,
    Role.SEER,
    Role.THIEF,
]


def setup_game(state: GameState, role_list: list[Role]) -> None:
    """
    ゲームを初期化し、役職を配布する。
    
    Args:
        state: ゲーム状態
        role_list: 使用する役職のリスト（プレイヤー数 + 中央カード2枚分）
    
    Note:
        role_listはプレイヤー数 + 2（中央カード）の長さである必要がある。
    """
    player_count = state.player_count
    expected_cards = player_count + 2  # 中央カードは常に2枚
    
    if len(role_list) != expected_cards:
        raise ValueError(
            f"役職カード数が不正です。期待: {expected_cards}, 実際: {len(role_list)}"
        )
    
    # 役職をシャッフル
    shuffled_roles = role_list.copy()
    random.shuffle(shuffled_roles)
    
    # プレイヤーに役職を配布
    player_ids = list(state.players.keys())
    for i, user_id in enumerate(player_ids):
        role = shuffled_roles[i]
        state.players[user_id].initial_role = role
        state.players[user_id].current_role = role
    
    # 残りを中央カードに
    state.center_cards = shuffled_roles[player_count:]
    
    # 夜の行動順序を設定
    state.night_action_order = NIGHT_ACTION_ORDER.copy()
    state.night_action_index = 0
    
    # フェーズを夜に
    state.phase = GamePhase.NIGHT


def get_current_night_role(state: GameState) -> Optional[Role]:
    """
    現在行動すべき役職を取得する。
    
    Returns:
        現在の役職。全ての行動が終了していればNone。
    """
    if state.night_action_index >= len(state.night_action_order):
        return None
    return state.night_action_order[state.night_action_index]


def advance_night_phase(state: GameState) -> Optional[Role]:
    """
    夜フェーズを次の役職に進める。
    
    Returns:
        次の役職。全ての行動が終了していればNone。
    """
    state.night_action_index += 1
    return get_current_night_role(state)


def is_night_phase_complete(state: GameState) -> bool:
    """夜フェーズが完了したかどうかを返す。"""
    return state.night_action_index >= len(state.night_action_order)


# =============================================================================
# 人狼の夜行動
# =============================================================================

def process_werewolf_night(state: GameState) -> dict[int, list[Player]]:
    """
    人狼の夜行動を処理する。
    
    人狼同士がお互いを確認する。
    
    Returns:
        人狼のuser_idをキー、他の人狼プレイヤーのリストを値とする辞書
    """
    # 初期役職が人狼のプレイヤーを取得
    werewolves = state.get_players_by_initial_role(Role.WEREWOLF)
    
    result: dict[int, list[Player]] = {}
    
    for wolf in werewolves:
        # 自分以外の人狼
        other_wolves = [w for w in werewolves if w.user_id != wolf.user_id]
        result[wolf.user_id] = other_wolves
        
        # 行動を記録
        wolf.night_action = NightAction(
            action_type=NightActionType.WEREWOLF_CHECK,
            result=f"他の人狼: {', '.join(w.username for w in other_wolves)}" if other_wolves else "あなたは唯一の人狼です"
        )
        wolf.has_acted = True
    
    return result


# =============================================================================
# 占い師の夜行動
# =============================================================================

def process_seer_action_player(
    state: GameState,
    seer_id: int,
    target_id: int
) -> Optional[Role]:
    """
    占い師が他プレイヤーの役職を見る。
    
    Args:
        state: ゲーム状態
        seer_id: 占い師のUser ID
        target_id: 対象プレイヤーのUser ID
    
    Returns:
        対象の現在の役職。無効な対象の場合はNone。
    """
    seer = state.get_player(seer_id)
    target = state.get_player(target_id)
    
    if seer is None or target is None:
        return None
    
    if seer.initial_role != Role.SEER:
        return None
    
    if seer_id == target_id:
        return None  # 自分自身は占えない
    
    # 行動を記録
    seer.night_action = NightAction(
        action_type=NightActionType.SEER_PLAYER,
        target_player_id=target_id,
        result=f"{target.username} の役職は {target.current_role.value} です"
    )
    seer.has_acted = True
    
    return target.current_role


def process_seer_action_center(
    state: GameState,
    seer_id: int
) -> Optional[list[Role]]:
    """
    占い師が中央カード2枚を見る。
    
    Args:
        state: ゲーム状態
        seer_id: 占い師のUser ID
    
    Returns:
        中央カード2枚の役職リスト。無効な場合はNone。
    """
    seer = state.get_player(seer_id)
    
    if seer is None:
        return None
    
    if seer.initial_role != Role.SEER:
        return None
    
    # 行動を記録
    center_roles = state.center_cards.copy()
    seer.night_action = NightAction(
        action_type=NightActionType.SEER_CENTER,
        result=f"中央カード: {center_roles[0].value}, {center_roles[1].value}"
    )
    seer.has_acted = True
    
    return center_roles


def process_seer_action(
    state: GameState,
    seer_id: int,
    target_player_id: Optional[int] = None,
    view_center: bool = False
) -> Optional[str]:
    """
    占い師の行動を統合的に処理する。
    
    Args:
        state: ゲーム状態
        seer_id: 占い師のUser ID
        target_player_id: 対象プレイヤーのUser ID（プレイヤーを占う場合）
        view_center: 中央カードを見る場合True
    
    Returns:
        結果メッセージ。無効な場合はNone。
    """
    if view_center:
        roles = process_seer_action_center(state, seer_id)
        if roles:
            return f"🔮 中央カードは **{roles[0].value}** と **{roles[1].value}** です"
        return None
    elif target_player_id is not None:
        role = process_seer_action_player(state, seer_id, target_player_id)
        if role:
            target = state.get_player(target_player_id)
            if target:
                return f"🔮 {target.username} の役職は **{role.value}** です"
        return None
    return None


# =============================================================================
# 怪盗の夜行動
# =============================================================================

def process_thief_action(
    state: GameState,
    thief_id: int,
    target_id: Optional[int] = None
) -> Optional[Role]:
    """
    怪盗が他プレイヤーとカードを交換する。
    
    Args:
        state: ゲーム状態
        thief_id: 怪盗のUser ID
        target_id: 対象プレイヤーのUser ID。Noneの場合はスキップ。
    
    Returns:
        交換後の怪盗の新しい役職。スキップまたは無効な場合はNone。
    """
    thief = state.get_player(thief_id)
    
    if thief is None:
        return None
    
    if thief.initial_role != Role.THIEF:
        return None
    
    # スキップの場合
    if target_id is None:
        thief.night_action = NightAction(
            action_type=NightActionType.THIEF_SKIP,
            result="何もしませんでした"
        )
        thief.has_acted = True
        return None
    
    target = state.get_player(target_id)
    
    if target is None:
        return None
    
    if thief_id == target_id:
        return None  # 自分自身とは交換できない
    
    # カードを交換
    old_thief_role = thief.current_role
    new_thief_role = target.current_role
    
    thief.current_role = new_thief_role
    target.current_role = old_thief_role
    
    # 行動を記録
    thief.night_action = NightAction(
        action_type=NightActionType.THIEF_SWAP,
        target_player_id=target_id,
        result=f"{target.username} とカードを交換しました。新しい役職: {new_thief_role.value}"
    )
    thief.has_acted = True
    
    return new_thief_role


# =============================================================================
# 投票処理
# =============================================================================

def register_vote(state: GameState, voter_id: int, target_id: int) -> bool:
    """
    投票を登録する。
    
    Args:
        state: ゲーム状態
        voter_id: 投票者のUser ID
        target_id: 投票先のUser ID
    
    Returns:
        投票が有効な場合True
    """
    voter = state.get_player(voter_id)
    target = state.get_player(target_id)
    
    if voter is None or target is None:
        return False
    
    if voter_id == target_id:
        return False  # 自分自身には投票できない
    
    if voter.vote_target_id is not None:
        return False  # 既に投票済み
    
    voter.vote_target_id = target_id
    return True


def calculate_votes(state: GameState) -> dict[int, int]:
    """
    投票を集計する。
    
    Returns:
        user_idをキー、得票数を値とする辞書
        -1 は「平和村」（誰も処刑しない）への投票を表す
    """
    vote_counts: dict[int, int] = {p.user_id: 0 for p in state.players.values()}
    vote_counts[-1] = 0  # 平和村への投票
    
    for player in state.players.values():
        if player.vote_target_id is not None:
            if player.vote_target_id in vote_counts:
                vote_counts[player.vote_target_id] += 1
            elif player.vote_target_id == -1:
                vote_counts[-1] += 1
    
    return vote_counts


def determine_execution(state: GameState) -> list[int]:
    """
    処刑対象を決定する。
    
    最多得票者を処刑する。同票の場合は誰も処刑しない。
    平和村（-1）が最多得票の場合も誰も処刑しない。
    
    Returns:
        処刑されるプレイヤーのUser IDリスト（0または1人）
    """
    vote_counts = calculate_votes(state)
    
    if not vote_counts:
        return []
    
    max_votes = max(vote_counts.values())
    
    if max_votes == 0:
        return []
    
    # 最多得票者を取得
    max_voted = [uid for uid, count in vote_counts.items() if count == max_votes]
    
    # 同票の場合は誰も処刑しない
    if len(max_voted) > 1:
        return []
    
    # 平和村（-1）が最多得票の場合は誰も処刑しない
    if max_voted[0] == -1:
        state.executed_player_ids = []
        return []
    
    state.executed_player_ids = max_voted
    return max_voted


# =============================================================================
# 勝敗判定
# =============================================================================

def determine_winner(state: GameState) -> list[Team]:
    """
    勝者を決定する。
    
    勝敗判定ルール:
    1. 吊り人が処刑された場合 → 吊り人のみ勝利
    2. 人狼が1人以上処刑された場合 → 村人陣営勝利
    3. それ以外（人狼が処刑されなかった場合）→ 人狼陣営勝利
    
    特殊ケース:
    - 誰も処刑されなかった場合:
      - 場に人狼がいる → 人狼陣営勝利
      - 場に人狼がいない → 村人陣営勝利
    
    Returns:
        勝者の陣営リスト
    """
    executed_ids = state.executed_player_ids
    
    # 処刑されたプレイヤーの情報を取得
    executed_players = [state.get_player(uid) for uid in executed_ids]
    executed_players = [p for p in executed_players if p is not None]
    
    # 処刑されたプレイヤーの最終役職を取得
    executed_roles = [p.current_role for p in executed_players]
    
    # 1. 吊り人が処刑された場合 → 吊り人のみ勝利
    if Role.TANNER in executed_roles:
        state.winners = [Team.TANNER]
        return [Team.TANNER]
    
    # 誰も処刑されなかった場合の特殊処理
    if not executed_ids:
        # 場に人狼がいるか確認（最終役職で判定）
        werewolves_in_game = state.get_players_by_role(Role.WEREWOLF, use_current=True)
        if werewolves_in_game:
            # 人狼がいるのに誰も処刑されなかった → 人狼勝利
            state.winners = [Team.WEREWOLF]
            return [Team.WEREWOLF]
        else:
            # 人狼がいない（全員中央カード）→ 村人勝利
            state.winners = [Team.VILLAGE]
            return [Team.VILLAGE]
    
    # 2. 人狼が処刑された場合 → 村人陣営勝利
    if Role.WEREWOLF in executed_roles:
        state.winners = [Team.VILLAGE]
        return [Team.VILLAGE]
    
    # 3. 人狼が処刑されなかった場合 → 人狼陣営勝利
    state.winners = [Team.WEREWOLF]
    return [Team.WEREWOLF]


def get_winner_message(state: GameState) -> str:
    """勝者メッセージを生成する。"""
    winners = state.winners
    
    if not winners:
        return "勝者なし"
    
    if Team.TANNER in winners:
        # 吊り人が勝った場合、吊り人プレイヤーを特定
        tanner_players = [
            p for p in state.players.values() 
            if p.current_role == Role.TANNER and p.user_id in state.executed_player_ids
        ]
        if tanner_players:
            return f"🎭 **吊り人（{tanner_players[0].username}）の単独勝利！**"
        return "🎭 **吊り人陣営の勝利！**"
    
    if Team.VILLAGE in winners:
        return "🏘️ **村人陣営の勝利！** 人狼を処刑しました！"
    
    if Team.WEREWOLF in winners:
        return "🐺 **人狼陣営の勝利！** 人狼は処刑を免れました！"
    
    return "結果不明"


def get_final_roles_message(state: GameState) -> str:
    """最終役職一覧のメッセージを生成する。"""
    lines: list[str] = []
    
    # プレイヤーの役職
    lines.append("**【プレイヤー】**")
    for player in state.players.values():
        initial = player.initial_role.value
        current = player.current_role.value
        
        if initial != current:
            lines.append(f"• {player.username}: {initial} → **{current}**")
        else:
            lines.append(f"• {player.username}: **{current}**")
    
    # 中央カード
    lines.append("")
    lines.append("**【中央カード】**")
    for i, role in enumerate(state.center_cards, 1):
        lines.append(f"• カード{i}: **{role.value}**")
    
    return "\n".join(lines)


def get_execution_message(state: GameState) -> str:
    """処刑結果のメッセージを生成する。"""
    executed_ids = state.executed_player_ids
    
    if not executed_ids:
        # 平和村が選ばれたか、同票かを判定
        vote_counts = calculate_votes(state)
        max_votes = max(vote_counts.values()) if vote_counts else 0
        max_voted = [uid for uid, count in vote_counts.items() if count == max_votes]
        
        if -1 in max_voted and len(max_voted) == 1:
            return "🕊️ **平和村が選ばれました！** 誰も処刑されませんでした。"
        return "⚖️ **同票のため、誰も処刑されませんでした。**"
    
    executed_players = [state.get_player(uid) for uid in executed_ids]
    executed_players = [p for p in executed_players if p is not None]
    
    if not executed_players:
        return "処刑結果を取得できませんでした。"
    
    names = ", ".join(p.username for p in executed_players)
    roles = ", ".join(p.current_role.value for p in executed_players)
    
    return f"⚖️ **{names}** が処刑されました。\n役職: **{roles}**"

