/* =========================================================================
 * 世界·恋语市 —— 引擎层
 * 职责：世界生成与分块渲染 / 时间与天气模拟 / 玩家控制与碰撞 /
 *       NPC 日程 AI / 资源·宝箱·交互物 / 异常残影 / 迷雾探索 / 存档
 * UI 层（world-ui.js）通过 WORLD_ENG 的回调接口接管 DOM 表现。
 * ========================================================================= */
(function () {
'use strict';

var D = window.WORLD_DATA;
var TILE = D.TILE, MW = D.MAP_W, MH = D.MAP_H, B = D.B, SOLID = D.SOLID;
var MAP_SEED = 20260815;   // 固定种子 → 世界确定性生成

/* ================= 随机 & 噪声 ================= */
function mulberry32(a) {
  return function () {
    a |= 0; a = a + 0x6D2B79F5 | 0;
    var t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}
function hash2(x, y, seed) {
  var h = Math.imul(x, 374761393) + Math.imul(y, 668265263) + Math.imul(seed | 0, 2246822519);
  h = Math.imul(h ^ h >>> 13, 1274126177);
  return ((h ^ h >>> 16) >>> 0) / 4294967296;
}
function smooth(t) { return t * t * (3 - 2 * t); }
function vnoise(x, y, seed) {
  var xi = Math.floor(x), yi = Math.floor(y);
  var xf = x - xi, yf = y - yi;
  var a = hash2(xi, yi, seed), b = hash2(xi + 1, yi, seed);
  var c = hash2(xi, yi + 1, seed), d = hash2(xi + 1, yi + 1, seed);
  var u = smooth(xf), v = smooth(yf);
  return a * (1 - u) * (1 - v) + b * u * (1 - v) + c * (1 - u) * v + d * u * v;
}
function fbm(x, y, seed, oct) {
  var v = 0, amp = 0.5, f = 1, tot = 0;
  for (var i = 0; i < (oct || 4); i++) {
    v += vnoise(x * f, y * f, seed + i * 101) * amp;
    tot += amp; amp *= 0.5; f *= 2;
  }
  return v / tot;
}

/* ================= 世界数据 ================= */
var biomeMap = null;      // Uint8Array MW*MH
var decorMap = null;      // Uint8Array（0 无 1 树 2 路灯 3 花）
var cityMask = null;      // 城区范围
var rngNodes = null;      // 节点生成用 rng

function idx(x, y) { return y * MW + x; }
function inMap(x, y) { return x >= 0 && y >= 0 && x < MW && y < MH; }
function biomeAt(x, y) {
  if (!inMap(x, y)) return B.DEEP;
  return biomeMap[idx(x, y)];
}
function isSolid(x, y) { return !!SOLID[biomeAt(x, y)]; }

/* 城市中心与半径 */
var CITY = { x: 92, y: 72, r: 17 };

function distCity(x, y) { return Math.hypot(x - CITY.x, y - CITY.y); }

function poiById(id) {
  for (var i = 0; i < D.POIS.length; i++) if (D.POIS[i].id === id) return D.POIS[i];
  return null;
}

/* ---------- 世界生成 ---------- */
function generateWorld() {
  biomeMap = new Uint8Array(MW * MH);
  decorMap = new Uint8Array(MW * MH);
  cityMask = new Uint8Array(MW * MH);

  var S1 = MAP_SEED, S2 = MAP_SEED + 7, S3 = MAP_SEED + 13;
  var x, y, i;

  /* 1) 基础地形：高度 + 湿度（东/南海偏置、北部山地偏置） */
  for (y = 0; y < MH; y++) {
    for (x = 0; x < MW; x++) {
      var h = fbm(x / 26, y / 26, S1, 5);
      var m = fbm(x / 20, y / 20, S2, 4);
      /* 海洋偏置：东部与南部 */
      h -= Math.max(0, (x - 112) / 34) * 0.55;
      h -= Math.max(0, (y - 108) / 40) * 0.45;
      /* 北部山脉隆起 */
      var north = Math.max(0, (34 - y) / 34);
      h += north * north * 0.42;
      /* 西部小丘 */
      h += Math.max(0, (18 - x) / 18) * 0.15;

      var b;
      if (h < 0.30) b = B.DEEP;
      else if (h < 0.365) b = B.WATER;
      else if (h < 0.40) b = B.SAND;
      else if (h > 0.80) b = B.SNOW;
      else if (h > 0.71) b = B.MOUNT;
      else if (h > 0.62) b = B.HILL;
      else if (m > 0.58) b = B.FOREST;
      else if (m > 0.40) b = B.GRASS;
      else b = B.FIELD;
      biomeMap[idx(x, y)] = b;
    }
  }

  /* 2) 西南湖泊（保证水域） */
  carveCircle(50, 104, 9, B.WATER);
  carveCircle(58, 110, 6, B.WATER);
  carveCircle(43, 99, 5, B.WATER);

  /* 3) 河流：北山 → 西南湖 */
  carveRiver(70, 30, 50, 104);

  /* 4) 城区：街道网格 + 建筑用地 */
  for (y = CITY.y - CITY.r; y <= CITY.y + CITY.r; y++) {
    for (x = CITY.x - CITY.r; x <= CITY.x + CITY.r; x++) {
      if (!inMap(x, y)) continue;
      var d = distCity(x, y);
      if (d > CITY.r) continue;
      /* 城内水域一律填平（城外海岸线不受影响），避免孤立海洞把玩家围死 */
      cityMask[idx(x, y)] = 1;
      var gx = (x - (CITY.x - CITY.r)) % 7, gy = (y - (CITY.y - CITY.r)) % 7;
      if (gx === 3 || gx === 4 || gy === 3) biomeMap[idx(x, y)] = B.ROAD;
      else biomeMap[idx(x, y)] = B.PLAZA;
    }
  }

  /* 5) 公园（覆盖为绿地） */
  var park = poiById('park');
  for (y = park.y; y < park.y + park.h; y++)
    for (x = park.x; x < park.x + park.w; x++)
      if (inMap(x, y)) { biomeMap[idx(x, y)] = B.PARK; cityMask[idx(x, y)] = 1; }

  /* 6) 神庙遗迹区 */
  var temple = poiById('temple');
  for (y = temple.y - 1; y < temple.y + temple.h + 1; y++)
    for (x = temple.x - 1; x < temple.x + temple.w + 1; x++)
      if (inMap(x, y) && biomeMap[idx(x, y)] !== B.DEEP && biomeMap[idx(x, y)] !== B.WATER)
        biomeMap[idx(x, y)] = B.HILL;

  /* 7) 建筑 POI 落地 */
  for (i = 0; i < D.POIS.length; i++) {
    var p = D.POIS[i];
    if (p.type !== 'build' && p.type !== 'bridge') continue;
    for (y = p.y; y < p.y + p.h; y++)
      for (x = p.x; x < p.x + p.w; x++)
        if (inMap(x, y)) biomeMap[idx(x, y)] = p.type === 'bridge' ? B.BRIDGE : B.BUILD;
  }
  /* 栈桥引桥（向海延伸的路面） */
  var pier = poiById('pier');
  for (x = pier.x - 6; x < pier.x; x++) if (inMap(x, pier.y + 3)) biomeMap[idx(x, pier.y + 3)] = B.PLAZA;

  /* 8) 建筑间隙的填充楼（城区内非路非POI处按格子放小楼） */
  var fillRng = mulberry32(MAP_SEED + 99);
  for (y = CITY.y - CITY.r; y <= CITY.y + CITY.r; y++) {
    for (x = CITY.x - CITY.r; x <= CITY.x + CITY.r; x++) {
      if (!inMap(x, y)) continue;
      if (biomeMap[idx(x, y)] !== B.PLAZA) continue;
      var gx2 = (x - (CITY.x - CITY.r)), gy2 = (y - (CITY.y - CITY.r));
      var cellX = Math.floor(gx2 / 7), cellY = Math.floor(gy2 / 7);
      var r = hash2(cellX, cellY, MAP_SEED + 55);
      if (r > 0.42) continue;                       // 部分街区留空（广场）
      var lx = gx2 % 7, ly = gy2 % 7;
      if (lx >= 1 && lx <= 3 && ly >= 1 && ly <= 3) biomeMap[idx(x, y)] = B.BUILD;
    }
  }
  /* 保证 POI 门口不堵：POI 建筑下方一行强制广场 */
  for (i = 0; i < D.POIS.length; i++) {
    var p2 = D.POIS[i];
    if (p2.type !== 'build') continue;
    for (x = p2.x - 1; x <= p2.x + p2.w; x++) {
      if (inMap(x, p2.y + p2.h)) {
        var bb = biomeMap[idx(x, p2.y + p2.h)];
        if (bb === B.BUILD) biomeMap[idx(x, p2.y + p2.h)] = B.ROAD;
      }
    }
  }

  /* 9) 装饰：树 / 路灯 / 花 */
  for (y = 0; y < MH; y++) {
    for (x = 0; x < MW; x++) {
      var bi = biomeMap[idx(x, y)];
      var n = hash2(x, y, MAP_SEED + 77);
      if (bi === B.FOREST && n > 0.52) decorMap[idx(x, y)] = 1;
      else if (bi === B.PARK && n > 0.74) decorMap[idx(x, y)] = 1;
      else if (bi === B.GRASS && n > 0.93) decorMap[idx(x, y)] = 1;
      else if (bi === B.ROAD && (x + y) % 9 === 0) decorMap[idx(x, y)] = 2;  // 路灯
      else if ((bi === B.GRASS || bi === B.PARK) && n < 0.06) decorMap[idx(x, y)] = 3;
    }
  }
  snapshotBase();
}

/* 原始地貌快照（「复原」笔刷 & 重建世界时使用） */
var baseBiome = null, baseDecor = null;
function snapshotBase() {
  baseBiome = biomeMap.slice();
  baseDecor = decorMap.slice();
}

function carveCircle(cx, cy, r, b) {
  for (var y = cy - r - 1; y <= cy + r + 1; y++)
    for (var x = cx - r - 1; x <= cx + r + 1; x++) {
      if (!inMap(x, y)) continue;
      if (Math.hypot(x - cx, y - cy) <= r) biomeMap[idx(x, y)] = b;
    }
}
function carveRiver(x0, y0, x1, y1) {
  var steps = Math.hypot(x1 - x0, y1 - y0) * 2.2;
  for (var i = 0; i <= steps; i++) {
    var t = i / steps;
    var wob = (vnoise(t * 6, 3.7, MAP_SEED + 31) - 0.5) * 11;
    var px = x0 + (x1 - x0) * t + wob * 0.8;
    var py = y0 + (y1 - y0) * t + wob * 0.5;
    var r = 1.4 + t * 1.2;
    for (var y = Math.floor(py - r); y <= py + r; y++)
      for (var x = Math.floor(px - r); x <= px + r; x++) {
        if (!inMap(x, y)) continue;
        var cur = biomeMap[idx(x, y)];
        if (cur === B.MOUNT || cur === B.SNOW) continue;   // 穿不过山，沿山脚改道
        if (Math.hypot(x - px, y - py) <= r) biomeMap[idx(x, y)] = B.WATER;
      }
  }
  /* 河上两座桥（保证东西通行） */
  bridgeAt(56, 74); bridgeAt(52, 92);
}
function bridgeAt(x, y) {
  for (var i = -1; i <= 1; i++) for (var j = -2; j <= 2; j++)
    if (inMap(x + i, y + j)) biomeMap[idx(x + i, y + j)] = B.BRIDGE;
}

/* ================= 固定交互物 ================= */
var SHARDS = [ { x: 89, y: 84 }, { x: 101, y: 69 }, { x: 124, y: 87 } ];            // 记忆碎片
var PAGES = [ { x: 78, y: 66 }, { x: 102, y: 70 }, { x: 89, y: 83 } ];              // 讲义散页
var PHOTOS = [ { id: 'ph_pier', x: 123, y: 90, name: '栈桥落日' }, { id: 'ph_park', x: 103, y: 72, name: '公园暮色' }, { id: 'ph_light', x: 113, y: 51, name: '灯塔剪影' } ];

/* 宝箱点位 */
var CHESTS = [
  { id: 'c_pier',   x: 125, y: 90 },
  { id: 'c_park',   x: 105, y: 67 },
  { id: 'c_mine',   x: 59,  y: 35 },
  { id: 'c_forest', x: 44,  y: 66 },
  { id: 'c_temple', x: 43,  y: 60 },
  { id: 'c_clock',  x: 93,  y: 73 },
  { id: 'c_dark',   x: 64,  y: 43 },
  { id: 'c_shore1', x: 113, y: 79 },
  { id: 'c_shore2', x: 109, y: 87 },
  { id: 'c_lake',   x: 46,  y: 93 }
];

/* 资源节点（确定性生成） */
var nodes = [];
function generateNodes() {
  nodes = [];
  var rng = mulberry32(MAP_SEED + 1234);
  var tries = 0;
  function place(type, count, cond) {
    var placed = 0;
    while (placed < count && tries < 60000) {
      tries++;
      var x = 2 + Math.floor(rng() * (MW - 4));
      var y = 2 + Math.floor(rng() * (MH - 4));
      var b = biomeAt(x, y);
      if (SOLID[b]) continue;
      if (!cond(x, y, b)) continue;
      var near = nodes.some(function (n) { return Math.abs(n.x - x) + Math.abs(n.y - y) < 4; });
      if (near) continue;
      nodes.push({ id: type + '_' + x + '_' + y, type: type, x: x, y: y });
      placed++;
    }
  }
  var NT = D.NODE_TYPES;
  place('herb', 26, function (x, y, b) { return NT.herb.biomes.indexOf(b) >= 0 && !cityMask[idx(x, y)]; });
  place('iron', 12, function (x, y, b) {
    var mine = poiById('mine');
    var nearMine = Math.abs(x - (mine.x + 1)) + Math.abs(y - (mine.y + 1)) < 9;
    return NT.iron.biomes.indexOf(b) >= 0 && nearMine;
  });
  place('fish', 14, function (x, y, b) {
    if (b !== B.GRASS && b !== B.SAND) return false;
    for (var dy = -1; dy <= 1; dy++) for (var dx = -1; dx <= 1; dx++)
      if (biomeAt(x + dx, y + dy) === B.WATER) return true;
    return false;
  });
  place('dew', 10, function (x, y, b) {
    var park = poiById('park');
    return (b === B.PARK) || (b === B.GRASS && Math.abs(x - park.x - 4) + Math.abs(y - park.y - 3) < 10);
  });
}

/* ================= 存档 ================= */
var SAVE_KEY = 'lucien_world_save_v1';
var S = null;   // 当前存档状态

function defaultSave() {
  var spawn = { x: 101.5, y: 81.5 };
  try { if (biomeMap) { var w = findWalkableNear(101, 81); spawn = { x: w.x + 0.5, y: w.y + 0.5 }; } } catch (e) {}
  return {
    ver: 1,
    timeMin: 8 * 60, day: 1, weather: 'clear', lastRollHour: -1,
    player: {
      x: spawn.x, y: spawn.y, dir: 0,
      lv: 1, exp: 0, hp: 100, sp: 100, money: 200, skillPts: 1,
      skills: [], equip: { weapon: 'weapon_umbrella', shoes: 'shoes_canvas', charm: 'charm_amulet' },
      bag: [{ id: 'bread', qty: 2 }, { id: 'coffee', qty: 1 }]
    },
    counters: {}, flags: {}, worldFlags: {},
    mainStage: 0, sides: {}, npcAff: {}, questTrack: null,
    explored: null, exploredCount: 0,
    nodes: {}, chests: {},
    seenPrologue: false, ending: null,
    settings: { sfx: true },
    playSec: 0, lucienCalls: {}
  };
}

/* RLE 压缩探索位图：[count, val, count, val...] */
function rleEncode(arr) {
  var out = [], run = 1;
  for (var i = 1; i <= arr.length; i++) {
    if (i < arr.length && arr[i] === arr[i - 1]) run++;
    else { out.push(run, arr[i - 1]); run = 1; }
  }
  return out.join(',');
}
function rleDecode(str) {
  var arr = new Uint8Array(MW * MH), parts = String(str).split(','), pos = 0;
  for (var i = 0; i < parts.length; i += 2) {
    var c = +parts[i], v = +parts[i + 1];
    for (var k = 0; k < c && pos < arr.length; k++) arr[pos++] = v;
  }
  return arr;
}

function saveGame() {
  if (!S) return;
  try {
    S.explored = rleEncode(exploredArr);
    localStorage.setItem(SAVE_KEY, JSON.stringify(S));
  } catch (e) { /* 存储满时静默 */ }
}
function loadGame() {
  try {
    var raw = localStorage.getItem(SAVE_KEY);
    if (raw) {
      var data = JSON.parse(raw);
      if (data && data.ver === 1) return data;
    }
  } catch (e) {}
  return null;
}

/* ================= 引擎状态 ================= */
var exploredArr = new Uint8Array(MW * MH);
var keys = {};
var running = false, lastTs = 0, rafId = 0;
var camera = { x: 101.5, y: 81.5 };
/* 渲染模式：'2d' 平面 canvas / '3d' 体素 WebGL（world-3d.js 提供扩展） */
var renderMode = '2d';
var ext3d = null;
var chunks = {};      // chunk 缓存
var chunkOrder = [];  // LRU
var npcs = [];        // 运行时 NPC 实体
var shadows = [];     // 异常残影
var particles = [];   // 天气粒子（屏幕空间）
var lightFlash = 0;   // 闪电
var npcV = {};        // npc id -> 实体
var lucienAffinityLv = 0;  // 全局心动等级（联动 min4）

/* canvas */
var cv = null, ctx = null, dpr = 1;
var viewW = 800, viewH = 600;
var miniCv = null, miniCtx = null;

/* ================= 工具 ================= */
function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
function lerp(a, b, t) { return a + (b - a) * t; }
function gameHour() { return Math.floor((S.timeMin % 1440) / 60); }
function gameClock() {
  var m = Math.floor(S.timeMin % 1440);
  var h = Math.floor(m / 60), mm = m % 60;
  return (h < 10 ? '0' : '') + h + ':' + (mm < 10 ? '0' : '') + mm;
}
function isNight() { var h = gameHour(); return h >= 20 || h < 5; }
function dayMin() { return S.timeMin % 1440; }
/* 绝对游戏分钟（跨天单调递增），供资源重生等时间差计算使用 */
function absMin() { return (S.day - 1) * 1440 + S.timeMin; }

/* 玩家数值汇总 */
function hasSkill(id) { return S.player.skills.indexOf(id) >= 0; }
function calcStats() {
  var p = S.player, st = { atk: 5 + p.lv * 2, spd: 4.2, hpMax: 100 + (p.lv - 1) * 10, spMax: 100 + (p.lv - 1) * 8, aff: 0, spSave: 0 };
  ['weapon', 'shoes', 'charm'].forEach(function (slot) {
    var id = p.equip[slot], eq = id && D.EQUIPS[id];
    if (!eq) return;
    st.atk += eq.atk || 0;
    st.spd *= 1 + (eq.spd || 0) / 100;
    st.hpMax += eq.hp || 0;
    st.spMax += eq.sp || 0;
    st.aff += eq.aff || 0;
    st.spSave += eq.spSave || 0;
  });
  if (hasSkill('bod1')) st.spd *= 1.10;
  if (hasSkill('bod3')) st.hpMax += 40;
  if (hasSkill('min4') && lucienAffinityLv >= 5) { st.spd *= 1.10; st.spSave += 15; }
  if (hasSkill('charm_bell') || (S.player.equip.charm === 'charm_bell')) st.spd *= 1.0; // 铃铛 spd 已在装备表
  return st;
}

/* ================= 背包 ================= */
function bagFind(id) {
  for (var i = 0; i < S.player.bag.length; i++) if (S.player.bag[i].id === id) return S.player.bag[i];
  return null;
}
function giveItem(id, qty) {
  qty = qty || 1;
  var it = D.ITEMS[id] || D.EQUIPS[id];
  if (!it) return;
  if (D.EQUIPS[id]) { S.player.bag.push({ id: id, qty: 1 }); toast('获得装备 ' + it.icon + ' ' + it.name); refreshUI(); return; }
  var slot = bagFind(id);
  if (slot) slot.qty += qty;
  else S.player.bag.push({ id: id, qty: qty });
  toast('获得 ' + it.icon + ' ' + it.name + ' ×' + qty);
  refreshUI();
}
function takeItem(id, qty) {
  qty = qty || 1;
  var slot = bagFind(id);
  if (!slot || slot.qty < qty) return false;
  slot.qty -= qty;
  if (slot.qty <= 0) S.player.bag.splice(S.player.bag.indexOf(slot), 1);
  refreshUI();
  return true;
}
function hasItem(id, qty) {
  var slot = bagFind(id);
  return !!slot && slot.qty >= (qty || 1);
}

/* ================= 经验/升级 ================= */
function expNeed(lv) { return 60 + lv * 40; }
function gainExp(n) {
  var p = S.player;
  p.exp += n;
  toast('经验 +' + n);
  while (p.exp >= expNeed(p.lv)) {
    p.exp -= expNeed(p.lv);
    p.lv++;
    p.skillPts++;
    var st = calcStats();
    p.hp = st.hpMax; p.sp = st.spMax;
    toast('🎉 升级！Lv.' + p.lv + '（技能点 +1）');
  }
  refreshUI();
}

/* ================= NPC 实体 ================= */
function npcScheduleTarget(npcDef) {
  /* 自定义居民：常驻锚点 */
  if (npcDef.anchor) return npcDef.anchor;
  /* 许墨剧情驻留：暗室解谜后停留在实验室旁，直到玩家完成对峙对话 */
  if (npcDef.id === 'xumo') {
    if (S.flags.m3_choice && S.flags.xumo_pin) S.flags.xumo_pin = null;
    if (S.flags.xumo_pin) return { x: S.flags.xumo_pin.x, y: S.flags.xumo_pin.y };
  }
  var h = gameHour(), target = npcDef.schedule[0].poi;
  for (var i = 0; i < npcDef.schedule.length; i++)
    if (h >= npcDef.schedule[i].h) target = npcDef.schedule[i].poi;
  var poi = poiById(target);
  var bx = poi.x + (poi.w || 2) / 2, by = poi.y + (poi.h || 2) + 0.6;
  return { x: bx, y: by };
}
function initNpcs() {
  npcs = [];
  npcV = {};
  for (var i = 0; i < D.NPCS.length; i++) {
    var def = D.NPCS[i];
    var t = npcScheduleTarget(def);
    var e = {
      def: def, x: t.x, y: t.y, tx: t.x, ty: t.y,
      wx: t.x, wy: t.y, state: 'idle', wob: Math.random() * 10
    };
    npcs.push(e); npcV[def.id] = e;
    if (def.avatar) getSpriteImg(def.avatar); /* 预加载头像，进视野即可绘制 */
  }
}
function moveEntity(e, dx, dy, dt, speed) {
  /* 分离轴移动 + 碰撞 */
  var nx = e.x + dx * speed * dt;
  if (!collideCircle(nx, e.y)) e.x = nx;
  var ny = e.y + dy * speed * dt;
  if (!collideCircle(e.x, ny)) e.y = ny;
}
function collideCircle(x, y) {
  var r = 0.34;
  var x0 = Math.floor(x - r), x1 = Math.floor(x + r);
  var y0 = Math.floor(y - r), y1 = Math.floor(y + r);
  for (var yy = y0; yy <= y1; yy++)
    for (var xx = x0; xx <= x1; xx++)
      if (isSolid(xx, yy)) return true;
  return false;
}
function updateNpc(e, dt) {
  var def = e.def;
  var t = npcScheduleTarget(def);
  e.tx = t.x; e.ty = t.y;
  var pd = Math.hypot(S.player.x - e.x, S.player.y - e.y);
  /* 远处 NPC 低频模拟：直接吸附 */
  if (pd > 38) {
    e.x = t.x + (hash2(Math.floor(t.x), e.wob * 10 | 0, 3) - 0.5) * 2;
    e.y = t.y + (hash2(0, Math.floor(t.y), 7) - 0.5) * 2;
    return;
  }
  var dx = t.x - e.x, dy = t.y - e.y;
  var d = Math.hypot(dx, dy);
  if (d > 1.2) {
    /* 雷暴/深夜 NPC 赶路回家（目标即家） */
    moveEntity(e, dx / d, dy / d, dt, def.speed);
    e.state = 'walk';
  } else {
    /* 到达：小范围漫游 */
    e.state = 'idle';
    e.wob += dt;
    if (Math.random() < dt * 0.4) {
      var ang = Math.random() * Math.PI * 2;
      var r = Math.random() * (def.wander || 1);
      e.wx = clamp(t.x + Math.cos(ang) * r, 1, MW - 2);
      e.wy = clamp(t.y + Math.sin(ang) * r, 1, MH - 2);
    }
    var wdx = e.wx - e.x, wdy = e.wy - e.y, wd = Math.hypot(wdx, wdy);
    if (wd > 0.3) moveEntity(e, wdx / wd, wdy / wd, dt, def.speed * 0.5);
  }
}

/* ================= 玩家 ================= */
function tryMovePlayer(dx, dy, dt) {
  var p = S.player;
  var st = calcStats();
  var speed = st.spd;
  var weatherDef = D.WEATHERS[S.weather];
  if (weatherDef.slow) speed *= 1 - weatherDef.slow / 100;
  if (isNight() && !hasSkill('bod4')) speed *= 0.88;
  var running = keys.shift && S.player.sp > 1;
  if (running) speed *= 1.55;

  var len = Math.hypot(dx, dy) || 1;
  moveEntity(p, dx / len, dy / len, dt, speed);
  if (dx || dy) p.dir = dx > 0 ? 1 : dx < 0 ? 3 : (dy > 0 ? 0 : 2);

  /* 体力 */
  var drain = 0;
  if (running) {
    drain = 1.1;
    if (hasSkill('bod2')) drain *= 0.6;
    if (S.player.equip.shoes === 'shoes_wind') drain *= 0.8;
  }
  if (hasSkill('min5')) drain *= 0.7;
  drain *= 1 - Math.min(60, st.spSave) / 100;
  if (drain > 0) p.sp = Math.max(0, p.sp - drain * dt);
  else {
    var regen = 0.55;
    if (hasSkill('bod5')) regen *= 2;
    p.sp = Math.min(st.spMax, p.sp + regen * dt);
  }
}

/* ================= 探索迷雾 ================= */
function updateExplore() {
  var px = Math.floor(S.player.x), py = Math.floor(S.player.y);
  var R = 6, changed = false;
  for (var dy = -R; dy <= R; dy++)
    for (var dx = -R; dx <= R; dx++) {
      if (dx * dx + dy * dy > R * R) continue;
      var x = px + dx, y = py + dy;
      if (!inMap(x, y)) continue;
      var i = idx(x, y);
      if (!exploredArr[i]) { exploredArr[i] = 1; S.exploredCount++; changed = true; }
    }
  return changed;
}
function explorePct() { return Math.round(S.exploredCount / (MW * MH) * 1000) / 10; }

/* ================= 天气 ================= */
function rollWeather() {
  var h = gameHour();
  if (S.lastRollHour === h + S.day * 24) return;
  S.lastRollHour = h + S.day * 24;
  var trans = D.WEATHER_TRANS[S.weather] || D.WEATHER_TRANS.clear;
  var r = Math.random(), acc = 0, next = S.weather;
  for (var k in trans) { acc += trans[k] / 100; if (r <= acc) { next = k; break; } }
  /* 夜间晴 → 星夜 */
  if (next === 'clear' && (h >= 21 || h < 4)) next = 'starry';
  if (next === 'starry' && h < 21 && h >= 4) next = 'clear';
  if (next !== S.weather) {
    S.weather = next;
    logWorld('weather', '天气转为「' + D.WEATHERS[next].name + '」' + D.WEATHERS[next].icon);
    toast('天气转为「' + D.WEATHERS[next].name + '」' + D.WEATHERS[next].icon); refreshUI();
  }
}

/* ================= 残影 ================= */
function spawnShadowChance(dt) {
  if (!isNight() || S.ending) return;
  if (S.mainStage >= 6) return;   // 结局后世界安宁
  var px = Math.floor(S.player.x), py = Math.floor(S.player.y);
  var inCity = inMap(px, py) && cityMask[idx(px, py)];
  if (inCity) return;
  if (shadows.length >= 2) return;
  if (Math.random() > dt * 0.045) return;
  var ang = Math.random() * Math.PI * 2, d = 9 + Math.random() * 6;
  var sx = S.player.x + Math.cos(ang) * d, sy = S.player.y + Math.sin(ang) * d;
  if (!inMap(Math.floor(sx), Math.floor(sy)) || isSolid(Math.floor(sx), Math.floor(sy))) return;
  var stg = S.mainStage;
  shadows.push({ x: sx, y: sy, hp: 26 + stg * 14, hpMax: 26 + stg * 14, atk: 4 + stg * 2, wob: Math.random() * 7 });
}
function updateShadows(dt) {
  if (battleShadow) return;   /* 战斗中冻结 */
  for (var i = shadows.length - 1; i >= 0; i--) {
    var s = shadows[i];
    var dx = S.player.x - s.x, dy = S.player.y - s.y;
    var d = Math.hypot(dx, dy);
    if (d > 30) { shadows.splice(i, 1); continue; }
    s.wob += dt;
    var sp = 1.7 + Math.sin(s.wob) * 0.3;
    var nx = s.x + dx / d * sp * dt, ny = s.y + dy / d * sp * dt;
    if (!collideCircle(nx, ny)) { s.x = nx; s.y = ny; }
    else if (!collideCircle(nx, s.y)) s.x = nx;
    else if (!collideCircle(s.x, ny)) s.y = ny;
    if (d < 0.75) { triggerBattle(s); return; }
  }
}
function battleEnd(win, fled) {
  var s = battleShadow;
  battleShadow = null;
  if (win) {
    shadows.splice(shadows.indexOf(s), 1);
    gainExp(22 + S.mainStage * 10);
    giveItem('crystal', 1 + (Math.random() < 0.4 ? 1 : 0));
    logWorld('battle', '击退了一团游荡的残影');
  } else if (fled) {
    /* 残影留在原地，玩家击退几步 */
    var ang = Math.atan2(S.player.y - s.y, S.player.x - s.x);
    S.player.x += Math.cos(ang) * 2; S.player.y += Math.sin(ang) * 2;
  } else {
    shadows.splice(shadows.indexOf(s), 1);
    S.player.hp = 1;
    S.player.money = Math.max(0, S.player.money - 20);
    var home = poiById('home');
    S.player.x = home.x + 1.5; S.player.y = home.y + home.h + 1;
    logWorld('battle', '被残影击倒，恍惚中被送回了公寓（¥-20）');
    toast('你在恍惚中被送回了公寓……（¥-20）');
  }
  refreshUI();
}

/* ================= 时间推进（与现实时钟 1:1 同步） ================= */
function advanceTime(dt) {
  /* 游戏时间直接采用本地现实时间：现实 1 秒 = 游戏 1 秒 */
  var now = new Date();
  S.timeMin = now.getHours() * 60 + now.getMinutes() + now.getSeconds() / 60;
  /* 天数以首次同步时的存档天数为锚点，按现实每 24 小时推进一天 */
  if (!S.realAnchor) { S.realAnchor = Date.now(); S.anchorDay = S.day; }
  var nd = S.anchorDay + Math.floor((Date.now() - S.realAnchor) / 86400000);
  if (nd > S.day) {
    S.day = nd;
    logWorld('day', '第 ' + S.day + ' 天开始了');
    toast('第 ' + S.day + ' 天开始了');
    pulseExpireCheck(S.day);
    /* 城市自己生长：新的一天有几率冒出新的动态（冷却 10 分钟真实时间） */
    if (S.mainStage >= 1 && S.day > pulseGenDay && Date.now() - pulseLastGenAt > 10 * 60 * 1000) {
      pulseGenDay = S.day;
      triggerPulseGen('', false, null);
    }
  }
  rollWeather();
}

/* ================= 自定义地点（后端持久化） ================= */
function _carvePlace(p) {
  /* build：落地为建筑 tile；mark：只放地标不改地形 */
  var kind = p.kind || p.type;
  if (kind !== 'build') return;
  var x, y;
  for (y = p.y; y < p.y + (p.h || 2); y++)
    for (x = p.x; x < p.x + (p.w || 2); x++)
      if (inMap(x, y)) biomeMap[idx(x, y)] = B.BUILD;
  /* 门口一行不堵 */
  for (x = p.x - 1; x <= p.x + (p.w || 2); x++) {
    if (inMap(x, p.y + (p.h || 2)) && biomeMap[idx(x, p.y + (p.h || 2))] === B.BUILD)
      biomeMap[idx(x, p.y + (p.h || 2))] = B.ROAD;
  }
}
function _clearChunks() {
  chunks = {}; chunkOrder = [];
  if (ext3d) ext3d.markTerrainDirty();
}

function applyCustomPlace(p, silent) {
  if (!p || !p.id) return;
  for (var i = 0; i < D.POIS.length; i++) if (D.POIS[i].id === p.id) return;
  D.POIS.push({
    id: p.id, name: p.name, x: p.x, y: p.y, w: p.w || 2, h: p.h || 2,
    type: p.kind === 'mark' ? 'mark' : 'build', icon: p.icon || '📍',
    color: '#9333ea', custom: true, img: p.img, desc: p.desc, comment: p.comment
  });
  if (biomeMap) { _carvePlace(p); _clearChunks(); }
  if (!silent) logWorld('place', '「' + (p.name || '新的角落') + '」出现在了恋语市');
}
function removeCustomPlace(id) {
  var kept = [], had = false, name = id;
  for (var i = 0; i < D.POIS.length; i++) {
    if (D.POIS[i].id === id) { had = true; name = D.POIS[i].name || id; continue; }
    kept.push(D.POIS[i]);
  }
  if (!had) return;
  logWorld('place', '「' + name + '」从城市中消失了');
  D.POIS.length = 0;
  Array.prototype.push.apply(D.POIS, kept);
  /* 地形确定性生成 → 重建后重放剩余自定义地点与地形编辑 */
  generateWorld();
  for (i = 0; i < D.POIS.length; i++) if (D.POIS[i].custom) _carvePlace(D.POIS[i]);
  if (Object.keys(worldEditIdx).length) replayEdits();
  _clearChunks();
}
function loadCustomPlaces() {
  try {
    fetch('/api/world/places').then(function (r) { return r.json(); }).then(function (d) {
      var list = (d && d.places) || [];
      var applied = false;
      for (var i = 0; i < list.length; i++) {
        var before = D.POIS.length;
        applyCustomPlace(list[i], true);
        if (D.POIS.length > before) applied = true;
      }
      if (applied) { _clearChunks(); toast('📍 自定义地点已同步（' + list.length + ' 处）'); }
    }).catch(function () {});
  } catch (e) {}
}

/* ================= 世界扩建：地形改造（建造模式） ================= */
var worldEditIdx = {};   // "x,y" -> {b?,d?} 已应用编辑
var editQueue = {};      // 待上传编辑
var editFlushIn = 0;     // 距下次冲刷秒数（0=无待传）

function clearChunkAt(x, y) {
  var key = Math.floor(x / D.CHUNK) + '_' + Math.floor(y / D.CHUNK);
  if (chunks[key]) {
    delete chunks[key];
    chunkOrder = chunkOrder.filter(function (k) { return k !== key; });
  }
}
function applyTileEdit(e, record) {
  if (!inMap(e.x, e.y)) return;
  var i = idx(e.x, e.y);
  if (e.b !== undefined && e.b !== null) biomeMap[i] = e.b;
  if (e.d !== undefined && e.d !== null) decorMap[i] = e.d;
  if (record) {
    var key = e.x + ',' + e.y;
    var cur = worldEditIdx[key] || {};
    var rec = {};
    if (e.b !== undefined && e.b !== null) rec.b = e.b;
    else if (cur.b !== undefined) rec.b = cur.b;
    if (e.d !== undefined && e.d !== null) rec.d = e.d;
    else if (cur.d !== undefined) rec.d = cur.d;
    worldEditIdx[key] = rec;
  }
  clearChunkAt(e.x, e.y);
  if (ext3d) ext3d.tileChanged(e.x, e.y);
}
function replayEdits() {
  for (var key in worldEditIdx) {
    var p = key.split(',');
    applyTileEdit({ x: +p[0], y: +p[1], b: worldEditIdx[key].b, d: worldEditIdx[key].d }, false);
  }
  _clearChunks();
}
function loadWorldEdits() {
  try {
    fetch('/api/world/edits').then(function (r) { return r.json(); }).then(function (d) {
      var list = (d && d.edits) || [];
      for (var i = 0; i < list.length; i++) {
        var e = list[i];
        worldEditIdx[e.x + ',' + e.y] = {
          b: e.b === undefined ? undefined : e.b,
          d: e.d === undefined ? undefined : e.d
        };
        applyTileEdit(e, false);
      }
      if (list.length) _clearChunks();
      unstickPlayer();
    }).catch(function () {});
  } catch (e) {}
}
/* 玩家被实体地形围死时自动挪到最近可通行格（旧档/地形变更兜底） */
function unstickPlayer() {
  if (!S || !biomeMap) return;
  var p = S.player, cx = Math.floor(p.x), cy = Math.floor(p.y);
  /* 中心格实体 或 上下左右四邻格全实体 → 完全无路可走 */
  if (!isSolid(cx, cy)) {
    if (!isSolid(cx, cy - 1) || !isSolid(cx, cy + 1) || !isSolid(cx - 1, cy) || !isSolid(cx + 1, cy)) return;
  }
  var w = findWalkableNear(p.x, p.y);
  p.x = w.x + 0.5; p.y = w.y + 0.5;
  toast('你从被困的地形中挪了出来');
  saveGame();
}
function resetWorldEdits() {
  worldEditIdx = {}; editQueue = {}; editFlushIn = 0;
  generateWorld();
  for (var i = 0; i < D.POIS.length; i++) if (D.POIS[i].custom) _carvePlace(D.POIS[i]);
  _clearChunks();
}
function flushEditsNow(useBeacon) {
  var keys = Object.keys(editQueue);
  if (!keys.length) { editFlushIn = 0; return; }
  var tiles = [];
  for (var i = 0; i < keys.length; i++) {
    var p = keys[i].split(','), q = editQueue[keys[i]];
    var t = { x: +p[0], y: +p[1] };
    if (q.b !== undefined) t.b = q.b;
    if (q.d !== undefined) t.d = q.d;
    tiles.push(t);
  }
  editQueue = {}; editFlushIn = 0;
  var body = JSON.stringify({ tiles: tiles });
  try {
    if (useBeacon && navigator.sendBeacon) {
      navigator.sendBeacon('/api/world/edits', new Blob([body], { type: 'application/json' }));
    } else {
      fetch('/api/world/edits', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: body
      }).catch(function () {});
    }
  } catch (e) {}
}
function tickEditQueue(dt) {
  if (!editFlushIn) return;
  editFlushIn -= dt;
  if (editFlushIn <= 0 || Object.keys(editQueue).length >= 40) flushEditsNow(false);
}

/* ---- 笔刷 ---- */
var BUILD_BRUSHES = {
  grass:   { icon: '🌿', name: '草坪',   b: B.GRASS,  clearDecor: true },
  road:    { icon: '🛤️', name: '道路',   b: B.ROAD,   clearDecor: true },
  plaza:   { icon: '⬜', name: '广场砖', b: B.PLAZA,  clearDecor: true },
  field:   { icon: '🌾', name: '田野',   b: B.FIELD,  clearDecor: true },
  sand:    { icon: '🏖️', name: '沙滩',   b: B.SAND,   clearDecor: true },
  forest:  { icon: '🌲', name: '林地',   b: B.FOREST, clearDecor: true },
  water:   { icon: '💧', name: '水面',   b: B.WATER,  clearDecor: true, solid: true },
  wall:    { icon: '🧱', name: '建筑',   b: B.BUILD,  clearDecor: true, solid: true },
  tree:    { icon: '🌳', name: '种树',   d: 1 },
  lamp:    { icon: '💡', name: '路灯',   d: 2 },
  flower:  { icon: '🌼', name: '花丛',   d: 3 },
  clearD:  { icon: '🧹', name: '清装饰', d: 0 },
  restore: { icon: '🧽', name: '复原',   restore: true }
};
var buildMode = { on: false, brush: 'grass', size: 1, painted: 0 };
var brushCursor = null;   // 鼠标悬停 tile（渲染笔刷预览框）

var BUILD_DONE_LINES = [
  '许墨看着你的作品：「城市规划的雏形。要不要考虑辅修一门设计课？」',
  '许墨远远看了一会儿：「你改造的这片地方，光照角度变好了。是巧合吗？」',
  '许墨：「蝴蝶会选择自己喜欢的花园——你建的这个，大概会被选中。」',
  '许墨：「地图更新了。不过我私人的那一份，早就以你为原点了。」'
];

function setBuildMode(on, brush, size) {
  var wasOn = buildMode.on;
  if (brush) buildMode.brush = brush;
  if (size) buildMode.size = size;
  buildMode.on = !!on;
  if (buildMode.on) {
    buildMode.painted = 0;
  } else if (wasOn) {
    flushEditsNow(false);   // 退出建造立即上传，不依赖 rAF
    if (buildMode.painted > 0) {
      logWorld('build', '用「' + BUILD_BRUSHES[buildMode.brush].name + '」改造了 ' + buildMode.painted + ' 格城市');
    }
    if (buildMode.painted >= 12) {
      toast(BUILD_DONE_LINES[Math.floor(Math.random() * BUILD_DONE_LINES.length)]);
      callAffinity('world', '亲手扩建了恋语市');
    }
  }
  if (!buildMode.on) brushCursor = null;
  if (ui.buildBar) ui.buildBar(buildMode, BUILD_BRUSHES[buildMode.brush]);
}
function paintTile(wx, wy) {
  var br = BUILD_BRUSHES[buildMode.brush];
  if (!br || !inMap(wx, wy)) return false;
  var p = S.player;
  /* 实体笔刷禁止涂在玩家近旁（防围死） */
  if (br.solid && Math.hypot(wx + 0.5 - p.x, wy + 0.5 - p.y) < 2.2) return false;
  var i = idx(wx, wy);
  var isRestore = !!br.restore;
  var e;
  if (isRestore) {
    e = { x: wx, y: wy, b: baseBiome[i], d: baseDecor[i] };
  } else if (br.b !== undefined) {
    e = { x: wx, y: wy, b: br.b, d: br.clearDecor ? 0 : decorMap[i] };
  } else {
    if (SOLID[biomeMap[i]]) return false;   // 装饰不能放在实体上
    e = { x: wx, y: wy, d: br.d };
  }
  /* 无变化不记账不扣费 */
  var nb = (e.b !== undefined && e.b !== null) ? e.b : biomeMap[i];
  var nd = (e.d !== undefined && e.d !== null) ? e.d : decorMap[i];
  if (biomeMap[i] === nb && decorMap[i] === nd) return false;
  if (!isRestore) {
    if (S.player.money < 5 || p.sp < 2) { toast('💰 建造需 ¥5 + 体力2（余额或体力不足）'); return false; }
    S.player.money -= 5;
    p.sp = Math.max(0, p.sp - 2);
    buildMode.painted++;
  }
  applyTileEdit(e, true);
  editQueue[wx + ',' + wy] = worldEditIdx[wx + ',' + wy];
  if (!editFlushIn) editFlushIn = 8;
  refreshUI();
  return true;
}
function screenToTile(cx, cy) {
  if (!cv) return null;
  /* 3D 模式：射线拾取地面平面 */
  if (renderMode === '3d' && ext3d) return ext3d.screenToTile(cx, cy);
  try {
    var rect = cv.getBoundingClientRect();
    var px = cx - rect.left, py = cy - rect.top;
    if (px < 0 || py < 0 || px > rect.width || py > rect.height) return null;
    return { x: Math.floor((px - offX) / TILE), y: Math.floor((py - offY) / TILE) };
  } catch (e) { return null; }
}
function paintScreen(cx, cy) {
  if (!buildMode.on) return 0;
  var t = screenToTile(cx, cy);
  if (!t) return 0;
  var r = buildMode.size, r0 = Math.floor((r - 1) / 2), n = 0;
  for (var dy = 0; dy < r; dy++)
    for (var dx = 0; dx < r; dx++)
      if (paintTile(t.x + r0 + dx, t.y + r0 + dy)) n++;
  if (n && ui.buildBar) ui.buildBar(buildMode, BUILD_BRUSHES[buildMode.brush]);
  return n;
}
function setBrushCursor(cx, cy) {
  brushCursor = (cx == null) ? null : screenToTile(cx, cy);
  if (ext3d) ext3d.setBrushCursorTile(brushCursor);
}

/* ================= 世界扩建：自定义居民 ================= */
function customNpcDialog(def) {
  return function (G) {
    var key = 'cnpc_i_' + def.id;
    var cnt = G.count(key);
    /* 初次见面：以人设 desc 作为开场白 */
    if (!cnt && def.desc) {
      return {
        text: def.desc,
        options: [
          { t: '（继续聊）', next: function () { G.incr(key); G.addAff(def.id, 1); return customNpcDialog(def)(G); } },
          { t: '（告辞）', eff: function () { G.incr(key); G.addAff(def.id, 1); } }
        ]
      };
    }
    var n = def.lines.length;
    var i = Math.min(n - 1, cnt % n);
    return {
      text: def.lines[i],
      options: [
        { t: '（继续聊）', next: function () { G.incr(key); G.addAff(def.id, 1); return customNpcDialog(def)(G); } },
        { t: '（告辞）', eff: function () { G.incr(key); G.addAff(def.id, 1); } }
      ]
    };
  };
}
function applyCustomNpc(n, silent) {
  if (!n || !n.id) return;
  for (var i = 0; i < D.NPCS.length; i++) if (D.NPCS[i].id === n.id) return;
  var def = {
    id: n.id, name: n.name, emoji: n.emoji || '🙂', color: n.color || '#8b5cf6',
    speed: 2.0, wander: 2, custom: true,
    anchor: { x: n.x + 0.5, y: n.y + 1.2 },
    lines: (n.lines && n.lines.length) ? n.lines : ['……'],
    desc: n.desc || '',
    mood: { morning: '自在', noon: '闲适', evening: '放松', night: '安静' }
  };
  def.dialog = customNpcDialog(def);
  D.NPCS.push(def);
  var e = {
    def: def, x: def.anchor.x, y: def.anchor.y, tx: def.anchor.x, ty: def.anchor.y,
    wx: def.anchor.x, wy: def.anchor.y, state: 'idle', wob: Math.random() * 10
  };
  npcs.push(e); npcV[def.id] = e;
  if (!silent) logWorld('npc', (n.name || '一位新朋友') + ' 住进了恋语市');
}
function removeCustomNpc(id) {
  var kept = [];
  var name = id;
  for (var i = 0; i < D.NPCS.length; i++) { if (D.NPCS[i].id === id) name = D.NPCS[i].name; if (D.NPCS[i].id !== id) kept.push(D.NPCS[i]); }
  D.NPCS.length = 0;
  Array.prototype.push.apply(D.NPCS, kept);
  npcs = npcs.filter(function (e) { return e.def.id !== id; });
  delete npcV[id];
  logWorld('npc', '送别了 ' + name);
}
function loadCustomNpcs() {
  try {
    fetch('/api/world/npcs').then(function (r) { return r.json(); }).then(function (d) {
      var list = (d && d.npcs) || [];
      for (var i = 0; i < list.length; i++) applyCustomNpc(list[i], true);
      if (list.length) toast('🧑 自定义居民已同步（' + list.length + ' 位）');
    }).catch(function () {});
  } catch (e) {}
}

/* ================= 世界脉搏（智能生成 · 城市动态） ================= */
var pulseEvents = [];    // 活跃事件 [{ev, poi}]
var pulseRumors = [];    // 城市传闻
var pulseVisitorIds = [];// 来客实体 id
var pulseLastGenAt = 0;  // 上次生成（真实 ms）
var pulseGenDay = 0;     // 上次自动生成的游戏日
var pulseVitality = 20;        // 城市活力 0-100
var pulseVitalityLevel = '';   // 活力等级名
var pulseVitalityLv = 0;       // 活力档位（0-3），跨档提示用
var pulseLocate = null;        // 定位信标 {x,y,label,until}
var PULSE_GIFT_ITEMS = ['bento', 'coffee', 'bread'];   // 可送来客的礼物

function applyPulseVitality(v, level) {
  var oldLv = pulseVitalityLv;
  var first = pulseVitalityLevel === '';
  pulseVitality = Math.max(0, Math.min(100, v));
  pulseVitalityLevel = level || '';
  pulseVitalityLv = pulseVitality >= 75 ? 3 : pulseVitality >= 50 ? 2 : pulseVitality >= 25 ? 1 : 0;
  if (!first && pulseVitalityLv > oldLv && pulseVitalityLevel) {
    toast('🌆 城市活力提升——恋语市已是「' + pulseVitalityLevel + '」');
  }
}
function pulseRarityColor(r) {
  if (r === 'epic') return 'hsl(' + ((performance.now() / 12) % 360) + ',90%,62%)';
  if (r === 'rare') return '#a855f7';
  return '#f59e0b';
}
function pulseRarityStars(r) { return r === 'epic' ? '★★★' : r === 'rare' ? '★★' : '★'; }

function findWalkableNear(x, y) {
  x = clamp(Math.round(x), 3, MW - 4); y = clamp(Math.round(y), 3, MH - 4);
  if (!isSolid(x, y)) return { x: x, y: y };
  for (var r = 1; r <= 14; r++) {
    for (var dy = -r; dy <= r; dy++) {
      for (var dx = -r; dx <= r; dx++) {
        if (Math.abs(dx) !== r && Math.abs(dy) !== r) continue;
        var nx = x + dx, ny = y + dy;
        if (inMap(nx, ny) && !isSolid(nx, ny)) return { x: nx, y: ny };
      }
    }
  }
  return { x: x, y: y };
}

function applyPulseEvent(ev) {
  if (!ev || !ev.id) return false;
  for (var i = 0; i < pulseEvents.length; i++) if (pulseEvents[i].ev.id === ev.id) return false;
  var pos = findWalkableNear(ev.x, ev.y);
  var poi = {
    id: ev.id, name: ev.title, x: pos.x, y: pos.y, w: 1, h: 1,
    type: 'mark', icon: ev.emoji || '✨', color: '#f59e0b', pulseEv: true
  };
  D.POIS.push(poi);
  ev.x = pos.x; ev.y = pos.y;
  pulseEvents.push({ ev: ev, poi: poi });
  return true;
}
function removePulseEvent(id) {
  pulseEvents = pulseEvents.filter(function (p) { return p.ev.id !== id; });
  var kept = D.POIS.filter(function (p) { return p.id !== id; });
  D.POIS.length = 0;
  Array.prototype.push.apply(D.POIS, kept);
}
function applyPulseVisitor(v) {
  if (!v || !v.id || npcV[v.id]) return false;
  var def = {
    id: v.id, name: v.name, emoji: v.emoji || '🧳', color: v.color || '#f59e0b',
    speed: 1.8, wander: 3, pulseV: true, expireDay: v.expire_day || 0,
    gifted: v.gifted ? 1 : 0,
    anchor: null,
    lines: (v.lines && v.lines.length) ? v.lines : ['……'],
    mood: { morning: '新奇', noon: '健谈', evening: '感伤', night: '安静' }
  };
  def.dialog = pulseVisitorDialog(def);
  D.NPCS.push(def);
  var pos = findWalkableNear(v.x, v.y);
  def.anchor = { x: pos.x + 0.5, y: pos.y + 1.2 };
  var e = {
    def: def, x: def.anchor.x, y: def.anchor.y, tx: def.anchor.x, ty: def.anchor.y,
    wx: def.anchor.x, wy: def.anchor.y, state: 'idle', wob: Math.random() * 10
  };
  npcs.push(e); npcV[v.id] = e;
  pulseVisitorIds.push(v.id);
  return true;
}
/* 来客对话：常规闲聊 + 送礼分支 */
function pulseVisitorDialog(def) {
  return function (G) {
    var node = customNpcDialog(def)(G);
    if (node && node.options && !def.gifted) {
      var hasGift = false;
      for (var i = 0; i < PULSE_GIFT_ITEMS.length; i++) if (hasItem(PULSE_GIFT_ITEMS[i])) { hasGift = true; break; }
      if (hasGift) {
        node.options = node.options.slice();
        node.options.splice(node.options.length - 1, 0, { t: '🎁 送件小礼物', next: function () { return visitorGiftNode(def); } });
      }
    }
    return node;
  };
}
function visitorGiftNode(def) {
  var give = null;
  for (var i = 0; i < PULSE_GIFT_ITEMS.length; i++) if (hasItem(PULSE_GIFT_ITEMS[i])) { give = PULSE_GIFT_ITEMS[i]; break; }
  if (!give) return { text: '（你翻遍了口袋，没找到合适的礼物。）', options: [{ t: '（下次再送吧）' }] };
  var itemName = (D.ITEMS[give] && D.ITEMS[give].name) || give;
  takeItem(give, 1);
  def.gifted = 1;
  logWorld('gift', '把' + itemName + '送给了来客 ' + def.name);
  refreshUI();
  fetch('/api/world/pulse/visitor/' + def.id + '/gift', { method: 'POST' })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.error) { toast(d.error); return; }
      var got = [];
      if (d.gift) {
        if (d.gift.money) { S.player.money += d.gift.money; got.push('¥' + d.gift.money); }
        if (d.gift.item && D.ITEMS[d.gift.item] && d.gift.qty > 0) {
          giveItem(d.gift.item, d.gift.qty);
          got.push((D.ITEMS[d.gift.item].name || d.gift.item) + '×' + d.gift.qty);
        }
      }
      if (typeof d.vitality === 'number') applyPulseVitality(d.vitality, d.vitality_level);
      if (d.affinity && d.affinity.delta) toast('💗 心动 +' + d.affinity.delta);
      if (got.length) toast('🎁 回礼：' + got.join(' · '));
      refreshUI();
    }).catch(function () { toast('礼物送出去了，但城市没响应…'); });
  return {
    text: '你把' + itemName + '递了过去。\n' + def.name + '愣了一下，眼睛亮起来，转身从行囊里取出一样东西，郑重地塞进你手里——',
    options: [{ t: '（收下回礼）' }]
  };
}
function pulseExpireCheck(day) {
  var evGone = 0, viGone = [];
  for (var i = pulseEvents.length - 1; i >= 0; i--) {
    if (day > (pulseEvents[i].ev.expire_day || day)) { evGone++; removePulseEvent(pulseEvents[i].ev.id); }
  }
  for (var j = pulseVisitorIds.length - 1; j >= 0; j--) {
    var id = pulseVisitorIds[j], ent = npcV[id];
    if (ent && day > (ent.def.expireDay || day)) {
      viGone.push(ent.def.name);
      removeCustomNpc(id);
      pulseVisitorIds.splice(j, 1);
    }
  }
  if (evGone && viGone.length) toast('🌫️ ' + evGone + ' 段城市故事落幕，' + viGone.join('、') + '踏上了新的旅程');
  else if (evGone) toast('🌫️ ' + evGone + ' 段城市故事悄然落幕了');
  else if (viGone.length) toast('🧳 ' + viGone.join('、') + ' 离开了恋语市，愿 TA 旅途平安');
}
function loadWorldPulse() {
  try {
    fetch('/api/world/pulse?day=' + (S ? S.day : 1)).then(function (r) { return r.json(); }).then(function (d) {
      pulseRumors = (d && d.rumors) || [];
      var evs = (d && d.events) || [], n = 0;
      for (var i = 0; i < evs.length; i++) if (applyPulseEvent(evs[i])) n++;
      var vs = (d && d.visitors) || [], m = 0;
      for (var j = 0; j < vs.length; j++) if (applyPulseVisitor(vs[j])) m++;
      if (typeof d.vitality === 'number') applyPulseVitality(d.vitality, d.vitality_level);
      if (n + m > 0) toast('📡 城市脉搏已同步（事件 ' + n + ' · 来客 ' + m + '）');
    }).catch(function () {});
  } catch (e) {}
}
function triggerPulseGen(seed, withPlace, cb) {
  var body = {
    day: S.day, hour: gameHour(), weather: S.weather, main_stage: S.mainStage,
    places: D.POIS.filter(function (p) { return p.custom; }).map(function (p) { return p.name; }).slice(-10),
    last_titles: pulseEvents.map(function (p) { return p.ev.title + '（' + (p.ev.type_name || '') + '）'; }).slice(-8),
    seed: seed || '', with_place: !!withPlace
  };
  fetch('/api/world/pulse/generate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.error) { toast(d.error); if (cb) cb(null, d.retry_after); return; }
    pulseLastGenAt = Date.now(); pulseGenDay = S.day;
    var news = { event: null, rumors: [], visitor: null, place: null };
    if (d.event && applyPulseEvent(d.event)) news.event = d.event;
    if (d.rumors && d.rumors.length) {
      pulseRumors = d.rumors.concat(pulseRumors).slice(0, 30);
      news.rumors = d.rumors;
    }
    if (d.visitor && applyPulseVisitor(d.visitor)) news.visitor = d.visitor;
    if (d.place) { applyCustomPlace(d.place); news.place = d.place; }
    if (typeof d.vitality === 'number') applyPulseVitality(d.vitality, d.vitality_level);
    callAffinity('world_pulse', '脉搏 ' + Date.now());
    if (d.affinity && d.affinity.delta) toast('💗 心动 +' + d.affinity.delta);
    if (ui.pulseNews) ui.pulseNews(news);
    refreshUI();
    if (cb) cb(news);
  }).catch(function () {
    toast('城市脉搏生成失败，请稍后再试');
    if (cb) cb(null);
  });
}
/* 传闻求证：请许墨出一份求证报告 */
function verifyPulseRumor(id, cb) {
  fetch('/api/world/pulse/rumor/' + id + '/verify', { method: 'POST' })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.error) { toast(d.error); if (cb) cb(null); return; }
      for (var i = 0; i < pulseRumors.length; i++) {
        if (pulseRumors[i].id === id) {
          pulseRumors[i].verify = d.verify;
          logWorld('rumor', '求证传闻「' + (pulseRumors[i].title || id) + '」：' + ((d.verify && d.verify.verdict_name) || '有了答案'));
          break;
        }
      }
      if (typeof d.vitality === 'number') applyPulseVitality(d.vitality, d.vitality_level);
      if (d.affinity && d.affinity.delta) toast('💗 心动 +' + d.affinity.delta);
      if (cb) cb(d.verify);
    }).catch(function () { toast('求证失败了，稍后再试'); if (cb) cb(null); });
}
/* 定位一个城市动态（来客/事件）：临时信标 60 秒 */
function locatePulseTarget(x, y, label) {
  pulseLocate = { x: x, y: y, label: label || '', until: Date.now() + 60000 };
  toast('🧭 已标记：「' + (label || '城市动态') + '」，跟着屏幕指示走');
}
function completePulseEvent(id, choiceIdx) {
  var item = null;
  for (var i = 0; i < pulseEvents.length; i++) if (pulseEvents[i].ev.id === id) { item = pulseEvents[i]; break; }
  if (!item) return null;
  var ev = item.ev, rw = ev.reward || {}, got = [];
  var ch = null;
  if (ev.choices && ev.choices.length && choiceIdx != null) {
    ch = ev.choices[Math.max(0, Math.min(ev.choices.length - 1, choiceIdx))];
  }
  var money = Math.max(0, (rw.money || 0) + (ch ? (ch.money_delta || 0) : 0));
  var exp = Math.max(0, (rw.exp || 0) + (ch ? (ch.exp_delta || 0) : 0));
  if (money) { S.player.money += money; got.push('¥' + money); }
  if (exp) { gainExp(exp); got.push(exp + ' 经验'); }
  if (rw.item && D.ITEMS[rw.item] && rw.qty > 0) {
    giveItem(rw.item, rw.qty);
    got.push((D.ITEMS[rw.item].name || rw.item) + '×' + rw.qty);
  }
  removePulseEvent(id);
  logWorld('pulse', '参与城市事件「' + (ev.title || ev.id) + '」' + (ch ? '，选择了「' + ch.label + '」' : ''));
  callAffinity('world_event', '事件 ' + id);
  refreshUI();
  try {
    fetch('/api/world/pulse/event/' + id + '/done', { method: 'POST' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && typeof d.vitality === 'number') applyPulseVitality(d.vitality, d.vitality_level);
      }).catch(function () {});
  } catch (e) {}
  return {
    got: got,
    label: ch ? ch.label : '',
    outcome: ch ? ch.outcome : (ev.story || ''),
    comment: ch ? (ch.comment || ev.comment || '') : (ev.comment || '')
  };
}

/* ================= 世界编年史（记录 · 持久化到后端，供「许墨的记忆」取材） ================= */
var logQueue = [];       // 待上报记录
var logFailed = [];      // 上报失败待重试（指数退避）
var logFlushIn = 4;      // 距下次上报秒数
var logRetryIn = 0;      // 距下次重试秒数
var logRetryBackoff = 5; // 重试退避倍数
var lastTalkLog = {};    // npc id -> absMin()（同一人 30 分钟内只记一次交谈）

/* 前端轻量去重窗口：避免循环触发同一条记录（如多帧调用） */
function _logQueueKey(it) {
  return it.day + '|' + it.time + '|' + it.type + '|' + String(it.text).slice(0, 60);
}
function logWorld(type, text) {
  if (!S || !text) return;
  try {
    var rec = {
      day: S.day, time: Math.round(S.timeMin), type: type,
      text: String(text).slice(0, 110),
      x: Math.round(S.player.x), y: Math.round(S.player.y)
    };
    /* 入队前对最近 8 条做去重 */
    var key = _logQueueKey(rec);
    for (var i = logQueue.length - 1; i >= 0 && i >= logQueue.length - 8; i--) {
      if (_logQueueKey(logQueue[i]) === key) return;
    }
    logQueue.push(rec);
    if (logQueue.length >= 20) _flushWorldLog(false);
  } catch (e) {}
}
function _flushWorldLog(useBeacon) {
  if (!logQueue.length) return;
  var batch = logQueue.splice(0, 40);
  var body = JSON.stringify({ entries: batch });
  try {
    if (useBeacon && navigator.sendBeacon) {
      navigator.sendBeacon('/api/world/log', new Blob([body], { type: 'application/json' }));
    } else {
      fetch('/api/world/log', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body, keepalive: true })
        .then(function (r) {
          /* 上报成功：清退避 */
          logRetryBackoff = 5;
          if (logFailed.length) {
            /* 把失败队列里没重复的塞回主队列 */
            var recovered = logFailed.splice(0);
            recovered.forEach(function (it) {
              if (!logQueue.some(function (q) { return _logQueueKey(q) === _logQueueKey(it); })) logQueue.push(it);
            });
          }
        })
        .catch(function () {
          /* 失败：把批次塞回失败队列，启用退避重试 */
          logFailed = logFailed.concat(batch);
          if (logFailed.length > 200) logFailed = logFailed.slice(-200);
          logRetryIn = logRetryBackoff;
          logRetryBackoff = Math.min(logRetryBackoff * 2, 120);
        });
    }
  } catch (e) {}
}
function tickLogQueue(dt) {
  logFlushIn -= dt;
  if (logFlushIn <= 0) { logFlushIn = 15; _flushWorldLog(false); }
  if (logFailed.length && logRetryIn > 0) {
    logRetryIn -= dt;
    if (logRetryIn <= 0) {
      /* 重试失败队列 */
      var retry = logFailed.splice(0, 40);
      logQueue = retry.concat(logQueue);
      _flushWorldLog(false);
    }
  }
}

/* ================= 交互系统 ================= */
var _interactCache = { t: 0, x: -999, y: -999, v: null };
function getInteractTarget() {
  /* 每帧全量扫描（NPC+碎片+宝箱+POI 约百项）并拼接 label 字符串开销不小，
     节流为：100ms 内且玩家位移 < 0.2 tile 时直接复用上次结果 */
  var now = performance.now();
  var pl = S.player;
  if (_interactCache.v !== null || _interactCache.t) {
    if (now - _interactCache.t < 100 &&
        Math.abs(pl.x - _interactCache.x) < 0.2 &&
        Math.abs(pl.y - _interactCache.y) < 0.2) {
      return _interactCache.v;
    }
  }
  var r = _computeInteractTarget();
  _interactCache.t = now; _interactCache.x = pl.x; _interactCache.y = pl.y;
  _interactCache.v = r;
  return r;
}
function _computeInteractTarget() {
  var p = S.player, best = null, bestD = 1.8;
  /* NPC */
  for (var i = 0; i < npcs.length; i++) {
    var e = npcs[i];
    var d = Math.hypot(e.x - p.x, e.y - p.y);
    if (d < bestD) { bestD = d; best = { kind: 'npc', e: e, label: '和 ' + e.def.name + ' 交谈' }; }
  }
  /* 记忆碎片 */
  for (i = 0; i < SHARDS.length; i++) {
    var sh = SHARDS[i];
    if (S.counters['shardTaken_' + i]) continue;
    if (S.mainStage < 1) continue;
    d = Math.hypot(sh.x + 0.5 - p.x, sh.y + 0.5 - p.y);
    if (d < bestD) { bestD = d; best = { kind: 'shard', i: i, label: '拾取 记忆碎片' }; }
  }
  /* 讲义 */
  for (i = 0; i < PAGES.length; i++) {
    var pg = PAGES[i];
    if (S.counters['pageTaken_' + i]) continue;
    var s2 = S.sides['s2'];
    if (!s2 || s2.state !== 1) continue;
    d = Math.hypot(pg.x + 0.5 - p.x, pg.y + 0.5 - p.y);
    if (d < bestD) { bestD = d; best = { kind: 'page', i: i, label: '捡起 讲义散页' }; }
  }
  /* 拍照点 */
  for (i = 0; i < PHOTOS.length; i++) {
    var ph = PHOTOS[i];
    if (S.flags['photo_' + ph.id]) continue;
    var s4 = S.sides['s4'];
    if (!s4 || s4.state !== 1 || !hasItem('camera')) continue;
    var hh = gameHour();
    if (hh < 17 && hh >= 4) continue;    /* 黄昏以后才能拍 */
    d = Math.hypot(ph.x + 0.5 - p.x, ph.y + 0.5 - p.y);
    if (d < bestD) { bestD = d; best = { kind: 'photo', ph: ph, label: '拍摄 ' + ph.name }; };
  }
  /* 资源节点 */
  for (i = 0; i < nodes.length; i++) {
    var nd = nodes[i];
    var def = D.NODE_TYPES[nd.type];
    if (!nodeAvailable(nd)) continue;
    d = Math.hypot(nd.x + 0.5 - p.x, nd.y + 0.5 - p.y);
    if (d < bestD) { bestD = d; best = { kind: 'node', n: nd, label: def.label.startsWith('采集') ? def.label : '采集 ' + def.label }; }
  }
  /* 宝箱 */
  for (i = 0; i < CHESTS.length; i++) {
    var ch = CHESTS[i];
    if (S.chests[ch.id]) continue;
    if (ch.id === 'c_clock' && !S.worldFlags.clock_open) continue;
    if (ch.id === 'c_dark' && !S.worldFlags.dark_open) continue;
    if (ch.id === 'c_roof' && !S.worldFlags.roof_open) continue;
    if (ch.id === 'c_temple' && !S.worldFlags.temple_open) continue;
    d = Math.hypot(ch.x + 0.5 - p.x, ch.y + 0.5 - p.y);
    if (d < bestD) { bestD = d; best = { kind: 'chest', c: ch, label: '打开 宝箱' }; }
  }
  /* POI 入口 */
  for (i = 0; i < D.POIS.length; i++) {
    var poi = D.POIS[i];
    var cx = poi.x + (poi.w || 1) / 2, cy = poi.y + (poi.h || 1) + 0.8;
    d = Math.hypot(cx - p.x, cy - p.y);
    if (d > 2.6) continue;
    if (poi.id === 'market') { if (d < bestD + 0.6) { bestD = d; best = { kind: 'shop', label: '进入 日夜超市' }; } }
    else if (poi.id === 'cafe' && S.mainStage === 0) { if (d < bestD + 0.8) { bestD = d; best = { kind: 'cafe0', label: '走进 街角咖啡店' }; } }
    else if (poi.id === 'home') {
      if (d < bestD + 0.6) {
        if (S.mainStage === 5 && !S.ending) { bestD = d; best = { kind: 'finale', label: '回家 · 整理一切' }; }
        else { bestD = d; best = { kind: 'rest', label: '回公寓 休息' }; }
      }
    }
    else if (poi.id === 'library') { if (S.mainStage === 2 && !S.worldFlags.library_open) { if (d < bestD + 0.6) { bestD = d; best = { kind: 'puzzle', id: 'libcode', label: '查看 密格书架' }; } } }
    else if (poi.id === 'clocktower') {
      var s3 = S.sides['s3'];
      if (!S.worldFlags.clock_open && s3 && s3.state >= 2 && d < bestD + 0.6) { bestD = d; best = { kind: 'puzzle', id: 'clockcode', label: '钟楼 密室铜锁' }; }
    }
    else if (poi.id === 'darklab') {
      if (!S.worldFlags.dark_open && S.mainStage === 3 && isNight() && hasItem('keycard') && d < bestD + 0.8) { bestD = d; best = { kind: 'puzzle', id: 'darkdoor', label: '刷卡 · 输入门禁密码' }; }
    }
    else if (poi.id === 'lighthouse') {
      if (S.worldFlags.lighthouse_lit && !S.worldFlags.tower_open && S.mainStage >= 4 && d < bestD + 1) { bestD = d; best = { kind: 'puzzle', id: 'lever', label: '灯塔 机关' }; }
      else if (S.worldFlags.tower_open && !S.flags.core_taken && S.mainStage >= 4 && d < bestD + 1) { bestD = d; best = { kind: 'core', label: '登上塔顶' }; }
    }
    else if (poi.id === 'garden') {
      if (!S.worldFlags.roof_open && d < bestD + 1.4) { bestD = d; best = { kind: 'garden', label: '爬上楼梯（屋顶花园）' }; }
    }
    else if (poi.id === 'temple' || poi.id === 'shrine') {
      if (!S.worldFlags.temple_open && d < bestD + 2.2) { bestD = d; best = { kind: 'puzzle', id: 'stele', label: '查看 星辰石碑' }; }
    }
    else if (poi.custom) {
      if (d < bestD + 0.8) { bestD = d; best = { kind: 'place', p: poi, label: '查看 ' + poi.name }; }
    }
    else if (poi.pulseEv) {
      if (d < bestD + 1) {
        var pev = null;
        for (var k = 0; k < pulseEvents.length; k++) if (pulseEvents[k].poi === poi) { pev = pulseEvents[k].ev; break; }
        if (pev) { bestD = d; best = { kind: 'pulse', ev: pev, label: '参与 ' + pev.title }; }
      }
    }
  }
  return best;
}

function nodeAvailable(nd) {
  var def = D.NODE_TYPES[nd.type];
  if (def.rainOnly && S.weather !== 'rain' && S.weather !== 'storm') return false;
  var h = S.nodes[nd.id];
  if (h === undefined) return true;
  if (def.respawnDays <= 0) return def.rainOnly ? (absMin() - h > 1440 * 0.5) : false;
  return absMin() - h >= def.respawnDays * 1440;
}

var interactTarget = null;

function doInteract() {
  var t = interactTarget;
  if (!t) return;
  var st = calcStats();
  if (t.kind === 'npc') {
    var nid = t.e.def.id;
    if (absMin() - (lastTalkLog[nid] || -1e9) > 30) { lastTalkLog[nid] = absMin(); logWorld('talk', '和 ' + t.e.def.name + ' 交谈'); }
    openDialog(t.e.def); return;
  }
  if (t.kind === 'shard') {
    S.counters['shardTaken_' + t.i] = 1;
    S.counters.shard = (S.counters.shard || 0) + 1;
    giveItem('shard', 1);
    logWorld('shard', '拾起一枚记忆碎片（' + S.counters.shard + '/3）');
    if (S.counters.shard >= 3 && S.mainStage === 1) toast('碎片集齐 3 枚，去找许墨（傍晚在咖啡店）');
    return;
  }
  if (t.kind === 'page') {
    S.counters['pageTaken_' + t.i] = 1;
    S.counters.page = (S.counters.page || 0) + 1;
    giveItem('page', 1);
    logWorld('page', '捡回一页讲义散页（' + S.counters.page + '/3）');
    if (S.counters.page >= 3) toast('讲义集齐 3 页，交还给白教授');
    return;
  }
  if (t.kind === 'photo') {
    S.flags['photo_' + t.ph.id] = 1;
    S.counters.photo = (S.counters.photo || 0) + 1;
    logWorld('photo', '拍下「' + t.ph.name + '」（' + S.counters.photo + '/3）');
    toast('📷 咔嗒——「' + t.ph.name + '」拍摄完成（' + S.counters.photo + '/3）');
    return;
  }
  if (t.kind === 'node') {
    var def = D.NODE_TYPES[t.n.type];
    if (S.player.sp < def.sp) { toast('体力不足，先吃点东西吧'); return; }
    S.player.sp -= def.sp;
    S.nodes[t.n.id] = absMin();
    gainExp(def.exp);
    giveItem(def.item, 1);
    logWorld('gather', (def.label || '采集') + '：获得' + ((D.ITEMS[def.item] && D.ITEMS[def.item].name) || def.item));
    if (def.item === 'dew') { S.counters.dew = (S.counters.dew || 0) + 1; }
    if (def.item === 'iron') { S.counters.iron = (S.counters.iron || 0) + 1; }
    return;
  }
  if (t.kind === 'chest') {
    S.chests[t.c.id] = 1;
    var loot = D.CHEST_LOOT[t.c.id];
    if (loot) {
      for (var i = 0; i < loot.items.length; i++) if (loot.items[i][1] > 0) giveItem(loot.items[i][0], loot.items[i][1]);
      if (loot.money) { S.player.money += loot.money; toast('💰 ¥+' + loot.money); }
      if (loot.exp) gainExp(loot.exp);
    }
    logWorld('chest', '打开了一只宝箱' + (loot && loot.money ? '（¥+' + loot.money + '）' : ''));
    return;
  }
  if (t.kind === 'shop') { openShop(); return; }
  if (t.kind === 'place') { ui.place(t.p); return; }
  if (t.kind === 'pulse') { if (ui.pulseEvent) ui.pulseEvent(t.ev); return; }
  if (t.kind === 'cafe0') { ui.prologue(); return; }
  if (t.kind === 'rest') { openRest(); return; }
  if (t.kind === 'finale') { runFinale(); return; }
  if (t.kind === 'puzzle') { openPuzzle(t.id); return; }
  if (t.kind === 'garden') {
    S.worldFlags.roof_open = 1;
    if (!S.flags.roof_looted) {
      S.flags.roof_looted = 1;
      logWorld('other', '第一次爬上屋顶花园——风里有栀子花的香气');
      toast('你顺着铁梯爬上屋顶——风里有栀子花的香气。');
      giveItem('charm_ginkgo', 1);
      S.player.money += 50;
      gainExp(80);
      toast('💰 ¥+50');
    } else {
      toast('屋顶的风很舒服。远处传来海声。');
    }
    return;
  }
  if (t.kind === 'core') {
    S.flags.core_taken = 1;
    giveItem('core', 1);
    logWorld('quest', '取得「回声核心」，该做出选择了');
    toast('取得「回声核心」。去找许墨，做出你的选择。');
    return;
  }
}

/* 谜题完成回调 */
function onPuzzleSolved(pid) {
  var pz = D.PUZZLES[pid];
  if (!pz) return;
  logWorld('puzzle', '解开了「' + (pz.name || pid) + '」');
  if (pid === 'libcode') {
    S.worldFlags.library_open = 1;
    giveItem('archive', 1);
    giveItem('shoes_wind', 1);
    gainExp(100);
    toast('密格开启：获得「旧档案」。把档案带给阿澈（傍晚在栈桥）。');
  } else if (pid === 'clockcode') {
    S.worldFlags.clock_open = 1;
    toast('铜锁转动——钟楼密室开了。');
  } else if (pid === 'darkdoor') {
    S.worldFlags.dark_open = 1;
    S.flags.dark_entered = 1;
    gainExp(150);
    toast('门开了。蓝光涌出的瞬间，你看清了墙上的字：ECHO · 阶段三。去找许墨。');
    /* 许墨出现在实验室外，等待对峙 */
    var xm = npcV['xumo'];
    var lab = poiById('darklab');
    if (xm) { xm.x = lab.x + lab.w + 1.5; xm.y = lab.y + lab.h * 0.5; }
    S.flags.xumo_pin = { x: lab.x + lab.w + 1.5, y: lab.y + lab.h + 0.8 };
  } else if (pid === 'lever') {
    S.worldFlags.tower_open = 1;
    toast('塔顶的门缓缓打开。');
  } else if (pid === 'stele') {
    S.worldFlags.temple_open = 1;
    gainExp(120);
    toast('石碑依次亮起——神庙的密室显形了。');
  }
  refreshUI();
}

/* 灯塔修复（对话层调用） */
function fixLighthouse() {
  takeItem('lens', 1); takeItem('bulb', 1);
  S.worldFlags.lighthouse_lit = 1;
  gainExp(200);
  toast('🗼 灯塔复明！北岬的光柱扫过海面。塔顶机关可以尝试开启了。');
}

/* 终章 */
function runFinale() {
  var G = makeG();
  var eid = D.judgeEnding(G);
  S.ending = eid;
  S.mainStage = 6;
  logWorld('quest', '旅程抵达结局「' + D.ENDINGS[eid].name + '」');
  if (eid === 'D' || eid === 'A') giveItem('charm_echo', 1);
  callAffinity('world_ending', '达成结局「' + D.ENDINGS[eid].name + '」');
  showEnding(eid);
  saveGame();
}

/* ================= G 接口（对话数据层使用） ================= */
function callAffinity(action, detail) {
  /* world_quest 按章节防重、world_ending 按结局防重；world 每次互动都计 */
  if (action !== 'world') {
    var key = action === 'world_quest' ? action + '|main' + S.mainStage : action + '|' + (detail || '');
    if (S.lucienCalls[key]) return;
    S.lucienCalls[key] = 1;
  }
  var d = detail || '世界·恋语市';
  try {
    fetch('/api/affinity/add', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: action, detail: String(d).slice(0, 60) })
    }).catch(function () {});
  } catch (e) {}
}
function makeG() {
  return {
    mainStage: function () { return S.mainStage; },
    setMain: function (n) { if (n > S.mainStage) { S.mainStage = n; logWorld('quest', '主线推进至第 ' + n + ' 幕'); refreshUI(); saveGame(); } },
    flag: function (k) { return S.flags[k]; },
    setFlag: function (k, v) { S.flags[k] = v; },
    count: function (id) { return S.counters[id] || 0; },
    incr: function (id) { S.counters[id] = (S.counters[id] || 0) + 1; refreshUI(); },
    aff: function (id) { return S.npcAff[id] || 0; },
    addAff: function (id, n) {
      var gain = n;
      if (hasSkill('min1')) gain *= 1.25;
      var st = calcStats();
      if (st.aff) gain *= 1 + st.aff / 100;
      S.npcAff[id] = Math.min(100, (S.npcAff[id] || 0) + Math.round(gain));
      var who = '好感 +' + Math.round(gain);
      for (var i = 0; i < D.NPCS.length; i++) if (D.NPCS[i].id === id) who = D.NPCS[i].name + ' ' + who;
      toast(who);
      refreshUI();
    },
    side: function (id) {
      var s = S.sides[id];
      return s || { state: 0, count: 0 };
    },
    startSide: function (id) { S.sides[id] = { state: 1, count: 0 }; refreshUI(); },
    setSide: function (id, state) { S.sides[id] = { state: state, count: (S.sides[id] || {}).count || 0 }; refreshUI(); },
    has: function (id, q) { return hasItem(id, q); },
    give: function (id, q) { giveItem(id, q); },
    take: function (id, q) { return takeItem(id, q); },
    money: function () { return S.player.money; },
    pay: function (n) { S.player.money = Math.max(0, S.player.money - n); refreshUI(); },
    addMoney: function (n) { S.player.money += n; refreshUI(); },
    gainExp: gainExp,
    toast: toast,
    weather: function () { return S.weather; },
    hour: gameHour,
    isNight: isNight,
    restFull: function () {
      var st = calcStats();
      S.player.hp = st.hpMax; S.player.sp = st.spMax;
      toast('你睡得很沉。状态全满。');
      refreshUI();
    },
    callAffinity: function (action) { callAffinity(action, '世界·恋语市'); },
    explorePct: explorePct,
    fixLighthouse: fixLighthouse
  };
}

/* ================= UI 回调（由 world-ui.js 注册） ================= */
var ui = {
  toast: function (m) { try { console.log('[world]', m); } catch (e) {} },
  refresh: function () {},
  dialog: function (npcDef) {},
  shop: function () {},
  rest: function () {},
  puzzle: function (pid) {},
  ending: function (eid) {},
  battle: function (shadow) {},
  prologue: function () {},
  place: function (poi) {},
  pulseEvent: function (ev) {},
  pulseNews: function (news) {},
  buildBar: function (bm, br) {}
};
function on(ev, fn) { ui[ev] = fn; }
function toast(m) { ui.toast(m); }
function refreshUI() { ui.refresh(); }
function openDialog(def) { ui.dialog(def); }
function openShop() { ui.shop(); }
function openRest() { ui.rest(); }
function openPuzzle(pid) { ui.puzzle(pid); }
function showEnding(eid) { ui.ending(eid); }

var battleShadow = null;
function triggerBattle(s) {
  if (battleShadow) return;
  battleShadow = s;
  ui.battle(s);
}

/* ================= 渲染 ================= */
function getChunk(cx, cy) {
  var key = cx + '_' + cy;
  var c = chunks[key];
  if (c) return c;
  var size = D.CHUNK * TILE;
  var canvas = document.createElement('canvas');
  canvas.width = size; canvas.height = size;
  var g = canvas.getContext('2d');
  for (var ty = 0; ty < D.CHUNK; ty++) {
    for (var tx = 0; tx < D.CHUNK; tx++) {
      var wx = cx * D.CHUNK + tx, wy = cy * D.CHUNK + ty;
      var b = biomeAt(wx, wy);
      var style = D.BIOME_STYLE[b] || D.BIOME_STYLE[3];
      var n = hash2(wx, wy, 404);
      g.fillStyle = n > 0.5 ? style.base : style.alt;
      g.fillRect(tx * TILE, ty * TILE, TILE, TILE);
      /* 水面波纹 */
      if (b === B.WATER || b === B.DEEP) {
        g.fillStyle = 'rgba(255,255,255,.4)';
        if (hash2(wx, wy, 11) > 0.7) g.fillRect(tx * TILE + 4, ty * TILE + TILE / 2, TILE - 8, 2);
      }
      /* 路面纹理 */
      if (b === B.ROAD) {
        g.fillStyle = 'rgba(255,255,255,.35)';
        g.fillRect(tx * TILE, ty * TILE + TILE - 3, TILE, 2);
      }
      if (b === B.PLAZA) {
        g.strokeStyle = 'rgba(124,58,237,.1)';
        g.strokeRect(tx * TILE + .5, ty * TILE + .5, TILE - 1, TILE - 1);
      }
      /* 建筑：屋顶 */
      if (b === B.BUILD) {
        g.fillStyle = 'rgba(76,29,149,.12)';
        g.fillRect(tx * TILE, ty * TILE, TILE, TILE);
        g.fillStyle = n > 0.5 ? '#cdbde9' : '#c0aee0';
        g.fillRect(tx * TILE + 1, ty * TILE + 1, TILE - 2, TILE - 2);
        /* 窗户 */
        g.fillStyle = 'rgba(255,255,255,.9)';
        g.fillRect(tx * TILE + 5, ty * TILE + 6, 6, 8);
        g.fillRect(tx * TILE + TILE - 11, ty * TILE + 6, 6, 8);
        g.fillStyle = 'rgba(109,40,217,.18)';
        g.fillRect(tx * TILE + 2, ty * TILE + TILE - 6, TILE - 4, 3);
      }
      /* 装饰 */
      var dec = inMap(wx, wy) ? decorMap[idx(wx, wy)] : 0;
      if (dec === 1) {  /* 树 */
        var trunkC = '#8d6748', leaf = n > 0.25 ? '#5cae6b' : '#6cbb78';
        g.fillStyle = trunkC;
        g.fillRect(tx * TILE + TILE / 2 - 2, ty * TILE + TILE / 2, 4, TILE / 2 - 2);
        g.fillStyle = leaf;
        g.beginPath();
        g.arc(tx * TILE + TILE / 2, ty * TILE + TILE / 2 - 4, TILE * 0.42, 0, Math.PI * 2);
        g.fill();
        g.fillStyle = 'rgba(255,255,255,.3)';
        g.beginPath();
        g.arc(tx * TILE + TILE / 2 - 4, ty * TILE + TILE / 2 - 8, TILE * 0.16, 0, Math.PI * 2);
        g.fill();
      } else if (dec === 3) { /* 花 */
        g.fillStyle = n > 0.5 ? '#e8a' : '#d6a';
        g.fillStyle = '#e78bb5';
        g.fillRect(tx * TILE + TILE / 2 - 2, ty * TILE + TILE / 2 - 2, 4, 4);
      }
      /* 高层地标（钟楼/灯塔塔基） */
      if (b === B.BUILD) {
        for (var pi = 0; pi < D.POIS.length; pi++) {
          var p = D.POIS[pi];
          if (!p.tall) continue;
          if (wx >= p.x && wx < p.x + p.w && wy >= p.y && wy < p.y + p.h) {
            if ((wx === p.x || wx === p.x + p.w - 1) && (wy === p.y || wy === p.y + p.h - 1)) {
              g.fillStyle = '#6d28d9';
              g.fillRect(tx * TILE + 4, ty * TILE + 4, TILE - 8, TILE - 8);
              g.fillStyle = '#f5c542';
              g.fillRect(tx * TILE + TILE / 2 - 3, ty * TILE + TILE / 2 - 3, 6, 6);
            }
          }
        }
      }
    }
  }
  chunks[key] = canvas;
  chunkOrder.push(key);
  /* LRU 淘汰 */
  while (chunkOrder.length > 40) {
    var old = chunkOrder.shift();
    delete chunks[old];
  }
  return canvas;
}

/* 主渲染 */
var offX = 0, offY = 0;   /* 世界→屏幕 像素偏移（所有绘制层共用） */
function render() {
  if (!ctx) return;
  var p = S.player;
  /* 相机 */
  camera.x = lerp(camera.x, p.x, 0.12);
  camera.y = lerp(camera.y, p.y, 0.12);
  var cpx = clamp(camera.x, viewW / TILE / 2, MW - viewW / TILE / 2);
  var cpy = clamp(camera.y, viewH / TILE / 2, MH - viewH / TILE / 2);
  offX = viewW / 2 - cpx * TILE;
  offY = viewH / 2 - cpy * TILE;

  ctx.clearRect(0, 0, viewW, viewH);

  /* 1) 地形 chunks */
  var c0x = Math.floor((cpx - viewW / TILE / 2) / D.CHUNK), c1x = Math.floor((cpx + viewW / TILE / 2) / D.CHUNK);
  var c0y = Math.floor((cpy - viewH / TILE / 2) / D.CHUNK), c1y = Math.floor((cpy + viewH / TILE / 2) / D.CHUNK);
  for (var cy = c0y; cy <= c1y; cy++)
    for (var cx = c0x; cx <= c1x; cx++) {
      if (cx < 0 || cy < 0 || cx * D.CHUNK >= MW || cy * D.CHUNK >= MH) continue;
      var ck = getChunk(cx, cy);
      ctx.drawImage(ck, Math.round(cx * D.CHUNK * TILE + offX), Math.round(cy * D.CHUNK * TILE + offY));
    }

  /* 2) 交互物 */
  drawWorldObjects(offX, offY);

  /* 3) 实体（残影 → NPC → 玩家） */
  drawShadows(offX, offY);
  drawNpcs(offX, offY);
  drawPlayer(offX, offY);
  drawTrackGuide(offX, offY);
  drawPulseLocate(offX, offY);

  /* 4) 昼夜光照 */
  drawLighting();

  /* 5) 天气 */
  drawWeatherFx();

  /* 6) 迷雾 */
  drawFog();

  /* 7) 建造模式：笔刷预览框 */
  if (buildMode.on && brushCursor) {
    var br = BUILD_BRUSHES[buildMode.brush] || BUILD_BRUSHES.grass;
    var rr = buildMode.size, r0 = Math.floor((rr - 1) / 2);
    var bx = (brushCursor.x + r0) * TILE + offX, by = (brushCursor.y + r0) * TILE + offY;
    ctx.fillStyle = 'rgba(147,51,234,.16)';
    ctx.fillRect(bx, by, rr * TILE, rr * TILE);
    ctx.strokeStyle = '#9333ea'; ctx.lineWidth = 2;
    ctx.setLineDash([5, 4]);
    ctx.strokeRect(bx + 1, by + 1, rr * TILE - 2, rr * TILE - 2);
    ctx.setLineDash([]);
    ctx.font = '14px "Segoe UI Emoji",sans-serif';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(br.icon, bx + rr * TILE / 2, by - 10);
  }
}

function sx(wx) { return wx * TILE + 0; }
function drawWorldObjects(ox, oy) {
  var i;
  ctx.font = '16px "Segoe UI Emoji","PingFang SC",sans-serif';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  /* 城市脉搏事件（信标光柱 + 上升光尘；稀有度着色） */
  for (i = 0; i < pulseEvents.length; i++) {
    var pe = pulseEvents[i].ev;
    var pex = pe.x * TILE + ox + TILE / 2, pey = pe.y * TILE + oy + TILE / 2;
    if (pex < -60 || pey < -90 || pex > viewW + 60 || pey > viewH + 60) continue;
    var rar = pe.rarity || 'common';
    var nowMs = performance.now();
    var pp2 = 0.6 + Math.sin(nowMs / 420 + i * 1.7) * 0.4;
    var col = pulseRarityColor(rar);
    var baseRgb = rar === 'rare' ? '168,85,247' : '245,158,11';
    /* 地面光晕 */
    ctx.fillStyle = 'rgba(' + baseRgb + ',' + (0.14 + pp2 * 0.2) + ')';
    ctx.beginPath(); ctx.ellipse(pex, pey + 6, 16 + pp2 * 8, 7, 0, 0, Math.PI * 2); ctx.fill();
    /* 光柱 */
    var bh = (rar === 'epic' ? 92 : rar === 'rare' ? 72 : 56) + pp2 * 8;
    var grad = ctx.createLinearGradient(pex, pey, pex, pey - bh);
    grad.addColorStop(0, 'rgba(' + baseRgb + ',.55)');
    grad.addColorStop(1, 'rgba(' + baseRgb + ',0)');
    ctx.fillStyle = grad;
    ctx.fillRect(pex - 4.5, pey - bh, 9, bh);
    /* 上升光尘 */
    for (var pi = 0; pi < 3; pi++) {
      var pt2 = ((nowMs / 1400) + pi / 3 + i * 0.31) % 1;
      var pdy = pey - pt2 * (bh + 10);
      ctx.fillStyle = 'rgba(' + baseRgb + ',' + (0.55 * (1 - pt2)) + ')';
      ctx.beginPath(); ctx.arc(pex + Math.sin(pt2 * 9 + pi * 2.1) * 5, pdy, 2.2, 0, Math.PI * 2); ctx.fill();
    }
    /* 光圈与图标 */
    ctx.strokeStyle = col; ctx.lineWidth = 1.8; ctx.globalAlpha = 0.85;
    ctx.beginPath(); ctx.arc(pex, pey, 9 + pp2 * 3, 0, Math.PI * 2); ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.font = '18px "Segoe UI Emoji","PingFang SC",sans-serif';
    ctx.fillText(pe.emoji || '✨', pex, pey - 5 - pp2 * 4);
    if (rar !== 'common') {
      ctx.font = 'bold 10px sans-serif';
      ctx.fillStyle = col;
      ctx.fillText(rar === 'epic' ? '★★★' : '★★', pex, pey + 17);
    }
    ctx.font = '16px "Segoe UI Emoji","PingFang SC",sans-serif';
    ctx.fillStyle = '#fff';
  }
  /* 记忆碎片 */
  for (i = 0; i < SHARDS.length; i++) {
    if (S.counters['shardTaken_' + i] || S.mainStage < 1) continue;
    var sh = SHARDS[i];
    var x = sh.x * TILE + ox + TILE / 2, y = sh.y * TILE + oy + TILE / 2;
    var pulse = 0.6 + Math.sin(performance.now() / 300 + i) * 0.4;
    ctx.fillStyle = 'rgba(96,165,250,' + (0.18 + pulse * 0.22) + ')';
    ctx.beginPath(); ctx.arc(x, y, 14 + pulse * 6, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#93c5fd';
    ctx.fillText('🔷', x, y);
  }
  /* 讲义 */
  for (i = 0; i < PAGES.length; i++) {
    if (S.counters['pageTaken_' + i]) continue;
    var s2 = S.sides['s2'];
    if (!s2 || s2.state !== 1) continue;
    var pg = PAGES[i];
    ctx.fillStyle = 'rgba(76,29,149,.9)';
    ctx.fillText('📄', pg.x * TILE + ox + TILE / 2, pg.y * TILE + oy + TILE / 2);
  }
  /* 拍照点 */
  for (i = 0; i < PHOTOS.length; i++) {
    var ph = PHOTOS[i], s4 = S.sides['s4'];
    if (S.flags['photo_' + ph.id] || !s4 || s4.state !== 1 || !hasItem('camera')) continue;
    var px = ph.x * TILE + ox + TILE / 2, py = ph.y * TILE + oy + TILE / 2;
    ctx.strokeStyle = 'rgba(34,197,94,.8)'; ctx.setLineDash([5, 4]); ctx.lineWidth = 1.5;
    ctx.strokeRect(px - 15, py - 15, 30, 30); ctx.setLineDash([]);
    ctx.fillStyle = '#fff';
    ctx.fillText('📷', px, py);
  }
  /* 资源节点 */
  for (i = 0; i < nodes.length; i++) {
    var nd = nodes[i];
    if (!nodeAvailable(nd)) continue;
    var nx = nd.x * TILE + ox + TILE / 2, ny = nd.y * TILE + oy + TILE / 2;
    if (nx < -40 || ny < -40 || nx > viewW + 40 || ny > viewH + 40) continue;
    var nt = D.NODE_TYPES[nd.type];
    ctx.fillText(nt.icon, nx, ny);
    if (hasSkill('per1')) {
      ctx.strokeStyle = 'rgba(139,92,246,.35)';
      ctx.beginPath(); ctx.arc(nx, ny, 13, 0, Math.PI * 2); ctx.stroke();
    }
  }
  /* 宝箱 */
  for (i = 0; i < CHESTS.length; i++) {
    var ch = CHESTS[i];
    if (S.chests[ch.id]) continue;
    if (ch.id === 'c_clock' && !S.worldFlags.clock_open) continue;
    if (ch.id === 'c_dark' && !S.worldFlags.dark_open) continue;
    if (ch.id === 'c_roof' && !S.worldFlags.roof_open) continue;
    if (ch.id === 'c_temple' && !S.worldFlags.temple_open) continue;
    var cx2 = ch.x * TILE + ox + TILE / 2, cy2 = ch.y * TILE + oy + TILE / 2;
    if (cx2 < -40 || cy2 < -40 || cx2 > viewW + 40 || cy2 > viewH + 40) continue;
    ctx.fillText('🧰', cx2, cy2);
  }
  /* POI 名称牌 */
  ctx.font = '11px "PingFang SC","Microsoft YaHei",sans-serif';
  for (i = 0; i < D.POIS.length; i++) {
    var poi = D.POIS[i];
    if (poi.hidden && !S.worldFlags[poi.id + '_found']) {
      /* 隐藏点接近才显示（心眼技能提前） */
      var dd = Math.hypot(poi.x - S.player.x, poi.y - S.player.y);
      if (dd > (hasSkill('per3') ? 12 : 3)) continue;
    }
    var tx = (poi.x + (poi.w || 1) / 2) * TILE + ox;
    var ty = poi.y * TILE + oy - 8;
    if (tx < -80 || ty < -30 || tx > viewW + 80 || ty > viewH + 30) continue;
    var label = poi.name;
    var w = ctx.measureText(label).width + 14;
    ctx.fillStyle = 'rgba(255,255,255,.94)';
    roundRect(ctx, tx - w / 2, ty - 10, w, 18, 9); ctx.fill();
    ctx.strokeStyle = 'rgba(124,58,237,.28)'; ctx.lineWidth = 1;
    roundRect(ctx, tx - w / 2 + .5, ty - 9.5, w - 1, 17, 8.5); ctx.stroke();
    ctx.fillStyle = '#4c1d95';
    ctx.fillText(label, tx, ty);
  }
  /* 灯塔光柱（修好后） */
  if (S.worldFlags.lighthouse_lit) {
    var lh = poiById('lighthouse');
    var lx = (lh.x + 1) * TILE + ox, ly = (lh.y + 0.5) * TILE + oy;
    var ang = performance.now() / 2600;
    var grad = ctx.createLinearGradient(lx, ly, lx + Math.cos(ang) * 260, ly + Math.sin(ang) * 260);
    grad.addColorStop(0, 'rgba(255,244,180,.35)');
    grad.addColorStop(1, 'rgba(255,244,180,0)');
    ctx.strokeStyle = grad; ctx.lineWidth = 26;
    ctx.beginPath(); ctx.moveTo(lx, ly); ctx.lineTo(lx + Math.cos(ang) * 260, ly + Math.sin(ang) * 260); ctx.stroke();
    ctx.strokeStyle = grad; ctx.lineWidth = 26;
    ctx.beginPath(); ctx.moveTo(lx, ly); ctx.lineTo(lx - Math.cos(ang) * 260, ly - Math.sin(ang) * 260); ctx.stroke();
  }
}
function roundRect(g, x, y, w, h, r) {
  g.beginPath();
  g.moveTo(x + r, y);
  g.arcTo(x + w, y, x + w, y + h, r);
  g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r);
  g.arcTo(x, y, x + w, y, r);
  g.closePath();
}

var spriteImgCache = {};
function getSpriteImg(src) {
  if (!spriteImgCache[src]) {
    var im = new Image();
    im.onload = function () { im._ok = true; };
    im.src = src;
    spriteImgCache[src] = im;
  }
  return spriteImgCache[src];
}
function drawNpcs(ox, oy) {
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  for (var i = 0; i < npcs.length; i++) {
    var e = npcs[i];
    var x = e.x * TILE + ox, y = e.y * TILE + oy;
    if (x < -60 || y < -60 || x > viewW + 60 || y > viewH + 60) continue;
    var bob = e.state === 'walk' ? Math.sin(performance.now() / 130 + i) * 2.5 : Math.sin(performance.now() / 700 + i) * 1.2;
    /* 阴影 */
    ctx.fillStyle = 'rgba(76,29,149,.16)';
    ctx.beginPath(); ctx.ellipse(x, y + 12, 10, 4, 0, 0, Math.PI * 2); ctx.fill();
    /* 身体圆 */
    ctx.fillStyle = e.def.color;
    ctx.beginPath(); ctx.arc(x, y + bob, 11, 0, Math.PI * 2); ctx.fill();
    var av = e.def.avatar ? getSpriteImg(e.def.avatar) : null;
    if (av && av._ok) {
      /* 图片头像：圆形裁剪绘制 */
      ctx.save();
      ctx.beginPath(); ctx.arc(x, y + bob, 11, 0, Math.PI * 2); ctx.clip();
      ctx.drawImage(av, x - 11, y - 11 + bob, 22, 22);
      ctx.restore();
      ctx.strokeStyle = 'rgba(255,255,255,.9)'; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(x, y + bob, 10.5, 0, Math.PI * 2); ctx.stroke();
    } else {
      ctx.fillStyle = 'rgba(255,255,255,.35)';
      ctx.beginPath(); ctx.arc(x - 3, y - 4 + bob, 4, 0, Math.PI * 2); ctx.fill();
      ctx.font = '13px "Segoe UI Emoji","PingFang SC",sans-serif';
      ctx.fillText(e.def.emoji, x, y + bob + 1);
    }
    /* 名字 */
    ctx.font = '11px "PingFang SC","Microsoft YaHei",sans-serif';
    var aff = S.npcAff[e.def.id] || 0;
    var label = e.def.name + (aff >= 15 ? ' ♡' + aff : '');
    var w = ctx.measureText(label).width + 10;
    ctx.fillStyle = 'rgba(255,255,255,.92)';
    roundRect(ctx, x - w / 2, y - 28 + bob, w, 15, 7); ctx.fill();
    ctx.strokeStyle = 'rgba(124,58,237,.22)'; ctx.lineWidth = 1;
    roundRect(ctx, x - w / 2 + .5, y - 27.5 + bob, w - 1, 14, 6.5); ctx.stroke();
    ctx.fillStyle = e.def.important ? '#6d28d9' : '#6f6785';
    ctx.fillText(label, x, y - 20 + bob);
    /* 心眼技能：心情 */
    if (hasSkill('min3')) {
      var moods = e.def.mood || {};
      var h = gameHour();
      var mk = h < 12 ? 'morning' : h < 17 ? 'noon' : h < 21 ? 'evening' : 'night';
      var mood = moods[mk] || '';
      if (mood) {
        ctx.fillStyle = '#7c3aed';
        ctx.font = '10px "PingFang SC",sans-serif';
        ctx.fillText('「' + mood + '」', x, y + 24);
      }
    }
  }
}
function drawPlayer(ox, oy) {
  var p = S.player;
  var x = p.x * TILE + ox, y = p.y * TILE + oy;
  ctx.fillStyle = 'rgba(76,29,149,.18)';
  ctx.beginPath(); ctx.ellipse(x, y + 13, 11, 4.5, 0, 0, Math.PI * 2); ctx.fill();
  var bob = (keys.w || keys.a || keys.s || keys.d || keys.up || keys.left || keys.down || keys.right)
    ? Math.sin(performance.now() / 110) * 2.8 : Math.sin(performance.now() / 900) * 1.2;
  ctx.fillStyle = '#e11d68';
  ctx.beginPath(); ctx.arc(x, y + bob, 12, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = 'rgba(255,255,255,.35)';
  ctx.beginPath(); ctx.arc(x - 3.5, y - 4.5 + bob, 4.5, 0, Math.PI * 2); ctx.fill();
  ctx.font = '13px "Segoe UI Emoji","PingFang SC",sans-serif';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText('👧', x, y + bob + 1);
  /* 名牌 */
  ctx.font = '11px "PingFang SC",sans-serif';
  var nw = ctx.measureText('你').width + 10;
  ctx.fillStyle = 'rgba(255,255,255,.92)';
  roundRect(ctx, x - nw / 2, y - 28 + bob, nw, 15, 7); ctx.fill();
  ctx.strokeStyle = 'rgba(219,39,119,.35)'; ctx.lineWidth = 1;
  roundRect(ctx, x - nw / 2 + .5, y - 27.5 + bob, nw - 1, 14, 6.5); ctx.stroke();
  ctx.fillStyle = '#db2777';
  ctx.fillText('你', x, y - 20 + bob);
}
function drawShadows(ox, oy) {
  for (var i = 0; i < shadows.length; i++) {
    var s = shadows[i];
    var x = s.x * TILE + ox, y = s.y * TILE + oy;
    var t = performance.now() / 400 + s.wob;
    ctx.fillStyle = 'rgba(76,29,149,' + (0.4 + Math.sin(t) * 0.15) + ')';
    ctx.beginPath();
    ctx.ellipse(x, y, 16 + Math.sin(t * 1.7) * 3, 20 + Math.cos(t * 1.3) * 3, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = 'rgba(196,181,253,.9)';
    ctx.font = '12px "Segoe UI Emoji",sans-serif';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText('👁', x, y - 4);
    ctx.fillText('👁', x, y + 6);
  }
}

function drawLighting() {
  var h = dayMin() / 60;   // 0-24 浮点
  var darkness = 0;
  if (h >= 19 && h < 21) darkness = (h - 19) / 2 * 0.5;
  else if (h >= 21 || h < 4.5) darkness = 0.5;
  else if (h >= 4.5 && h < 6.5) darkness = (6.5 - h) / 2 * 0.5;
  var wd = D.WEATHERS[S.weather];
  var weatherDim = 0;
  if (wd.light < 0) weatherDim = Math.min(0.24, -wd.light / 120);
  var total = clamp(darkness + weatherDim, 0, 0.62);
  if (total > 0.02) {
    /* 夜晚柔和紫蓝，天气阴偏灰紫 */
    var blue = darkness > 0.02;
    ctx.fillStyle = blue
      ? 'rgba(56,44,112,' + total + ')'
      : 'rgba(104,100,130,' + total + ')';
    ctx.fillRect(0, 0, viewW, viewH);
    /* 灯光点（夜间/暗天开灯） */
    if (darkness > 0.15) {
      ctx.save();
      ctx.globalCompositeOperation = 'lighter';
      drawLamps();
      ctx.restore();
    }
  }
}
function drawLamps() {
  var ox = offX, oy = offY;
  var t0x = Math.floor(camera.x - viewW / TILE / 2) - 1, t1x = Math.ceil(camera.x + viewW / TILE / 2) + 1;
  var t0y = Math.floor(camera.y - viewH / TILE / 2) - 1, t1y = Math.ceil(camera.y + viewH / TILE / 2) + 1;
  for (var y = t0y; y <= t1y; y++)
    for (var x = t0x; x <= t1x; x++) {
      if (!inMap(x, y)) continue;
      var b = biomeMap[idx(x, y)];
      var px = x * TILE + ox + TILE / 2, py = y * TILE + oy + TILE / 2;
      if (decorMap[idx(x, y)] === 2) {   /* 路灯 */
        lampGlow(px, y * TILE + oy + 4, 46, 'rgba(255,214,130,.30)');
      } else if (b === B.BUILD) {        /* 窗户暖光 */
        if (hash2(x, y, 88) > 0.4) lampGlow(px, py, 26, 'rgba(255,208,120,.16)');
      }
    }
  /* 灯塔光 */
  if (S.worldFlags.lighthouse_lit) {
    var lh = poiById('lighthouse');
    lampGlow((lh.x + 1) * TILE + ox, (lh.y + 0.5) * TILE + oy, 90, 'rgba(255,240,170,.45)');
  }
  /* 玩家随身微光 */
  lampGlow(S.player.x * TILE + ox, S.player.y * TILE + oy, 60, 'rgba(180,160,255,.14)');
}
var _glowCache = {};
function lampGlow(x, y, r, color) {
  /* 预渲染离屏贴图缓存（按 半径+颜色 键）：夜间城区几十盏灯 × 每帧新建渐变
     是 2D 模式最大的 GC 源；drawImage 缓存贴图比重建渐变快一个数量级 */
  var key = r + '|' + color;
  var spr = _glowCache[key];
  if (!spr) {
    var c = document.createElement('canvas');
    var d = Math.ceil(r * 2) + 4;
    c.width = c.height = d;
    var g2 = c.getContext('2d');
    var gr = g2.createRadialGradient(d / 2, d / 2, 2, d / 2, d / 2, r);
    gr.addColorStop(0, color);
    gr.addColorStop(1, 'rgba(0,0,0,0)');
    g2.fillStyle = gr;
    g2.fillRect(0, 0, d, d);
    spr = _glowCache[key] = c;
  }
  ctx.drawImage(spr, x - spr.width / 2, y - spr.height / 2);
}

/* 天气粒子（屏幕空间） */
function drawWeatherFx() {
  var wd = D.WEATHERS[S.weather];
  if (!wd.particle) return;
  var maxP = 160;
  while (particles.length < maxP && wd.particle !== 'fog') particles.push(newParticle(wd.particle));
  if (wd.particle === 'fog') particles.length = 0;
  if (wd.particle === 'star') maxP = 60;
  ctx.save();
  for (var i = particles.length - 1; i >= 0; i--) {
    var pt = particles[i];
    pt.life -= 1 / 60;
    pt.x += pt.vx / 60; pt.y += pt.vy / 60;
    if (pt.x < -20) pt.x = viewW + 20; if (pt.x > viewW + 20) pt.x = -20;
    if (pt.y > viewH + 20) { if (wd.particle !== 'star') pt.y = -20; else continue; }
    if (pt.life <= 0) { particles.splice(i, 1); continue; }
    if (pt.kind === 'rain' || pt.kind === 'storm') {
      ctx.strokeStyle = 'rgba(110,145,200,.55)';
      ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.moveTo(pt.x, pt.y); ctx.lineTo(pt.x - 3, pt.y + 12); ctx.stroke();
    } else if (pt.kind === 'snow') {
      ctx.fillStyle = 'rgba(255,255,255,.95)';
      ctx.strokeStyle = 'rgba(147,180,225,.55)'; ctx.lineWidth = .8;
      ctx.beginPath(); ctx.arc(pt.x, pt.y, pt.r || 2, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    } else if (pt.kind === 'star') {
      var tw = 0.4 + Math.abs(Math.sin(performance.now() / 700 + pt.ph)) * 0.6;
      ctx.fillStyle = 'rgba(255,252,235,' + tw * 0.95 + ')';
      ctx.fillRect(pt.x, pt.y, 2, 2);
    }
  }
  ctx.restore();
  /* 雷暴闪电 */
  if (wd.particle === 'storm') {
    if (lightFlash > 0) {
      ctx.fillStyle = 'rgba(255,255,255,' + lightFlash * 0.5 + ')';
      ctx.fillRect(0, 0, viewW, viewH);
      lightFlash -= 0.04;
    } else if (Math.random() < 0.004) lightFlash = 1;
  }
  /* 雾：可见度圈 */
  if (wd.particle === 'fog' || (wd.vis && wd.vis < 1)) {
    var g = ctx.createRadialGradient(viewW / 2, viewH / 2, viewH * 0.22, viewW / 2, viewH / 2, viewH * 0.75);
    g.addColorStop(0, 'rgba(226,222,240,0)');
    g.addColorStop(1, 'rgba(216,211,234,.8)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, viewW, viewH);
  }
}
function newParticle(kind) {
  var p = { kind: kind, x: Math.random() * viewW, y: Math.random() * viewH, life: 3 + Math.random() * 4 };
  if (kind === 'rain') { p.vx = -60; p.vy = 620; }
  else if (kind === 'storm') { p.vx = -140; p.vy = 900; }
  else if (kind === 'snow') { p.vx = (Math.random() - 0.5) * 40; p.vy = 50 + Math.random() * 40; p.r = 1.4 + Math.random() * 1.8; }
  else if (kind === 'star') { p.vx = 0; p.vy = 0; p.ph = Math.random() * 7; p.x = Math.random() * viewW; p.y = Math.random() * viewH * 0.65; }
  return p;
}

/* 迷雾 */
function drawFog() {
  var ox = offX, oy = offY;
  var t0x = Math.floor(camera.x - viewW / TILE / 2) - 1, t1x = Math.ceil(camera.x + viewW / TILE / 2) + 1;
  var t0y = Math.floor(camera.y - viewH / TILE / 2) - 1, t1y = Math.ceil(camera.y + viewH / TILE / 2) + 1;
  ctx.fillStyle = 'rgba(240,237,249,.95)';
  for (var y = t0y; y <= t1y; y++)
    for (var x = t0x; x <= t1x; x++) {
      if (!inMap(x, y)) continue;
      if (!exploredArr[idx(x, y)])
        ctx.fillRect(Math.floor(x * TILE + ox), Math.floor(y * TILE + oy), TILE + 1, TILE + 1);
    }
}

/* ================= 小地图 ================= */
var miniScale = 2;
function renderMinimap() {
  if (!miniCtx) return;
  var size = MW * miniScale;
  miniCtx.clearRect(0, 0, size, size);
  var step = 2;   /* 每 2 tile 采样 */
  for (var y = 0; y < MH; y += step)
    for (var x = 0; x < MW; x += step) {
      var i = idx(x, y);
      if (!exploredArr[i]) continue;
      var b = biomeMap[i];
      var st = D.BIOME_STYLE[b];
      miniCtx.fillStyle = st.base;
      miniCtx.fillRect(x * miniScale, y * miniScale, step * miniScale, step * miniScale);
    }
  /* 任务指引：主线目标点 */
  var guide = mainGuidePoint();
  if (guide) {
    miniCtx.fillStyle = '#ea580c';
    miniCtx.beginPath();
    miniCtx.arc(guide.x * miniScale, guide.y * miniScale, 4, 0, Math.PI * 2);
    miniCtx.fill();
  }
  /* 任务追踪目标（紫 ⭐） */
  var tg = trackedGuide();
  if (tg) {
    var tp2 = 0.6 + Math.sin(performance.now() / 300) * 0.4;
    miniCtx.strokeStyle = '#7c3aed'; miniCtx.lineWidth = 1.5;
    miniCtx.beginPath();
    miniCtx.arc(clamp(tg.x, 0, MW - 1) * miniScale, clamp(tg.y, 0, MH - 1) * miniScale, 5 + tp2 * 2, 0, Math.PI * 2);
    miniCtx.stroke();
    miniCtx.fillStyle = '#7c3aed';
    miniCtx.beginPath();
    miniCtx.arc(clamp(tg.x, 0, MW - 1) * miniScale, clamp(tg.y, 0, MH - 1) * miniScale, 3.5, 0, Math.PI * 2);
    miniCtx.fill();
  }
  /* 技能：许墨位置 */
  if (hasSkill('min2')) {
    var xm = npcV['xumo'];
    if (xm && exploredArr[idx(clamp(Math.floor(xm.x), 0, MW - 1), clamp(Math.floor(xm.y), 0, MH - 1))]) {
      miniCtx.fillStyle = '#7c3aed';
      miniCtx.beginPath();
      miniCtx.arc(xm.x * miniScale, xm.y * miniScale, 4, 0, Math.PI * 2);
      miniCtx.fill();
    }
  }
  /* 感知：资源/宝箱 */
  if (hasSkill('per1')) {
    miniCtx.fillStyle = 'rgba(22,163,74,.95)';
    for (var i2 = 0; i2 < nodes.length; i2++) {
      var nd = nodes[i2];
      if (!nodeAvailable(nd)) continue;
      if (Math.hypot(nd.x - S.player.x, nd.y - S.player.y) > 40) continue;
      miniCtx.fillRect(nd.x * miniScale - 1, nd.y * miniScale - 1, 3, 3);
    }
  }
  if (hasSkill('per2')) {
    miniCtx.fillStyle = 'rgba(217,119,6,.95)';
    for (var c = 0; c < CHESTS.length; c++) {
      if (S.chests[CHESTS[c].id]) continue;
      var cc = CHESTS[c];
      if (cc.id === 'c_clock' && !S.worldFlags.clock_open) continue;
      if (cc.id === 'c_dark' && !S.worldFlags.dark_open) continue;
      if (cc.id === 'c_roof' && !S.worldFlags.roof_open) continue;
      if (cc.id === 'c_temple' && !S.worldFlags.temple_open) continue;
      miniCtx.fillRect(cc.x * miniScale - 1.5, cc.y * miniScale - 1.5, 4, 4);
    }
  }
  /* per4: 碎片方向 */
  if (hasSkill('per4') && S.mainStage === 1) {
    miniCtx.fillStyle = '#2563eb';
    for (var s3 = 0; s3 < SHARDS.length; s3++) {
      if (S.counters['shardTaken_' + s3]) continue;
      miniCtx.fillRect(SHARDS[s3].x * miniScale - 2, SHARDS[s3].y * miniScale - 2, 5, 5);
    }
  }
  /* 玩家 */
  miniCtx.fillStyle = '#ff2d78';
  miniCtx.strokeStyle = '#fff'; miniCtx.lineWidth = 1.5;
  miniCtx.beginPath();
  miniCtx.arc(S.player.x * miniScale, S.player.y * miniScale, 4, 0, Math.PI * 2);
  miniCtx.fill(); miniCtx.stroke();
}

/* 主线指引点 */
function mainGuidePoint() {
  var st = S.mainStage;
  function pt(id) { var p = poiById(id); return { x: p.x + (p.w || 1) / 2, y: p.y + (p.h || 1) + 1 }; }
  if (st === 0) return pt('cafe');
  if (st === 1) {
    for (var i = 0; i < SHARDS.length; i++)
      if (!S.counters['shardTaken_' + i]) return { x: SHARDS[i].x, y: SHARDS[i].y };
    return npcV['xumo'] ? { x: npcV['xumo'].x, y: npcV['xumo'].y } : pt('cafe');
  }
  if (st === 2) return hasItem('archive') ? (npcV['ache'] ? { x: npcV['ache'].x, y: npcV['ache'].y } : pt('pier')) : pt('library');
  if (st === 3) return pt('darklab');
  if (st === 4) {
    if (!S.worldFlags.gear_done) return pt('mine');
    if (!hasItem('lens') && !S.chests['c_pier']) return { x: 125, y: 90 };
    if (!hasItem('bulb')) return pt('market');
    if (!S.worldFlags.lighthouse_lit) return npcV['laozhou'] ? { x: npcV['laozhou'].x, y: npcV['laozhou'].y } : pt('lighthouse');
    if (!S.flags.core_taken) return pt('lighthouse');
    return npcV['xumo'] ? { x: npcV['xumo'].x, y: npcV['xumo'].y } : pt('cafe');
  }
  if (st === 5) return pt('home');
  return null;
}

/* ================= 任务追踪 =================
 * questGuide(id)：'main' | 's1'..'s6' → {x, y, tip} 或 null
 */
function questGuide(id) {
  function pt(id2) { var p = poiById(id2); return p ? { x: p.x + (p.w || 1) / 2, y: p.y + (p.h || 1) + 1 } : null; }
  function npcPt(nid) { var e = npcV[nid]; return e ? { x: e.x, y: e.y } : null; }
  function nearestOf(list, takenFn) {
    var best = null, bd = 1e9;
    for (var i = 0; i < list.length; i++) {
      if (takenFn(list[i])) continue;
      var d = Math.hypot(list[i].x + 0.5 - S.player.x, list[i].y + 0.5 - S.player.y);
      if (d < bd) { bd = d; best = list[i]; }
    }
    return best;
  }
  if (id === 'main') {
    var g = mainGuidePoint();
    if (!g) return null;
    return { x: g.x, y: g.y, tip: '主线 · ' + D.MAIN_STAGES[Math.min(S.mainStage, D.MAIN_STAGES.length - 1)].title };
  }
  var q = S.sides[id];
  if (!q) return null;
  var p, n;
  if (id === 's1') {
    if (q.state === 1) {
      if (!hasItem('catfood')) { p = pt('market'); return p ? { x: p.x, y: p.y, tip: '去日夜超市买猫粮（¥20）' } : null; }
      n = npcPt('xiaoman'); return n ? { x: n.x, y: n.y, tip: '把猫粮给小满过目，去见墨鱼' } : null;
    }
    if (q.state === 2) { n = npcPt('cat'); return n ? { x: n.x, y: n.y, tip: '找到墨鱼，喂它猫粮' } : null; }
    if (q.state === 3 && !S.flags.s1_done_talk) { n = npcPt('xiaoman'); return n ? { x: n.x, y: n.y, tip: '回去告诉小满（领谢礼）' } : null; }
    return null;
  }
  if (id === 's2') {
    if (q.state === 1) {
      if ((S.counters.page || 0) >= 3) { n = npcPt('bai'); return n ? { x: n.x, y: n.y, tip: '把 3 页讲义交还白教授' } : null; }
      var pg = nearestOf(PAGES, function (t) { return S.counters['pageTaken_' + PAGES.indexOf(t)]; });
      return pg ? { x: pg.x + 0.5, y: pg.y + 0.5, tip: '捡回讲义散页（' + (S.counters.page || 0) + '/3）' } : null;
    }
    return null;
  }
  if (id === 's3') {
    if (q.state <= 2) { n = npcPt('chen'); return n ? { x: n.x, y: n.y, tip: q.state === 1 ? '听陈爷爷讲故事（' + (S.counters.lore || 0) + '/3）' : '再和陈爷爷聊聊（领取线索）' } : null; }
    return null;
  }
  if (id === 's4') {
    if (q.state === 1) {
      if ((S.counters.photo || 0) >= 3) { n = npcPt('ache'); return n ? { x: n.x, y: n.y, tip: '把胶片相机交还阿澈' } : null; }
      var ph = nearestOf(PHOTOS, function (t) { return S.flags['photo_' + t.id]; });
      if (!ph) return null;
      var hh = gameHour();
      var nightOk = hh >= 17 || hh < 4;
      return { x: ph.x + 0.5, y: ph.y + 0.5, tip: nightOk ? '拍摄「' + ph.name + '」（' + (S.counters.photo || 0) + '/3）' : '黄昏 17:00 后才能拍摄（' + ph.name + '）' };
    }
    return null;
  }
  if (id === 's5') {
    if (q.state === 1) {
      if ((S.counters.dew || 0) >= 3) { n = npcPt('xiaoman'); return n ? { x: n.x, y: n.y, tip: '把晨露花交给小满焙茶' } : null; }
      var dew = null, bd2 = 1e9;
      for (var i2 = 0; i2 < nodes.length; i2++) {
        var nd = nodes[i2];
        if (nd.type !== 'dew' || !nodeAvailable(nd)) continue;
        var d2 = Math.hypot(nd.x - S.player.x, nd.y - S.player.y);
        if (d2 < bd2) { bd2 = d2; dew = nd; }
      }
      if (dew) return { x: dew.x + 0.5, y: dew.y + 0.5, tip: '采集晨露花（' + (S.counters.dew || 0) + '/3）' };
      var pk = pt('park');
      return pk ? { x: pk.x, y: pk.y, tip: '等一场雨——晨露花只在雨后出现' } : null;
    }
    if (q.state === 2) { n = npcPt('xumo'); return n ? { x: n.x, y: n.y, tip: '把花茶送给许墨' } : null; }
    return null;
  }
  if (id === 's6') {
    if (q.state === 1) {
      if ((S.counters.iron || 0) >= 3) { n = npcPt('laozhou'); return n ? { x: n.x, y: n.y, tip: '把 3 块铁矿石交给老周' } : null; }
      var mn = pt('mine');
      return mn ? { x: mn.x, y: mn.y, tip: '去北岭矿脉采集铁矿石（' + (S.counters.iron || 0) + '/3）' } : null;
    }
    if (q.state === 2) {
      if (!hasItem('lens')) { p = pt('pier'); return p ? { x: 125, y: 90, tip: '栈桥尽头寻找黄铜透镜（宝箱）' } : null; }
      if (!hasItem('bulb')) { p = pt('market'); return p ? { x: p.x, y: p.y, tip: '去日夜超市买大灯泡（¥50）' } : null; }
      n = npcPt('laozhou');
      return n ? { x: n.x, y: n.y, tip: '零件齐了，找老周点亮灯塔' } : null;
    }
    return null;
  }
  return null;
}
function setTrack(id) {
  S.questTrack = id || null;
  saveGame();
  refreshUI();
}
function trackedGuide() {
  return S.questTrack ? questGuide(S.questTrack) : null;
}
/* 场景内追踪指示：目标光圈；屏幕外时边缘箭头 + 距离 */
function drawTrackGuide(ox, oy) {
  var g = trackedGuide();
  if (!g) return;
  var tx = g.x * TILE + ox + TILE / 2, ty = g.y * TILE + oy + TILE / 2;
  var pulse = 0.6 + Math.sin(performance.now() / 300) * 0.4;
  if (tx > -24 && tx < viewW + 24 && ty > -24 && ty < viewH + 24) {
    ctx.save();
    ctx.strokeStyle = 'rgba(147,51,234,.95)';
    ctx.lineWidth = 2.5;
    ctx.setLineDash([6, 4]);
    ctx.beginPath(); ctx.arc(tx, ty, 15 + pulse * 5, 0, Math.PI * 2); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(147,51,234,' + (0.10 + pulse * 0.14) + ')';
    ctx.beginPath(); ctx.arc(tx, ty, 15 + pulse * 5, 0, Math.PI * 2); ctx.fill();
    ctx.font = '14px "Segoe UI Emoji",sans-serif';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText('🎯', tx, ty - 24 - pulse * 3);
    ctx.restore();
    return;
  }
  var px = S.player.x * TILE + ox + TILE / 2, py = S.player.y * TILE + oy + TILE / 2;
  var ang = Math.atan2(ty - py, tx - px);
  var cx = viewW / 2, cy = viewH / 2, m = 30;
  var ca = Math.cos(ang), sa = Math.sin(ang), len = 1e9;
  if (ca > 0.001) len = Math.min(len, (viewW - m - cx) / ca);
  if (ca < -0.001) len = Math.min(len, (m - cx) / ca);
  if (sa > 0.001) len = Math.min(len, (viewH - m - cy) / sa);
  if (sa < -0.001) len = Math.min(len, (m - cy) / sa);
  len = Math.max(0, Math.min(len, Math.hypot(tx - px, ty - py)));
  var ex = cx + ca * len, ey = cy + sa * len;
  ctx.save();
  ctx.translate(ex, ey);
  ctx.rotate(ang);
  ctx.fillStyle = '#7c3aed';
  ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(13, 0); ctx.lineTo(-8, -8); ctx.lineTo(-3, 0); ctx.lineTo(-8, 8);
  ctx.closePath(); ctx.fill(); ctx.stroke();
  ctx.restore();
  var dist = Math.round(Math.hypot(g.x - S.player.x, g.y - S.player.y) * 10);
  ctx.fillStyle = '#7c3aed';
  ctx.strokeStyle = 'rgba(255,255,255,.9)'; ctx.lineWidth = 3;
  ctx.font = 'bold 11px sans-serif';
  ctx.textAlign = 'center'; ctx.textBaseline = 'top';
  ctx.strokeText(dist + 'm', ex, ey + 12);
  ctx.fillText(dist + 'm', ex, ey + 12);
}

/* 城市脉搏定位信标：金色 🧭，屏幕外时边缘箭头（与任务追踪互不冲突） */
function drawPulseLocate(ox, oy) {
  if (!pulseLocate) return;
  if (Date.now() > pulseLocate.until) { pulseLocate = null; return; }
  var tx = pulseLocate.x * TILE + ox + TILE / 2, ty = pulseLocate.y * TILE + oy + TILE / 2;
  var pulse = 0.6 + Math.sin(performance.now() / 260) * 0.4;
  if (tx > -24 && tx < viewW + 24 && ty > -24 && ty < viewH + 24) {
    ctx.save();
    ctx.strokeStyle = 'rgba(245,158,11,.95)';
    ctx.lineWidth = 2.5;
    ctx.setLineDash([7, 4]);
    ctx.beginPath(); ctx.arc(tx, ty, 16 + pulse * 6, 0, Math.PI * 2); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(245,158,11,' + (0.12 + pulse * 0.16) + ')';
    ctx.beginPath(); ctx.arc(tx, ty, 16 + pulse * 6, 0, Math.PI * 2); ctx.fill();
    ctx.font = '15px "Segoe UI Emoji",sans-serif';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText('🧭', tx, ty - 26 - pulse * 3);
    ctx.restore();
    return;
  }
  var px = S.player.x * TILE + ox + TILE / 2, py = S.player.y * TILE + oy + TILE / 2;
  var ang = Math.atan2(ty - py, tx - px);
  var cx = viewW / 2, cy = viewH / 2, m = 46;
  var ca = Math.cos(ang), sa = Math.sin(ang), len = 1e9;
  if (ca > 0.001) len = Math.min(len, (viewW - m - cx) / ca);
  if (ca < -0.001) len = Math.min(len, (m - cx) / ca);
  if (sa > 0.001) len = Math.min(len, (viewH - m - cy) / sa);
  if (sa < -0.001) len = Math.min(len, (m - cy) / sa);
  len = Math.max(0, Math.min(len, Math.hypot(tx - px, ty - py)));
  var ex = cx + ca * len, ey = cy + sa * len;
  ctx.save();
  ctx.translate(ex, ey);
  ctx.rotate(ang);
  ctx.fillStyle = '#f59e0b';
  ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(13, 0); ctx.lineTo(-8, -8); ctx.lineTo(-3, 0); ctx.lineTo(-8, 8);
  ctx.closePath(); ctx.fill(); ctx.stroke();
  ctx.restore();
  var dist = Math.round(Math.hypot(pulseLocate.x - S.player.x, pulseLocate.y - S.player.y) * 10);
  ctx.fillStyle = '#b45309';
  ctx.strokeStyle = 'rgba(255,255,255,.9)'; ctx.lineWidth = 3;
  ctx.font = 'bold 11px sans-serif';
  ctx.textAlign = 'center'; ctx.textBaseline = 'top';
  ctx.strokeText(dist + 'm', ex, ey + 12);
  ctx.fillText(dist + 'm', ex, ey + 12);
}

/* ================= 主循环 ================= */
var autoSaveAcc = 0, miniAcc = 0;
function loop(ts) {
  if (!running) return;
  rafId = requestAnimationFrame(loop);
  var dt = Math.min(0.05, (ts - lastTs) / 1000 || 0.016);
  lastTs = ts;
  S.playSec += dt;

  advanceTime(dt);
  updateNpcsAll(dt);
  spawnShadowChance(dt);
  updateShadows(dt);
  tickEditQueue(dt);
  tickLogQueue(dt);

  /* 玩家输入（非弹窗状态）：键盘 + 虚拟摇杆（D-pad/画布拖拽）
   * 3D 模式下按相机方位角旋转输入方向（屏幕方向 ≠ 世界方向） */
  if (!ui.isModal || !ui.isModal()) {
    var ia = (renderMode === '3d' && ext3d) ? (ext3d.inputAngle() || 0) : 0;
    var dx = 0, dy = 0;
    if (keys.w || keys.up) dy -= 1;
    if (keys.s || keys.down) dy += 1;
    if (keys.a || keys.left) dx -= 1;
    if (keys.d || keys.right) dx += 1;
    if (dx || dy) { var m1 = rotInput(dx, dy, ia); tryMovePlayer(m1.x, m1.y, dt); }
    else if (joy.active && (joy.dx || joy.dy)) {
      var m2 = rotInput(joy.dx, joy.dy, ia);
      tryMovePlayer(m2.x, m2.y, dt * (joy.mag || 1));
    }
  }

  interactTarget = getInteractTarget();
  if (ui.setInteract) ui.setInteract(interactTarget);

  updateExplore();
  if (renderMode === '3d' && ext3d) ext3d.frame(dt);
  else render();

  miniAcc += dt;
  if (miniAcc > 1.2) { miniAcc = 0; renderMinimap(); }
  autoSaveAcc += dt;
  if (autoSaveAcc > 30) { autoSaveAcc = 0; saveGame(); }

  if (ui.tick) ui.tick(dt);
}
function updateNpcsAll(dt) {
  for (var i = 0; i < npcs.length; i++) updateNpc(npcs[i], dt);
}

/* ================= 输入 ================= */
var KEYMAP = {
  w: 'w', arrowup: 'up', s: 's', arrowdown: 'down',
  a: 'a', arrowleft: 'left', d: 'd', arrowright: 'right', shift: 'shift'
};
function onKeyDown(e) {
  if (!running) return;
  if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
  var k = KEYMAP[e.key.toLowerCase()];
  if (k) { keys[k] = true; e.preventDefault(); }
  if ((e.key === 'e' || e.key === 'E') && (!ui.isModal || !ui.isModal())) { doInteract(); e.preventDefault(); }
}
function onKeyUp(e) {
  var k = KEYMAP[e.key.toLowerCase()];
  if (k) keys[k] = false;
}
/* 虚拟摇杆（触摸/鼠标按住拖动） */
var joy = { active: false, dx: 0, dy: 0, mag: 1 };
function applyJoy() {
  if (joy.active && (!ui.isModal || !ui.isModal())) {
    var ia = (renderMode === '3d' && ext3d) ? (ext3d.inputAngle() || 0) : 0;
    var m = rotInput(joy.dx, joy.dy, ia);
    tryMovePlayer(m.x, m.y, 0.05);
  }
}
/* 屏幕方向 → 世界方向（a=相机方位角；a=0 时与 2D 俯视一致） */
function rotInput(dx, dy, a) {
  if (!a) return { x: dx, y: dy };
  var c = Math.cos(a), s = Math.sin(a);
  return { x: dx * c + dy * s, y: -dx * s + dy * c };
}

/* ================= 尺寸 ================= */
function resize() {
  if (!cv) return;
  var rect = cv.parentElement.getBoundingClientRect();
  dpr = Math.min(2, window.devicePixelRatio || 1);
  viewW = Math.max(320, Math.floor(rect.width));
  viewH = Math.max(240, Math.floor(rect.height));
  cv.width = viewW * dpr; cv.height = viewH * dpr;
  cv.style.width = viewW + 'px'; cv.style.height = viewH + 'px';
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  particles.length = 0;
  if (ext3d) ext3d.resize();
}

/* ================= 生命周期 ================= */
var ro = null;
function init() {
  generateWorld();
  generateNodes();
  var loaded = loadGame();
  S = loaded || defaultSave();
  if (!loaded) {
    /* 新档初始探索 */
    exploredArr = new Uint8Array(MW * MH);
    S.exploredCount = 0;
    updateExplore();
  } else {
    exploredArr = S.explored ? rleDecode(S.explored) : new Uint8Array(MW * MH);
  }
  initNpcs();
  loadCustomPlaces();
  loadWorldEdits();
  loadCustomNpcs();
  loadWorldPulse();
  unstickPlayer();   /* 旧档出生点被地形围死时立即脱困 */
}
function start() {
  if (!S) init();
  if (running) return;
  running = true;
  document.addEventListener('keydown', onKeyDown);
  document.addEventListener('keyup', onKeyUp);
  lastTs = performance.now();
  rafId = requestAnimationFrame(loop);
  saveGame();
}
function pause() {
  if (!running) return;
  running = false;
  cancelAnimationFrame(rafId);
  document.removeEventListener('keydown', onKeyDown);
  document.removeEventListener('keyup', onKeyUp);
  flushEditsNow(false);
  _flushWorldLog(false);
  saveGame();
}
/* 页面隐藏/关闭时兜底上传（rAF 后台会停摆） */
document.addEventListener('visibilitychange', function () {
  if (document.visibilityState === 'hidden') { flushEditsNow(true); _flushWorldLog(true); }
});
window.addEventListener('beforeunload', function () { flushEditsNow(true); _flushWorldLog(true); });
function bindCanvas(canvasEl, miniEl) {
  cv = canvasEl; ctx = cv.getContext('2d');
  miniCv = miniEl;
  if (miniEl) miniCtx = miniEl.getContext('2d');
  resize();
  if (ro) ro.disconnect();
  ro = new ResizeObserver(resize);
  ro.observe(cv.parentElement);
}
function setLucienLevel(lv) { lucienAffinityLv = lv || 0; }

/* ================= 2D/3D 渲染模式 ================= */
function register3D(ext) {
  ext3d = ext;
  if (ext && renderMode === '3d') ext.setEnabled(true);
}
function setRenderMode(m) {
  if (m !== '2d' && m !== '3d') m = '2d';
  if (m === '3d' && !ext3d) m = '2d';
  renderMode = m;
  if (ext3d) ext3d.setEnabled(m === '3d');
  if (m === '2d') {
    camera.x = S ? S.player.x : camera.x;
    camera.y = S ? S.player.y : camera.y;
  }
}
function getRenderMode() { return renderMode; }
/* 3D 层只读数据引用 */
function _gridRefs() {
  return { biome: biomeMap, decor: decorMap, explored: exploredArr };
}
function resetSave() {
  try { localStorage.removeItem(SAVE_KEY); } catch (e) {}
  S = defaultSave();
  exploredArr = new Uint8Array(MW * MH);
  S.exploredCount = 0;
  initNpcs();
  updateExplore();
  refreshUI();
}

/* ================= 暴露 ================= */
window.WORLD_ENG = {
  D: D,
  start: start, pause: pause, init: init,
  bindCanvas: bindCanvas, on: on,
  makeG: makeG,
  save: saveGame, resetSave: resetSave,
  doInteract: doInteract,
  battleEnd: battleEnd,
  calcStats: calcStats, hasSkill: hasSkill,
  gainExp: gainExp, giveItem: giveItem, takeItem: takeItem, hasItem: hasItem,
  fixLighthouse: fixLighthouse,
  onPuzzleSolved: onPuzzleSolved,
  callAffinity: callAffinity,
  setLucienLevel: setLucienLevel,
  gameClock: gameClock, gameHour: gameHour, isNight: isNight,
  explorePct: explorePct, mainGuidePoint: mainGuidePoint,
  questGuide: questGuide, setTrack: setTrack, trackedGuide: trackedGuide,
  /* 2D/3D 渲染模式 */
  register3D: register3D,
  setRenderMode: setRenderMode,
  getRenderMode: getRenderMode,
  _gridRefs: _gridRefs,
  decorAt: function (x, y) { return inMap(x, y) ? decorMap[idx(x, y)] : 0; },
  camRef: function () { return camera; },
  npcAll: function () { return npcs; },
  shadowsAll: function () { return shadows; },
  nodesAll: function () { return nodes; },
  nodeAvail: function (nd) { return nodeAvailable(nd); },
  staticsAll: function () { return { SHARDS: SHARDS, PAGES: PAGES, PHOTOS: PHOTOS, CHESTS: CHESTS }; },
  pulseLocateRef: function () { return pulseLocate; },
  state: function () { return S; },
  weatherDef: function () { return D.WEATHERS[S.weather]; },
  getNpc: function (id) { return npcV[id]; },
  joy: joy, applyJoy: applyJoy,
  poiById: poiById,
  loadCustomPlaces: loadCustomPlaces,
  applyCustomPlace: applyCustomPlace,
  removeCustomPlace: removeCustomPlace,
  /* 世界脉搏 */
  loadWorldPulse: loadWorldPulse,
  triggerPulseGen: triggerPulseGen,
  completePulseEvent: completePulseEvent,
  verifyPulseRumor: verifyPulseRumor,
  locatePulseTarget: locatePulseTarget,
  /* 世界编年史 */
  logWorld: logWorld,
  flushWorldLog: _flushWorldLog,
  pulseData: function () {
    return {
      events: pulseEvents.map(function (p) { return p.ev; }),
      rumors: pulseRumors,
      visitors: pulseVisitorIds.map(function (id) {
        var e = npcV[id];
        return e ? {
          id: id, name: e.def.name, emoji: e.def.emoji, expireDay: e.def.expireDay,
          gifted: e.def.gifted ? 1 : 0,
          x: Math.round(e.x), y: Math.round(e.y)
        } : null;
      }).filter(Boolean),
      vitality: pulseVitality,
      vitalityLevel: pulseVitalityLevel
    };
  },
  mapSample: biomeAt,
  exploredAt: function (x, y) { return inMap(x, y) ? !!exploredArr[idx(x, y)] : false; },
  /* 世界扩建 · 创造 */
  BUILD_BRUSHES: BUILD_BRUSHES,
  setBuildMode: setBuildMode,
  buildState: function () { return buildMode; },
  paintScreen: paintScreen,
  setBrushCursor: setBrushCursor,
  worldEditCount: function () { return Object.keys(worldEditIdx).length; },
  loadWorldEdits: loadWorldEdits,
  resetWorldEdits: resetWorldEdits,
  flushEditsNow: flushEditsNow,
  applyCustomNpc: applyCustomNpc,
  removeCustomNpc: removeCustomNpc,
  loadCustomNpcs: loadCustomNpcs,
  findWalkableNear: findWalkableNear
};

})();
