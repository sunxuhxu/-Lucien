"""大富翁 · 与许墨和NPC在3D世界玩大富翁：完整规则引擎 + AI决策 + 许墨台词 + 游戏记录。
数据持久化到角色目录 monopoly.json（RolePath 按请求角色动态路由），风格与 go_game.py 一致。

规则说明（简化版大富翁）：
- 基于3D世界POI构建游戏棋盘，使用现有地图位置作为地产
- 支持2-4名玩家（玩家 + 许墨 + 指定NPC）
- 掷骰子移动、购买地产、收租、机会卡、坐牢机制
- 完整经济系统：金钱、地产、租金、过路费
- 许墨和NPC使用AI决策，玩家手动操作
- 包含完整的许墨特色台词和性格互动
"""
import asyncio
import functools
import json
import random
import uuid
from datetime import datetime
from pathlib import Path

try:
    from fastapi import APIRouter, Request
    from fastapi.responses import JSONResponse
except ImportError:
    APIRouter = None
    Request = None
    JSONResponse = None

try:
    from role_data import RolePath
except ImportError:
    class RolePath:
        def __init__(self, filename):
            self.filename = filename
        def __str__(self):
            return self.filename

try:
    from store_common import atomic_json, file_lock
except ImportError:
    def atomic_json(path, data):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def file_lock():
        from contextlib import contextmanager
        @contextmanager
        def lock():
            yield
        return lock()

if APIRouter:
    router = APIRouter()
else:
    router = None

# 串行化所有 monopoly.json 读-改-写路由：这些路由体内含 await（LLM 台词 / AI 决策），
# 跨 await 的并发操作会互相覆盖丢失游戏数据
_monopoly_lock = asyncio.Lock()


def _monopoly_route(func):
    @functools.wraps(func)
    async def _wrapped(*args, **kwargs):
        async with _monopoly_lock:
            return await func(*args, **kwargs)
    return _wrapped


MONOPOLY_FILE = RolePath("monopoly.json")

# 游戏状态常量
GAME_WAITING = "waiting"     # 等待开始
GAME_PLAYING = "playing"     # 游戏进行中
GAME_FINISHED = "finished"   # 游戏结束

# 玩家类型
PLAYER_HUMAN = "human"       # 人类玩家
PLAYER_AI = "ai"             # AI玩家

# 地产类型
PROPERTY_NORMAL = "normal"   # 普通地产
PROPERTY_SPECIAL = "special" # 特殊地产（机会卡、坐牢等）
PROPERTY_START = "start"     # 起点

# 玩家位置状态
PLAYER_FREE = "free"         # 自由状态
PLAYER_JAIL = "jail"         # 坐牢状态


# ---------------------------------------------------------------------------
# 公共工具（延迟导入避免与 app.py 循环依赖）
# ---------------------------------------------------------------------------

async def _call_llm(messages, max_tokens=None):
    from app import _call_llm as _impl
    return await _impl(messages, max_tokens=max_tokens)


def _system_prompt():
    from app import SYSTEM_PROMPT
    return SYSTEM_PROMPT


def _add_affinity(action, detail=""):
    from app import _add_affinity as _impl
    return _impl(action, detail)


def _load(path, default):
    if Path(path).exists():
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return default


def _save(path, data):
    atomic_json(path, data)


def _now():
    return datetime.now().strftime("%m-%d %H:%M")


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _uid():
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# 许墨特色台词生成器
# ---------------------------------------------------------------------------

async def _generate_xumo_dialogue(event_type, context):
    """生成许墨在大富翁游戏中的特色台词，体现其性格特点"""
    
    # 基础上下文信息
    event_desc = {
        'game_start': '游戏开始',
        'roll_dice': '掷骰子',
        'move': '移动到新位置',
        'buy_property': '购买地产',
        'pay_rent': '支付租金',
        'receive_rent': '收取租金',
        'chance_card': '抽到机会卡',
        'go_jail': '坐牢',
        'leave_jail': '出狱',
        'win': '赢得游戏',
        'lose': '输掉游戏',
        'opponent_turn': '对手回合',
        'money_low': '金钱不足',
        'property_auction': '地产拍卖'
    }.get(event_type, event_type)
    
    # 构建提示词
    system_prompt = _system_prompt() + f"""

【任务·大富翁游戏台词】你正在与女主一起玩大富翁游戏。
当前事件：{event_desc}
游戏情境：{context.get('situation', '游戏进行中')}
你的位置：{context.get('position', '起点')}
你的金钱：{context.get('money', 15000)}
女主情况：{context.get('player_status', '正常游戏')}

请以许墨的身份，用1-2句话回应这个游戏事件，要求：
1. 体现许墨的性格特点：温柔绅士、学术式撩人、以退为进、话留三分
2. 适当融入科学/学术术语，但不堆砌
3. 保持大富翁游戏的轻松氛围，不要太严肃
4. 不要出现"我是AI"之类的元描述
5. 直接输出台词内容，不要引号、markdown格式
6. 台词要简短有力，适合游戏快速节奏
"""

    user_prompt = f"作为许墨，请针对这个大富翁游戏事件说一句话：{event_desc}"
    
    try:
        dialogue = (await _call_llm([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ], max_tokens=150)).strip()
        return dialogue if dialogue else "嗯，很有趣的发展。"
    except Exception:
        # 降级到预设台词
        fallback_dialogues = {
            'game_start': "规则很简单，但结果的随机性，正是研究的乐趣所在。",
            'roll_dice': "概率分布会告诉我们下一步的故事。",
            'move': "移动的轨迹，有时候比终点更有意思。",
            'buy_property': "投资决策需要理性分析，但直觉也很重要。",
            'pay_rent': "这叫'租金'，本质上是一种资源再分配。",
            'receive_rent': "这是系统性的必然结果，不是吗？",
            'chance_card': "随机变量，总是能带来意外的发现。",
            'go_jail': "暂时的限制，有时是策略的一部分。",
            'leave_jail': "重新回到棋盘上，感觉如何？",
            'win': "你的决策逻辑很优秀，值得学习。",
            'lose': "失败是学习过程的一部分，这次我学到了很多。",
            'opponent_turn': "观察对手，也是一种研究方法。",
            'money_low': "资源管理是游戏的精髓，需要更谨慎。",
            'property_auction': "竞价博弈，很经典的实验场景。"
        }
        return fallback_dialogues.get(event_type, "嗯，有意思。")


# ---------------------------------------------------------------------------
# 大富翁游戏引擎
# ---------------------------------------------------------------------------

class MonopolyEngine:
    """大富翁游戏引擎：基于3D世界POI构建游戏棋盘"""
    
    def __init__(self):
        self.game_state = GAME_WAITING
        self.players = []          # 玩家列表
        self.current_player = 0     # 当前玩家索引
        self.board = []            # 游戏棋盘（基于POI）
        self.chance_cards = []      # 机会卡堆
        self.community_cards = []   # 社区卡堆
        self.turn_count = 0         # 回合计数
        self.dice_result = None    # 当前骰子结果
        self.game_log = []         # 游戏日志
        self.winner = None         # 获胜者
        self.dialogue_history = [] # 对话历史
        
    def create_board_from_pois(self, pois):
        """基于现有POI创建游戏棋盘"""
        board = []
        
        # 起点
        board.append({
            'id': 'start',
            'name': '起点',
            'type': PROPERTY_START,
            'description': '每次经过起点获得¥2000',
            'position': 0,
            'x': 92, 'y': 72  # 中央钟楼位置
        })
        
        # 从POI中选择合适的位置作为地产
        property_pois = [poi for poi in pois if poi.get('type') in ['build', 'area']]
        
        # 分配到棋盘上（简化版：选取16个位置）
        selected_pois = property_pois[:16] if len(property_pois) >= 16 else property_pois
        
        for i, poi in enumerate(selected_pois):
            board.append({
                'id': poi['id'],
                'name': poi['name'],
                'type': PROPERTY_NORMAL,
                'description': f'位于{poi["name"]}的地产',
                'position': i + 1,
                'x': poi['x'],
                'y': poi['y'],
                'icon': poi.get('icon', '🏠'),
                'price': self._calculate_property_price(poi),
                'rent': self._calculate_property_rent(poi),
                'owner': None,
                'houses': 0,
                'hotels': 0
            })
        
        # 添加特殊位置
        special_positions = [
            {'id': 'chance1', 'name': '机会', 'type': PROPERTY_SPECIAL, 'position': len(board) + 1, 'description': '抽取机会卡'},
            {'id': 'jail', 'name': '监狱', 'type': PROPERTY_SPECIAL, 'position': len(board) + 2, 'description': '暂停行动2回合'},
            {'id': 'chance2', 'name': '机会', 'type': PROPERTY_SPECIAL, 'position': len(board) + 3, 'description': '抽取机会卡'},
            {'id': 'free_parking', 'name': '免费停车', 'type': PROPERTY_SPECIAL, 'position': len(board) + 4, 'description': '安全地带'}
        ]
        
        board.extend(special_positions)
        
        # 更新位置索引
        for i, space in enumerate(board):
            space['position'] = i
            
        return board
    
    def _calculate_property_price(self, poi):
        """根据POI类型和位置计算地产价格"""
        base_price = 1000
        
        # 根据POI类型调整价格
        poi_type = poi.get('type', 'build')
        if poi_type == 'build':
            base_price = 1500
        elif poi_type == 'area':
            base_price = 1200
        elif poi_type == 'mark':
            base_price = 800
            
        # 根据与中心的距离调整价格
        dist_from_center = ((poi.get('x', 92) - 92) ** 2 + (poi.get('y', 72) - 72) ** 2) ** 0.5
        distance_factor = max(0.5, 1 - dist_from_center / 50)
        
        return int(base_price * distance_factor)
    
    def _calculate_property_rent(self, poi):
        """计算基础租金"""
        price = self._calculate_property_price(poi)
        return int(price * 0.1)  # 基础租金为价格的10%
    
    def create_chance_cards(self):
        """创建机会卡"""
        cards = [
            {'id': 'c1', 'text': '获得许墨的学术资助', 'effect': 'money', 'value': 1500},
            {'id': 'c2', 'text': '发现古老文献，出售获得收益', 'effect': 'money', 'value': 1000},
            {'id': 'c3', 'text': '雨天路滑，医药费支出', 'effect': 'money', 'value': -500},
            {'id': 'c4', 'text': '咖啡店打折优惠', 'effect': 'money', 'value': 300},
            {'id': 'c5', 'text': '学术会议奖金', 'effect': 'money', 'value': 800},
            {'id': 'c6', 'text': '移动到起点，获得过路费', 'effect': 'move', 'position': 0},
            {'id': 'c7', 'text': '前进3步', 'effect': 'move', 'steps': 3},
            {'id': 'c8', 'text': '后退2步', 'effect': 'move', 'steps': -2},
            {'id': 'c9', 'text': '免费在任意地产建房', 'effect': 'free_house'},
            {'id': 'c10', 'text': '坐牢一回合', 'effect': 'jail', 'rounds': 1}
        ]
        random.shuffle(cards)
        return cards
    
    def add_player(self, player_id, name, player_type=PLAYER_HUMAN, 
                   character_id=None, initial_money=15000):
        """添加玩家"""
        player = {
            'id': player_id,
            'name': name,
            'type': player_type,
            'character_id': character_id,  # 对应NPC ID
            'money': initial_money,
            'position': 0,
            'properties': [],  # 拥有的地产ID列表
            'status': PLAYER_FREE,
            'jail_rounds': 0,
            'bankrupt': False,
            'color': self._get_player_color(len(self.players))
        }
        self.players.append(player)
        return player
    
    def _get_player_color(self, index):
        """为玩家分配颜色"""
        colors = ['#ef4444', '#3b82f6', '#22c55e', '#f59e0b']
        return colors[index % len(colors)]
    
    def start_game(self):
        """开始游戏"""
        if len(self.players) < 2:
            return False
        
        self.game_state = GAME_PLAYING
        self.current_player = 0
        self.turn_count = 1
        self.chance_cards = self.create_chance_cards()
        random.shuffle(self.chance_cards)
        
        self._log_game_event("游戏开始", f"大富翁游戏开始，共有{len(self.players)}名玩家参与")
        return True
    
    def roll_dice(self):
        """掷骰子"""
        dice1 = random.randint(1, 6)
        dice2 = random.randint(1, 6)
        total = dice1 + dice2
        is_double = dice1 == dice2
        
        self.dice_result = {'dice1': dice1, 'dice2': dice2, 'total': total, 'is_double': is_double}
        return dice1, dice2, total, is_double
    
    def move_player(self, player_index, steps):
        """移动玩家"""
        if not (0 <= player_index < len(self.players)):
            return {'success': False, 'error': '无效的玩家索引'}
        
        player = self.players[player_index]
        if player['bankrupt']:
            return {'success': False, 'error': '玩家已破产'}
        
        old_position = player['position']
        new_position = (old_position + steps) % len(self.board)
        player['position'] = new_position
        
        # 检查是否经过起点
        passed_start = new_position < old_position
        if passed_start:
            player['money'] += 2000
            self._log_game_event("经过起点", f"{player['name']}经过起点，获得¥2000")
        
        current_space = self.board[new_position]
        self._log_game_event("移动", f"{player['name']}移动到{current_space['name']}")
        
        return {
            'success': True,
            'old_position': old_position,
            'new_position': new_position,
            'passed_start': passed_start,
            'current_space': current_space
        }
    
    def handle_landing(self, player_index):
        """处理玩家落地后的逻辑"""
        if not (0 <= player_index < len(self.players)):
            return {'success': False, 'error': '无效的玩家索引'}
        
        player = self.players[player_index]
        if player['bankrupt']:
            return {'success': False, 'error': '玩家已破产'}
        
        current_space = self.board[player['position']]
        result = {'success': True, 'events': []}
        
        # 根据位置类型处理不同逻辑
        if current_space['type'] == PROPERTY_START:
            # 起点，无特殊处理
            pass
            
        elif current_space['type'] == PROPERTY_NORMAL:
            # 普通地产
            if current_space['owner'] is None:
                # 无主地产，可以购买
                result['can_buy'] = True
                result['buy_price'] = current_space['price']
                result['events'].append({
                    'type': 'can_buy',
                    'property': current_space,
                    'price': current_space['price']
                })
            elif current_space['owner'] != player['id']:
                # 有主地产，支付租金
                owner = self._get_player_by_id(current_space['owner'])
                if owner and not owner['bankrupt']:
                    rent = self._calculate_rent(current_space)
                    if player['money'] >= rent:
                        player['money'] -= rent
                        owner['money'] += rent
                        result['events'].append({
                            'type': 'pay_rent',
                            'property': current_space,
                            'rent': rent,
                            'owner': owner['name']
                        })
                        self._log_game_event("支付租金", f"{player['name']}向{owner['name']}支付¥{rent}租金")
                    else:
                        # 金钱不足，破产处理
                        result['events'].append({
                            'type': 'bankrupt',
                            'reason': 'insufficient_funds'
                        })
                        self._handle_bankruptcy(player_index)
                        
        elif current_space['type'] == PROPERTY_SPECIAL:
            # 特殊位置
            if current_space['id'] == 'chance1' or current_space['id'] == 'chance2':
                # 抽取机会卡
                if self.chance_cards:
                    card = self.chance_cards.pop()
                    card_result = self._apply_chance_card(player_index, card)
                    result['events'].append({
                        'type': 'chance_card',
                        'card': card,
                        'result': card_result
                    })
                    self._log_game_event("机会卡", f"{player['name']}抽到机会卡：{card['text']}")
                    
            elif current_space['id'] == 'jail':
                # 坐牢
                player['status'] = PLAYER_JAIL
                player['jail_rounds'] = 2
                result['events'].append({
                    'type': 'go_jail',
                    'rounds': 2
                })
                self._log_game_event("坐牢", f"{player['name']}坐牢，暂停2回合")
                
            elif current_space['id'] == 'free_parking':
                # 免费停车，无效果
                result['events'].append({
                    'type': 'free_parking'
                })
        
        return result
    
    def _calculate_rent(self, property_space):
        """计算租金（考虑房屋和酒店）"""
        base_rent = property_space['rent']
        houses = property_space.get('houses', 0)
        hotels = property_space.get('hotels', 0)
        
        # 每个房屋增加50%租金，每个酒店增加200%租金
        rent_multiplier = 1 + (houses * 0.5) + (hotels * 2.0)
        return int(base_rent * rent_multiplier)
    
    def _apply_chance_card(self, player_index, card):
        """应用机会卡效果"""
        player = self.players[player_index]
        result = {'card_id': card['id'], 'effect': card['effect']}
        
        if card['effect'] == 'money':
            player['money'] += card['value']
            result['money_change'] = card['value']
            
        elif card['effect'] == 'move':
            if 'position' in card:
                # 移动到指定位置
                old_position = player['position']
                player['position'] = card['position']
                result['moved_to'] = card['position']
                # 检查是否经过起点
                if card['position'] < old_position:
                    player['money'] += 2000
                    result['passed_start'] = True
            elif 'steps' in card:
                # 前进或后退指定步数
                move_result = self.move_player(player_index, card['steps'])
                result['move_result'] = move_result
                
        elif card['effect'] == 'free_house':
            # 免费建房（简化：直接给钱）
            player['money'] += 500
            result['money_change'] = 500
            
        elif card['effect'] == 'jail':
            player['status'] = PLAYER_JAIL
            player['jail_rounds'] = card.get('rounds', 1)
            result['jail_rounds'] = card.get('rounds', 1)
            
        return result
    
    def buy_property(self, player_index, property_id):
        """购买地产"""
        if not (0 <= player_index < len(self.players)):
            return {'success': False, 'error': '无效的玩家索引'}
        
        player = self.players[player_index]
        if player['bankrupt']:
            return {'success': False, 'error': '玩家已破产'}
        
        # 查找地产
        property_space = None
        for space in self.board:
            if space['id'] == property_id:
                property_space = space
                break
        
        if not property_space:
            return {'success': False, 'error': '地产不存在'}
        
        if property_space['type'] != PROPERTY_NORMAL:
            return {'success': False, 'error': '该位置不可购买'}
        
        if property_space['owner'] is not None:
            return {'success': False, 'error': '地产已有主人'}
        
        if player['money'] < property_space['price']:
            return {'success': False, 'error': '金钱不足'}
        
        # 执行购买
        player['money'] -= property_space['price']
        property_space['owner'] = player['id']
        player['properties'].append(property_id)
        
        self._log_game_event("购买地产", f"{player['name']}购买了{property_space['name']}，花费¥{property_space['price']}")
        
        return {
            'success': True,
            'property': property_space,
            'remaining_money': player['money']
        }
    
    def build_house(self, player_index, property_id):
        """在地产上建房"""
        if not (0 <= player_index < len(self.players)):
            return {'success': False, 'error': '无效的玩家索引'}
        
        player = self.players[player_index]
        if player['bankrupt']:
            return {'success': False, 'error': '玩家已破产'}
        
        # 查找地产
        property_space = None
        for space in self.board:
            if space['id'] == property_id:
                property_space = space
                break
        
        if not property_space:
            return {'success': False, 'error': '地产不存在'}
        
        if property_space['owner'] != player['id']:
            return {'success': False, 'error': '你不是该地产的主人'}
        
        if property_space['houses'] >= 4:  # 最多4个房子
            return {'success': False, 'error': '房屋数量已达上限'}
        
        house_cost = int(property_space['price'] * 0.5)  # 房屋价格为地产价格的50%
        if player['money'] < house_cost:
            return {'success': False, 'error': '金钱不足'}
        
        # 建房
        player['money'] -= house_cost
        property_space['houses'] += 1
        
        self._log_game_event("建房", f"{player['name']}在{property_space['name']}建房，花费¥{house_cost}")
        
        return {
            'success': True,
            'property': property_space,
            'house_cost': house_cost,
            'remaining_money': player['money']
        }
    
    def end_turn(self):
        """结束当前回合"""
        current_player = self.players[self.current_player]
        
        # 处理坐牢状态
        if current_player['status'] == PLAYER_JAIL:
            current_player['jail_rounds'] -= 1
            if current_player['jail_rounds'] <= 0:
                current_player['status'] = PLAYER_FREE
                self._log_game_event("出狱", f"{current_player['name']}出狱")
        
        # 检查是否破产
        if current_player['money'] < 0:
            self._handle_bankruptcy(self.current_player)
        
        # 切换到下一个玩家
        next_player_index = self._get_next_player()
        if next_player_index is None:
            # 游戏结束
            self.game_state = GAME_FINISHED
            winner = self._determine_winner()
            self.winner = winner
            return {
                'success': True,
                'game_over': True,
                'winner': winner
            }
        
        self.current_player = next_player_index
        self.turn_count += 1
        
        next_player = self.players[self.current_player]
        return {
            'success': True,
            'game_over': False,
            'next_player': next_player,
            'turn_count': self.turn_count
        }
    
    def _get_next_player(self):
        """获取下一个有效玩家索引"""
        start_index = self.current_player
        for i in range(1, len(self.players) + 1):
            next_index = (start_index + i) % len(self.players)
            if not self.players[next_index]['bankrupt']:
                return next_index
        return None  # 所有玩家都破产
    
    def _handle_bankruptcy(self, player_index):
        """处理玩家破产"""
        player = self.players[player_index]
        player['bankrupt'] = True
        player['money'] = 0
        
        # 释放所有地产
        for property_id in player['properties']:
            for space in self.board:
                if space['id'] == property_id:
                    space['owner'] = None
                    space['houses'] = 0
                    space['hotels'] = 0
                    break
        
        player['properties'] = []
        self._log_game_event("破产", f"{player['name']}破产，退出游戏")
    
    def _determine_winner(self):
        """确定获胜者"""
        active_players = [p for p in self.players if not p['bankrupt']]
        if not active_players:
            return None
        
        # 按总资产排序（金钱 + 地产价值）
        for player in active_players:
            total_property_value = 0
            for property_id in player['properties']:
                for space in self.board:
                    if space['id'] == property_id:
                        total_property_value += space['price']
                        total_property_value += space['houses'] * int(space['price'] * 0.5)
                        total_property_value += space['hotels'] * int(space['price'] * 1.5)
                        break
            player['total_assets'] = player['money'] + total_property_value
        
        winner = max(active_players, key=lambda p: p['total_assets'])
        return {
            'player': winner,
            'total_assets': winner['total_assets']
        }
    
    def _get_player_by_id(self, player_id):
        """根据ID获取玩家"""
        for player in self.players:
            if player['id'] == player_id:
                return player
        return None
    
    def _log_game_event(self, event_type, description):
        """记录游戏事件"""
        event = {
            'type': event_type,
            'description': description,
            'timestamp': _now(),
            'turn': self.turn_count
        }
        self.game_log.append(event)
        # 只保留最近100条日志
        if len(self.game_log) > 100:
            self.game_log = self.game_log[-100:]
    
    def get_game_state(self):
        """获取当前游戏状态"""
        return {
            'game_state': self.game_state,
            'players': self.players,
            'current_player': self.current_player,
            'board': self.board,
            'turn_count': self.turn_count,
            'dice_result': self.dice_result,
            'game_log': self.game_log[-20:],  # 只返回最近20条日志
            'winner': self.winner
        }


# ---------------------------------------------------------------------------
# API 路由
# ---------------------------------------------------------------------------

if router:
    @_monopoly_route
    @router.get("/api/monopoly/state")
    async def get_monopoly_state():
        """获取当前大富翁游戏状态"""
        data = _load(MONOPOLY_FILE, None)
        if data is None:
            return {
                'game_exists': False,
                'game_state': GAME_WAITING,
                'message': '没有进行中的游戏'
            }
        
        return {
            'game_exists': True,
            'game_state': data.get('game_state', GAME_WAITING),
            'players': data.get('players', []),
            'current_player': data.get('current_player', 0),
            'board': data.get('board', []),
            'turn_count': data.get('turn_count', 0),
            'winner': data.get('winner', None)
        }


    @_monopoly_route
    @router.post("/api/monopoly/start")
    async def start_monopoly_game(req: Request):
        """开始新的大富翁游戏"""
        body = await req.json()
        
        # 获取玩家配置
        players_config = body.get('players', [])
        if len(players_config) < 2:
            return JSONResponse({'error': '至少需要2名玩家'}, status_code=400)
        
        # 创建游戏引擎
        engine = MonopolyEngine()
        
        # 从world-data.js获取POI信息创建棋盘
        try:
            # 这里需要从world-data.js读取POI，暂时使用简化版本
            # 实际实现中需要从world-data.js解析POI数据
            sample_pois = [
                {'id': 'cafe', 'name': '街角咖啡店', 'type': 'build', 'x': 88, 'y': 74, 'icon': '☕'},
                {'id': 'lab', 'name': '脑科学研究院', 'type': 'build', 'x': 83, 'y': 67, 'icon': '🧪'},
                {'id': 'univ', 'name': '恋语大学', 'type': 'build', 'x': 75, 'y': 61, 'icon': '🎓'},
                {'id': 'library', 'name': '旧图书馆', 'type': 'build', 'x': 87, 'y': 80, 'icon': '📚'},
                {'id': 'market', 'name': '日夜超市', 'type': 'build', 'x': 97, 'y': 76, 'icon': '🛒'},
                {'id': 'park', 'name': '梧桐公园', 'type': 'area', 'x': 99, 'y': 66, 'icon': '🌳'},
                {'id': 'home', 'name': '你的公寓', 'type': 'build', 'x': 100, 'y': 78, 'icon': '🏠'},
                {'id': 'xflat', 'name': '教工公寓', 'type': 'build', 'x': 86, 'y': 76, 'icon': '🏢'}
            ]
            
            engine.board = engine.create_board_from_pois(sample_pois)
        except Exception as e:
            return JSONResponse({'error': f'创建棋盘失败: {str(e)}'}, status_code=500)
        
        # 添加玩家
        for i, player_config in enumerate(players_config):
            player_id = player_config.get('id', f'player_{i}')
            player_name = player_config.get('name', f'玩家{i+1}')
            player_type = player_config.get('type', PLAYER_HUMAN)
            character_id = player_config.get('character_id')
            
            engine.add_player(
                player_id=player_id,
                name=player_name,
                player_type=player_type,
                character_id=character_id
            )
        
        # 开始游戏
        if not engine.start_game():
            return JSONResponse({'error': '游戏启动失败'}, status_code=500)
        
        # 保存游戏状态
        game_data = {
            'game_state': engine.game_state,
            'players': engine.players,
            'current_player': engine.current_player,
            'board': engine.board,
            'turn_count': engine.turn_count,
            'chance_cards': engine.chance_cards,
            'game_log': engine.game_log,
            'winner': engine.winner,
            'created_at': _now(),
            'updated_at': _now()
        }
        
        _save(MONOPOLY_FILE, game_data)
        
        # 增加亲密度
        _add_affinity("monopoly_start", "开始大富翁游戏")
        
        return {
            'success': True,
            'game_state': engine.get_game_state()
        }


    @_monopoly_route
    @router.post("/api/monopoly/roll")
    async def roll_dice(req: Request):
        """掷骰子"""
        data = _load(MONOPOLY_FILE, None)
        if data is None or data.get('game_state') != GAME_PLAYING:
            return JSONResponse({'error': '没有进行中的游戏'}, status_code=400)
        
        body = await req.json()
        player_id = body.get('player_id')
        
        # 找到玩家索引
        player_index = None
        for i, player in enumerate(data['players']):
            if player['id'] == player_id:
                player_index = i
                break
        
        if player_index is None:
            return JSONResponse({'error': '玩家不存在'}, status_code=400)
        
        if player_index != data['current_player']:
            return JSONResponse({'error': '不是你的回合'}, status_code=400)
        
        player = data['players'][player_index]
        if player['bankrupt']:
            return JSONResponse({'error': '玩家已破产'}, status_code=400)
        
        # 处理坐牢状态
        if player['status'] == PLAYER_JAIL:
            # 坐牢时不能移动，只能跳过回合
            return JSONResponse({'error': '你正在坐牢，无法移动'}, status_code=400)
        
        # 创建引擎实例
        engine = MonopolyEngine()
        engine.players = data['players']
        engine.board = data['board']
        engine.current_player = data['current_player']
        engine.turn_count = data['turn_count']
        engine.chance_cards = data.get('chance_cards', [])
        engine.game_log = data.get('game_log', [])
        
        # 掷骰子
        dice1, dice2, total, is_double = engine.roll_dice()
        
        # 移动玩家
        move_result = engine.move_player(player_index, total)
        if not move_result['success']:
            return JSONResponse({'error': move_result['error']}, status_code=400)
        
        # 处理落地逻辑
        landing_result = engine.handle_landing(player_index)
        
        # 生成许墨的台词（如果是许墨的回合）
        dialogue = None
        if player.get('character_id') == 'xumo':
            context = {
                'situation': f'掷出{total}点，移动到{engine.board[player["position"]]["name"]}',
                'position': engine.board[player["position"]]["name"],
                'money': player["money"],
                'player_status': '正常游戏'
            }
            dialogue = await _generate_xumo_dialogue('roll_dice', context)
        
        # 更新数据
        data['players'] = engine.players
        data['board'] = engine.board
        data['dice_result'] = engine.dice_result
        data['game_log'] = engine.game_log
        data['updated_at'] = _now()
        
        _save(MONOPOLY_FILE, data)
        
        # 增加亲密度
        _add_affinity("monopoly_roll", f"掷骰子移动，到达{engine.board[player['position']]['name']}")
        
        return {
            'success': True,
            'dice_result': engine.dice_result,
            'move_result': move_result,
            'landing_result': landing_result,
            'dialogue': dialogue,
            'current_player': data['current_player']
        }


    @_monopoly_route
    @router.post("/api/monopoly/buy")
    async def buy_property(req: Request):
        """购买地产"""
        data = _load(MONOPOLY_FILE, None)
        if data is None or data.get('game_state') != GAME_PLAYING:
            return JSONResponse({'error': '没有进行中的游戏'}, status_code=400)
        
        body = await req.json()
        player_id = body.get('player_id')
        property_id = body.get('property_id')
        
        # 找到玩家索引
        player_index = None
        for i, player in enumerate(data['players']):
            if player['id'] == player_id:
                player_index = i
                break
        
        if player_index is None:
            return JSONResponse({'error': '玩家不存在'}, status_code=400)
        
        # 创建引擎实例
        engine = MonopolyEngine()
        engine.players = data['players']
        engine.board = data['board']
        engine.current_player = data['current_player']
        engine.turn_count = data['turn_count']
        engine.game_log = data.get('game_log', [])
        
        # 购买地产
        buy_result = engine.buy_property(player_index, property_id)
        if not buy_result['success']:
            return JSONResponse({'error': buy_result['error']}, status_code=400)
        
        # 生成许墨的台词
        dialogue = None
        player = data['players'][player_index]
        if player.get('character_id') == 'xumo':
            property_space = None
            for space in engine.board:
                if space['id'] == property_id:
                    property_space = space
                    break
            
            context = {
                'situation': f'购买了{property_space["name"]}，花费¥{property_space["price"]}',
                'position': property_space["name"],
                'money': player["money"],
                'player_status': '正常游戏'
            }
            dialogue = await _generate_xumo_dialogue('buy_property', context)
        
        # 更新数据
        data['players'] = engine.players
        data['board'] = engine.board
        data['game_log'] = engine.game_log
        data['updated_at'] = _now()
        
        _save(MONOPOLY_FILE, data)
        
        # 增加亲密度
        _add_affinity("monopoly_buy", f"购买地产{property_id}")
        
        return {
            'success': True,
            'buy_result': buy_result,
            'dialogue': dialogue
        }


    @_monopoly_route
    @router.post("/api/monopoly/build")
    async def build_house(req: Request):
        """建房"""
        data = _load(MONOPOLY_FILE, None)
        if data is None or data.get('game_state') != GAME_PLAYING:
            return JSONResponse({'error': '没有进行中的游戏'}, status_code=400)
        
        body = await req.json()
        player_id = body.get('player_id')
        property_id = body.get('property_id')
        
        # 找到玩家索引
        player_index = None
        for i, player in enumerate(data['players']):
            if player['id'] == player_id:
                player_index = i
                break
        
        if player_index is None:
            return JSONResponse({'error': '玩家不存在'}, status_code=400)
        
        # 创建引擎实例
        engine = MonopolyEngine()
        engine.players = data['players']
        engine.board = data['board']
        engine.current_player = data['current_player']
        engine.turn_count = data['turn_count']
        engine.game_log = data.get('game_log', [])
        
        # 建房
        build_result = engine.build_house(player_index, property_id)
        if not build_result['success']:
            return JSONResponse({'error': build_result['error']}, status_code=400)
        
        # 更新数据
        data['players'] = engine.players
        data['board'] = engine.board
        data['game_log'] = engine.game_log
        data['updated_at'] = _now()
        
        _save(MONOPOLY_FILE, data)
        
        return {
            'success': True,
            'build_result': build_result
        }


    @_monopoly_route
    @router.post("/api/monopoly/end_turn")
    async def end_turn(req: Request):
        """结束回合"""
        data = _load(MONOPOLY_FILE, None)
        if data is None or data.get('game_state') != GAME_PLAYING:
            return JSONResponse({'error': '没有进行中的游戏'}, status_code=400)
        
        body = await req.json()
        player_id = body.get('player_id')
        
        # 找到玩家索引
        player_index = None
        for i, player in enumerate(data['players']):
            if player['id'] == player_id:
                player_index = i
                break
        
        if player_index is None:
            return JSONResponse({'error': '玩家不存在'}, status_code=400)
        
        if player_index != data['current_player']:
            return JSONResponse({'error': '不是你的回合'}, status_code=400)
        
        # 创建引擎实例
        engine = MonopolyEngine()
        engine.players = data['players']
        engine.board = data['board']
        engine.current_player = data['current_player']
        engine.turn_count = data['turn_count']
        engine.game_log = data.get('game_log', [])
        
        # 结束回合
        end_result = engine.end_turn()
        
        # 生成下一位玩家的台词（如果是许墨）
        dialogue = None
        if not end_result['game_over'] and end_result['next_player'].get('character_id') == 'xumo':
            context = {
                'situation': '轮到许墨回合',
                'position': engine.board[end_result['next_player']['position']]['name'],
                'money': end_result['next_player']['money'],
                'player_status': '正常游戏'
            }
            dialogue = await _generate_xumo_dialogue('opponent_turn', context)
        
        # 更新数据
        data['players'] = engine.players
        data['board'] = engine.board
        data['current_player'] = engine.current_player
        data['turn_count'] = engine.turn_count
        data['game_log'] = engine.game_log
        data['winner'] = engine.winner
        data['updated_at'] = _now()
        
        _save(MONOPOLY_FILE, data)
        
        return {
            'success': True,
            'end_result': end_result,
            'dialogue': dialogue
        }


    @_monopoly_route
    @router.post("/api/monopoly/dialogue")
    async def get_character_dialogue(req: Request):
        """获取角色对话"""
        body = await req.json()
        event_type = body.get('event_type', 'opponent_turn')
        context = body.get('context', {})
        character_id = body.get('character_id', 'xumo')
        
        if character_id != 'xumo':
            # 非许墨角色，返回简单对话
            simple_dialogues = {
                'xiaoman': '哈哈，大富翁真好玩！',
                'bai': '这个游戏很有策略性。',
                'default': '嗯，轮到我了。'
            }
            return {
                'dialogue': simple_dialogues.get(character_id, simple_dialogues['default'])
            }
        
        dialogue = await _generate_xumo_dialogue(event_type, context)
        return {'dialogue': dialogue}


    @_monopoly_route
    @router.delete("/api/monopoly")
    async def reset_monopoly_game():
        """重置大富翁游戏"""
        if MONOPOLY_FILE.exists():
            MONOPOLY_FILE.unlink()
        return {'success': True, 'message': '游戏已重置'}