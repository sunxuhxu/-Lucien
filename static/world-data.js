/* =========================================================================
 * 世界·恋语市 —— 开放世界数据层
 * 包含：POI / 物品 / 装备 / 技能树 / NPC(日程+AI对话) / 任务(主线+支线) /
 *       谜题 / 城市故事 / 结局 / 天气表
 * 依赖：无（纯数据 + 对话生成函数，通过 G 接口与引擎交互）
 * ========================================================================= */
(function () {
'use strict';

/* ===== 基础常量 ===== */
var TILE = 32;                 // 每 tile 像素
var MAP_W = 144, MAP_H = 144;  // 地图尺寸（tile）
var CHUNK = 16;                // 分块渲染尺寸

/* 生物群系 */
var B = {
  DEEP: 0, WATER: 1, SAND: 2, GRASS: 3, FOREST: 4, HILL: 5,
  MOUNT: 6, SNOW: 7, ROAD: 8, PLAZA: 9, BUILD: 10, PARK: 11,
  FLOOR: 12, BRIDGE: 13, FIELD: 14
};
var SOLID = {}; SOLID[B.DEEP] = SOLID[B.WATER] = SOLID[B.MOUNT] = SOLID[B.SNOW] = SOLID[B.BUILD] = 1;

/* 地形配色（清新明亮·浅色紫白风格，变体由噪声扰动） */
var BIOME_STYLE = {
  0:  { base: '#a9d6ea', alt: '#9ecfe5' },          // 深海（清新湖蓝）
  1:  { base: '#c4e5f2', alt: '#b8dff0' },          // 浅水
  2:  { base: '#f2e5c0', alt: '#ecdcb1' },          // 沙滩（奶油黄）
  3:  { base: '#b3dd9f', alt: '#a8d794' },          // 草地
  4:  { base: '#8ecb8a', alt: '#82c27e' },          // 森林
  5:  { base: '#cdd8a8', alt: '#c2d09c' },          // 丘陵
  6:  { base: '#c9cdd8', alt: '#bcc1cf' },          // 山地（浅灰）
  7:  { base: '#f6f9fc', alt: '#e9eff6' },          // 雪峰
  8:  { base: '#aaa5bf', alt: '#9e99b5' },          // 马路（浅紫灰）
  9:  { base: '#ded9ec', alt: '#d3cde4' },          // 广场砖（浅紫白）
  10: { base: '#c5b4e2', alt: '#b8a5d8' },          // 建筑（浅紫）
  11: { base: '#bce2ac', alt: '#b0db9f' },          // 公园草
  12: { base: '#ded5ef', alt: '#d3c9e7' },          // 室内地板
  13: { base: '#d8ba9a', alt: '#cdaf8c' },          // 木桥
  14: { base: '#e9dda8', alt: '#e0d399' }           // 田野
};

/* ===== POI（兴趣点 / 建筑） ===== */
/* type: build(建筑方块) | mark(地标点) | area(区域) */
var POIS = [
  { id: 'home',       name: '你的公寓',     x: 100, y: 78, w: 3, h: 3, type: 'build', icon: '🏠', color: '#8b6bb8', monopoly_price: 1200, monopoly_rent: 120 },
  { id: 'cafe',       name: '街角咖啡店',   x: 88,  y: 74, w: 4, h: 3, type: 'build', icon: '☕', color: '#b0703c', monopoly_price: 1500, monopoly_rent: 150 },
  { id: 'lab',        name: '脑科学研究院', x: 83,  y: 67, w: 5, h: 4, type: 'build', icon: '🧪', color: '#5f6fb0', monopoly_price: 1800, monopoly_rent: 180 },
  { id: 'univ',       name: '恋语大学',     x: 75,  y: 61, w: 5, h: 4, type: 'build', icon: '🎓', color: '#4f8f7a', monopoly_price: 1600, monopoly_rent: 160 },
  { id: 'library',    name: '旧图书馆',     x: 87,  y: 80, w: 4, h: 3, type: 'build', icon: '📚', color: '#9a7c54', monopoly_price: 1400, monopoly_rent: 140 },
  { id: 'market',     name: '日夜超市',     x: 97,  y: 76, w: 3, h: 3, type: 'build', icon: '🛒', color: '#c05a6a', monopoly_price: 1300, monopoly_rent: 130 },
  { id: 'xflat',      name: '教工公寓',     x: 86,  y: 76, w: 3, h: 3, type: 'build', icon: '🏢', color: '#7a7fb0', monopoly_price: 1100, monopoly_rent: 110 },
  { id: 'clocktower', name: '中央钟楼',     x: 92,  y: 72, w: 2, h: 2, type: 'build', icon: '🕰️', color: '#a08a5c', tall: true, monopoly_price: 2000, monopoly_rent: 200 },
  { id: 'park',       name: '梧桐公园',     x: 99,  y: 66, w: 8, h: 7, type: 'area',  icon: '🌳', color: '#5d9b53', monopoly_price: 1700, monopoly_rent: 170 },
  { id: 'lighthouse', name: '北岬灯塔',     x: 112, y: 48, w: 2, h: 3, type: 'build', icon: '🗼', color: '#d0d6e0', tall: true, monopoly_price: 1900, monopoly_rent: 190 },
  { id: 'temple',     name: '神庙遗迹',     x: 42,  y: 58, w: 5, h: 4, type: 'area',  icon: '⛩️', color: '#7d8a6a', monopoly_price: 1000, monopoly_rent: 100 },
  { id: 'darklab',    name: '废弃实验室',   x: 64,  y: 39, w: 4, h: 3, type: 'build', icon: '🚪', color: '#5a4a6a', hidden: true, monopoly_price: 800, monopoly_rent: 80 },
  { id: 'pier',       name: '临海栈桥',     x: 122, y: 84, w: 2, h: 8, type: 'bridge', icon: '🌉', color: '#a9825c', monopoly_price: 900, monopoly_rent: 90 },
  { id: 'mine',       name: '北岭矿脉',     x: 58,  y: 34, w: 4, h: 3, type: 'area',  icon: '⛏️', color: '#8a8f98', monopoly_price: 850, monopoly_rent: 85 },
  { id: 'shrine',     name: '星辰石碑群',   x: 41,  y: 57, w: 3, h: 3, type: 'area',  icon: '🗿', color: '#8d9c86', monopoly_price: 750, monopoly_rent: 75 },
  { id: 'garden',     name: '屋顶花园',     x: 90,  y: 75, w: 1, h: 1, type: 'mark',  icon: '🌸', color: '#d98ab0', hidden: true, monopoly_price: 600, monopoly_rent: 60 }
];

/* ===== 物品 ===== */
var ITEMS = {
  /* 材料 */
  herb:     { name: '薄荷草',   icon: '🌿', kind: 'mat',  desc: '城郊常见草药，清凉提神。' },
  iron:     { name: '铁矿石',   icon: '🪨', kind: 'mat',  desc: '北岭矿脉采出的矿石，可修灯塔。' },
  fish:     { name: '河鱼',     icon: '🐟', kind: 'mat',  desc: '河边钓上来的小鱼，猫很喜欢。' },
  dew:      { name: '晨露花',   icon: '💧', kind: 'mat',  desc: '只在雨后开放的淡紫色小花，花瓣凝着露水。' },
  shard:    { name: '记忆碎片', icon: '🔷', kind: 'mat',  desc: '幽蓝的碎片，靠近时耳边有细碎的低语。', key: true },
  crystal:  { name: '残影结晶', icon: '🟣', kind: 'mat',  desc: '夜间异常残影消散后留下的结晶，微微发烫。' },
  /* 食物（sp=体力 hp=生命） */
  bread:    { name: '面包',     icon: '🍞', kind: 'food', sp: 25, hp: 5,  desc: '超市的黄油面包。' },
  coffee:   { name: '热咖啡',   icon: '☕', kind: 'food', sp: 40, hp: 0,  desc: '咖啡店外带的热美式，和他喝的同款。' },
  bento:    { name: '便当',     icon: '🍱', kind: 'food', sp: 70, hp: 25, desc: '荤素搭配，吃完很有力气。' },
  catfood:  { name: '猫粮',     icon: '🥫', kind: 'food', sp: 0,  hp: 0,  desc: '小满推荐的牌子，墨鱼爱吃。' },
  /* 任务关键道具 */
  keycard:  { name: '旧门禁卡', icon: '💳', kind: 'key',  desc: '背面写着"B-SWAN · ECHO"，似乎能打开某扇门。', key: true },
  archive:  { name: '旧档案',   icon: '📁', kind: 'key',  desc: '图书馆密格里的档案：「回声计划 · 阶段三」。', key: true },
  lens:     { name: '黄铜透镜', icon: '🔍', kind: 'key',  desc: '打磨精细的透镜，灯塔的核心部件。', key: true },
  bulb:     { name: '灯塔灯泡', icon: '💡', kind: 'key',  desc: '大功率灯泡，超市老板娘从仓库翻出来的。', key: true },
  camera:   { name: '胶片相机', icon: '📷', kind: 'key',  desc: '阿澈的旧相机，按快门会发出清脆的咔嗒声。', key: true },
  page:     { name: '讲义散页', icon: '📄', kind: 'key',  desc: '被风吹散的讲义，页脚有白教授的批注。', key: true },
  teabox:   { name: '晨露花茶', icon: '🫖', kind: 'key',  desc: '小满焙的花茶，装在素白铁盒里。', key: true },
  core:     { name: '回声核心', icon: '💠', kind: 'key',  desc: '灯塔顶端的数据核心，仍在微微搏动。', key: true }
};
/* 装备（quality: 1白 2绿 3蓝 4紫） */
var EQUIPS = {
  weapon_umbrella:  { slot: 'weapon', name: '木柄伞',     icon: '☂️', q: 1, atk: 3,  desc: '晴雨两用，防身勉强够。' },
  weapon_baton:     { slot: 'weapon', name: '伸缩警棍',   icon: '🥍', q: 2, atk: 7,  desc: '阿澈托人弄来的，手感扎实。' },
  weapon_supp:      { slot: 'weapon', name: 'Evol抑制器', icon: '⚡', q: 3, atk: 12, desc: '能把异常残影"按"回数据态的装置。' },
  shoes_canvas:     { slot: 'shoes',  name: '帆布鞋',     icon: '👟', q: 1, spd: 0,   desc: '磨旧了，但很合脚。' },
  shoes_runner:     { slot: 'shoes',  name: '公园跑鞋',   icon: '👟', q: 2, spd: 15, desc: '轻便透气，跑起来带风。' },
  shoes_wind:       { slot: 'shoes',  name: '疾风靴',     icon: '🥾', q: 3, spd: 30, spSave: 20, desc: '内衬减震层，长途跋涉不累。' },
  charm_amulet:     { slot: 'charm',  name: '平安符',     icon: '🧿', q: 1, hp: 10,  desc: '外婆求来的，针脚细密。' },
  charm_ginkgo:     { slot: 'charm',  name: '银杏书签',   icon: '🍂', q: 2, aff: 20, desc: '夹在《记忆的神经基础》第137页的书签。' },
  charm_butterfly:  { slot: 'charm',  name: '蝶形吊坠',   icon: '🦋', q: 3, aff: 40, hp: 20, desc: '银质蝴蝶，翅膀在光下泛紫。' },
  charm_echo:       { slot: 'charm',  name: '回声核心·戒', icon: '💠', q: 4, aff: 60, hp: 40, sp: 20, atk: 4, desc: '真相大白后，由核心残料铸成。' },
  charm_bell:       { slot: 'charm',  name: '墨鱼的铃铛', icon: '🔔', q: 2, spd: 8,  desc: '戴上它，总感觉有猫跟着你。' }
};

/* ===== 技能树 ===== */
var SKILLS = [
  /* 感知系 */
  { id: 'per1', line: 'per', tier: 1, name: '洞察', icon: '👁️', desc: '小地图显示附近的资源点。' },
  { id: 'per2', line: 'per', tier: 2, name: '寻宝', icon: '🗺️', desc: '小地图显示未开启的宝箱。', req: 'per1' },
  { id: 'per3', line: 'per', tier: 3, name: '心眼', icon: '✨', desc: '靠近隐藏入口时会隐约心悸。', req: 'per2' },
  { id: 'per4', line: 'per', tier: 4, name: '共鸣', icon: '🔷', desc: '小地图显示记忆碎片与核心的方位。', req: 'per3' },
  { id: 'per5', line: 'per', tier: 5, name: '天眼', icon: '🌟', desc: '大地图直接标出全部资源与宝箱。', req: 'per4' },
  /* 心灵系（Evol） */
  { id: 'min1', line: 'min', tier: 1, name: '直觉', icon: '💭', desc: '对话中获得的好感 +25%。' },
  { id: 'min2', line: 'min', tier: 2, name: '感应', icon: '🧲', desc: '小地图常显许墨的位置。', req: 'min1' },
  { id: 'min3', line: 'min', tier: 3, name: '心语', icon: '💗', desc: '对话时能看到对方此刻的心情。', req: 'min2' },
  { id: 'min4', line: 'min', tier: 4, name: '联结', icon: '🔗', desc: '全局心动等级≥5 时：移速+10%、体力消耗-15%。', req: 'min3' },
  { id: 'min5', line: 'min', tier: 5, name: '觉醒', icon: '🌀', desc: '所有体力消耗 -30%。', req: 'min4' },
  /* 体术系 */
  { id: 'bod1', line: 'bod', tier: 1, name: '疾行', icon: '🏃', desc: '移动速度 +10%。' },
  { id: 'bod2', line: 'bod', tier: 2, name: '轻盈', icon: '🪶', desc: '奔跑的体力消耗 -40%。', req: 'bod1' },
  { id: 'bod3', line: 'bod', tier: 3, name: '坚韧', icon: '🛡️', desc: '生命上限 +40。', req: 'bod2' },
  { id: 'bod4', line: 'bod', tier: 4, name: '净化', icon: '💊', desc: '免疫夜间的异常减速。', req: 'bod3' },
  { id: 'bod5', line: 'bod', tier: 5, name: '不息', icon: '♻️', desc: '体力自然回复速度翻倍。', req: 'bod4' }
];

/* ===== 天气 ===== */
var WEATHERS = {
  clear:  { name: '晴',   icon: '☀️', light: 0,   particle: null },
  cloudy: { name: '多云', icon: '⛅', light: -6,  particle: null },
  rain:   { name: '小雨', icon: '🌧️', light: -18, particle: 'rain',  slow: 8 },
  storm:  { name: '雷暴', icon: '⛈️', light: -30, particle: 'storm', slow: 15 },
  fog:    { name: '浓雾', icon: '🌫️', light: -22, particle: 'fog',   vis: 0.55 },
  snow:   { name: '降雪', icon: '🌨️', light: -15, particle: 'snow',  slow: 10 },
  starry: { name: '星夜', icon: '🌌', light: 0,   particle: 'star' }
};
/* 马尔可夫转移表（每小时判定） */
var WEATHER_TRANS = {
  clear:  { clear: 55, cloudy: 28, rain: 6,  fog: 5,  storm: 2, snow: 4 },
  cloudy: { clear: 30, cloudy: 34, rain: 16, fog: 10, storm: 5, snow: 5 },
  rain:   { clear: 18, cloudy: 34, rain: 34, fog: 8,  storm: 6 },
  storm:  { clear: 10, cloudy: 26, rain: 44, fog: 6,  storm: 14 },
  fog:    { clear: 30, cloudy: 30, rain: 12, fog: 28 },
  snow:   { clear: 20, cloudy: 30, snow: 44, fog: 6 }
};

/* ===== 城市故事（陈爷爷 / 线索载体） ===== */
var CITY_LORE = [
  { id: 'lore1', title: '一 · 建市', text: '恋语市是 1987 年建市的，那年我十七岁，跟着父亲来修第一条海堤。城市年轻，人也年轻。要记数字的话——就记 1987，这座城市的生日。' },
  { id: 'lore2', title: '二 · 钟楼', text: '中央钟楼是建市那年铸的，地基下面有一间密室，放着一些建市时的物件。老图纸上的门锁是四位数字……听说用的是建市之年。年轻人，好奇的话去看看，密码就藏在历史里。' },
  { id: 'lore3', title: '三 · 灯塔与山', text: '北岬的灯塔熄了很多年。山那边曾经有一片研究设施，后来废弃了，夜里偶有蓝光。老人们说，灯塔再亮起来的那天，山里的东西就会安分。' }
];

/* ===== NPC =====
 * schedule: 按游戏小时切换目标点（POI 附近）
 * dialog(G): 返回对话节点 {name, emoji, text, options:[{t, next:fn|null, cond:fn, eff:fn}]}
 */
function affLevel(v) {
  if (v >= 80) return '挚友';
  if (v >= 60) return '信任';
  if (v >= 35) return '熟悉';
  if (v >= 15) return '认识';
  return '陌生';
}

var NPCS = [
  /* ---------- 许墨 ---------- */
  {
    id: 'xumo', name: '许墨', emoji: '🧪', color: '#7c3aed', speed: 2.6, wander: 1, important: true, avatar: '/avatar?v=3',
    mood: { morning: '平静', noon: '从容', evening: '温柔', night: '专注' },
    schedule: [
      { h: 0,  poi: 'lab' }, { h: 5, poi: 'xflat' }, { h: 8, poi: 'lab' },
      { h: 12, poi: 'univ' }, { h: 14, poi: 'lab' }, { h: 18, poi: 'cafe' },
      { h: 21, poi: 'xflat' }
    ],
    dialog: function (G) {
      var st = G.mainStage(), aff = G.aff('xumo');
      var hour = G.hour();
      /* 主线节点对话 */
      if (st === 1 && G.count('shard') >= 3 && !G.flag('m1_xumo')) {
        return {
          text: '你把三枚碎片摊在桌上。他看了很久，指尖在杯沿停了一下——\n「……不整齐的边缘，像是被人为撕开的。」他抬眼看你，「记忆不会自己碎掉。有别的东西在撕它。」\n「旧图书馆的地下书库，或许有答案。今晚九点前，我在那里等你。」',
          options: [
            { t: '「好，我一定到。」', eff: function () { G.setFlag('m1_xumo'); G.setMain(2); G.addAff('xumo', 6); G.callAffinity('world_quest'); } },
            { t: '「为什么帮我？」', eff: function () { G.setFlag('m1_xumo'); G.setMain(2); G.addAff('xumo', 8); G.callAffinity('world_quest'); },
              next: function () { return { text: '他微微一笑，镜片后的目光很静。\n「大概是——研究兴趣。」他顿了顿，「当然，如果这个答案让你失望，我可以换一个。」', options: [{ t: '（继续）', eff: function () {} }] }; } }
          ]
        };
      }
      if (st === 3 && G.flag('dark_entered') && !G.flag('m3_choice')) {
        var c1 = {
          text: '蓝色屏幕的光落在他脸上。他不再避让你的目光。\n「你都知道了。」他说得很轻，「回声计划——用一座城市做样本，观测情绪如何在人群里衰减、失真。」\n「我从一开始就该告诉你。现在说，还来得及吗？」',
          options: [
            { t: '「你骗了我。」（质问）', eff: function () { G.setFlag('m3_choice', 'confront'); G.addAff('xumo', 2); G.callAffinity('world');
              G.toast('许墨沉默了很久，说：' + '「嗯。对不起。」'); G.setMain(4); } },
            { t: '「我信你。」（信任）', eff: function () { G.setFlag('m3_choice', 'trust'); G.addAff('xumo', 12); G.callAffinity('world');
              G.toast('他眼角的笑意先于嘴角出现。'); G.setMain(4); },
              next: function () { return { text: '他怔了一下，随即低声笑了。\n「……你知道吗，信任是一种高耗能的神经活动。」他伸手，轻轻碰了碰你的发梢，「但很值得。」\n「接下来，去北岬灯塔。答案的最后一环在那里。」', options: [{ t: '（继续）', eff: function () {} }] }; } },
            { t: '（沉默地看他）', eff: function () { G.setFlag('m3_choice', 'silent'); G.addAff('xumo', 6); G.callAffinity('world');
              G.toast('他读懂了你的沉默：「不急着下结论。也好。」'); G.setMain(4); } }
          ]
        };
        return c1;
      }
      if (st === 4 && G.flag('core_taken') && !G.flag('m4_choice')) {
        return {
          text: '海风把他的风衣吹得很平。他看着你手里的核心，很认真地问：\n「现在，选择权在你。」\n「销毁它，一切归零，城市安全，但真相永远沉在海底；保留它，力量太大，也会被更大的人盯上；……或者，交给我。让我用我的方式，护它周全。」',
          options: [
            { t: '销毁核心', eff: function () { G.setFlag('m4_choice', 'destroy'); G.setMain(5); } },
            { t: '保留核心', eff: function () { G.setFlag('m4_choice', 'keep'); G.setMain(5); } },
            { t: '交给他', eff: function () { G.setFlag('m4_choice', 'give'); G.addAff('xumo', 8); G.callAffinity('world'); G.setMain(5); } }
          ]
        };
      }
      /* 支线：花茶 */
      if (G.has('teabox')) {
        return {
          text: '他注意到你手里的素白铁盒，挑了挑眉。\n「晨露花？」他接过，凑近闻了闻，「挥发油的比例很妙……焙茶的火候，是你掌握的吗？」\n「那么，」他把铁盒收进风衣内袋，动作很珍重，「这杯茶，我会慢慢喝。」',
          options: [{ t: '（递给他）', eff: function () { G.take('teabox', 1); G.addAff('xumo', 10); G.callAffinity('world_quest'); G.toast('许墨好感 +10'); } }]
        };
      }
      /* 分支日常 */
      if (hour >= 18 && hour < 21) {
        return {
          text: aff >= 60
            ? '靠窗的位置，他面前放着两杯咖啡——一杯是他的黑咖啡，另一杯加了奶。\n「来了？」他把那杯往你面前推了推，「我刚在书里读到一句：记忆的可靠度，取决于记录者的在意程度。」\n「所以我记下的你，应该很可靠。」'
            : '他在靠窗的位置读书，面前的黑咖啡已经见底。\n「坐。」他合上书，「这个位置的日落，是全城最好的——光穿过梧桐叶的缝隙，落在桌面上，像一场缓慢的衍射。」',
          options: [
            { t: '聊聊最近', next: function () {
                return { text: st >= 5 ? '「城市安静下来了。」他望着窗外，「异常消退之后，海平线比去年更清楚。」\n他看向你，「是你的功劳。——不接受反驳，这是学术结论。'
                  : '「最近城里……有些说不清的事。」他指尖轻推镜框，「如果你注意到什么异样，随时可以告诉我。」',
                  options: [{ t: '（点头）', eff: function () { G.addAff('xumo', 2); G.callAffinity('world'); } }] };
              } },
            { t: '只是看看他', eff: function () { G.addAff('xumo', 1); G.callAffinity('world'); G.toast('他放下书，陪你坐了一会儿。好感 +1'); } }
          ]
        };
      }
      if (hour >= 0 && hour < 5) {
        return {
          text: '深夜的研究院楼下，他刚结束工作，白大褂搭在臂弯。\n「这个点还在外面？」他微微皱眉，随即又松开，「……等我五分钟，送你回去。」\n（体力完全恢复了）',
          options: [{ t: '「好。」', eff: function () { G.restFull(); G.addAff('xumo', 3); G.callAffinity('world'); } }]
        };
      }
      return {
        text: aff >= 40
          ? '他从资料里抬头，看到是你，眉眼温和下来。\n「嗯，我在。」他指了指对面的椅子，「正好，想听听你今天的见闻。」'
          : '他正在整理课题资料，见你走近，礼貌地颔首。\n「你好。有什么我可以帮忙的吗？」',
        options: [
          { t: '聊聊工作', next: function () {
              return { text: '「记忆。」他说，「它比人以为的更脆弱，也比人以为的更顽固。」\n「我研究它，是想知道——被记住这件事，究竟发生在哪里。」',
                options: [{ t: '（继续）', eff: function () { G.addAff('xumo', 2); G.callAffinity('world'); } }] };
            } },
          { t: '告辞', eff: function () {} }
        ]
      };
    }
  },

  /* ---------- 小满（咖啡店店员） ---------- */
  {
    id: 'xiaoman', name: '小满', emoji: '🌻', color: '#eab308', speed: 2.0, wander: 2,
    mood: { morning: '元气', noon: '忙碌', evening: '雀跃', night: '困倦' },
    schedule: [
      { h: 0, poi: 'xflat' }, { h: 8, poi: 'cafe' }, { h: 20, poi: 'home' }
    ],
    dialog: function (G) {
      var s1 = G.side('s1'), s5 = G.side('s5');
      /* s1 咖啡店的猫 */
      if (s1.state === 1 && G.has('catfood')) {
        return {
          text: '「你买到猫粮了！」小满眼睛一亮，「墨鱼就在店门口那边——去喂喂它吧，它认识拿罐头的人。」',
          options: [{ t: '（去找墨鱼）', eff: function () { G.setSide('s1', 2); } }]
        };
      }
      if (s1.state === 0) {
        return {
          text: '「哎，同学！」小满擦着杯子凑过来，「附近有只流浪猫叫墨鱼，最近总不见影。你要是看到它……帮我把这罐猫粮带过去？它最爱吃这个。」\n（任务：咖啡店的猫）',
          options: [
            { t: '交给我吧', eff: function () { G.startSide('s1'); G.toast('接到支线：咖啡店的猫'); } },
            { t: '下次一定', eff: function () {} }
          ]
        };
      }
      if (s1.state === 3 && !G.flag('s1_done_talk')) {
        return {
          text: '「墨鱼肯让你摸了？！」小满惊叹，「它连许教授都只让摸三秒。」\n她从围裙里掏出个小铃铛：「给，谢谢礼！戴上它，墨鱼没准会悄悄跟着你哦。」',
          options: [{ t: '（收下铃铛）', eff: function () { G.setFlag('s1_done_talk'); G.give('charm_bell', 1); G.toast('获得装备：墨鱼的铃铛'); } }]
        };
      }
      /* s5 雨中之花 */
      if (s5.state === 0 && G.aff('xiaoman') >= 30) {
        return {
          text: '「跟你说个秘密～」小满压低声音，「雨停之后，公园的草地上会开一种淡紫色的花，叫晨露花，只有一天的花期。」\n「我一直想用它焙一壶花茶……采三朵来，我教你焙茶？」\n（任务：雨中之花）',
          options: [
            { t: '好啊', eff: function () { G.startSide('s5'); G.toast('接到支线：雨中之花'); } },
            { t: '再想想', eff: function () {} }
          ]
        };
      }
      if (s5.state === 1 && G.count('dew') >= 3) {
        return {
          text: '「采到了！」小满像捧着宝贝一样接过晨露花，「焙茶要小火慢烘，看好了——」\n空气里渐渐漫开一层清苦回甘的香气。她把茶装进素白铁盒：「去吧，送给想送的人。」',
          options: [{ t: '（收下花茶）', eff: function () { G.take('dew', 3); G.give('teabox', 1); G.setSide('s5', 2); G.toast('获得：晨露花茶（可送给许墨）'); } }]
        };
      }
      /* 日常 */
      var rainy = G.weather() === 'rain' || G.weather() === 'storm';
      return {
        text: rainy
          ? '「下雨天咖啡店最舒服了～」小满托着腮，「热美式第二杯半价，要来一杯吗？」'
          : '「欢迎光临！」小满笑着招呼，「今天有新到的黄油面包，配咖啡绝了～」',
        options: [
          { t: '买杯热咖啡（¥12）', cond: function () { return G.money() >= 12; }, eff: function () { G.pay(12); G.give('coffee', 1); G.addAff('xiaoman', 2); } },
          { t: '买份便当（¥28）', cond: function () { return G.money() >= 28; }, eff: function () { G.pay(28); G.give('bento', 1); G.addAff('xiaoman', 2); } },
          { t: '聊聊天', next: function () {
              return { text: '「许教授啊，每天傍晚都来，永远坐靠窗，永远黑咖啡。」小满挤挤眼，「不过最近他好像……会多看门口几眼。你懂的。」',
                options: [{ t: '（微笑）', eff: function () { G.addAff('xiaoman', 1); } }] };
            } }
        ]
      };
    }
  },

  /* ---------- 白教授 ---------- */
  {
    id: 'bai', name: '白教授', emoji: '📚', color: '#0ea5e9', speed: 1.6, wander: 1,
    mood: { morning: '严谨', noon: '随和', evening: '怀旧', night: '安眠' },
    schedule: [
      { h: 0, poi: 'univ' }, { h: 8, poi: 'univ' }, { h: 17, poi: 'park' }, { h: 20, poi: 'univ' }
    ],
    dialog: function (G) {
      var s2 = G.side('s2');
      if (s2.state === 1 && G.count('page') >= 3) {
        return {
          text: '「都找回来了！」白教授接过散页，仔细对齐，「第七版的勘误、还有我批注的参考文献……真是太感谢了。」\n他执意塞给你酬劳：「知识无价，但跑腿有价，哈哈。」',
          options: [{ t: '（收下）', eff: function () { G.take('page', 3); G.setSide('s2', 3); G.addMoney(120); G.gainExp(80); G.addAff('bai', 15); G.toast('支线完成：失落的讲义（+¥120）'); G.callAffinity('world_quest'); } }]
        };
      }
      if (s2.state === 0) {
        return {
          text: '「哎呀。」白教授抱着一摞讲义，风一吹，最上面几页飘了出去。「年轻人，能帮我追回来吗？风把它们吹向大学、公园和旧图书馆那几处了……」\n（任务：失落的讲义）',
          options: [
            { t: '没问题', eff: function () { G.startSide('s2'); G.toast('接到支线：失落的讲义'); } },
            { t: '我很忙', eff: function () {} }
          ]
        };
      }
      return {
        text: G.hour() >= 17
          ? '白教授坐在公园长椅上喂鸽子。「教学三十年，最喜欢这个时辰。」他感慨，「城市跑得越来越快，总得有人坐下来，替它记着点什么。」'
          : '「脑科学？」白教授推推眼镜，「那可是个好方向。不过我先提醒你——那栋研究院楼里，有些课题……啧，不说也罢。」',
        options: [
          { t: '打听研究院', next: function () {
              return { text: '他左右看看，声音压低：「十年前有批设备半夜进出，说是搬去山那边了。后来，就再没人提。」\n「年轻人，好奇心要有，命也要有。」',
                options: [{ t: '（记下了）', eff: function () { G.addAff('bai', 2); } }] };
            } },
          { t: '告辞', eff: function () {} }
        ]
      };
    }
  },

  /* ---------- 陈爷爷 ---------- */
  {
    id: 'chen', name: '陈爷爷', emoji: '🍵', color: '#f97316', speed: 1.2, wander: 2,
    mood: { morning: '精神', noon: '晒暖', evening: '健谈', night: '归家' },
    schedule: [
      { h: 0, poi: 'home' }, { h: 6, poi: 'park' }, { h: 10, poi: 'clocktower' },
      { h: 16, poi: 'park' }, { h: 20, poi: 'home' }
    ],
    dialog: function (G) {
      var s3 = G.side('s3'), loreIdx = G.count('lore');
      if (s3.state === 1 && loreIdx < 3) {
        var lore = CITY_LORE[loreIdx];
        return {
          text: '「想听故事？」陈爷爷眯眼一笑，「坐。」\n\n【' + lore.title + '】\n' + lore.text,
          options: [
            { t: '（认真听完）', eff: function () { G.incr('lore'); G.addAff('chen', 4);
              if (G.count('lore') >= 3) { G.setSide('s3', 2); G.toast('听完三段故事：钟楼密室的线索已入手'); }
              else G.toast('城市记忆 ' + G.count('lore') + '/3'); } },
            { t: '（心不在焉）', eff: function () { G.addAff('chen', 1); G.toast('陈爷爷叹了口气，下次再听吧。'); } }
          ]
        };
      }
      if (s3.state === 0) {
        return {
          text: '「小姑娘，走路别急。」陈爷爷摇着蒲扇，「这座城市的每一块砖都有故事。想听吗？我这儿有三段，讲完你就算半个恋语人了。」\n（任务：城市记忆）',
          options: [
            { t: '我想听', eff: function () { G.startSide('s3'); G.toast('接到支线：城市记忆'); } },
            { t: '先不了', eff: function () {} }
          ]
        };
      }
      if (s3.state === 2) {
        return {
          text: '「三段都讲完喽。」陈爷爷很欣慰，「钟楼密室的密码，我提过线索了——建市之年，四个数字。」\n「替我看一眼密室里的老照片，那里面有我父亲修海堤的样子。」',
          options: [{ t: '（去钟楼看看）', eff: function () { G.setSide('s3', 3); G.gainExp(60); G.toast('支线完成：城市记忆（获得密室线索）'); G.callAffinity('world_quest'); } }]
        };
      }
      return {
        text: '「钟楼的钟，五十年没差过一秒。」陈爷爷仰头看着钟楼，「东西老了，反而可靠——人老了，就只剩故事喽，哈哈。」',
        options: [{ t: '陪他坐会儿', eff: function () { G.addAff('chen', 2); G.toast('陈爷爷很高兴。好感 +2'); } }]
      };
    }
  },

  /* ---------- 阿澈（记者） ---------- */
  {
    id: 'ache', name: '阿澈', emoji: '🎙️', color: '#22c55e', speed: 2.4, wander: 2,
    mood: { morning: '整理', noon: '敏锐', evening: '兴奋', night: '追查' },
    schedule: [
      { h: 0, poi: 'home' }, { h: 10, poi: 'clocktower' }, { h: 13, poi: 'pier' },
      { h: 16, poi: 'park' }, { h: 18, poi: 'pier' }, { h: 22, poi: 'home' }
    ],
    dialog: function (G) {
      var s4 = G.side('s4'), st = G.mainStage();
      /* 主线 stage2：旧档案 */
      if (st === 2 && G.has('archive')) {
        return {
          text: '阿澈快速翻着档案，眼睛越来越亮：「回声计划……阶段三……我的天，这可比获奖报道大得多。」\n她抽出一张旧门禁卡塞给你：「山那边废弃实验室的。门禁密码——我查过人事档案，那间实验室启用那天，是某位教授的生日，十一月中。」\n「去查吧。夜里再去，别被人撞见。」',
          options: [{ t: '（收下门禁卡）', eff: function () { G.take('archive', 1); G.give('keycard', 1); G.setMain(3); G.addAff('ache', 8); G.toast('主线推进：暗室（夜间 20:00–24:00 探访废弃实验室）'); } }]
        };
      }
      if (s4.state === 1 && G.count('photo') >= 3) {
        return {
          text: '「胶片我收下了。」阿澈掂了掂相机，「构图不错，有眼力。」\n她递来一根伸缩警棍：「谢礼。最近夜里不太平，带着防身。」',
          options: [{ t: '（收下警棍）', eff: function () { G.take('camera', 1); G.setSide('s4', 3); G.give('weapon_baton', 1); G.gainExp(90); G.addMoney(80); G.addAff('ache', 12); G.toast('支线完成：记者的镜头（获得伸缩警棍）'); G.callAffinity('world_quest'); } }]
        };
      }
      if (s4.state === 0 && st >= 1) {
        return {
          text: '「你也发现那些异样了？」阿澈打量着你，「我是《恋语晚报》的记者，正在做城市记忆异常的选题。」\n她把一台胶片相机挂到你脖子上：「帮我拍三处地点——栈桥、梧桐公园、北岬灯塔。要黄昏以后的光线。」\n（任务：记者的镜头）',
          options: [
            { t: '成交', eff: function () { G.startSide('s4'); G.give('camera', 1); G.toast('接到支线：记者的镜头（获得相机）'); } },
            { t: '再说吧', eff: function () {} }
          ]
        };
      }
      return {
        text: '「这座城市有秘密。」阿澈咬着笔帽，「十年前那批夜间运输、山里的蓝光、还有最近市民的记忆错乱……全都指向同一个方向。」\n她压低声音：「盯紧那栋研究院。」',
        options: [{ t: '多谢提醒', eff: function () { G.addAff('ache', 2); } }]
      };
    }
  },

  /* ---------- 老周（灯塔守望人） ---------- */
  {
    id: 'laozhou', name: '老周', emoji: '🎣', color: '#64748b', speed: 1.4, wander: 2,
    mood: { morning: '勤快', noon: '守候', evening: '期盼', night: '守望' },
    schedule: [ { h: 0, poi: 'lighthouse' } ],
    dialog: function (G) {
      var s6 = G.side('s6'), st = G.mainStage();
      /* 主线 stage4：三件套齐全 → 点灯 */
      if (st === 4 && G.flag('gear_done') && G.has('lens') && G.has('bulb')) {
        return {
          text: '「零件齐了？」老周眼睛一亮，接过透镜和灯泡，利落地爬上塔架。\n铛——铛——铛——\n三十年不亮的老灯塔，在暮色里骤然睁开眼睛。光柱扫过海面的那一刻，老周背对着你，肩膀微微发抖。\n「上得去吗？塔顶的机关是老式三杆锁——我教过你的。」',
          options: [{ t: '「我上去看看。」', eff: function () { G.fixLighthouse(); } }]
        };
      }
      if (s6.state === 1 && G.count('iron') >= 3) {
        return {
          text: '「好矿石！」老周敲打着铁矿石，火星四溅。「齿轮我来打，不过灯塔还差两样——黄铜透镜和一只大灯泡。」\n「透镜，听说早年流落到栈桥那头了；灯泡，城里日夜超市应该有。」',
          options: [{ t: '（交出铁矿石）', eff: function () { G.take('iron', 3); G.setSide('s6', 2); G.setFlag('gear_done'); G.addAff('laozhou', 10); G.toast('齿轮打造完成（还差透镜与灯泡）'); } }]
        };
      }
      if (G.flag('lighthouse_lit')) {
        return {
          text: '老周仰头望着转动的光柱，眼眶发红：「三十年了……它又转起来了。」\n他用力拍拍你的肩：「丫头，恋语市会记住你的。」',
          options: [{ t: '（陪他看会儿灯塔）', eff: function () { G.addAff('laozhou', 3); } }]
        };
      }
      if (s6.state === 0 && st >= 3) {
        return {
          text: '「灯塔？」老周眯眼看着锈蚀的塔身，「我守了它三十年，修得起，可零件难寻——至少要三块铁矿石打齿轮。」\n「北岭矿脉有矿石，山路难走，你自己掂量。」\n（任务：灯塔零件）',
          options: [
            { t: '我去采矿石', eff: function () { G.startSide('s6'); G.toast('接到支线：灯塔零件'); } },
            { t: '以后再说', eff: function () {} }
          ]
        };
      }
      return {
        text: '「夜里山那边有蓝光，你不晓得吧。」老周指着北面的山影，「老人说灯塔亮了，那些光就消停。」\n他叹口气：「可惜塔老了，灯也瞎了。」',
        options: [{ t: '聊聊灯塔', next: function () {
            return { text: '「灯塔顶的机关还是老式的，三根拉杆。」老周比划着，「以前开塔顶，用的是摩斯码里 L 的节奏——上、上、下。」',
              options: [{ t: '（记住了）', eff: function () { G.addAff('laozhou', 2); } }] };
          } }]
      };
    }
  },

  /* ---------- 墨鱼（猫） ---------- */
  {
    id: 'cat', name: '墨鱼', emoji: '🐈‍⬛', color: '#334155', speed: 3.0, wander: 4, isCat: true,
    mood: { morning: '打盹', noon: '巡逻', evening: '蹲守', night: '夜行' },
    schedule: [ { h: 0, poi: 'cafe' } ],
    dialog: function (G) {
      var s1 = G.side('s1');
      if (s1.state === 2 && G.has('catfood')) {
        return {
          text: '黑猫警惕地盯着你。你打开罐头，它嗅了嗅，凑上前来，尾巴尖轻轻卷起。\n「喵。」（它允许你摸头了）',
          options: [{ t: '（摸摸它）', eff: function () { G.take('catfood', 1); G.setSide('s1', 3); G.addAff('cat', 20); G.gainExp(50); G.toast('墨鱼接受了你！回去告诉小满吧'); } }]
        };
      }
      return {
        text: '一只油光水滑的黑猫蹲在墙头，尾巴一下一下地摆。它打量你片刻，又懒洋洋地移开视线。\n「喵——」',
        options: [
          { t: '（伸出手）', next: function () { return { text: '它嗅了嗅你的指尖，没有靠近，也没有走开。\n好像……在等什么。', options: [{ t: '（收手）', eff: function () { G.addAff('cat', 1); } }] }; } },
          { t: '（给它拍照）', eff: function () { G.toast('它优雅地转身，只留给你一个背影。'); } }
        ]
      };
    }
  }
];

/* ===== 资源点定义（引擎生成位置，这里定义类型） ===== */
var NODE_TYPES = {
  herb:  { item: 'herb',  icon: '🌿', biomes: [3, 4, 11], respawnDays: 2, sp: 6,  exp: 8,  label: '薄荷草丛' },
  iron:  { item: 'iron',  icon: '🪨', biomes: [5, 6],     respawnDays: 3, sp: 12, exp: 15, label: '铁矿露头' },
  fish:  { item: 'fish',  icon: '🎣', biomes: [1],        respawnDays: 0, sp: 10, exp: 10, label: '钓鱼点', nearWater: true },
  dew:   { item: 'dew',   icon: '💧', biomes: [3, 11],    respawnDays: 0, sp: 5,  exp: 12, label: '晨露花', rainOnly: true }
};

/* ===== 谜题 ===== */
var PUZZLES = {
  libcode: {
    name: '图书馆 · 密格书架',
    type: 'code', len: 3, answer: '987',
    hint: '泛黄的便签：「建市之年，取后三。」',
    onSolve: 'library_open'
  },
  clockcode: {
    name: '钟楼 · 密室铜锁',
    type: 'code', len: 4, answer: '1987',
    hint: '陈爷爷说：门锁用的是建市之年，四个数字。',
    onSolve: 'clock_open'
  },
  darkdoor: {
    name: '实验室 · 门禁',
    type: 'code', len: 4, answer: '1115',
    hint: '人事档案：实验室启用日 = 某位教授的生日，十一月中。（他的生日是 11 月 15 日）',
    onSolve: 'dark_open'
  },
  lever: {
    name: '灯塔 · 三杆机关',
    type: 'lever', answer: [1, 1, 0],
    hint: '老周：摩斯码里 L 的节奏——上、上、下。',
    onSolve: 'tower_open'
  },
  stele: {
    name: '神庙 · 星辰石碑',
    type: 'stele', answer: [2, 3, 4, 1],
    hint: '石壁刻着：「自春而始，历夏经秋，至冬而终。」石碑上分别刻着：Ⅰ·冬、Ⅱ·春、Ⅲ·夏、Ⅳ·秋。',
    onSolve: 'temple_open'
  }
};

/* ===== 宝箱（固定点位由引擎放置；此处定义内容） ===== */
var CHEST_LOOT = {
  c_pier:    { items: [['lens', 1]],                       money: 0,  exp: 40 },
  c_park:    { items: [['bread', 2]],                       money: 30, exp: 20 },
  c_mine:    { items: [['iron', 2]],                        money: 0,  exp: 30 },
  c_forest:  { items: [['herb', 3]],                        money: 20, exp: 20 },
  c_temple:  { items: [['charm_butterfly', 1]],             money: 0,  exp: 120 },
  c_clock:   { items: [['weapon_supp', 1], ['crystal', 2]], money: 200, exp: 150 },
  c_dark:    { items: [['archive_hint', 0]],                money: 0,  exp: 0 },
  c_roof:    { items: [['charm_ginkgo', 1]],                money: 50, exp: 80 },
  c_shore1:  { items: [['coffee', 1]],                      money: 10, exp: 10 },
  c_shore2:  { items: [['bento', 1]],                       money: 15, exp: 10 },
  c_lake:    { items: [['shoes_runner', 1]],                money: 0,  exp: 60 }
};

/* ===== 主线章节（用于任务面板展示） ===== */
var MAIN_STAGES = [
  { title: '序幕 · 异象之信', hint: '去街角咖啡店，看看那条神秘信息指向的地方。' },
  { title: '第一章 · 记忆碎片', hint: '收集 3 枚记忆碎片（旧图书馆外 / 梧桐公园 / 临海栈桥），交给许墨。' },
  { title: '第二章 · 回声计划', hint: '在旧图书馆找到密格书架，破译密码，然后把档案带给阿澈。' },
  { title: '第三章 · 暗室', hint: '夜间（20:00–24:00）前往山麓的废弃实验室，用门禁卡进入。' },
  { title: '第四章 · 灯塔之光', hint: '修复北岬灯塔（齿轮×1 透镜×1 灯泡×1），登上塔顶取得核心。' },
  { title: '终章 · 抉择', hint: '回到公寓，整理这一切，做出最终决定。' },
  { title: '尾声 · 之后', hint: '城市恢复了平静。四处走走，看看大家的变化吧。' }
];

/* ===== 支线任务展示 =====
 * lock:  领取所需条件（函数，S→bool）；lockTxt: 不满足时的提示
 * reward: 奖励描述（面板展示）
 */
var SIDE_QUESTS = [
  { id: 's1', title: '咖啡店的猫', giver: '小满', desc: '帮小满找到流浪猫墨鱼并喂食。',
    reward: '经验 + 好感 · 装备「墨鱼的铃铛」' },
  { id: 's2', title: '失落的讲义', giver: '白教授', desc: '追回被风吹散的 3 页讲义。',
    reward: '经验 +80 · ¥120' },
  { id: 's3', title: '城市记忆',   giver: '陈爷爷', desc: '听陈爷爷讲完三段城市故事。',
    reward: '经验 +60 · 钟楼密室线索' },
  { id: 's4', title: '记者的镜头', giver: '阿澈',   desc: '黄昏后为阿澈拍摄栈桥、公园、灯塔。',
    lock: function (S) { return S.mainStage >= 1; }, lockTxt: '需推进主线至第一章',
    reward: '经验 +90 · ¥80 · 装备「伸缩警棍」' },
  { id: 's5', title: '雨中之花',   giver: '小满',   desc: '雨后采 3 朵晨露花，焙一壶花茶送给许墨。',
    lock: function (S) { return (S.npcAff.xiaoman || 0) >= 30; }, lockTxt: '需与小满好感≥30（多去咖啡店聊聊）',
    reward: '许墨好感 +10' },
  { id: 's6', title: '灯塔零件',   giver: '老周',   desc: '采集 3 块铁矿石，为灯塔打造齿轮。',
    lock: function (S) { return S.mainStage >= 3; }, lockTxt: '需推进主线至第三章',
    reward: '推进主线 · 灯塔复明' }
];

/* ===== 结局 ===== */
var ENDINGS = {
  D: {
    id: 'D', name: '熵减之约', icon: '💠',
    text: '你把核心放进他掌心。他握住它，也握住你的手。\n「熵增是宇宙的宿命，」他说，「但生命存在的意义，就是在局部对抗它。」\n回声计划的数据在他手里化作漫天流萤，升入夜空——那是一整座城市被偷走的记忆，正在归还。\n后来的事，报纸只写了一行：恋语市灯塔复明，研究者不详。\n而你记得的版本要长得多：记得他推了推镜框说「观测结束」；记得海边那杯慢慢凉掉的咖啡；记得他说——\n「样本编号 F-01，观测对象：你。观测结论：不可替代。」\n「实验永不终止。这一次，以恋人名义。」'
  },
  A: {
    id: 'A', name: '平行线的交点', icon: '🕯️',
    text: '你把核心交给他。他收得很轻，像收起一句迟到的告白。\n「给我一点时间。」他说，「我会让它在阳光下透明地存在——所有的数据，所有的错误，包括我的。」\n三个月后，回声计划的完整档案出现在市图书馆的公开书架上，落款只有一个代号：Ares。\n有人问他图什么。他望着窗外梧桐树下的你，笑意从眼角开始：\n「图她在意的结果。」\n城市的记忆仍在缓慢愈合。而你与他的那条平行线，从此有了交点。'
  },
  B: {
    id: 'B', name: '守望者', icon: '🌊',
    text: '你松开手，核心坠入黑色的海。\n蓝光在浪里闪了三下，熄灭。像一场漫长的梦，终于有人肯醒。\n「有些真相，」你想，「不值得用一座城市去赌。」\n许墨在你身后站了很久，最后只是替你拢了拢被海风吹乱的外套。\n「我会记下今晚，」他轻声说，「用不会褪色的那种墨水。」\n异常再也没有出现。城市安好，只是偶尔，会有人在梦里听到灯塔的雾笛。\n而你成了唯一的守望者——守着一整座城市，和它不再重演的夜晚。'
  },
  C: {
    id: 'C', name: '观测样本', icon: '🦋',
    text: '你保留了核心。它在你掌心微微搏动，像一颗不属于任何人的心脏。\n你没有销毁它，也没有交给他——信任与怀疑在天平两端，你选择了握紧自己。\n许墨看着你，目光很深，最终只是笑了笑：「……也好。这次，换我做被观测的一方。」\n他转身走进夜色。你不知道的是，那晚之后，所有指向你的档案都被逐一抹去。\n你继续生活，只是偶尔在深夜收到没有署名的讯息：\n「今晚异常系数 0.3，平安。——A」\n你从没回过。但你都留着。'
  }
};

/* 结局判定（在终章触发时调用） */
function judgeEnding(G) {
  var c1 = G.flag('m3_choice'), c2 = G.flag('m4_choice');
  var aff = G.aff('xumo');
  var sides = ['s1', 's2', 's3', 's4', 's5', 's6'];
  var allSide = sides.every(function (id) { return G.side(id).state === 3; });
  if (c2 === 'give' && c1 === 'trust' && aff >= 80 && allSide && G.explorePct() >= 55) return 'D';
  if (c2 === 'give' && c1 !== 'confront' && aff >= 60) return 'A';
  if (c2 === 'destroy') return 'B';
  return 'C';
}

/* ===== 开场剧情 ===== */
var PROLOGUE = [
  { t: '深夜 23:47。', d: '手机在枕边亮起。一条没有署名的信息：「你最近，是不是忘了一些不该忘的事？」' },
  { t: '街角咖啡店。', d: '信息的末尾是一个地址，和一句「明早八点，我在那里等你——L」。' },
  { t: '恋语市，秋天。', d: '近来城里流传着一种说法：有人一觉醒来，遗忘了整整一周；有人记的事，从未发生过。他们说这是"记忆的流感"。' },
  { t: '而你隐约觉得，', d: '这条信息背后的人，与你失去的那段记忆有关。' },
  { t: '《世界 · 恋语市》', d: 'WASD / 方向键移动 · E 或点击按钮交互 · M 大地图 · J 任务 · B 背包 · K 技能\n祝你在恋语市，找回属于你的记忆。' }
];

/* ===== 暴露到全局 ===== */
window.WORLD_DATA = {
  TILE: TILE, MAP_W: MAP_W, MAP_H: MAP_H, CHUNK: CHUNK,
  B: B, SOLID: SOLID, BIOME_STYLE: BIOME_STYLE,
  POIS: POIS, ITEMS: ITEMS, EQUIPS: EQUIPS, SKILLS: SKILLS,
  WEATHERS: WEATHERS, WEATHER_TRANS: WEATHER_TRANS,
  NPCS: NPCS, NODE_TYPES: NODE_TYPES, PUZZLES: PUZZLES,
  CHEST_LOOT: CHEST_LOOT, MAIN_STAGES: MAIN_STAGES, SIDE_QUESTS: SIDE_QUESTS,
  CITY_LORE: CITY_LORE, ENDINGS: ENDINGS, PROLOGUE: PROLOGUE,
  judgeEnding: judgeEnding, affLevel: affLevel,
  /* 建模扩展·v2 */
  DECOR_TYPES: DECOR_TYPES, DECOR_DIST: DECOR_DIST,
  SEASONS: SEASONS, SEASON_DAYS: SEASON_DAYS, seasonByDay: seasonByDay,
  WILDLIFE_TYPES: WILDLIFE_TYPES, WILDLIFE_CAP: WILDLIFE_CAP,
  NEW_ITEMS: NEW_ITEMS, NEW_EQUIPS: NEW_EQUIPS, NEW_NODE_TYPES: NEW_NODE_TYPES,
  ENEMIES: ENEMIES, ELEMENT_CHART: ELEMENT_CHART, PLAYER_ELEMENTS: PLAYER_ELEMENTS,
  VEHICLES: VEHICLES, BUS_STOPS: BUS_STOPS, FERRY_PORTS: FERRY_PORTS,
  NPC_NEEDS: NPC_NEEDS, BUILD_TEMPLATES: BUILD_TEMPLATES,
  PASSERBY_TEMPLATES: PASSERBY_TEMPLATES, TRANSPORT_SCHEDULE: TRANSPORT_SCHEDULE
};


/* ====== 【建模扩展·v2】新增数据 ====== */
/* 装饰类型（4→16）：0 无 / 1 树 / 2 路灯 / 3 花
 * 4 石头 / 5 灌木 / 6 蘑菇 / 7 长椅 / 8 围栏 / 9 喷泉 /
 * 10 摊位 / 11 路标 / 12 篝火 / 13 枯树 / 14 野花丛 / 15 路灯(古典) */
var DECOR_TYPES = {
  0:  { name: '空',     icon: '',     solid: 0, h: 0 },
  1:  { name: '树',     icon: '🌳',  solid: 1, h: 22 },
  2:  { name: '路灯',   icon: '💡',  solid: 0, h: 14, light: 1 },
  3:  { name: '花',     icon: '🌸',  solid: 0, h: 6 },
  4:  { name: '石头',   icon: '🪨',  solid: 1, h: 8 },
  5:  { name: '灌木',   icon: '🌿',  solid: 0, h: 8 },
  6:  { name: '蘑菇',   icon: '🍄',  solid: 0, h: 5 },
  7:  { name: '长椅',   icon: '🪑',  solid: 0, h: 7, sit: 1 },
  8:  { name: '围栏',   icon: '🚧',  solid: 1, h: 9 },
  9:  { name: '喷泉',   icon: '⛲',  solid: 1, h: 14 },
  10: { name: '摊位',   icon: '🏪',  solid: 1, h: 16, shop: 1 },
  11: { name: '路标',   icon: '🪧',  solid: 0, h: 12 },
  12: { name: '篝火',   icon: '🔥',  solid: 0, h: 10, light: 2, warm: 1 },
  13: { name: '枯树',   icon: '🥀',  solid: 1, h: 18 },
  14: { name: '野花丛', icon: '🌺',  solid: 0, h: 5 },
  15: { name: '古典路灯', icon: '🏮', solid: 0, h: 14, light: 1 }
};
/* 装饰概率表：按 biome 索引（key 是 biome，value 是 {decor: weight}） */
var DECOR_DIST = {
  0: {}, 1: {},                       // 深海/浅水
  2: { 4: 0.08, 14: 0.05 },           // 沙滩：石头/野花
  3: { 1: 0.10, 5: 0.06, 14: 0.08, 6: 0.02, 7: 0.02 },  // 草地
  4: { 1: 0.40, 5: 0.12, 6: 0.05, 13: 0.02 },            // 森林
  5: { 4: 0.10, 5: 0.08, 13: 0.03 },                     // 丘陵
  6: { 4: 0.18 },                                          // 山地
  7: { 4: 0.06 },                                          // 雪峰
  8: { 2: 0.04, 11: 0.02, 15: 0.01 },                     // 马路
  9: { 2: 0.05, 11: 0.03, 7: 0.04, 15: 0.02 },            // 广场
  10: {},                                                  // 建筑
  11: { 1: 0.18, 14: 0.12, 9: 0.02, 7: 0.06 },            // 公园
  12: {},                                                  // 室内
  13: {},                                                  // 木桥
  14: { 14: 0.10, 7: 0.03, 5: 0.04 }                      // 田野
};

/* 季节系统：每 7 个游戏日 = 1 季，循环 春→夏→秋→冬 */
var SEASONS = {
  spring: { name: '春', icon: '🌱', next: 'summer', tint: '#a8d8b9', grassBoost: 1.3, flowerChance: 1.4, snow: 0, rainBias: 5 },
  summer: { name: '夏', icon: '☀️', next: 'autumn', tint: '#f5e08c', grassBoost: 1.0, flowerChance: 1.0, snow: 0, rainBias: 8 },
  autumn: { name: '秋', icon: '🍂', next: 'winter', tint: '#e0a868', grassBoost: 0.7, flowerChance: 0.6, snow: 0, rainBias: 12 },
  winter: { name: '冬', icon: '❄️', next: 'spring', tint: '#e8eef5', grassBoost: 0.3, flowerChance: 0.1, snow: 1, rainBias: -10, frozenLake: 1 }
};
var SEASON_DAYS = 7;   // 每季天数
function seasonByDay(day) {
  var idx = Math.floor((day - 1) / SEASON_DAYS) % 4;
  return ['spring', 'summer', 'autumn', 'winter'][idx];
}

/* 流动生物：纯视觉生态层，无碰撞 */
var WILDLIFE_TYPES = {
  bird:      { name: '飞鸟',   icon: '🐦', speed: 3.5, hours: [6,7,8,9,10,16,17,18], seasonMul: { spring: 1.4, summer: 1.2, autumn: 0.8, winter: 0.3 } },
  butterfly: { name: '蝴蝶',   icon: '🦋', speed: 1.2, hours: [9,10,11,12,13,14,15,16], seasonMul: { spring: 1.6, summer: 1.5, autumn: 0.5, winter: 0 } },
  firefly:   { name: '萤火虫', icon: '✨', speed: 0.5, hours: [20,21,22,23,0], seasonMul: { spring: 0.6, summer: 1.8, autumn: 1.0, winter: 0 } },
  fish:      { name: '游鱼',   icon: '🐟', speed: 0.8, hours: [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23], seasonMul: { spring: 1.0, summer: 1.0, autumn: 0.9, winter: 0.4 }, waterOnly: 1 },
  cat:       { name: '野猫',   icon: '🐈', speed: 1.0, hours: [5,6,7,8,17,18,19,20,21], seasonMul: { spring: 1.0, summer: 0.8, autumn: 1.1, winter: 0.5 } }
};
/* 每种生物在视野内最大同时存在数 */
var WILDLIFE_CAP = { bird: 5, butterfly: 6, firefly: 12, fish: 4, cat: 1 };

/* ===== 资源节点扩展（4→15） =====
 * biome 字段：兼容数值（旧）或数组（新）。nearWater/nearMine/nearForest 为附加条件。
 * tool：所需采集工具（无则徒手）。respawnDays：-1=一次性，0=雨后/特殊，>0=天数。
 */
/* 新增材料（追加到 ITEMS，幂等——若已存在则跳过） */
var NEW_ITEMS = {
  copper:    { name: '铜矿石',   icon: '🟤', kind: 'mat',  desc: '红棕色的铜矿，导电性极佳。' },
  silver:    { name: '银矿石',   icon: '⚪', kind: 'mat',  desc: '山中 rare 矿脉，月光下泛冷光。' },
  coal:      { name: '煤炭',     icon: '⚫', kind: 'mat',  desc: '北岭煤层，可烧制木炭与冶金。' },
  crystal2:  { name: '紫水晶',   icon: '🔮', kind: 'mat',  desc: '山洞深处的晶簇，能量稳定。' },
  shell:     { name: '贝壳',     icon: '🐚', kind: 'mat',  desc: '栈桥下捡到的彩色贝壳。' },
  mushroom:  { name: '野蘑菇',   icon: '🍄', kind: 'mat',  desc: '森林里的白蘑菇，谨慎食用。' },
  berry:     { name: '浆果',     icon: '🫐', kind: 'mat',  desc: '酸甜的野生浆果。' },
  cotton:    { name: '棉花',     icon: '☁️', kind: 'mat',  desc: '田野里的白绒团。' },
  spice:     { name: '香草',     icon: '🌿', kind: 'mat',  desc: '香气浓郁的料理香草。' },
  silk:      { name: '蚕丝',     icon: '🧵', kind: 'mat',  desc: '野蚕吐的丝，可织布。' },
  honey:     { name: '蜂蜜',     icon: '🍯', kind: 'food', sp: 20, hp: 8,  desc: '林间蜂巢割下的蜜。' },
  roe:       { name: '鱼籽',     icon: '🟠', kind: 'mat',  desc: '河鱼腹中的鱼籽，鲜美。' },
  pearl:     { name: '珍珠',     icon: '⚪', kind: 'mat',  desc: '极罕见的贝中之珠。', key: true },
  herb_mint: { name: '胡椒薄荷', icon: '🌿', kind: 'mat',  desc: '清凉的薄荷变种。' },
  herb_lav:  { name: '薰衣草',   icon: '💜', kind: 'mat',  desc: '紫色花穗，安神助眠。' }
};
/* 采集工具（追加到 EQUIPS） */
var NEW_EQUIPS = {
  tool_pick:   { slot: 'tool', name: '矿工镐',   icon: '⛏️', q: 1, desc: '采集铜/铁/银/煤的必备工具。', gather: ['copper','iron','silver','coal','crystal2'] },
  tool_rod:    { slot: 'tool', name: '竹钓竿',   icon: '🎣', q: 1, desc: '河边钓鱼效率 +50%。', gather: ['fish','roe'] },
  tool_sickle: { slot: 'tool', name: '镰刀',     icon: '🔪', q: 1, desc: '收割棉花/香草/薄荷/薰衣草。', gather: ['cotton','spice','herb_mint','herb_lav','herb'] },
  tool_net:    { slot: 'tool', name: '捕虫网',   icon: '🪲', q: 1, desc: '可在白天捕捉蝴蝶/萤火虫（装饰用）。', gather: ['butterfly','firefly'] },
  tool_axe:    { slot: 'tool', name: '手斧',     icon: '🪓', q: 1, desc: '砍伐枯树获得木料。', gather: ['wood'] },
  tool_bucket: { slot: 'tool', name: '水桶',     icon: '🪣', q: 1, desc: '海边捡贝壳、捞鱼籽。', gather: ['shell','roe','pearl'] }
};
/* 新装备槽：tool（采集工具，不影响战斗属性） */
/* 注：玩家 equip 对象增加 tool 字段即可，不影响已有 weapon/shoes/charm 三槽 */

/* 扩展 NODE_TYPES（原 4 个保留，新增 11 个） */
var NEW_NODE_TYPES = {
  copper:  { item: 'copper',   icon: '🟤', biomes: [5, 6], respawnDays: 3, sp: 10, exp: 14, label: '铜矿露头', tool: 'tool_pick' },
  silver:  { item: 'silver',   icon: '⚪', biomes: [6, 7], respawnDays: 5, sp: 16, exp: 26, label: '银矿脉',   tool: 'tool_pick', rare: 1 },
  coal:    { item: 'coal',     icon: '⚫', biomes: [5, 6], respawnDays: 3, sp: 8,  exp: 10, label: '煤层',     tool: 'tool_pick' },
  crystal2:{ item: 'crystal2', icon: '🔮', biomes: [6, 7], respawnDays: 6, sp: 18, exp: 30, label: '水晶洞',   tool: 'tool_pick', rare: 1, nightOnly: 1 },
  shell:   { item: 'shell',    icon: '🐚', biomes: [2, 1],  respawnDays: 2, sp: 4, exp: 6,  label: '贝壳滩',   tool: 'tool_bucket', nearWater: 1 },
  mushroom:{ item: 'mushroom', icon: '🍄', biomes: [4, 11],respawnDays: 2, sp: 4, exp: 8,  label: '蘑菇圈',   tool: 'tool_sickle', forestDepth: 1 },
  berry:   { item: 'berry',    icon: '🫐', biomes: [3, 4, 11], respawnDays: 2, sp: 4, exp: 8, label: '浆果丛' },
  cotton:  { item: 'cotton',   icon: '☁️', biomes: [14],   respawnDays: 3, sp: 6, exp: 10, label: '棉田',     tool: 'tool_sickle' },
  spice:   { item: 'spice',    icon: '🌿', biomes: [3, 14],respawnDays: 2, sp: 5, exp: 9,  label: '香草丛',   tool: 'tool_sickle' },
  pearl:   { item: 'pearl',    icon: '⚪', biomes: [1],    respawnDays: 0, sp: 8, exp: 40, label: '珠贝',     tool: 'tool_bucket', nearWater: 1, rare: 2, rainOnly: 0 },
  herb_mint:{ item: 'herb_mint',icon: '🌿', biomes: [3, 11],respawnDays: 2, sp: 4, exp: 8,  label: '胡椒薄荷', tool: 'tool_sickle' },
  herb_lav: { item: 'herb_lav', icon: '💜', biomes: [11, 4],respawnDays: 3, sp: 6, exp: 12, label: '薰衣草',  tool: 'tool_sickle', eveningOnly: 1 },
  silk:    { item: 'silk',     icon: '🧵', biomes: [4],     respawnDays: 4, sp: 8, exp: 18, label: '野蚕茧',  tool: 'tool_sickle', forestDepth: 1, rare: 1 },
  honey:   { item: 'honey',    icon: '🍯', biomes: [4],    respawnDays: 4, sp: 6, exp: 16, label: '蜂巢',    tool: 'tool_bucket', forestDepth: 1, rare: 1 }
};

/* ===== 异常残影敌人（5 种）=====
 * kind: shadow(追击)/ranged(远程)/splitter(分裂)/boss(首领)/lurker(潜伏)
 * 元素克制：normal < fire < ice < lightning < normal（相克循环）
 */
var ENEMIES = {
  shadow:   { name: '游荡残影', icon: '🌫️', hp: 26, atk: 4,  def: 0,  exp: 22, drop: 'crystal', dropN: 1, kind: 'shadow',   el: 'normal', spd: 1.7, sight: 30, color: '#5a4a8a' },
  ranged:   { name: '远程残影', icon: '🏹', hp: 18, atk: 6,  def: 0,  exp: 26, drop: 'crystal', dropN: 1, kind: 'ranged',   el: 'lightning', spd: 1.2, sight: 22, color: '#3a6a8a', range: 8 },
  splitter: { name: '分裂残影', icon: '🫧', hp: 22, atk: 3,  def: 1,  exp: 30, drop: 'crystal', dropN: 2, kind: 'splitter', el: 'ice', spd: 1.4, sight: 24, color: '#6a8a9a', splitAt: 0.4, splitInto: 2 },
  lurker:   { name: '潜伏残影', icon: '👁️', hp: 16, atk: 8,  def: 0,  exp: 28, drop: 'crystal', dropN: 1, kind: 'lurker',   el: 'fire', spd: 0.0, sight: 6, color: '#8a3a3a', stealth: 1, ambush: 1 },
  boss:     { name: '回声巨影', icon: '💠', hp: 120,atk: 12, def: 4,  exp: 200,drop: 'core',     dropN: 1, kind: 'boss',     el: 'normal', spd: 1.0, sight: 40, color: '#7a3aaa', phase2At: 0.5 }
};
/* 元素克制：el[key] 对 [target, mul] */
var ELEMENT_CHART = {
  normal:    { fire: 1.5, ice: 0.8, lightning: 1.0, normal: 1.0 },
  fire:      { ice: 1.5, lightning: 0.8, normal: 1.0, fire: 1.0 },
  ice:       { lightning: 1.5, normal: 0.8, fire: 1.0, ice: 1.0 },
  lightning: { normal: 1.5, fire: 0.8, ice: 1.0, lightning: 1.0 }
};
/* 玩家可解锁的元素（通过装备/技能） */
var PLAYER_ELEMENTS = {
  normal:    { name: '普通', icon: '⚔️' },
  fire:      { name: '火',   icon: '🔥', unlock: 'weapon_supp', desc: 'Evol抑制器附魔后普攻带火' },
  ice:       { name: '冰',   icon: '❄️', unlock: 'skill_min5',  desc: '觉醒技能解锁冰系' },
  lightning: { name: '雷',   icon: '⚡', unlock: 'charm_echo',  desc: '回声核心·戒附雷系' }
};

/* ===== 交通工具 ===== */
var VEHICLES = {
  bike:   { name: '自行车', icon: '🚲', cost: 200,  spdMul: 1.6, spDrain: 0.6, desc: '公寓楼下取用，1.6 倍速，体力消耗 -40%。' },
  bus:    { name: '公交',   icon: '🚌', cost: 5,    spdMul: 4.0, spDrain: 0.0, desc: '点对点传送：钟楼 ↔ 大学 ↔ 灯塔 ↔ 栈桥。' },
  ferry:  { name: '渡轮',   icon: '⛴️', cost: 15,  spdMul: 3.0, spDrain: 0.0, desc: '海岸 ↔ 海岛（东北角神秘岛），解锁新区域。' }
};
/* 公交站点（POI id） */
var BUS_STOPS = ['clocktower', 'univ', 'lighthouse', 'pier'];
/* 渡轮码头 */
var FERRY_PORTS = [
  { id: 'main', x: 124, y: 88, name: '栈桥码头' },
  { id: 'isle', x: 134, y: 22, name: '雾岛码头' }
];

/* ===== NPC 需求系统 =====
 * 每个 NPC 每天可触发 1 个需求（凌晨 5 点重置）：
 *   want: 想要的物品 id（满足后给奖励）
 *   reward: { money, aff, item, exp }
 *   dialog_hint: 玩家走近时 NPC 主动提需求的对白
 *   dialog_done: 交付后的对白
 */
var NPC_NEEDS = {
  xumo: [
    { want: 'coffee',  reward: { aff: 6, exp: 10 }, dialog_hint: '「……今天的实验还要熬到很晚，能帮我带杯咖啡吗？」', dialog_done: '「……温度刚好。谢了。」' },
    { want: 'herb_lav',reward: { aff: 8, exp: 14 }, dialog_hint: '「薰衣草——能让人在数据流里短暂停下来。如果有……」', dialog_done: '他接过花穗，放在鼻尖轻嗅。' },
    { want: 'archive', reward: { aff: 10, exp: 0 }, dialog_hint: '（旧档案相关）', dialog_done: '「……你找到了。」他声音很轻。' }
  ],
  xiaoman: [
    { want: 'berry',   reward: { aff: 4, money: 15 }, dialog_hint: '「想做新的浆果慕斯～如果能采到浆果就好啦！」', dialog_done: '「哇！我马上做一份给你尝！」' },
    { want: 'fish',    reward: { aff: 4, money: 20 }, dialog_hint: '「店里的猫粮快没了……能帮我钓条鱼吗？」', dialog_done: '「墨鱼有口福啦～」' }
  ],
  bai: [
    { want: 'page',    reward: { aff: 6, exp: 14 }, dialog_hint: '「又被风吹散了几页讲义……能帮我捡回来吗？」', dialog_done: '「谢谢。这一页正是关键的批注。」' },
    { want: 'herb_mint',reward: { aff: 4, exp: 8 }, dialog_hint: '「最近老花眼厉害，听说胡椒薄荷能提神……」', dialog_done: '「这就泡一杯。」' }
  ]
};

/* ===== AI 建筑模板（玩家可一键放置的预设建筑） ===== */
var BUILD_TEMPLATES = {
  cafe_mini:    { name: '迷你咖啡亭', icon: '☕', w: 2, h: 2, b: 10, decors: [{ d: 2, dx: 0, dy: 2 }], cost: 80,  sp: 20 },
  shrine_mini:  { name: '迷你神龛',   icon: '⛩️', w: 2, h: 2, b: 10, decors: [{ d: 11, dx: 1, dy: 2 }], cost: 120, sp: 25 },
  fountain_sq:  { name: '广场喷泉',   icon: '⛲', w: 3, h: 3, b: 9,  decors: [{ d: 9, dx: 1, dy: 1 }, { d: 7, dx: 0, dy: 0 }, { d: 7, dx: 2, dy: 0 }, { d: 7, dx: 0, dy: 2 }, { d: 7, dx: 2, dy: 2 }], cost: 200, sp: 35 },
  garden_plot:  { name: '花圃',       icon: '🌺', w: 3, h: 3, b: 11, decors: [{ d: 3, dx: 0, dy: 0 }, { d: 3, dx: 1, dy: 0 }, { d: 3, dx: 2, dy: 0 }, { d: 14, dx: 0, dy: 1 }, { d: 14, dx: 1, dy: 1 }, { d: 14, dx: 2, dy: 1 }, { d: 5, dx: 0, dy: 2 }, { d: 5, dx: 2, dy: 2 }], cost: 60, sp: 15 },
  campfire:     { name: '营地篝火',   icon: '🔥', w: 1, h: 1, b: 3,  decors: [{ d: 12, dx: 0, dy: 0 }], cost: 30, sp: 10 },
  lamp_post:    { name: '街道路灯',   icon: '💡', w: 1, h: 1, b: 8,  decors: [{ d: 2, dx: 0, dy: 0 }], cost: 15, sp: 5 },
  bench_park:   { name: '公园长椅',   icon: '🪑', w: 1, h: 1, b: 11, decors: [{ d: 7, dx: 0, dy: 0 }], cost: 20, sp: 6 },
  fence_plot:   { name: '围栏圈地',   icon: '🚧', w: 3, h: 3, b: 14, decors: [{ d: 8, dx: 0, dy: 0 }, { d: 8, dx: 1, dy: 0 }, { d: 8, dx: 2, dy: 0 }, { d: 8, dx: 0, dy: 2 }, { d: 8, dx: 1, dy: 2 }, { d: 8, dx: 2, dy: 2 }, { d: 8, dx: 0, dy: 1 }, { d: 8, dx: 2, dy: 1 }], cost: 40, sp: 12 }
};

/* ===== 流动居民模板（路上随机出现的城市居民，纯视觉+简短对话） ===== */
var PASSERBY_TEMPLATES = [
  { id: 'p_student',  emoji: '🎓', color: '#4f8f7a', dialog: ['「赶早八赶早八……」', '「今天图书馆占得到座吗？」', '「食堂的咖喱饭yyds。」'] },
  { id: 'p_office',   emoji: '💼', color: '#5f6fb0', dialog: ['「又要加班了。」', '「地铁好挤。」', '「周末去哪吃？」'] },
  { id: 'p_elder',    emoji: '🧓', color: '#9a7c54', dialog: ['「现在的年轻人啊……」', '「天气真好。」', '「我家孙子会走路了。」'] },
  { id: 'p_kid',      emoji: '🧒', color: '#eab308', dialog: ['「姐姐姐姐！」', '「看我的纸飞机！」', '「明天去公园！」'] },
  { id: 'p_jogger',   emoji: '🏃', color: '#c05a6a', dialog: ['「呼……呼……」', '「今天十公里。」', '「早跑舒服多了。」'] },
  { id: 'p_cyclist',  emoji: '🚲', color: '#7a3aaa', dialog: ['「叮铃～让一让。」', '「环城路风景不错。」'] },
  { id: 'p_vendor',   emoji: '🏪', color: '#b0703c', dialog: ['「新鲜草莓～」', '「烤红薯嘞～」', '「便宜的围巾～」'] }
];

/* ===== 公交/渡轮时刻（每小时一班） ===== */
var TRANSPORT_SCHEDULE = {
  bus:  { interval_h: 1, first_h: 6, last_h: 22, wait_min: 5 },  /* 等待 5 分钟游戏时间 */
  ferry:{ interval_h: 3, first_h: 8, last_h: 18, wait_min: 10 }
};

/* 合并新对象到原对象（幂等）——移到末尾，NEW_* 已定义 */
Object.keys(NEW_ITEMS).forEach(function (k) { if (!ITEMS[k]) ITEMS[k] = NEW_ITEMS[k]; });
Object.keys(NEW_EQUIPS).forEach(function (k) { if (!EQUIPS[k]) EQUIPS[k] = NEW_EQUIPS[k]; });
Object.keys(NEW_NODE_TYPES).forEach(function (k) { if (!NODE_TYPES[k]) NODE_TYPES[k] = NEW_NODE_TYPES[k]; });

/* 修复：v2 数据在 window.WORLD_DATA 初次赋值之后才定义，末尾补挂 */
Object.assign(window.WORLD_DATA, {
  DECOR_TYPES: DECOR_TYPES, DECOR_DIST: DECOR_DIST,
  SEASONS: SEASONS, SEASON_DAYS: SEASON_DAYS, seasonByDay: seasonByDay,
  WILDLIFE_TYPES: WILDLIFE_TYPES, WILDLIFE_CAP: WILDLIFE_CAP,
  NEW_ITEMS: NEW_ITEMS, NEW_EQUIPS: NEW_EQUIPS, NEW_NODE_TYPES: NEW_NODE_TYPES,
  ENEMIES: ENEMIES, ELEMENT_CHART: ELEMENT_CHART, PLAYER_ELEMENTS: PLAYER_ELEMENTS,
  VEHICLES: VEHICLES, BUS_STOPS: BUS_STOPS, FERRY_PORTS: FERRY_PORTS,
  NPC_NEEDS: NPC_NEEDS, BUILD_TEMPLATES: BUILD_TEMPLATES,
  PASSERBY_TEMPLATES: PASSERBY_TEMPLATES, TRANSPORT_SCHEDULE: TRANSPORT_SCHEDULE
});

/* =========================================================================
 * 建筑入内·室内场景配置（INTERIORS）
 * 每个建筑的室内热点布局（坐标为百分比 0-100，基于 16:9 横版背景图）
 * 热点类型：rest 休息 / work 工作·学习 / npc 与许墨互动 / view 观景·氛围
 * img/desc/comment 由服务端 /api/world/interiors/{place_id} AI 生成后缓存
 * ========================================================================= */
var INTERIORS = {
  home: {
    name: '你的公寓', icon: '🏠',
    prompt_hint: '温馨单身公寓室内，木质地板，纱帘阳光，沙发床铺书桌厨房阳台，紫色调装饰，许墨常来做客',
    hotspots: [
      { id: 'bed',      type: 'rest',  label: '小憩',   icon: '🛏️', x: 18, y: 68 },
      { id: 'desk',     type: 'work',  label: '书桌',   icon: '📚', x: 62, y: 52 },
      { id: 'kitchen',  type: 'work',  label: '一起做饭', icon: '🍳', x: 82, y: 72 },
      { id: 'xumo',     type: 'npc',   label: '许墨',   icon: '💜', x: 45, y: 45 }
    ]
  },
  cafe: {
    name: '街角咖啡店', icon: '☕',
    prompt_hint: '暖色调咖啡店内，吧台咖啡机，窗边卡座，黑板手写菜单，木质桌椅，盆栽绿植，午后斜阳',
    hotspots: [
      { id: 'bar',      type: 'work',  label: '点单',   icon: '☕', x: 25, y: 55 },
      { id: 'window',   type: 'view',  label: '窗边座', icon: '🪟', x: 70, y: 50 },
      { id: 'book',     type: 'work',  label: '书架',   icon: '📖', x: 50, y: 70 },
      { id: 'xumo',     type: 'npc',   label: '许墨',   icon: '💜', x: 72, y: 52 }
    ]
  },
  lab: {
    name: '脑科学研究院', icon: '🧪',
    prompt_hint: '脑科学研究院实验室内，精密仪器，显微镜，脑波扫描仪，书架档案柜，白大褂挂架，冷白灯光配紫色夜光',
    hotspots: [
      { id: 'bench',    type: 'work',  label: '实验台', icon: '🧪', x: 28, y: 55 },
      { id: 'scope',    type: 'work',  label: '显微镜', icon: '🔬', x: 55, y: 60 },
      { id: 'archive',  type: 'view',  label: '档案',   icon: '🗄️', x: 78, y: 50 },
      { id: 'xumo',     type: 'npc',   label: '许墨工位', icon: '💜', x: 45, y: 50 }
    ]
  },
  univ: {
    name: '恋语大学', icon: '🎓',
    prompt_hint: '恋语大学教室走廊内，阶梯教室门，走廊长椅，公告板，窗外樱花校园，午后阳光',
    hotspots: [
      { id: 'classroom',type: 'work',  label: '教室',   icon: '🏫', x: 30, y: 50 },
      { id: 'library', type: 'work',  label: '自习角', icon: '📚', x: 60, y: 55 },
      { id: 'lawn',    type: 'rest',  label: '草坪',   icon: '🌳', x: 80, y: 70 },
      { id: 'office',  type: 'npc',   label: '许墨办公室', icon: '💜', x: 48, y: 50 }
    ]
  },
  library: {
    name: '旧图书馆', icon: '📚',
    prompt_hint: '旧图书馆阅览室内，高耸书架，绿色台灯，木质长桌，拱形彩窗，尘埃光柱，古典氛围',
    hotspots: [
      { id: 'read',     type: 'work',  label: '阅览座', icon: '📖', x: 35, y: 60 },
      { id: 'rare',    type: 'view',  label: '古籍区', icon: '📜', x: 70, y: 50 },
      { id: 'window',  type: 'view',  label: '彩窗',   icon: '🪟', x: 85, y: 30 },
      { id: 'xumo',    type: 'npc',   label: '许墨常坐', icon: '💜', x: 40, y: 62 }
    ]
  },
  market: {
    name: '日夜超市', icon: '🛒',
    prompt_hint: '日夜超市内，货架陈列，收银台，鲜食冷柜，灯光通明，城市深夜便利店氛围',
    hotspots: [
      { id: 'shelf',   type: 'work',  label: '货架',   icon: '🥫', x: 30, y: 55 },
      { id: 'fresh',   type: 'work',  label: '鲜食',   icon: '🍙', x: 55, y: 60 },
      { id: 'counter', type: 'shop',  label: '收银',   icon: '💳', x: 78, y: 55 },
      { id: 'xumo',    type: 'npc',   label: '许墨',   icon: '💜', x: 50, y: 58 }
    ]
  },
  xflat: {
    name: '教工公寓', icon: '🏢',
    prompt_hint: '教工公寓楼内走廊客厅，米色墙面，木质门牌，绿植盆栽，午后斜阳透过楼道窗',
    hotspots: [
      { id: 'living',   type: 'rest',  label: '客厅',   icon: '🛋️', x: 30, y: 60 },
      { id: 'kitchen', type: 'work',  label: '一起做饭', icon: '🍳', x: 60, y: 65 },
      { id: 'study',   type: 'work',  label: '书房',   icon: '📚', x: 78, y: 50 },
      { id: 'door',    type: 'npc',   label: '许墨门口', icon: '💜', x: 45, y: 55 }
    ]
  },
  clocktower: {
    name: '中央钟楼', icon: '🕰️',
    prompt_hint: '钟楼钟摆室内，巨大铜钟齿轮，机械钟摆，圆形观景台俯瞰恋语市，黄昏金光',
    hotspots: [
      { id: 'pendulum',type: 'view',  label: '钟摆',   icon: '⚙️', x: 30, y: 50 },
      { id: 'gears',   type: 'view',  label: '齿轮',   icon: '🔧', x: 55, y: 60 },
      { id: 'view',    type: 'view',  label: '观景台', icon: '🌆', x: 78, y: 40 },
      { id: 'xumo',    type: 'npc',   label: '许墨',   icon: '💜', x: 50, y: 55 }
    ]
  },
  lighthouse: {
    name: '北岬灯塔', icon: '🗼',
    prompt_hint: '灯塔灯室内，巨大透镜，螺旋铁梯，海景观景台，海风夜星，孤寂浪漫氛围',
    hotspots: [
      { id: 'lamp',    type: 'view',  label: '灯室',   icon: '💡', x: 30, y: 45 },
      { id: 'stair',   type: 'view',  label: '螺旋梯', icon: '🌀', x: 55, y: 60 },
      { id: 'sea',     type: 'view',  label: '观海台', icon: '🌊', x: 78, y: 50 },
      { id: 'xumo',    type: 'npc',   label: '许墨',   icon: '💜', x: 50, y: 55 }
    ]
  },
  darklab: {
    name: '废弃实验室', icon: '🚪',
    prompt_hint: '废弃实验室尘封内景，破旧仪器，倒下的桌椅，散落档案，昏暗应急灯，神秘悬疑氛围',
    hotspots: [
      { id: 'instr',   type: 'view',  label: '仪器',   icon: '🔬', x: 28, y: 55 },
      { id: 'cabinet', type: 'work',  label: '档案柜', icon: '🗄️', x: 55, y: 60 },
      { id: 'door',    type: 'view',  label: '暗门',   icon: '🚪', x: 80, y: 50 },
      { id: 'xumo',    type: 'npc',   label: '许墨',   icon: '💜', x: 45, y: 55 }
    ]
  },
  park: {
    name: '梧桐公园', icon: '🌳',
    prompt_hint: '梧桐公园户外场景，茂密梧桐树，长椅喷泉，花坛小径，斑驳阳光午后',
    hotspots: [
      { id: 'bench',   type: 'rest',  label: '长椅',   icon: '🪑', x: 30, y: 65 },
      { id: 'fountain',type: 'view',  label: '喷泉',   icon: '⛲', x: 55, y: 50 },
      { id: 'flowers', type: 'view',  label: '花坛',   icon: '🌸', x: 78, y: 65 },
      { id: 'xumo',    type: 'npc',   label: '许墨',   icon: '💜', x: 50, y: 58 }
    ]
  },
  temple: {
    name: '神庙遗迹', icon: '⛩️',
    prompt_hint: '神庙遗迹户外场景，古老石柱，苔藓祭坛，藤蔓缠绕，斑驳阳光穿过断壁',
    hotspots: [
      { id: 'pillar',  type: 'view',  label: '石柱',   icon: '🏛️', x: 30, y: 50 },
      { id: 'altar',   type: 'view',  label: '祭坛',   icon: '🗿', x: 55, y: 60 },
      { id: 'moss',    type: 'view',  label: '苔地',   icon: '🍃', x: 78, y: 65 },
      { id: 'xumo',    type: 'npc',   label: '许墨',   icon: '💜', x: 50, y: 55 }
    ]
  },
  mine: {
    name: '北岭矿脉', icon: '⛏️',
    prompt_hint: '北岭矿脉矿洞口场景，矿石堆，废弃矿车，木质支撑，提灯昏黄，探险氛围',
    hotspots: [
      { id: 'ore',     type: 'work',  label: '矿堆',   icon: '💎', x: 30, y: 60 },
      { id: 'cart',    type: 'view',  label: '矿车',   icon: '🛒', x: 55, y: 65 },
      { id: 'tunnel',  type: 'view',  label: '矿洞',   icon: '🕳️', x: 78, y: 55 },
      { id: 'xumo',    type: 'npc',   label: '许墨',   icon: '💜', x: 50, y: 60 }
    ]
  },
  shrine: {
    name: '星辰石碑群', icon: '🗿',
    prompt_hint: '星辰石碑群户外场景，环形石碑阵列，主碑中央，星象图刻痕，月光铺地神秘氛围',
    hotspots: [
      { id: 'main',    type: 'view',  label: '主碑',   icon: '🗿', x: 50, y: 50 },
      { id: 'ring',    type: 'view',  label: '环列',   icon: '⭕', x: 28, y: 60 },
      { id: 'star',    type: 'view',  label: '星图',   icon: '🌟', x: 78, y: 45 },
      { id: 'xumo',    type: 'npc',   label: '许墨',   icon: '💜', x: 50, y: 65 }
    ]
  },
  pier: {
    name: '临海栈桥', icon: '🌉',
    prompt_hint: '临海栈桥木质桥面场景，延伸至海中，栏杆海风，灯塔远景，黄昏橙红',
    hotspots: [
      { id: 'fish',    type: 'rest',  label: '桥头',   icon: '🎣', x: 25, y: 60 },
      { id: 'mid',     type: 'view',  label: '中段',   icon: '🌊', x: 50, y: 55 },
      { id: 'end',     type: 'view',  label: '尽头',   icon: '🌅', x: 78, y: 50 },
      { id: 'xumo',    type: 'npc',   label: '许墨',   icon: '💜', x: 50, y: 58 }
    ]
  },
  garden: {
    name: '屋顶花园', icon: '🌸',
    prompt_hint: '屋顶花园露台场景，藤蔓花架，藤椅圆桌，城市夜景天际线，星空柔和',
    hotspots: [
      { id: 'bed',     type: 'view',  label: '花圃',   icon: '🌷', x: 28, y: 60 },
      { id: 'chair',   type: 'rest',  label: '藤椅',   icon: '🪑', x: 55, y: 65 },
      { id: 'sky',     type: 'view',  label: '星空',   icon: '✨', x: 80, y: 30 },
      { id: 'xumo',    type: 'npc',   label: '许墨',   icon: '💜', x: 55, y: 60 }
    ]
  }
};

/* ===== 大富翁游戏配置 ===== */
/* 基于3D世界POI构建大富翁棋盘，使用现有地图位置作为地产 */
var MONOPOLY_CONFIG = {
  /* 游戏棋盘：基于POI顺序排列 */
  board_order: [
    'start',      // 起点 - 中央钟楼
    'cafe',       // 街角咖啡店
    'lab',        // 脑科学研究院
    'univ',       // 恋语大学
    'library',    // 旧图书馆
    'market',     // 日夜超市
    'xflat',      // 教工公寓
    'park',       // 梧桐公园
    'lighthouse', // 北岬灯塔
    'temple',     // 神庙遗迹
    'darklab',    // 废弃实验室
    'pier',       // 临海栈桥
    'mine',       // 北岭矿脉
    'shrine',     // 星辰石碑群
    'garden',     // 屋顶花园
    'home'        // 你的公寓
  ],
  
  /* 特殊位置配置 */
  special_spaces: {
    'start': {
      name: '起点',
      icon: '🏁',
      description: '每次经过起点获得¥2000',
      effect: 'pass_start'
    },
    'chance1': {
      name: '机会',
      icon: '🎲',
      description: '抽取机会卡',
      effect: 'chance_card'
    },
    'chance2': {
      name: '机会',
      icon: '🎲',
      description: '抽取机会卡',
      effect: 'chance_card'
    },
    'jail': {
      name: '监狱',
      icon: '🔒',
      description: '暂停行动2回合',
      effect: 'go_jail'
    },
    'free_parking': {
      name: '免费停车',
      icon: '🅿️',
      description: '安全地带',
      effect: 'none'
    }
  },
  
  /* 机会卡配置 */
  chance_cards: [
    { id: 'c1', text: '获得许墨的学术资助', effect: 'money', value: 1500 },
    { id: 'c2', text: '发现古老文献，出售获得收益', effect: 'money', value: 1000 },
    { id: 'c3', text: '雨天路滑，医药费支出', effect: 'money', value: -500 },
    { id: 'c4', text: '咖啡店打折优惠', effect: 'money', value: 300 },
    { id: 'c5', text: '学术会议奖金', effect: 'money', value: 800 },
    { id: 'c6', text: '移动到起点，获得过路费', effect: 'move', position: 0 },
    { id: 'c7', text: '前进3步', effect: 'move', steps: 3 },
    { id: 'c8', text: '后退2步', effect: 'move', steps: -2 },
    { id: 'c9', text: '免费在任意地产建房', effect: 'free_house' },
    { id: 'c10', text: '坐牢一回合', effect: 'jail', rounds: 1 }
  ],
  
  /* 许墨特色台词模板 */
  xumo_dialogues: {
    game_start: '规则很简单，但结果的随机性，正是研究的乐趣所在。',
    roll_dice: '概率分布会告诉我们下一步的故事。',
    move: '移动的轨迹，有时候比终点更有意思。',
    buy_property: '投资决策需要理性分析，但直觉也很重要。',
    pay_rent: '这叫"租金"，本质上是一种资源再分配。',
    receive_rent: '这是系统性的必然结果，不是吗？',
    chance_card: '随机变量，总是能带来意外的发现。',
    go_jail: '暂时的限制，有时是策略的一部分。',
    leave_jail: '重新回到棋盘上，感觉如何？',
    win: '你的决策逻辑很优秀，值得学习。',
    lose: '失败是学习过程的一部分，这次我学到了很多。',
    opponent_turn: '观察对手，也是一种研究方法。',
    money_low: '资源管理是游戏的精髓，需要更谨慎。',
    property_auction: '竞价博弈，很经典的实验场景。'
  },
  
  /* 可用NPC配置 */
  available_npcs: [
    { id: 'xumo', name: '许墨', emoji: '🧪', color: '#7c3aed', difficulty: 'hard' },
    { id: 'xiaoman', name: '小满', emoji: '🌻', color: '#eab308', difficulty: 'easy' },
    { id: 'bai', name: '白教授', emoji: '📚', color: '#0ea5e9', difficulty: 'medium' }
  ],
  
  /* 游戏规则配置 */
  rules: {
    initial_money: 15000,
    pass_start_bonus: 2000,
    max_houses: 4,
    house_cost_ratio: 0.5,  // 房屋价格为地产价格的50%
    rent_ratio: 0.1,         // 基础租金为价格的10%
    house_rent_bonus: 0.5,  // 每个房屋增加50%租金
    hotel_rent_bonus: 2.0,  // 每个酒店增加200%租金
    jail_rounds: 2,
    max_players: 4,
    min_players: 2
  }
};

/* 暴露 INTERIORS 到 window.WORLD_DATA，前端 world-ui.js 通过 D.INTERIORS 访问 */
Object.assign(window.WORLD_DATA, { INTERIORS: INTERIORS, MONOPOLY_CONFIG: MONOPOLY_CONFIG });

/* 暴露到 G（world-engine 通过 window.WORLD_DATA 访问） */
/* （数据本身已是顶层 var，挂在 IIFE 内 → 通过 window.WORLD_DATA 暴露） */

})();
