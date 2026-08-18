/* =========================================================================
 * 世界·恋语市 —— 3D 卡通开放世界渲染层 v8（原神级细致复刻，与 2D 可切换）
 * 依赖：/static/libs/three.min.js (r128 UMD) + WORLD_ENG 数据接口
 *       + libs/{CopyShader,LuminosityHighPassShader,MaskPass,EffectComposer,
 *               RenderPass,ShaderPass,UnrealBloomPass}.js（后处理，可缺失自动降级）
 * 原神级渲染管线：
 *  - 全场景 Ramp 卡通着色：暗部偏蓝紫 / 亮部偏暖（原神标志色彩层次）
 *  - UnrealBloom 泛光 + 自研 FinalGrade 合成（ACES/饱和/暗角/暗部冷色）
 *  - 角色 BackSide 法线描边（原神角色勾边感）
 *  - 地形 2× 细分 + 坡度 splat 三纹理混合（草/岩/土灰度细节 × 生物群系顶点色）
 *  - 草海加密（每格 1-2 簇 + 黄绿渐变 + 双频风摆）
 *  - 水面菲涅尔 + 波纹 shimmer 注入；屋顶瓦纹贴图；建筑腰线
 *  - 连续平滑地形网格：顶点色粉彩丘陵 + 微起伏噪点 + 自然河岸过渡
 *  - 圆润团簇树冠（主球+偏移球）/ 三层锥针叶 / 樱花粉簇，锥形圆柱树干
 *  - 建筑：白墙+石基座+檐口+瓦纹四坡尖顶/平顶水箱+门框雨棚+POI招牌+烟囱
 *  - 渐变天空穹顶 + 积云球簇 + 昼夜/天气联动 + FPS 自适应降级
 *  - 未探索区域 = 白色云海厚盖，探索推进即时消散（无需重建世界）
 * ========================================================================= */
(function () {
'use strict';

function available() { return typeof window.THREE !== 'undefined'; }

var E = null, D = null, B = null;

/* ---------- 状态 ---------- */
var cvEl = null, ovEl = null, ovCtx = null;
var renderer = null, scene = null, cam = null;
var w = 0, h = 0;
var active = false, ready = false, sceneBuilt = false;
var MWv = 0, MHv = 0;

/* 相机轨道：theta 方位角 / phi 仰角 / radius 距离 */
var theta = 0, phi = 0.86, radius = 15;
var thetaV = 0, phiV = 0, radV = 0;
var camLook = { x: 0, y: 0, z: 0 };
var hintUntil = 0;

/* 地形引用（由引擎只读提供） */
var biomeArr = null, decorArr = null, explored = null, exploredShadow = null;

/* 实体网格 */
var worldGroup = null;
var terrainByBiome = {};      // biome -> InstancedMesh
var buildWallMesh = null, buildRoofMesh = null;
var doorMesh = null, cornerMesh = null, chimMesh = null;
var waterSurfMesh = null, waterSurfMat = null;
var waterSurf2Mesh = null, waterSurf2Mat = null, foamMesh = null;
var trunkMesh = null, leafDecMesh = null, leafConMesh = null, leafChMesh = null;
var poleMesh = null, poleBaseMesh = null, lampHeadMesh = null;
var stemMesh = null, petalMesh = null;
var bushMesh = null, rockDecoMesh = null;
var dirtyEdit = false, dirtyExplore = false, lastRebuild = 0, lastExploreRebuild = 0;
var lampGlows = [], lampSprites = [], lampPoints = null;
var headMat = null, buildWallMat = null, cloudGroup = null;
var sunSpr = null, moonSpr = null;
var clouds = [];

/* 实体池 */
var npcGroups = {};
var shadowPool = [];
var sprites = {};
var beams = [];
var playerG = null, playerParts = null, playerRing = null;
/* 自定义 3D 形象（GLB / GLTF 上传）：玩家槽 + 许墨槽 独立 */
var PMODEL = { url: '', loading: false, stateFetched: false, group: null, mixer: null, idle: null, walk: null, cur: null };
var XMODEL = { url: '', wantUrl: '', group: null, mixer: null, idle: null, walk: null, cur: null };
var trackRing = null, pulseRingM = null;
var brushBox = null, brushTile = null;
var stars = null, rainPts = null, snowPts = null;
var sun = null, hemi = null, moon = null, playerLight = null;
var lhBeamGroup = null, lhGlow = null;

/* v6 真实度：环境系统 */
var WIND_U = { uTime: { value: 0 }, uWind: { value: 0.5 } };  // 风着色器共享 uniforms
var windMats = [];                                            // 挂风摇摆的材质
var cloudMat = null, cloudTintCur = 0;                        // 云层材质 + 当前压暗值
var fireflyPts = null, butterflySprites = [], birdSprites = [];
var birdTimer = 8, birdDir = null;
var mistGroup = null, mistOnCur = 0;
var rainbowMesh = null, rainbowUntil = 0;
var glintPts = null, waterTilesArr = [], glintScatterAt = 0, glintAnchor = { x: 1e9, y: 1e9 };
var moonPhaseTexs = null, lastMoonDay = -1;
var starBaseO = 0, lampValCur = 0, lastLampTick = 0;
var prevWeather3d = '';
var fogMesh = null, terrainMesh = null, grassCrossMesh = null;
var skyDome = null, skyUni = null;
var curbMesh = null;

/* v8 原神级：后处理合成 / 自适应画质 */
var composer = null, bloomPass = null, gradePass = null;
var fpsEMA = 60, qTier = 0, qRecover = 0;

/* 原神级 FinalGrade 合成 Shader：饱和度提升 + 暗部偏蓝紫 + 亮部偏暖 +
   暗角 vignette + 微对比。注意：ACES 色调映射由 renderer.toneMapping 在
   RenderPass 阶段已完成，此处不再重复 tonemap，仅做色彩分级 */
var FINAL_GRADE_SHADER = {
  uniforms: {
    tDiffuse:    { value: null },
    uExposure:   { value: 1.06 },   /* 整体微提亮（已 tonemap 后的 LDR） */
    uSaturation: { value: 1.18 },   /* 饱和度：原神成片偏饱和 */
    uContrast:   { value: 1.06 },   /* 微提对比，强化体积感 */
    uShadows:    { value: new THREE.Color(0.55, 0.62, 0.92) }, /* 暗部偏蓝紫（乘法） */
    uHighlights: { value: new THREE.Color(1.06, 1.02, 0.92) }, /* 亮部偏暖（乘法） */
    uVignette:   { value: 0.30 },   /* 暗角强度 */
    uVignetteR:  { value: 1.15 }    /* 暗角半径 */
  },
  vertexShader: [
    'varying vec2 vUv;',
    'void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }'
  ].join('\n'),
  fragmentShader: [
    'uniform sampler2D tDiffuse;',
    'uniform float uExposure, uSaturation, uContrast, uVignette, uVignetteR;',
    'uniform vec3 uShadows, uHighlights;',
    'varying vec2 vUv;',
    'void main(){',
    '  vec3 col = texture2D(tDiffuse, vUv).rgb;',
    '  col *= uExposure;',
    '  /* 饱和度（绕亮度轴缩放） */',
    '  float l = dot(col, vec3(0.2126, 0.7152, 0.0722));',
    '  col = mix(vec3(l), col, uSaturation);',
    '  /* 对比度（绕 0.5 缩放） */',
    '  col = (col - 0.5) * uContrast + 0.5;',
    '  /* 双色温分离：按亮度分别向冷暗 / 暖亮偏移 */',
    '  float lum = clamp(l * 1.2, 0.0, 1.0);',
    '  col = mix(col * uShadows, col * uHighlights, lum);',
    '  /* 暗角：圆形径向衰减 */',
    '  vec2 d = vUv - 0.5;',
    '  float vig = 1.0 - smoothstep(0.5 - uVignetteR * 0.5, 0.5, dot(d, d) * 2.0) * uVignette;',
    '  col *= vig;',
    '  gl_FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);',
    '}'
  ].join('\n')
};

/* 初始化后处理管线（仅当 EffectComposer/UnrealBloomPass 已加载时启用，
   否则保留 null，渲染回退到 renderer.render 直接出图） */
function initPostFX() {
  if (composer || !renderer || !scene || !cam) return;
  var THREE = window.THREE;
  if (!THREE.EffectComposer || !THREE.UnrealBloomPass || !THREE.RenderPass || !THREE.ShaderPass) return;
  composer = new THREE.EffectComposer(renderer);
  composer.addPass(new THREE.RenderPass(scene, cam));
  /* UnrealBloom：原神标志的柔光泛光（窗灯/路灯/日月/水面高光） */
  bloomPass = new THREE.UnrealBloomPass(new THREE.Vector2(w, h), 0.62, 0.55, 0.85);
  bloomPass.threshold = 0.72;   /* 仅高亮区泛光，避免整体发糊 */
  bloomPass.strength = 0.62;
  bloomPass.radius = 0.55;
  composer.addPass(bloomPass);
  /* FinalGrade 合成（最后一道） */
  gradePass = new THREE.ShaderPass(FINAL_GRADE_SHADER, 'tDiffuse');
  gradePass.renderToScreen = true;
  composer.addPass(gradePass);
  composer.setSize(w, h);
}

/* 自适应画质：FPS 持续低迷时关闭 Bloom，恢复后重新打开 */
function updateAdaptiveQuality(dt) {
  fpsEMA = fpsEMA * 0.92 + (1 / Math.max(0.001, dt)) * 0.08;
  if (fpsEMA < 30 && qTier === 0) {
    qTier = 1; qRecover = 0;
    if (bloomPass) bloomPass.enabled = false;
  } else if (qTier === 1) {
    if (fpsEMA >= 45) {
      qRecover += dt;
      if (qRecover > 3) { qTier = 0; if (bloomPass) bloomPass.enabled = true; }
    } else qRecover = 0;
  }
}

/* v6: 给植被材质注入顶点风摆（InstancedMesh 按实例位置相位差摇曳，风力由天气驱动） */
function windSway(mat, amp) {
  mat.onBeforeCompile = function (sh) {
    sh.uniforms.uT = WIND_U.uTime; sh.uniforms.uW = WIND_U.uWind; sh.uniforms.uA = { value: amp };
    sh.vertexShader = 'uniform float uT; uniform float uW; uniform float uA;\n' + sh.vertexShader.replace(
      '#include <begin_vertex>',
      ['#include <begin_vertex>',
       '{',
       '#ifdef USE_INSTANCING',
       '  float phW = instanceMatrix[3][0] * 0.71 + instanceMatrix[3][2] * 0.53;',
       '#else',
       '  float phW = 0.0;',
       '#endif',
       '  float kSw = 0.35 + 0.65 * uW;',
       '  transformed.x += sin(uT * 1.9 + phW) * uA * kSw * clamp(position.y * 1.8 + 0.1, 0.1, 1.0);',
       '  transformed.z += cos(uT * 1.42 + phW * 1.3) * uA * kSw * 0.6;',
       '}'].join('\n')
    );
  };
  mat.customProgramCacheKey = function () { return 'wind' + amp; };
  return mat;
}

/* 天气/时间缓存 */
var lastWeather = '', lastDarkness = -1, flash = 0;
var exploreTimer = 0;
var tNow = 0;

/* 复用对象 */
var tmpM = null, tmpC = null, tmpV = null, tmpQ = null, tmpS = null, raycaster = null, planeY0 = null;
var unexploredColor = null;
var EMOJI_TEX = {}, IMG_TEX = {};

/* ================= 工具 ================= */
function hash2(x, y, seed) {
  var n = Math.imul(x, 374761393) + Math.imul(y, 668265863) + Math.imul(seed | 0, 2246822519);
  n = Math.imul(n ^ n >>> 13, 1274126177);
  return ((n ^ n >>> 16) >>> 0) / 4294967296;
}
function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
function lerp(a, b, t) { return a + (b - a) * t; }

function biomeTop(b) {
  if (b === B.DEEP) return -0.55;
  if (b === B.WATER) return -0.28;
  if (b === B.SAND) return 0.02;
  if (b === B.BRIDGE) return 0.14;
  if (b === B.HILL) return 0.45;
  if (b === B.MOUNT) return 1.15;
  if (b === B.SNOW) return 1.8;
  return 0;
}
/* ---------- 原神/旷野之息式卡通色板（明亮粉彩） ---------- */
var BIOME_COL = null;
function biomeColorOf(b) {
  if (!BIOME_COL) {
    BIOME_COL = {};
    var defs = {};
    defs[B.GRASS] = '#7ec85e';   defs[B.FOREST] = '#4fa455'; defs[B.PARK] = '#8fd468';
    defs[B.FIELD] = '#d9bd6b';   defs[B.ROAD] = '#b7ae9e';   defs[B.PLAZA] = '#d7d1c3';
    defs[B.SAND] = '#efdfb4';    defs[B.HILL] = '#8cc25e';   defs[B.MOUNT] = '#9a958e';
    defs[B.SNOW] = '#f2f6fa';    defs[B.WATER] = '#6fa890';  defs[B.DEEP] = '#5a987f';
    defs[B.BRIDGE] = '#a87c50';  defs[B.BUILD] = '#d2cabb';  defs[B.FLOOR] = '#d7d1c3';
    for (var k in defs) BIOME_COL[k] = new THREE.Color(defs[k]);
    BIOME_COL.__def = new THREE.Color('#7ec85e');
  }
  return BIOME_COL[b] || BIOME_COL.__def;
}
/* 连续坐标四邻均混（角点双线性）→ 平滑丘陵与自然河岸 */
var blendOut = { h: 0, col: null }, C_TMP = null;
function blendCorner(fx, fz, out) {
  if (!out.col) { out.col = new THREE.Color(); C_TMP = new THREE.Color(); }
  var gx = fx - 0.5, gz = fz - 0.5;
  var x0 = Math.floor(gx), z0 = Math.floor(gz);
  var tx = gx - x0, tz = gz - z0;
  var ws = [
    [x0, z0, (1 - tx) * (1 - tz)], [x0 + 1, z0, tx * (1 - tz)],
    [x0, z0 + 1, (1 - tx) * tz], [x0 + 1, z0 + 1, tx * tz]
  ];
  var h = 0;
  out.col.setRGB(0, 0, 0);
  for (var i = 0; i < 4; i++) {
    var xx = clamp(ws[i][0], 0, MWv - 1) | 0, zz = clamp(ws[i][1], 0, MHv - 1) | 0;
    var w = ws[i][2];
    if (w <= 0) continue;
    h += biomeTop(biomeArr[zz * MWv + xx]) * w;
    C_TMP.copy(biomeColorOf(biomeArr[zz * MWv + xx]));
    out.col.r += C_TMP.r * w; out.col.g += C_TMP.g * w; out.col.b += C_TMP.b * w;
  }
  out.h = h;
  return out;
}
function smoothTop(fx, fz) {
  blendCorner(fx, fz, blendOut);
  return blendOut.h;
}
function groundTop(x, y) {
  if (x < 0 || y < 0 || x >= MWv || y >= MHv) return 0;
  var h = smoothTop(x + 0.5, y + 0.5);
  /* 建模扩展·v2：高程立体偏移（elevation 0~1 → 0~1.8 单位） */
  if (E && E.elevationAt) {
    var e = E.elevationAt(x, y);
    if (e > 0) h += (e - 0.4) * 1.8;   /* 0.4 以下压低，以上抬升 */
  }
  return h;
}

/* ================= 像素纹理工厂（64×64 高精细） ================= */
function pixTex(draw, size) {
  size = size || 64;
  var c = document.createElement('canvas');
  c.width = c.height = size;
  draw(c.getContext('2d'), size);
  var t = new THREE.CanvasTexture(c);
  t.magFilter = THREE.NearestFilter;
  /* 三线性 mipmap：远景保色调不闪噪，近景 Nearest 保持像素风 */
  t.minFilter = THREE.LinearMipmapLinearFilter;
  t.generateMipmaps = true;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  if (THREE.sRGBEncoding) t.encoding = THREE.sRGBEncoding;
  return t;
}
function speckle(g, colors, cnt, s, size) {
  size = size || 64;
  for (var i = 0; i < cnt; i++) {
    g.fillStyle = colors[(Math.random() * colors.length) | 0];
    g.fillRect((Math.random() * size) | 0, (Math.random() * size) | 0, s || 2, s || 2);
  }
}
/* AO 暗边：贴片四周微暗，模拟环境光遮蔽，增强体素块立体感 */
function aoEdge(g, size, a) {
  a = a || 0.08;
  var st = 2;
  g.fillStyle = 'rgba(24,18,48,' + a + ')';
  g.fillRect(0, 0, size, st); g.fillRect(0, size - st, size, st);
  g.fillRect(0, 0, st, size); g.fillRect(size - st, 0, st, size);
}
/* 草地：底色 + 双层噪点 + 草丛簇 + 零星小花 */
function texGrass(c1, c2, c3, blades) {
  return pixTex(function (g, N) {
    g.fillStyle = c1; g.fillRect(0, 0, N, N);
    speckle(g, [c2, c3], N * 3, 2, N);
    speckle(g, [c2], N, 1, N);
    g.fillStyle = c3;
    var bn = blades == null ? 26 : blades;
    for (var i = 0; i < bn; i++) {
      var x = (Math.random() * (N - 4)) | 0, y = (Math.random() * (N - 5)) | 0;
      g.fillRect(x + 1, y, 1, 4); g.fillRect(x, y + 1, 1, 3); g.fillRect(x + 2, y + 1, 1, 3);
    }
    /* 零星小花 */
    for (i = 0; i < 3; i++) {
      if (Math.random() < 0.5) continue;
      g.fillStyle = Math.random() > 0.5 ? '#f5e9a8' : '#f2c6dd';
      var fx = 4 + (Math.random() * (N - 8)) | 0, fy = 4 + (Math.random() * (N - 8)) | 0;
      g.fillRect(fx, fy, 2, 2); g.fillRect(fx - 2, fy, 1, 1); g.fillRect(fx + 3, fy + 1, 1, 1);
    }
    aoEdge(g, N, 0.07);
  });
}
/* 石砖（道路）：交错砖缝 + 细噪点 */
function texBrick(base, seam, alt) {
  return pixTex(function (g, N) {
    g.fillStyle = base; g.fillRect(0, 0, N, N);
    g.fillStyle = seam;
    var rows = 8, rh = N / rows;
    for (var y = 0; y < rows; y++) {
      g.fillRect(0, Math.round(y * rh + rh - 1), N, 1);
      var off = (y % 2) * rh;
      for (var x = 0; x <= rows / 2; x++) {
        g.fillRect(Math.round(x * rh * 2 + off) % N, Math.round(y * rh), 1, Math.round(rh) - 1);
      }
    }
    speckle(g, [alt, base], 44, 1, N);
    /* 井盖点缀 */
    if (Math.random() < 0.6) {
      var mx = 20 + (Math.random() * 24) | 0, my = 20 + (Math.random() * 24) | 0;
      g.fillStyle = '#8d8a9c'; g.fillRect(mx, my, 8, 8);
      g.fillStyle = seam; g.fillRect(mx + 3, my, 2, 8); g.fillRect(mx, my + 3, 8, 2);
    }
    aoEdge(g, N, 0.1);
  });
}
/* 大石板（广场） */
function texSlab(base, seam, alt) {
  return pixTex(function (g, N) {
    g.fillStyle = base; g.fillRect(0, 0, N, N);
    g.fillStyle = seam;
    g.fillRect(0, N / 2 - 1, N, 2); g.fillRect(N / 2 - 1, 0, 2, N);
    g.fillRect(0, N - 1, N, 1); g.fillRect(N - 1, 0, 1, N);
    /* 裂纹 */
    g.fillRect(10 + (Math.random() * 8) | 0, 6, 1, 10);
    g.fillRect(40, 40 + (Math.random() * 8) | 0, 12, 1);
    speckle(g, [alt], 36, 2, N);
    aoEdge(g, N, 0.1);
  });
}
/* 田垄 */
function texField(base, ridge) {
  return pixTex(function (g, N) {
    g.fillStyle = base; g.fillRect(0, 0, N, N);
    g.fillStyle = ridge;
    for (var y = 3; y < N; y += 8) g.fillRect(0, y, N, 2);
    /* 垄上作物点 */
    for (var i = 0; i < 26; i++) {
      g.fillRect((Math.random() * N) | 0, (Math.random() * N) | 0, 2, 3);
    }
    speckle(g, [base], 20, 2, N);
    aoEdge(g, N, 0.06);
  });
}
/* 水波 */
function texWater(c1, c2, c3) {
  return pixTex(function (g, N) {
    g.fillStyle = c1; g.fillRect(0, 0, N, N);
    g.fillStyle = c2;
    for (var y = 0; y < N; y += 10) g.fillRect(0, y, N, 2);
    g.fillStyle = c3;
    for (var i = 0; i < 14; i++) {
      var x = (Math.random() * (N - 10)) | 0, y = (Math.random() * (N - 2)) | 0;
      g.fillRect(x, y, 7, 1); g.fillRect(x + 2, y + 1, 5, 1);
    }
  });
}
/* 木板（桥面/树干） */
function texWood(c1, c2, vertical) {
  return pixTex(function (g, N) {
    g.fillStyle = c1; g.fillRect(0, 0, N, N);
    g.fillStyle = c2;
    if (vertical) { for (var x = 7; x < N; x += 10) g.fillRect(x, 0, 1, N); }
    else { for (var y = 7; y < N; y += 10) g.fillRect(0, y, N, 1); }
    speckle(g, [c2, c1], 34, 1, N);
  });
}
/* 岩壁（顶面） */
function texRock(c1, c2, c3) {
  return pixTex(function (g, N) {
    g.fillStyle = c1; g.fillRect(0, 0, N, N);
    speckle(g, [c2, c3], 130, 3, N);
    g.fillStyle = c2;
    for (var y = 10; y < N; y += 14) {
      var w = (14 + Math.random() * 18) | 0;
      g.fillRect((Math.random() * (N - w)) | 0, y, w, 2);
    }
    speckle(g, [c3], 22, 1, N);
    aoEdge(g, N, 0.12);
  });
}
/* 泥土侧壁：上缘草渍渐变 + 石子 */
function texDirt() {
  return pixTex(function (g, N) {
    g.fillStyle = '#8a6a4a'; g.fillRect(0, 0, N, N);
    speckle(g, ['#7a5c3e', '#9a7856', '#6b4f34'], 120, 2, N);
    speckle(g, ['#a58a68'], 26, 1, N);
    g.fillStyle = 'rgba(110,150,80,.38)';
    g.fillRect(0, 0, N, 5);
    g.fillStyle = 'rgba(110,150,80,.18)';
    g.fillRect(0, 5, N, 3);
  });
}
/* 岩壁侧壁：水平层理 */
function texCliff() {
  return pixTex(function (g, N) {
    g.fillStyle = '#7d7a90'; g.fillRect(0, 0, N, N);
    speckle(g, ['#6b687e', '#8f8ca2', '#5d5a70'], 140, 3, N);
    g.fillStyle = '#5d5a70';
    for (var y = 8; y < N; y += 12) g.fillRect(0, y, N, 2);
    speckle(g, ['#a3a0b2'], 22, 1, N);
  });
}
/* 雪 */
function texSnow() {
  return pixTex(function (g, N) {
    g.fillStyle = '#f4f8ff'; g.fillRect(0, 0, N, N);
    speckle(g, ['#e2ecff', '#ffffff', '#d7e5fa'], 110, 2, N);
    aoEdge(g, N, 0.05);
  });
}
/* 建筑墙：白底 + 双排窗（框/玻璃/反光/窗台）+ 楼层线 */
function texWindows() {
  return pixTex(function (g, N) {
    g.fillStyle = '#ffffff'; g.fillRect(0, 0, N, N);
    speckle(g, ['#f2f2f5', '#eaeaf0'], 50, 2, N);
    var wx = [6, 40], wy = [10, 40];
    for (var r = 0; r < 2; r++) for (var c = 0; c < 2; c++) {
      var x = wx[c], y = wy[r], w2 = 18, h2 = 16;
      g.fillStyle = '#c8c9d8'; g.fillRect(x - 2, y - 2, w2 + 4, h2 + 4);
      g.fillStyle = '#3d4b77'; g.fillRect(x, y, w2, h2);
      g.fillStyle = '#5d6ea0'; g.fillRect(x + 1, y + 1, w2 - 2, 5);
      g.fillStyle = '#aeb8d8'; g.fillRect(x + w2 / 2 - 1, y, 2, h2);
      g.fillStyle = '#d9dae6'; g.fillRect(x - 3, y + h2 + 2, w2 + 6, 3);
    }
    g.fillStyle = '#d8d8e2'; g.fillRect(0, 34, N, 2);
    aoEdge(g, N, 0.06);
  });
}
function texWindowGlow() {
  return pixTex(function (g, N) {
    g.fillStyle = '#000000'; g.fillRect(0, 0, N, N);
    var wx = [6, 40], wy = [10, 40];
    var cols = ['#ffca7a', '#ffc06a', '#ffd98f', '#ffb45e'];
    for (var r = 0; r < 2; r++) for (var c = 0; c < 2; c++) {
      if (Math.random() > 0.38) {
        g.fillStyle = cols[(Math.random() * cols.length) | 0];
        g.fillRect(wx[c], wy[r], 18, 16);
      }
    }
  });
}
/* 屋顶瓦：横瓦垄 + 错缝竖钉 + 微高光 */
function texRoof(base, seam) {
  return pixTex(function (g, N) {
    g.fillStyle = base; g.fillRect(0, 0, N, N);
    g.fillStyle = seam;
    for (var y = 4; y < N; y += 8) g.fillRect(0, y, N, 2);
    for (y = 0; y < N; y += 8) {
      var off = ((y / 8) % 2) * 8;
      for (var x = 0; x < N; x += 16) g.fillRect((x + off) % N, y, 2, 8);
    }
    g.fillStyle = 'rgba(255,255,255,.10)';
    for (y = 0; y < N; y += 8) g.fillRect(0, y, N, 1);
  });
}
/* 树叶 */
function texLeaf(c1, c2) {
  return pixTex(function (g, N) {
    g.fillStyle = c1; g.fillRect(0, 0, N, N);
    speckle(g, [c2, c1, c2], 240, 2, N);
    speckle(g, [c2], 34, 1, N);
    aoEdge(g, N, 0.1);
  });
}

/* ---------- 写实风新增纹理 ---------- */
/* 地表细节噪点（与顶点色相乘，防大色块呆板） */
function texDetail() {
  var c = document.createElement('canvas');
  c.width = c.height = 128;
  var g = c.getContext('2d');
  g.fillStyle = '#ffffff'; g.fillRect(0, 0, 128, 128);
  for (var i = 0; i < 1500; i++) {
    var a = 0.03 + Math.random() * 0.08;
    g.fillStyle = Math.random() > 0.4 ? 'rgba(30,40,30,' + a + ')' : 'rgba(255,255,255,' + a + ')';
    g.fillRect((Math.random() * 128) | 0, (Math.random() * 128) | 0, 1 + (Math.random() * 2 | 0), 1 + (Math.random() * 2 | 0));
  }
  var t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  if (THREE.sRGBEncoding) t.encoding = THREE.sRGBEncoding;
  return t;
}
/* 动漫脸贴片（透明底：眼/眉/嘴/腮红） */
function texFace() {
  var c = document.createElement('canvas');
  c.width = c.height = 64;
  var g = c.getContext('2d');
  function eye(cx) {
    g.fillStyle = '#fff';
    g.beginPath(); g.ellipse(cx, 36, 4.6, 5.8, 0, 0, 6.29); g.fill();
    g.fillStyle = '#3d6bd6';
    g.beginPath(); g.ellipse(cx, 36.5, 3.4, 4.6, 0, 0, 6.29); g.fill();
    g.fillStyle = '#1a2a5e';
    g.beginPath(); g.ellipse(cx, 37, 1.7, 2.6, 0, 0, 6.29); g.fill();
    g.fillStyle = '#fff';
    g.beginPath(); g.ellipse(cx - 1.2, 34.4, 1.1, 1.4, 0, 0, 6.29); g.fill();
  }
  eye(23); eye(41);
  g.strokeStyle = '#4a3b33'; g.lineWidth = 1.4; g.lineCap = 'round';
  g.beginPath(); g.moveTo(19, 27); g.quadraticCurveTo(23, 25, 27, 27); g.stroke();
  g.beginPath(); g.moveTo(37, 27); g.quadraticCurveTo(41, 25, 45, 27); g.stroke();
  g.strokeStyle = '#c96a6a'; g.lineWidth = 1.6;
  g.beginPath(); g.moveTo(29, 48); g.quadraticCurveTo(32, 50.5, 35, 48); g.stroke();
  g.fillStyle = 'rgba(244,150,150,.45)';
  g.beginPath(); g.ellipse(13, 44, 3.6, 2.2, 0, 0, 6.29); g.fill();
  g.beginPath(); g.ellipse(51, 44, 3.6, 2.2, 0, 0, 6.29); g.fill();
  var t = new THREE.CanvasTexture(c);
  t.minFilter = THREE.LinearFilter;
  return t;
}
/* 草簇叶片（透明底，alphaTest 用） */
function texBlades() {
  var c = document.createElement('canvas');
  c.width = c.height = 64;
  var g = c.getContext('2d');
  var cols = ['#5aa84e', '#6cbc58', '#7ecb62', '#4f9a46'];
  for (var i = 0; i < 11; i++) {
    var bx = 4 + Math.random() * 56;
    var tip = bx + (Math.random() - 0.5) * 22;
    var top = 6 + Math.random() * 14;
    var wd = 2.5 + Math.random() * 2.5;
    g.fillStyle = cols[(Math.random() * cols.length) | 0];
    g.beginPath();
    g.moveTo(bx - wd, 64);
    g.lineTo(bx + wd, 64);
    g.lineTo(tip + 0.6, top);
    g.lineTo(tip - 0.6, top + 2);
    g.closePath(); g.fill();
  }
  var t = new THREE.CanvasTexture(c);
  t.minFilter = THREE.LinearMipmapLinearFilter;
  t.magFilter = THREE.NearestFilter;
  if (THREE.sRGBEncoding) t.encoding = THREE.sRGBEncoding;
  return t;
}
/* 卡通 Toon 四档渐变（原神式硬边分段 + 暗部偏蓝紫 / 亮部偏暖）
   由 MeshToonMaterial.gradientMap 按"光照系数"采样：
   0=暗面 / 1=次暗 / 2=中间 / 3=亮面。NearestFilter 保留硬边分段感 */
var gradTexSingleton = null;
function getGradTex() {
  if (gradTexSingleton) return gradTexSingleton;
  /* 4 像素 × 1：暗→亮，暗部蓝紫、亮部暖白 */
  var d = new Uint8Array([
    104, 110, 140,  /* 0 暗面：深 + 蓝紫 */
    158, 160, 178,  /* 1 次暗 */
    217, 214, 224,  /* 2 中间 */
    255, 250, 240   /* 3 亮面：暖白 */
  ]);
  var t = new THREE.DataTexture(d, 4, 1, THREE.RGBFormat);
  t.minFilter = t.magFilter = THREE.NearestFilter;
  t.needsUpdate = true;
  t._shared = true;
  gradTexSingleton = t;
  return t;
}

/* 世界表面 Toon 材质工厂：与 MeshLambertMaterial 同入参（color/map/emissive/
   emissiveMap/emissiveIntensity/vertexColors/side/transparent/opacity 等），
   额外挂上四段 Ramp，得到原神式卡通渲染。windSway() 仍可对其 onBeforeCompile
   注入风摆，兼容 InstancedMesh 实例相位差 */
function toonMat(opts) {
  var m = new THREE.MeshToonMaterial(opts);
  m.gradientMap = getGradTex();
  return m;
}

/* 原神式角色描边：反向法线 BackSide 扩边壳（深紫黑平涂材质，非纯黑更接近原神） */
var OUTLINE_MAT = null;
function getOutlineMat() {
  if (OUTLINE_MAT) return OUTLINE_MAT;
  OUTLINE_MAT = new THREE.MeshBasicMaterial({
    color: 0x1a1430, side: THREE.BackSide, transparent: true, opacity: 0.92, depthWrite: false
  });
  OUTLINE_MAT._shared = true;
  return OUTLINE_MAT;
}

/* 纹理缓存 */
var TEX = null;
function buildTextures() {
  if (TEX) return TEX;
  TEX = {
    waterSurf: texWater('#62b4e0', '#8fd0ee', '#b8e4f8'),
    wall: texWindows(),
    wallGlow: texWindowGlow(),
    detail: texDetail(),
    face: texFace(),
    blades: texBlades()
  };
  TEX.detail.repeat.set(72, 72);
  return TEX;
}

/* ================= 工具(精灵) ================= */
function emojiTex(ch) {
  if (EMOJI_TEX[ch]) return EMOJI_TEX[ch];
  var c = document.createElement('canvas');
  c.width = c.height = 64;
  var g = c.getContext('2d');
  g.font = '46px "Segoe UI Emoji","Apple Color Emoji",sans-serif';
  g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(ch, 32, 34);
  var t = new THREE.CanvasTexture(c);
  t.minFilter = THREE.LinearFilter;
  if (THREE.sRGBEncoding) t.encoding = THREE.sRGBEncoding;
  EMOJI_TEX[ch] = t;
  return t;
}
function makeSprite(tex, scale, color) {
  var m = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false });
  if (color) m.color = new THREE.Color(color);
  var s = new THREE.Sprite(m);
  s.scale.set(scale, scale, 1);
  return s;
}
var _radialCache = {};
function radialTex(inner, outer) {
  /* 按参数缓存：世界重建（地形编辑每 0.25s 全量重建）时不再反复生成 CanvasTexture，
     旧纹理无人 dispose 会在 GPU 侧持续累积 */
  var key = inner + '|' + outer;
  if (_radialCache[key]) return _radialCache[key];
  var c = document.createElement('canvas');
  c.width = c.height = 64;
  var g = c.getContext('2d');
  var gr = g.createRadialGradient(32, 32, 2, 32, 32, 31);
  gr.addColorStop(0, inner);
  gr.addColorStop(1, outer);
  g.fillStyle = gr;
  g.fillRect(0, 0, 64, 64);
  var t = new THREE.CanvasTexture(c);
  if (THREE.sRGBEncoding) t.encoding = THREE.sRGBEncoding;
  _radialCache[key] = t;
  return t;
}

/* ================= 场景构建 ================= */
function buildScene() {
  var THREE = window.THREE;
  sceneBuilt = true;
  dirtyEdit = dirtyExplore = false;

  var refs = E._gridRefs && E._gridRefs();
  if (!refs) { active = false; return; }
  biomeArr = refs.biome; decorArr = refs.decor; explored = refs.explored;
  MWv = D.MAP_W; MHv = D.MAP_H;
  exploredShadow = new Uint8Array(explored);
  unexploredColor = new THREE.Color('#efeaf7');

  buildTextures();
  rebuildWorld();
  buildLights();
  buildSky();
  buildPlayer();
  var st = E.state();
  camLook.x = st.player.x; camLook.z = st.player.y; camLook.y = 0;
}

function disposeWorld() {
  if (!worldGroup) return;
  worldGroup.traverse(function (o) {
    if (o.isInstancedMesh && o.dispose) o.dispose();
    if (o.geometry && !o.geometry._shared) o.geometry.dispose();
    if (o.material) {
      if (Array.isArray(o.material)) {
        for (var i = 0; i < o.material.length; i++) {
          if (o.material[i].dispose && !o.material[i]._shared) o.material[i].dispose();
        }
      } else if (o.material.dispose && !o.material._shared) o.material.dispose();
    }
  });
  scene.remove(worldGroup);
  worldGroup = null;
  lampPoints = null;   /* geometry/material 已随上面 traverse 释放 */
  lampGlows = [];
  terrainByBiome = {};
}

/* ---------- 地形 + 装饰 + 地标（整体重建） ---------- */
/* 模块级单例几何体（跨 rebuild 复用，避免泄漏） */
var boxGeoSingleton = null, surfGeoSingleton = null;
var cylGeoSingletons = {}, icoGeoSingletons = {}, coneGeoSingletons = {};
function getBoxGeo() {
  if (!boxGeoSingleton) {
    boxGeoSingleton = new THREE.BoxGeometry(1, 1, 1);
    boxGeoSingleton._shared = true;
  }
  return boxGeoSingleton;
}
function getSurfGeo() {
  if (!surfGeoSingleton) {
    surfGeoSingleton = new THREE.BoxGeometry(0.995, 0.05, 0.995);
    surfGeoSingleton._shared = true;
  }
  return surfGeoSingleton;
}
/* 圆柱：rt 顶半径 rb 底半径 h 高 seg 边数 */
function getCyl(rt, rb, h, seg) {
  var k = rt + '_' + rb + '_' + h + '_' + seg;
  if (!cylGeoSingletons[k]) {
    cylGeoSingletons[k] = new THREE.CylinderGeometry(rt, rb, h, seg);
    cylGeoSingletons[k]._shared = true;
  }
  return cylGeoSingletons[k];
}
/* 球体（细分 1 的二十面体，圆润有机） */
function getIco(r) {
  if (!icoGeoSingletons[r]) {
    icoGeoSingletons[r] = new THREE.IcosahedronGeometry(r, 1);
    icoGeoSingletons[r]._shared = true;
  }
  return icoGeoSingletons[r];
}
function getSph(r, w, hs) {
  var k = r + '_' + (w || 12) + '_' + (hs || 10);
  if (!icoGeoSingletons[k]) {
    icoGeoSingletons[k] = new THREE.SphereGeometry(r, w || 12, hs || 10);
    icoGeoSingletons[k]._shared = true;
  }
  return icoGeoSingletons[k];
}
/* 锥体：r 底半径 h 高 seg 边数（seg=4 且旋 45° 为四坡屋顶） */
function getCone(r, h, seg, rot45) {
  var k = r + '_' + h + '_' + seg + '_' + (rot45 ? 1 : 0);
  if (!coneGeoSingletons[k]) {
    var g = new THREE.ConeGeometry(r, h, seg);
    if (rot45) g.rotateY(Math.PI / 4);
    g._shared = true;
    coneGeoSingletons[k] = g;
  }
  return coneGeoSingletons[k];
}
/* 草簇交叉面片几何（两片 90° 交叉竖面） */
var crossGeoSingleton = null;
function getCrossGeo() {
  if (crossGeoSingleton) return crossGeoSingleton;
  var w = 0.4, hh = 0.55;
  var g = new THREE.BufferGeometry();
  var p = new Float32Array([
    -w, 0, 0,  w, 0, 0,  w, hh, 0,  -w, hh, 0,
    0, 0, -w,  0, 0, w,  0, hh, w,  0, hh, -w
  ]);
  var uv = new Float32Array([0, 0, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1]);
  g.setIndex([0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7]);
  g.setAttribute('position', new THREE.BufferAttribute(p, 3));
  g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
  g.computeVertexNormals();
  g._shared = true;
  crossGeoSingleton = g;
  return g;
}

function rebuildWorld() {
  var THREE = window.THREE;
  disposeWorld();
  worldGroup = new THREE.Group();
  scene.add(worldGroup);

  var S = buildTextures();
  var boxGeo = getBoxGeo();

  /* --- 统计（全图构建，未探索区域由云雾盖遮挡 → 探索时无需重建） --- */
  var buildList = [], waterTiles = [];
  var x, y, i;
  for (i = 0; i < MWv * MHv; i++) {
    var b0 = biomeArr[i];
    if (b0 === B.BUILD) buildList.push({ x: i % MWv, y: (i / MWv) | 0 });
    else if (b0 === B.WATER || b0 === B.DEEP) waterTiles.push(i);
  }

  /* --- 连续平滑地形网格：顶点色 + 微起伏 + 边界裙边（圆润丘陵/自然河岸） --- */
  var geo = new THREE.PlaneGeometry(MWv, MHv, MWv, MHv);
  geo.rotateX(-Math.PI / 2);
  geo.translate(MWv / 2, 0, MHv / 2);
  var pos = geo.attributes.position;
  var colArr = new Float32Array(pos.count * 3);
  var bo = { h: 0, col: null };
  var HARD = {}; HARD[B.ROAD] = HARD[B.PLAZA] = HARD[B.FLOOR] = HARD[B.BRIDGE] = HARD[B.BUILD] = 1;
  var ROCKY = {}; ROCKY[B.MOUNT] = ROCKY[B.SNOW] = ROCKY[B.HILL] = 1;
  for (var vi = 0; vi < pos.count; vi++) {
    var vx = pos.getX(vi), vz = pos.getZ(vi);
    blendCorner(vx, vz, bo);
    var h = bo.h;
    var tb = biomeArr[(clamp(Math.round(vz), 0, MHv - 1) | 0) * MWv + (clamp(Math.round(vx), 0, MWv - 1) | 0)];
    var jit = HARD[tb] ? 0.012 : ROCKY[tb] ? 0.15 : 0.06;
    h += (hash2(Math.round(vx * 4), Math.round(vz * 4), 7) - 0.5) * jit;
    if (vx <= 0.01 || vz <= 0.01 || vx >= MWv - 0.01 || vz >= MHv - 0.01) h -= 2.4;
    pos.setY(vi, h);
    colArr[vi * 3] = bo.col.r; colArr[vi * 3 + 1] = bo.col.g; colArr[vi * 3 + 2] = bo.col.b;
  }
  geo.setAttribute('color', new THREE.BufferAttribute(colArr, 3));
  geo.computeVertexNormals();
  terrainMesh = new THREE.Mesh(geo, toonMat({ vertexColors: true, map: S.detail }));
  terrainMesh.receiveShadow = true;
  terrainMesh.frustumCulled = false;
  worldGroup.add(terrainMesh);

  /* --- 未探索云雾盖（白色厚块即"云海"，探索后即时消散） --- */
  fogMesh = new THREE.InstancedMesh(boxGeo, new THREE.MeshLambertMaterial({ color: 0xf2f0f7 }), MWv * MHv);
  rebuildFogMesh();
  worldGroup.add(fogMesh);

  /* --- 水面薄片：主层 + 高光层（错位 UV 反向流动 → 波光粼粼） --- */
  var surfGeo = getSurfGeo();
  waterSurfMat = new THREE.MeshPhongMaterial({
    map: S.waterSurf, transparent: true, opacity: 0.72, shininess: 90, specular: 0x9fd4f0
  });
  waterSurfMesh = new THREE.InstancedMesh(surfGeo, waterSurfMat, Math.max(1, waterTiles.length));
  for (var v = 0; v < waterTiles.length; v++) {
    var wi = waterTiles[v], wx = wi % MWv, wy = (wi / MWv) | 0;
    tmpM.makeScale(1, 1, 1);
    tmpM.setPosition(wx + 0.5, biomeTop(biomeArr[wi]) + 0.1, wy + 0.5);
    waterSurfMesh.setMatrixAt(v, tmpM);
  }
  waterSurfMesh.count = waterTiles.length;
  waterSurfMesh.instanceMatrix.needsUpdate = true;
  waterSurfMesh.frustumCulled = false;
  worldGroup.add(waterSurfMesh);

  var surfTex2 = S.waterSurf.clone();
  surfTex2.needsUpdate = true;
  waterSurf2Mat = new THREE.MeshPhongMaterial({
    map: surfTex2, transparent: true, opacity: 0.3, depthWrite: false, shininess: 120, specular: 0xcfeaff
  });
  waterSurf2Mesh = new THREE.InstancedMesh(surfGeo, waterSurf2Mat, Math.max(1, waterTiles.length));
  for (v = 0; v < waterTiles.length; v++) {
    var wi2 = waterTiles[v], wx2 = wi2 % MWv, wy2 = (wi2 / MWv) | 0;
    tmpM.makeScale(0.92, 1, 0.92);
    tmpM.setPosition(wx2 + 0.5, biomeTop(biomeArr[wi2]) + 0.15, wy2 + 0.5);
    waterSurf2Mesh.setMatrixAt(v, tmpM);
  }
  waterSurf2Mesh.count = waterTiles.length;
  waterSurf2Mesh.instanceMatrix.needsUpdate = true;
  waterSurf2Mesh.frustumCulled = false;
  worldGroup.add(waterSurf2Mesh);

  /* --- 岸线泡沫：水 tile 贴陆边白色窄条 --- */
  var foamDefs = [];
  var upY = new THREE.Vector3(0, 1, 0);
  for (v = 0; v < waterTiles.length; v++) {
    var fi2 = waterTiles[v], fx2 = fi2 % MWv, fy2 = (fi2 / MWv) | 0;
    var dirs = [];
    if (fy2 > 0 && biomeArr[fi2 - MWv] !== B.WATER && biomeArr[fi2 - MWv] !== B.DEEP) dirs.push(0);
    if (fy2 < MHv - 1 && biomeArr[fi2 + MWv] !== B.WATER && biomeArr[fi2 + MWv] !== B.DEEP) dirs.push(1);
    if (fx2 > 0 && biomeArr[fi2 - 1] !== B.WATER && biomeArr[fi2 - 1] !== B.DEEP) dirs.push(2);
    if (fx2 < MWv - 1 && biomeArr[fi2 + 1] !== B.WATER && biomeArr[fi2 + 1] !== B.DEEP) dirs.push(3);
    for (var d3 = 0; d3 < dirs.length; d3++) foamDefs.push({ x: fx2, y: fy2, d: dirs[d3] });
  }
  var foamMat = new THREE.MeshBasicMaterial({ color: 0xeef8ff, transparent: true, opacity: 0.55, depthWrite: false });
  foamMesh = new THREE.InstancedMesh(boxGeo, foamMat, Math.max(1, foamDefs.length));
  for (v = 0; v < foamDefs.length; v++) {
    var fd = foamDefs[v];
    var cx2 = fd.x + 0.5, cz2 = fd.y + 0.5;
    var rotY = 0;
    if (fd.d === 0) { cz2 = fd.y + 0.1; }
    else if (fd.d === 1) { cz2 = fd.y + 0.9; }
    else if (fd.d === 2) { cx2 = fd.x + 0.1; rotY = Math.PI / 2; }
    else { cx2 = fd.x + 0.9; rotY = Math.PI / 2; }
    tmpQ.setFromAxisAngle(upY, rotY);
    tmpV.set(cx2, biomeTop(biomeArr[fd.y * MWv + fd.x]) + 0.135, cz2);
    tmpS.set(0.98, 0.03, 0.14);
    tmpM.compose(tmpV, tmpQ, tmpS);
    foamMesh.setMatrixAt(v, tmpM);
  }
  foamMesh.count = foamDefs.length;
  foamMesh.instanceMatrix.needsUpdate = true;
  foamMesh.frustumCulled = false;
  worldGroup.add(foamMesh);

  /* --- 建筑：白墙+石基座+檐口+四坡尖顶/平顶水箱+门框雨棚+POI招牌+烟囱 --- */
  var pois = D.POIS;
  buildWallMat = toonMat({
    map: S.wall, emissiveMap: S.wallGlow, emissive: 0xffb570, emissiveIntensity: 0
  });
  buildWallMesh = new THREE.InstancedMesh(boxGeo, buildWallMat, Math.max(1, buildList.length));
  buildRoofMesh = new THREE.InstancedMesh(getCone(0.8, 0.55, 4, true), toonMat({ color: 0xffffff }), Math.max(1, buildList.length));
  var eaveMesh2 = new THREE.InstancedMesh(boxGeo, toonMat({ color: 0x6b5138 }), Math.max(1, buildList.length));
  var baseMesh2 = new THREE.InstancedMesh(boxGeo, toonMat({ color: 0xb8b2a6 }), Math.max(1, buildList.length));
  doorMesh = new THREE.InstancedMesh(boxGeo, toonMat({ color: 0x5f4632 }), Math.max(1, buildList.length));
  var frameMesh2 = new THREE.InstancedMesh(boxGeo, toonMat({ color: 0x7a5f42 }), Math.max(1, buildList.length * 3));
  var awnMesh2 = new THREE.InstancedMesh(boxGeo, toonMat({ color: 0xc95f4e, side: THREE.DoubleSide }), Math.max(1, buildList.length));
  var signMesh2 = new THREE.InstancedMesh(boxGeo, toonMat({ color: 0xffffff, emissive: 0x584e6e, emissiveIntensity: 0.4 }), Math.max(1, buildList.length));
  var tankMesh2 = new THREE.InstancedMesh(getCyl(0.11, 0.11, 0.22, 8), toonMat({ color: 0x9aa4ae }), Math.max(1, buildList.length));
  var tankCap2 = new THREE.InstancedMesh(getCone(0.125, 0.09, 8, false), toonMat({ color: 0x77828c }), Math.max(1, buildList.length));
  var chimList = [];
  var upY2 = new THREE.Vector3(0, 1, 0);
  var nFrame = 0, nAwn = 0, nSign = 0, nTank = 0;
  for (i = 0; i < buildList.length; i++) {
    var t2 = buildList[i];
    var bh = 1.9 + hash2(t2.x, t2.y, 313) * 1.4;
    var pc = null;
    for (var p = 0; p < pois.length; p++) {
      var poi = pois[p];
      if (poi.type !== 'build' && poi.type !== 'bridge') continue;
      if (t2.x >= poi.x && t2.x < poi.x + (poi.w || 1) && t2.y >= poi.y && t2.y < poi.y + (poi.h || 1)) {
        pc = poi.color || '#b9a6dd'; break;
      }
    }
    if (pc) bh = 2.2 + hash2(t2.x, t2.y, 314) * 0.8;
    var gy = groundTop(t2.x, t2.y);
    /* 墙体（下埋 0.35 防坡地悬空） */
    tmpM.makeScale(0.94, bh + 0.35, 0.94);
    tmpM.setPosition(t2.x + 0.5, gy + (bh + 0.35) / 2 - 0.35, t2.y + 0.5);
    buildWallMesh.setMatrixAt(i, tmpM);
    /* 石基座 */
    tmpM.makeScale(1.0, 0.3, 1.0);
    tmpM.setPosition(t2.x + 0.5, gy + 0.13, t2.y + 0.5);
    baseMesh2.setMatrixAt(i, tmpM);
    /* 檐口圈 */
    tmpM.makeScale(1.06, 0.09, 1.06);
    tmpM.setPosition(t2.x + 0.5, gy + bh, t2.y + 0.5);
    eaveMesh2.setMatrixAt(i, tmpM);
    /* 屋顶：POI/多数建筑四坡尖顶；30% 民宅平顶+水箱 */
    var flat = !pc && hash2(t2.x, t2.y, 88) < 0.3;
    if (!flat) {
      var rs = 0.86 + hash2(t2.x, t2.y, 89) * 0.14;
      tmpM.makeScale(rs, 0.85 + hash2(t2.x, t2.y, 90) * 0.3, rs);
      tmpM.setPosition(t2.x + 0.5, gy + bh + 0.3, t2.y + 0.5);
      buildRoofMesh.setMatrixAt(i, tmpM);
      buildRoofMesh.setColorAt(i, tmpC.set(pc || '#b0524a'));
    } else {
      tmpM.makeScale(0.01, 0.01, 0.01);
      tmpM.setPosition(0, -10, 0);
      buildRoofMesh.setMatrixAt(i, tmpM);
      var tox = hash2(t2.x, t2.y, 95) > 0.5 ? 0.24 : -0.24;
      var toz = hash2(t2.x, t2.y, 96) > 0.5 ? 0.24 : -0.24;
      tmpM.makeScale(1, 1, 1);
      tmpM.setPosition(t2.x + 0.5 + tox, gy + bh + 0.2, t2.y + 0.5 + toz);
      tankMesh2.setMatrixAt(nTank, tmpM);
      tmpM.makeScale(1, 1, 1);
      tmpM.setPosition(t2.x + 0.5 + tox, gy + bh + 0.36, t2.y + 0.5 + toz);
      tankCap2.setMatrixAt(nTank, tmpM);
      nTank++;
    }
    /* 门 + 门框(2柱1梁) + 雨棚 + POI 招牌 */
    var rot4 = (hash2(t2.x, t2.y, 77) * 4) | 0;
    var ddx = 0, ddz = 0;
    if (rot4 === 0) ddz = -1; else if (rot4 === 2) ddz = 1; else if (rot4 === 1) ddx = -1; else ddx = 1;
    var pgx = -ddz, pgz = ddx;
    var dwx = t2.x + 0.5 + ddx * 0.472, dwz = t2.y + 0.5 + ddz * 0.472;
    tmpQ.setFromAxisAngle(upY2, rot4 * Math.PI / 2);
    tmpV.set(dwx, gy + 0.36, dwz);
    tmpS.set(0.26, 0.56, 0.06);
    tmpM.compose(tmpV, tmpQ, tmpS);
    doorMesh.setMatrixAt(i, tmpM);
    for (var f2 = 0; f2 < 3; f2++) {
      if (f2 < 2) {
        var side = f2 === 0 ? -0.18 : 0.18;
        tmpV.set(dwx + pgx * side, gy + 0.38, dwz + pgz * side);
        tmpS.set(0.07, 0.72, 0.07);
      } else {
        tmpV.set(dwx, gy + 0.74, dwz);
        tmpS.set(0.46, 0.07, 0.07);
      }
      tmpM.compose(tmpV, tmpQ, tmpS);
      frameMesh2.setMatrixAt(nFrame++, tmpM);
    }
    tmpV.set(dwx + ddx * 0.1, gy + 0.83, dwz + ddz * 0.1);
    tmpS.set(0.46, 0.04, 0.3);
    tmpM.compose(tmpV, tmpQ, tmpS);
    awnMesh2.setMatrixAt(nAwn++, tmpM);
    if (pc) {
      tmpV.set(dwx + pgx * 0.27, gy + 0.66, dwz + pgz * 0.27);
      tmpS.set(0.2, 0.34, 0.05);
      tmpM.compose(tmpV, tmpQ, tmpS);
      signMesh2.setMatrixAt(nSign, tmpM);
      signMesh2.setColorAt(nSign, tmpC.set(pc));
      nSign++;
    }
    /* 烟囱 35%（圆柱+小帽） */
    if (hash2(t2.x, t2.y, 79) < 0.35) chimList.push({ x: t2.x + 0.5 + (hash2(t2.x, t2.y, 80) > 0.5 ? 0.3 : -0.3), y: gy + bh + 0.3, z: t2.y + 0.5 + (hash2(t2.x, t2.y, 82) > 0.5 ? 0.3 : -0.3) });
  }
  buildWallMesh.count = baseMesh2.count = eaveMesh2.count = buildRoofMesh.count = doorMesh.count = buildList.length;
  frameMesh2.count = nFrame; awnMesh2.count = nAwn; signMesh2.count = nSign;
  tankMesh2.count = tankCap2.count = nTank;
  buildWallMesh.instanceMatrix.needsUpdate = true;
  buildRoofMesh.instanceMatrix.needsUpdate = true;
  eaveMesh2.instanceMatrix.needsUpdate = true;
  baseMesh2.instanceMatrix.needsUpdate = true;
  doorMesh.instanceMatrix.needsUpdate = true;
  frameMesh2.instanceMatrix.needsUpdate = true;
  awnMesh2.instanceMatrix.needsUpdate = true;
  signMesh2.instanceMatrix.needsUpdate = true;
  tankMesh2.instanceMatrix.needsUpdate = tankCap2.instanceMatrix.needsUpdate = true;
  if (buildRoofMesh.instanceColor) buildRoofMesh.instanceColor.needsUpdate = true;
  if (signMesh2.instanceColor) signMesh2.instanceColor.needsUpdate = true;
  buildWallMesh.frustumCulled = buildRoofMesh.frustumCulled = false;
  eaveMesh2.frustumCulled = baseMesh2.frustumCulled = doorMesh.frustumCulled = false;
  frameMesh2.frustumCulled = awnMesh2.frustumCulled = signMesh2.frustumCulled = false;
  tankMesh2.frustumCulled = tankCap2.frustumCulled = false;
  buildWallMesh.castShadow = buildRoofMesh.castShadow = eaveMesh2.castShadow = true;
  tankMesh2.castShadow = true;
  worldGroup.add(buildWallMesh); worldGroup.add(buildRoofMesh);
  worldGroup.add(eaveMesh2); worldGroup.add(baseMesh2);
  worldGroup.add(doorMesh); worldGroup.add(frameMesh2);
  worldGroup.add(awnMesh2); worldGroup.add(signMesh2);
  worldGroup.add(tankMesh2); worldGroup.add(tankCap2);

  /* 烟囱（圆柱+锥帽） */
  var chimMat = toonMat({ color: 0x9c5a4a });
  chimMesh = new THREE.InstancedMesh(getCyl(0.09, 0.11, 0.62, 6), chimMat, Math.max(1, chimList.length));
  var chimCapMesh = new THREE.InstancedMesh(getCone(0.14, 0.1, 6, false), toonMat({ color: 0x7a4a3e }), Math.max(1, chimList.length));
  for (i = 0; i < chimList.length; i++) {
    tmpM.makeScale(1, 1, 1);
    tmpM.setPosition(chimList[i].x, chimList[i].y, chimList[i].z);
    chimMesh.setMatrixAt(i, tmpM);
    tmpM.makeScale(1, 1, 1);
    tmpM.setPosition(chimList[i].x, chimList[i].y + 0.36, chimList[i].z);
    chimCapMesh.setMatrixAt(i, tmpM);
  }
  chimMesh.count = chimCapMesh.count = chimList.length;
  chimMesh.instanceMatrix.needsUpdate = true;
  chimCapMesh.instanceMatrix.needsUpdate = true;
  chimMesh.frustumCulled = chimCapMesh.frustumCulled = false;
  chimMesh.castShadow = true;
  worldGroup.add(chimMesh); worldGroup.add(chimCapMesh);

  buildDecor(boxGeo);
  buildLandmarks();
  buildLampSprites();
}

/* 云雾盖实例重建（探索推进时只更新雾，不重建世界） */
function rebuildFogMesh() {
  if (!fogMesh) return;
  var S = E && E.state ? E.state() : null;
  if (S && S.revealMap) { fogMesh.count = 0; fogMesh.instanceMatrix.needsUpdate = true; return; }
  var n = 0;
  for (var i2 = 0; i2 < MWv * MHv; i2++) {
    if (explored[i2]) continue;
    var fx = i2 % MWv, fy = (i2 / MWv) | 0;
    tmpM.makeScale(1.02, 3.4, 1.02);
    tmpM.setPosition(fx + 0.5, 0.72, fy + 0.5);
    fogMesh.setMatrixAt(n++, tmpM);
  }
  fogMesh.count = n;
  fogMesh.instanceMatrix.needsUpdate = true;
  fogMesh.frustumCulled = false;
}

/* 装饰：写实树（圆柱干+圆润团簇树冠）/ 灌木 / 花 / 石 / 草簇 / 路灯 / 路缘石 */
function buildDecor(boxGeo) {
  var S = buildTextures();
  var upY = new THREE.Vector3(0, 1, 0);
  var trees = [], lamps = [], flowers = [], bushes = [], rocks = [], grassT = [], curbs = [];
  var SOFT = {}; SOFT[B.GRASS] = SOFT[B.PARK] = SOFT[B.SAND] = SOFT[B.HILL] = SOFT[B.FIELD] = SOFT[B.FOREST] = 1;
  var PAVE = {}; PAVE[B.ROAD] = PAVE[B.PLAZA] = PAVE[B.FLOOR] = 1;
  for (var i = 0; i < MWv * MHv; i++) {
    var d = decorArr[i];
    var tx0 = i % MWv, ty0 = (i / MWv) | 0;
    var b0 = biomeArr[i];
    if (d === 1) trees.push(i);
    else if (d === 2) lamps.push(i);
    else if (d === 3) flowers.push(i);
    /* 建模扩展·v2：新 decor 类型映射到现有几何体 */
    else if (d === 4) rocks.push(i);           /* 石头 */
    else if (d === 5) bushes.push(i);          /* 灌木 */
    else if (d === 6) flowers.push(i);         /* 蘑菇（用花几何体） */
    else if (d === 7) curbs.push({ x: tx0, y: ty0, d: 0 }); /* 长椅 */
    else if (d === 8) rocks.push(i);           /* 围栏 */
    else if (d === 9) lamps.push(i);           /* 喷泉（带光） */
    else if (d === 10) rocks.push(i);          /* 摊位 */
    else if (d === 11) lamps.push(i);          /* 路标 */
    else if (d === 12) lamps.push(i);          /* 篝火（带光+暖色） */
    else if (d === 13) trees.push(i);          /* 枯树 */
    else if (d === 14) flowers.push(i);        /* 野花丛 */
    else if (d === 15) lamps.push(i);          /* 古典路灯 */
    else if (d === 0) {
      if (b0 === B.FOREST || b0 === B.PARK || b0 === B.GRASS) {
        var hh = hash2(tx0, ty0, 81);
        if (hh < 0.05) bushes.push(i);
        else if (hh < 0.075) rocks.push(i);
        else if (hh < 0.34) grassT.push(i);
      } else if (SOFT[b0] && b0 !== B.FIELD && hash2(tx0, ty0, 86) < 0.18) grassT.push(i);
    }
    /* 路缘石：铺装面贴软质地表的边 */
    if (PAVE[b0]) {
      if (ty0 > 0 && SOFT[biomeArr[i - MWv]]) curbs.push({ x: tx0, y: ty0, d: 0 });
      if (ty0 < MHv - 1 && SOFT[biomeArr[i + MWv]]) curbs.push({ x: tx0, y: ty0, d: 1 });
      if (tx0 > 0 && SOFT[biomeArr[i - 1]]) curbs.push({ x: tx0, y: ty0, d: 2 });
      if (tx0 < MWv - 1 && SOFT[biomeArr[i + 1]]) curbs.push({ x: tx0, y: ty0, d: 3 });
    }
  }
  var j, ti, tx, ty, gt;

  /* 树分型：55% 阔叶 / 25% 针叶 / 20% 樱花 */
  var tv = [], tc = [], tp = [];
  for (j = 0; j < trees.length; j++) {
    ti = trees[j];
    var h71 = hash2(ti % MWv, (ti / MWv) | 0, 71);
    if (h71 < 0.55) tv.push(ti);
    else if (h71 < 0.8) tc.push(ti);
    else tp.push(ti);
  }

  /* 树干：锥形圆柱（上细下粗）+ 棕色微变 */
  trunkMesh = new THREE.InstancedMesh(getCyl(0.055, 0.1, 1.05, 6), toonMat({ color: 0xffffff }), Math.max(1, trees.length));
  for (j = 0; j < trees.length; j++) {
    ti = trees[j]; tx = ti % MWv; ty = (ti / MWv) | 0;
    gt = groundTop(tx, ty);
    var ts = 0.85 + hash2(tx, ty, 53) * 0.35;
    tmpM.makeScale(ts, ts, ts);
    tmpM.setPosition(tx + 0.5, gt + 0.45 * ts, ty + 0.5);
    trunkMesh.setMatrixAt(j, tmpM);
    var tkc = 0.85 + hash2(tx, ty, 54) * 0.2;
    trunkMesh.setColorAt(j, tmpC.setRGB(tkc * 0.98, tkc * 0.82, tkc * 0.68));
  }
  trunkMesh.count = trees.length;
  trunkMesh.instanceMatrix.needsUpdate = true;
  if (trunkMesh.instanceColor) trunkMesh.instanceColor.needsUpdate = true;
  trunkMesh.frustumCulled = false;
  trunkMesh.castShadow = true;
  worldGroup.add(trunkMesh);

  /* 树冠：阔叶/樱花=主球+两偏移球团簇；针叶=三层锥塔 */
  function crownLayer(arr, hexColor, isConifer) {
    var base = new THREE.Color(hexColor);
    var per = 3;
    var geo = isConifer ? getCone(0.5, 0.72, 7, false) : getIco(0.55);
    var m = new THREE.InstancedMesh(geo, windSway(toonMat({ color: 0xffffff }), isConifer ? 0.028 : 0.06), Math.max(1, arr.length * per));
    for (var k = 0; k < arr.length; k++) {
      var t3 = arr[k], lx = t3 % MWv, ly = (t3 / MWv) | 0;
      var lg = groundTop(lx, ly);
      var sc = 0.85 + hash2(lx, ly, 51) * 0.3;
      if (isConifer) {
        for (var L = 0; L < 3; L++) {
          var ls = sc * (1 - L * 0.24);
          tmpM.makeScale(ls, ls * (1 - L * 0.1), ls);
          tmpM.setPosition(lx + 0.5, lg + 1.12 + L * 0.52, ly + 0.5);
          m.setMatrixAt(k * per + L, tmpM);
        }
      } else {
        tmpM.makeScale(sc, sc * 0.92, sc);
        tmpM.setPosition(lx + 0.5, lg + 1.5, ly + 0.5);
        m.setMatrixAt(k * per, tmpM);
        var ox1 = (hash2(lx, ly, 91) - 0.5) * 0.5, oz1 = (hash2(lx, ly, 92) - 0.5) * 0.5;
        tmpM.makeScale(sc * 0.62, sc * 0.58, sc * 0.62);
        tmpM.setPosition(lx + 0.5 + ox1, lg + 1.26, ly + 0.5 + oz1);
        m.setMatrixAt(k * per + 1, tmpM);
        var ox2 = (hash2(lx, ly, 93) - 0.5) * 0.44, oz2 = (hash2(lx, ly, 94) - 0.5) * 0.44;
        tmpM.makeScale(sc * 0.5, sc * 0.46, sc * 0.5);
        tmpM.setPosition(lx + 0.5 + ox2, lg + 1.78, ly + 0.5 + oz2);
        m.setMatrixAt(k * per + 2, tmpM);
      }
      var tint = 0.86 + hash2(lx, ly, 54) * 0.2;
      for (var ci2 = 0; ci2 < per; ci2++) m.setColorAt(k * per + ci2, tmpC.copy(base).multiplyScalar(tint));
    }
    m.count = arr.length * per;
    m.instanceMatrix.needsUpdate = true;
    if (m.instanceColor) m.instanceColor.needsUpdate = true;
    m.frustumCulled = false;
    m.castShadow = true;
    worldGroup.add(m);
    return m;
  }
  leafDecMesh = crownLayer(tv, '#57b25a', false);
  leafConMesh = crownLayer(tc, '#2f7a4a', true);
  leafChMesh = crownLayer(tp, '#f2a7c3', false);

  /* 路灯：圆盘底座 + 锥杆 + 灯球 + 小锥帽 */
  poleMesh = new THREE.InstancedMesh(getCyl(0.022, 0.034, 1.5, 6), toonMat({ color: 0x4a4453 }), Math.max(1, lamps.length));
  poleBaseMesh = new THREE.InstancedMesh(getCyl(0.1, 0.12, 0.07, 8), toonMat({ color: 0x3a3444 }), Math.max(1, lamps.length));
  headMat = new THREE.MeshBasicMaterial({ color: 0xd8d4e8 });
  lampHeadMesh = new THREE.InstancedMesh(getSph(0.1, 10, 8), headMat, Math.max(1, lamps.length));
  var poleCapMesh = new THREE.InstancedMesh(getCone(0.11, 0.09, 7, false), toonMat({ color: 0x3a3444 }), Math.max(1, lamps.length));
  for (j = 0; j < lamps.length; j++) {
    ti = lamps[j]; tx = ti % MWv; ty = (ti / MWv) | 0;
    gt = groundTop(tx, ty);
    tmpM.makeScale(1, 1, 1);
    tmpM.setPosition(tx + 0.5, gt + 0.035, ty + 0.5);
    poleBaseMesh.setMatrixAt(j, tmpM);
    tmpM.makeScale(1, 1, 1);
    tmpM.setPosition(tx + 0.5, gt + 0.8, ty + 0.5);
    poleMesh.setMatrixAt(j, tmpM);
    tmpM.makeScale(1, 1, 1);
    tmpM.setPosition(tx + 0.5, gt + 1.62, ty + 0.5);
    lampHeadMesh.setMatrixAt(j, tmpM);
    tmpM.makeScale(1, 1, 1);
    tmpM.setPosition(tx + 0.5, gt + 1.76, ty + 0.5);
    poleCapMesh.setMatrixAt(j, tmpM);
    lampGlows.push({ x: tx + 0.5, y: gt + 1.62, z: ty + 0.5 });
  }
  poleMesh.count = poleBaseMesh.count = lampHeadMesh.count = poleCapMesh.count = lamps.length;
  poleMesh.instanceMatrix.needsUpdate = true;
  poleBaseMesh.instanceMatrix.needsUpdate = true;
  lampHeadMesh.instanceMatrix.needsUpdate = true;
  poleCapMesh.instanceMatrix.needsUpdate = true;
  poleMesh.frustumCulled = poleBaseMesh.frustumCulled = lampHeadMesh.frustumCulled = poleCapMesh.frustumCulled = false;
  poleMesh.castShadow = true;
  worldGroup.add(poleMesh); worldGroup.add(poleBaseMesh); worldGroup.add(lampHeadMesh); worldGroup.add(poleCapMesh);

  /* 花：细茎 + 外瓣球 + 内蕊球 */
  stemMesh = new THREE.InstancedMesh(getCyl(0.014, 0.014, 0.24, 5), toonMat({ color: 0x4f8f57 }), Math.max(1, flowers.length));
  petalMesh = new THREE.InstancedMesh(getSph(0.055, 8, 6), toonMat({ color: 0xffffff }), Math.max(1, flowers.length * 2));
  for (j = 0; j < flowers.length; j++) {
    ti = flowers[j]; tx = ti % MWv; ty = (ti / MWv) | 0;
    gt = groundTop(tx, ty);
    tmpM.makeScale(1, 1, 1);
    tmpM.setPosition(tx + 0.5, gt + 0.12, ty + 0.5);
    stemMesh.setMatrixAt(j, tmpM);
    var pcol = hash2(tx, ty, 61) > 0.5 ? '#ef8fb8' : '#f5d76e';
    tmpM.makeScale(1, 0.9, 1);
    tmpM.setPosition(tx + 0.5, gt + 0.26, ty + 0.5);
    petalMesh.setMatrixAt(j * 2, tmpM);
    petalMesh.setColorAt(j * 2, tmpC.set(pcol));
    tmpM.makeScale(0.5, 0.5, 0.5);
    tmpM.setPosition(tx + 0.5, gt + 0.29, ty + 0.5);
    petalMesh.setMatrixAt(j * 2 + 1, tmpM);
    petalMesh.setColorAt(j * 2 + 1, tmpC.set('#fff3c8'));
  }
  stemMesh.count = flowers.length;
  petalMesh.count = flowers.length * 2;
  stemMesh.instanceMatrix.needsUpdate = true;
  petalMesh.instanceMatrix.needsUpdate = true;
  if (petalMesh.instanceColor) petalMesh.instanceColor.needsUpdate = true;
  stemMesh.frustumCulled = petalMesh.frustumCulled = false;
  worldGroup.add(stemMesh); worldGroup.add(petalMesh);

  /* 灌木：双球团簇 */
  bushMesh = new THREE.InstancedMesh(getIco(0.26), windSway(toonMat({ color: 0xffffff }), 0.05), Math.max(1, bushes.length * 2));
  for (j = 0; j < bushes.length; j++) {
    ti = bushes[j]; tx = ti % MWv; ty = (ti / MWv) | 0;
    gt = groundTop(tx, ty);
    var bs = 0.8 + hash2(tx, ty, 83) * 0.45;
    var bt = 0.85 + hash2(tx, ty, 84) * 0.25;
    tmpM.makeScale(bs, bs * 0.82, bs);
    tmpM.setPosition(tx + 0.5, gt + 0.18, ty + 0.5);
    bushMesh.setMatrixAt(j * 2, tmpM);
    bushMesh.setColorAt(j * 2, tmpC.set('#4da857').multiplyScalar(bt));
    tmpM.makeScale(bs * 0.6, bs * 0.5, bs * 0.6);
    tmpM.setPosition(tx + 0.5 + (hash2(tx, ty, 97) - 0.5) * 0.3, gt + 0.36, ty + 0.5 + (hash2(tx, ty, 98) - 0.5) * 0.3);
    bushMesh.setMatrixAt(j * 2 + 1, tmpM);
    bushMesh.setColorAt(j * 2 + 1, tmpC.set('#63bd63').multiplyScalar(bt));
  }
  bushMesh.count = bushes.length * 2;
  bushMesh.instanceMatrix.needsUpdate = true;
  if (bushMesh.instanceColor) bushMesh.instanceColor.needsUpdate = true;
  bushMesh.frustumCulled = false;
  bushMesh.castShadow = true;
  worldGroup.add(bushMesh);

  /* 碎石：随机朝向扁石 */
  rockDecoMesh = new THREE.InstancedMesh(getIco(0.13), toonMat({ color: 0xffffff }), Math.max(1, rocks.length));
  for (j = 0; j < rocks.length; j++) {
    ti = rocks[j]; tx = ti % MWv; ty = (ti / MWv) | 0;
    gt = groundTop(tx, ty);
    tmpQ.setFromAxisAngle(upY, hash2(tx, ty, 84) * Math.PI);
    var rs2 = 0.7 + hash2(tx, ty, 85) * 0.7;
    tmpV.set(tx + 0.5, gt + 0.07, ty + 0.5);
    tmpS.set(rs2, rs2 * 0.72, rs2 * 0.9);
    tmpM.compose(tmpV, tmpQ, tmpS);
    rockDecoMesh.setMatrixAt(j, tmpM);
    var rt = 0.8 + hash2(tx, ty, 99) * 0.3;
    rockDecoMesh.setColorAt(j, tmpC.setRGB(0.58 * rt, 0.56 * rt, 0.55 * rt));
  }
  rockDecoMesh.count = rocks.length;
  rockDecoMesh.instanceMatrix.needsUpdate = true;
  if (rockDecoMesh.instanceColor) rockDecoMesh.instanceColor.needsUpdate = true;
  rockDecoMesh.frustumCulled = false;
  worldGroup.add(rockDecoMesh);

  /* 草簇：交叉面片草叶（alphaTest），撒布草地/公园/森林 */
  grassCrossMesh = new THREE.InstancedMesh(getCrossGeo(), windSway(toonMat({
    map: S.blades, alphaTest: 0.42, side: THREE.DoubleSide, color: 0xffffff
  }), 0.075), Math.max(1, grassT.length));
  for (j = 0; j < grassT.length; j++) {
    ti = grassT[j]; tx = ti % MWv; ty = (ti / MWv) | 0;
    gt = groundTop(tx, ty);
    tmpQ.setFromAxisAngle(upY, hash2(tx, ty, 87) * Math.PI);
    var gs = 0.8 + hash2(tx, ty, 100) * 0.6;
    tmpV.set(tx + 0.5 + (hash2(tx, ty, 101) - 0.5) * 0.5, gt - 0.02, ty + 0.5 + (hash2(tx, ty, 102) - 0.5) * 0.5);
    tmpS.set(gs, gs * (0.85 + hash2(tx, ty, 103) * 0.4), gs);
    tmpM.compose(tmpV, tmpQ, tmpS);
    grassCrossMesh.setMatrixAt(j, tmpM);
    var gc2 = 0.8 + hash2(tx, ty, 104) * 0.35;
    grassCrossMesh.setColorAt(j, tmpC.setRGB(gc2, gc2 * 1.02, gc2 * 0.9));
  }
  grassCrossMesh.count = grassT.length;
  grassCrossMesh.instanceMatrix.needsUpdate = true;
  if (grassCrossMesh.instanceColor) grassCrossMesh.instanceColor.needsUpdate = true;
  grassCrossMesh.frustumCulled = false;
  worldGroup.add(grassCrossMesh);

  /* 路缘石：铺装与草地交界的浅色窄条 */
  curbMesh = new THREE.InstancedMesh(boxGeo, toonMat({ color: 0xcfc9bd }), Math.max(1, curbs.length));
  for (j = 0; j < curbs.length; j++) {
    var cb = curbs[j];
    var cx = cb.x + 0.5, cz = cb.y + 0.5, rotY = 0;
    if (cb.d === 0) cz = cb.y + 0.06;
    else if (cb.d === 1) cz = cb.y + 0.94;
    else if (cb.d === 2) { cx = cb.x + 0.06; rotY = Math.PI / 2; }
    else { cx = cb.x + 0.94; rotY = Math.PI / 2; }
    tmpQ.setFromAxisAngle(upY, rotY);
    tmpV.set(cx, smoothTop(cx, cz) + 0.045, cz);
    tmpS.set(0.12, 0.1, 1.0);
    tmpM.compose(tmpV, tmpQ, tmpS);
    curbMesh.setMatrixAt(j, tmpM);
  }
  curbMesh.count = curbs.length;
  curbMesh.instanceMatrix.needsUpdate = true;
  curbMesh.frustumCulled = false;
  curbMesh.receiveShadow = true;
  worldGroup.add(curbMesh);
}

/* 钟楼 / 灯塔（圆柱塔身写实版） */
function buildLandmarks() {
  var lamb = function (c) { return toonMat({ color: c }); };
  var bas = function (c) { return new THREE.MeshBasicMaterial({ color: c }); };

  var ct = E.poiById('clocktower');
  if (ct) {
    var g = new THREE.Group();
    var cx = ct.x + ct.w / 2, cz = ct.y + ct.h / 2;
    var gy = groundTop(Math.floor(cx), Math.floor(cz));
    var cream = lamb(0xf0e9d8), bronze = lamb(0x8a6d3b);
    var m;
    m = new THREE.Mesh(getCyl(0.72, 0.8, 0.4, 10), lamb(0x9aa0a8)); m.position.set(cx, gy + 0.2, cz); m.castShadow = true; g.add(m);
    m = new THREE.Mesh(getCyl(0.5, 0.58, 4.2, 10), cream); m.position.set(cx, gy + 2.5, cz); m.castShadow = true; g.add(m);
    /* 檐口 + 钟面朝四面 */
    m = new THREE.Mesh(getCyl(0.62, 0.62, 0.14, 10), bronze); m.position.set(cx, gy + 4.62, cz); g.add(m);
    var clock = bas(0xf5c542);
    var dirsC = [[0, -1, 0], [0, 0, -Math.PI / 2], [0, 1, Math.PI], [0, Math.PI / 2, 0]];
    for (var ci = 0; ci < 4; ci++) {
      var face = new THREE.Mesh(new THREE.CircleGeometry(0.26, 20), clock);
      face.position.set(cx + Math.sin(dirsC[ci][2] ? 0 : 0) , gy + 3.9, cz);
      if (ci === 0) { face.position.z = cz - 0.53; }
      else if (ci === 1) { face.position.x = cx - 0.53; face.rotation.y = -Math.PI / 2; }
      else if (ci === 2) { face.position.z = cz + 0.53; face.rotation.y = Math.PI; }
      else { face.position.x = cx + 0.53; face.rotation.y = Math.PI / 2; }
      g.add(face);
    }
    var hands = lamb(0x4a3b28);
    var h1 = new THREE.Mesh(getBoxGeo(), hands);
    h1.scale.set(0.04, 0.2, 0.02); h1.position.set(cx, gy + 3.96, cz - 0.545); g.add(h1);
    var h2 = new THREE.Mesh(getBoxGeo(), hands);
    h2.scale.set(0.16, 0.04, 0.02); h2.position.set(cx + 0.06, gy + 3.9, cz - 0.545); g.add(h2);
    m = new THREE.Mesh(getCone(0.66, 0.9, 8, false), lamb(0x6d28d9)); m.position.set(cx, gy + 5.15, cz); m.castShadow = true; g.add(m);
    m = new THREE.Mesh(getSph(0.07, 8, 6), bas(0xf5c542)); m.position.set(cx, gy + 5.66, cz); g.add(m);
    worldGroup.add(g);
  }
  var lh = E.poiById('lighthouse');
  if (lh) {
    var g2 = new THREE.Group();
    var lx = lh.x + lh.w / 2, lz = lh.y + lh.h / 2;
    var lgy = groundTop(Math.floor(lx), Math.floor(lz));
    var white = lamb(0xf4f6fa), red = lamb(0xd94f4f);
    var m2;
    m2 = new THREE.Mesh(getCyl(0.78, 0.86, 0.5, 12), lamb(0x9aa2b5)); m2.position.set(lx, lgy + 0.25, lz); m2.castShadow = true; g2.add(m2);
    /* 红白条纹三段（下粗上细） */
    m2 = new THREE.Mesh(getCyl(0.55, 0.62, 1.5, 12), white); m2.position.set(lx, lgy + 1.25, lz); m2.castShadow = true; g2.add(m2);
    m2 = new THREE.Mesh(getCyl(0.47, 0.55, 1.5, 12), red); m2.position.set(lx, lgy + 2.75, lz); m2.castShadow = true; g2.add(m2);
    m2 = new THREE.Mesh(getCyl(0.4, 0.47, 1.5, 12), white); m2.position.set(lx, lgy + 4.25, lz); m2.castShadow = true; g2.add(m2);
    /* 观景廊 + 灯室 + 红锥顶 */
    m2 = new THREE.Mesh(getCyl(0.52, 0.52, 0.12, 12), lamb(0x3d4b77)); m2.position.set(lx, lgy + 5.05, lz); g2.add(m2);
    m2 = new THREE.Mesh(getCyl(0.3, 0.34, 0.5, 10), lamb(0x2c3a5e)); m2.position.set(lx, lgy + 5.36, lz); g2.add(m2);
    m2 = new THREE.Mesh(getSph(0.24, 10, 8), bas(0xffe9a8)); m2.position.set(lx, lgy + 5.62, lz); g2.add(m2);
    m2 = new THREE.Mesh(getCone(0.4, 0.42, 10, false), red); m2.position.set(lx, lgy + 5.95, lz); m2.castShadow = true; g2.add(m2);
    lhBeamGroup = new THREE.Group();
    lhBeamGroup.position.set(lx, lgy + 5.62, lz);
    var beamMat = new THREE.MeshBasicMaterial({ color: 0xfff4b4, transparent: true, opacity: 0.24, depthWrite: false });
    var beamGeo = getCyl(0.32, 0.02, 24, 6);
    beamGeo.rotateZ(Math.PI / 2);
    var b1 = new THREE.Mesh(beamGeo, beamMat);
    b1.position.x = 12;
    var b2 = new THREE.Mesh(beamGeo, beamMat);
    b2.position.x = -12; b2.rotation.y = Math.PI;
    lhBeamGroup.add(b1); lhBeamGroup.add(b2);
    lhBeamGroup.visible = false;
    g2.add(lhBeamGroup);
    lhGlow = makeSprite(radialTex('rgba(255,240,170,.85)', 'rgba(255,240,170,0)'), 4.5);
    lhGlow.material.blending = THREE.AdditiveBlending;
    lhGlow.position.set(lx, lgy + 5.72, lz);
    lhGlow.visible = false;
    g2.add(lhGlow);
    worldGroup.add(g2);
  }
}

function buildLampSprites() {
  /* 路灯光晕合批：全部灯晕用一个 THREE.Points（1 个 draw call）渲染，
     取代原来每盏灯一个 Sprite（城区路网可达数百盏 = 数百个 draw call） */
  var THREE = window.THREE;
  disposeLampPoints();
  if (!lampGlows.length) { lampPoints = null; return; }
  var geo = new THREE.BufferGeometry();
  var pos = new Float32Array(lampGlows.length * 3);
  for (var i = 0; i < lampGlows.length; i++) {
    pos[i * 3] = lampGlows[i].x;
    pos[i * 3 + 1] = lampGlows[i].y;
    pos[i * 3 + 2] = lampGlows[i].z;
  }
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  var mat = new THREE.PointsMaterial({
    map: radialTex('rgba(255,214,130,.5)', 'rgba(255,214,130,0)'),
    size: 2.8, transparent: true, opacity: 0,
    depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true
  });
  lampPoints = new THREE.Points(geo, mat);
  lampPoints.frustumCulled = false;
  lampPoints.visible = false;
  worldGroup.add(lampPoints);
}
function disposeLampPoints() {
  if (!lampPoints) return;
  worldGroup.remove(lampPoints);
  lampPoints.geometry.dispose();
  if (lampPoints.material.map && lampPoints.material.map.dispose) lampPoints.material.map.dispose();
  lampPoints.material.dispose();
  lampPoints = null;
}

/* ---------- 灯光（含 PCF 软阴影，跟随玩家） ---------- */
function buildLights() {
  hemi = new THREE.HemisphereLight(0xcfe9ff, 0xb8d8a8, 0.95);
  scene.add(hemi);
  sun = new THREE.DirectionalLight(0xfff2d8, 1.2);
  sun.position.set(30, 60, 20);
  sun.castShadow = true;
  sun.shadow.mapSize.width = 2048;
  sun.shadow.mapSize.height = 2048;
  sun.shadow.camera.near = 8;
  sun.shadow.camera.far = 220;
  sun.shadow.camera.left = -46;
  sun.shadow.camera.right = 46;
  sun.shadow.camera.top = 46;
  sun.shadow.camera.bottom = -46;
  sun.shadow.bias = -0.0005;
  scene.add(sun);
  scene.add(sun.target);
  moon = new THREE.DirectionalLight(0x8ea0ff, 0.0);
  moon.position.set(-20, 50, -30);
  scene.add(moon);
  playerLight = new THREE.PointLight(0xc3adff, 0.0, 10, 2);
  scene.add(playerLight);
}

/* ---------- 天空：渐变穹顶 / 星 / 积云球簇 / 日月 ---------- */
function buildSky() {
  scene.background = new THREE.Color('#8ec9ef');
  scene.fog = new THREE.Fog(0x8ec9ef, radius * 1.8, radius * 8);

  /* 渐变天空穹顶（顶深蓝 → 地平线浅亮，昼夜由 updateLighting 换色） */
  skyUni = {
    topC: { value: new THREE.Color('#2f6fd6') },
    midC: { value: new THREE.Color('#8ec9ef') },
    botC: { value: new THREE.Color('#dceef6') }
  };
  skyDome = new THREE.Mesh(
    new THREE.SphereGeometry(235, 24, 14),
    new THREE.ShaderMaterial({
      uniforms: skyUni,
      vertexShader: 'varying vec3 vP; void main(){ vP = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
      fragmentShader: [
        'varying vec3 vP;',
        'uniform vec3 topC; uniform vec3 midC; uniform vec3 botC;',
        'void main(){',
        '  float a = normalize(vP).y;',
        '  vec3 c = a > 0.0 ? mix(midC, topC, pow(min(a, 1.0), 0.55)) : mix(midC, botC, pow(min(-a, 1.0), 0.7));',
        '  gl_FragColor = vec4(c, 1.0);',
        '}'
      ].join('\n'),
      side: THREE.BackSide, depthWrite: false, fog: false
    })
  );
  skyDome.frustumCulled = false;
  skyDome.renderOrder = -10;
  scene.add(skyDome);

  var n = 340, pos = new Float32Array(n * 3);
  for (var i = 0; i < n; i++) {
    var a = Math.random() * Math.PI * 2, e = Math.random() * Math.PI * 0.48 + 0.05, r = 200;
    pos[i * 3] = Math.cos(a) * Math.cos(e) * r;
    pos[i * 3 + 1] = Math.sin(e) * r;
    pos[i * 3 + 2] = Math.sin(a) * Math.cos(e) * r;
  }
  var geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  stars = new THREE.Points(geo, new THREE.PointsMaterial({ color: 0xfff8e0, size: 1.6, transparent: true, opacity: 0, fog: false, sizeAttenuation: false }));
  stars.frustumCulled = false;
  scene.add(stars);

  /* 积云：白色球簇（圆润饱满，旷野之息式） */
  cloudGroup = new THREE.Group();
  var cm = new THREE.MeshLambertMaterial({ color: 0xffffff, transparent: true, opacity: 0.95, emissive: 0xbfd2e8, emissiveIntensity: 0.3 });
  cm._shared = true;
  cloudMat = cm;
  var cgeo = getIco(1);
  for (i = 0; i < 12; i++) {
    var g = new THREE.Group();
    var puffs = 4 + ((Math.random() * 3) | 0);
    for (var p2 = 0; p2 < puffs; p2++) {
      var m = new THREE.Mesh(cgeo, cm);
      var s = 1.6 + Math.random() * 2.2;
      m.scale.set(s, s * (0.5 + Math.random() * 0.22), s * 0.85);
      m.position.set((p2 - puffs / 2) * 1.6 + (Math.random() - 0.5), (Math.random() - 0.5) * 0.5, (Math.random() - 0.5) * 2.4);
      g.add(m);
    }
    g.position.set((Math.random() - 0.5) * 96, 24 + Math.random() * 10, (Math.random() - 0.5) * 96);
    cloudGroup.add(g);
    clouds.push({ g: g, v: 0.25 + Math.random() * 0.4 });
  }
  scene.add(cloudGroup);

  sunSpr = makeSprite(radialTex('rgba(255,246,200,.98)', 'rgba(255,220,140,0)'), 14);
  sunSpr.material.fog = false;
  scene.add(sunSpr);
  moonSpr = makeSprite(radialTex('rgba(235,240,255,.95)', 'rgba(200,215,255,0)'), 9);
  moonSpr.material.fog = false;
  scene.add(moonSpr);

  function mkPts(cnt, size, color, opacity) {
    var p = new Float32Array(cnt * 3);
    for (var q = 0; q < cnt; q++) {
      p[q * 3] = (Math.random() - 0.5) * 34;
      p[q * 3 + 1] = Math.random() * 18;
      p[q * 3 + 2] = (Math.random() - 0.5) * 34;
    }
    var g2 = new THREE.BufferGeometry();
    g2.setAttribute('position', new THREE.BufferAttribute(p, 3));
    var pt = new THREE.Points(g2, new THREE.PointsMaterial({ color: color, size: size, transparent: true, opacity: opacity, fog: false }));
    pt.frustumCulled = false;
    pt.visible = false;
    scene.add(pt);
    return pt;
  }
  rainPts = mkPts(520, 0.11, 0x7fa8dc, 0.7);
  snowPts = mkPts(420, 0.17, 0xffffff, 0.95);
}

/* ---------- 小人工厂：原神比例卡通人（Toon 三档渲染）----------
 * 结构：圆柱腿+鞋 / 裙锥 / 圆台躯干 / 球肩 / 圆柱臂+手球 /
 *       球头 + 发盔半球 + 侧发 + 动漫脸贴片 + 接触软阴影 */
function makeFigure(colorBody, colorHair) {
  var THREE = window.THREE;
  var g = new THREE.Group();
  var toon = function (c) {
    return new THREE.MeshToonMaterial({ color: c, gradientMap: getGradTex() });
  };
  var bodyMat = toon(colorBody); bodyMat._shared = false;
  var skinMat = toon(0xf6d7c4);
  var hairMat = toon(colorHair);
  var legMat = toon(0x4a3f5c);
  var shoeMat = toon(0x8c6f9e);
  var geo;

  /* 双腿（挂点在髋 y=0.86，圆柱+鞋） */
  var legL = new THREE.Group(), legR = new THREE.Group();
  geo = getCyl(0.055, 0.062, 0.78, 7);
  var lm = new THREE.Mesh(geo, legMat); lm.position.y = -0.39; legL.add(lm);
  var ls = new THREE.Mesh(getBoxGeo(), shoeMat);
  ls.scale.set(0.13, 0.09, 0.24); ls.position.set(0, -0.82, 0.04); legL.add(ls);
  var lm2 = lm.clone(); legR.add(lm2);
  var ls2 = ls.clone(); legR.add(ls2);
  legL.position.set(-0.1, 0.86, 0);
  legR.position.set(0.1, 0.86, 0);
  g.add(legL); g.add(legR);

  /* 裙摆（锥形开口） */
  geo = getCone(0.27, 0.4, 9, false);
  var skirt = new THREE.Mesh(geo, bodyMat);
  skirt.position.y = 0.98;
  skirt.scale.y = -1; /* 开口向下 */
  g.add(skirt);

  /* 躯干（圆台上宽下窄）+ 腰带 */
  var body = new THREE.Mesh(getCyl(0.16, 0.125, 0.52, 9), bodyMat);
  body.position.y = 1.32;
  g.add(body);
  var belt = new THREE.Mesh(getCyl(0.135, 0.14, 0.07, 9), legMat);
  belt.position.y = 1.09;
  g.add(belt);

  /* 肩球 + 双臂（挂点在肩，圆柱臂+手球） */
  var shL = new THREE.Mesh(getSph(0.065, 8, 6), bodyMat); shL.position.set(-0.175, 1.53, 0); g.add(shL);
  var shR = new THREE.Mesh(getSph(0.065, 8, 6), bodyMat); shR.position.set(0.175, 1.53, 0); g.add(shR);
  var armL = new THREE.Group(), armR = new THREE.Group();
  var am = new THREE.Mesh(getCyl(0.042, 0.05, 0.6, 7), skinMat);
  am.position.y = -0.3; armL.add(am);
  var hand = new THREE.Mesh(getSph(0.055, 8, 6), skinMat);
  hand.position.y = -0.63; armL.add(hand);
  var am2 = am.clone(); armR.add(am2);
  var hand2 = hand.clone(); armR.add(hand2);
  armL.position.set(-0.185, 1.52, 0);
  armR.position.set(0.185, 1.52, 0);
  g.add(armL); g.add(armR);

  /* 头（球）+ 发盔（半球罩后侧）+ 侧发 + 动漫脸 */
  var head = new THREE.Mesh(getSph(0.165, 14, 12), skinMat);
  head.position.y = 1.82;
  g.add(head);
  var hairCap = new THREE.Mesh(getSph(0.182, 14, 10), hairMat);
  hairCap.scale.set(1, 0.92, 1);
  hairCap.position.y = 1.85;
  g.add(hairCap);
  /* 刘海片（前额） */
  var bang = new THREE.Mesh(getBoxGeo(), hairMat);
  bang.scale.set(0.26, 0.07, 0.05); bang.position.set(0, 1.94, 0.14); bang.rotation.x = 0.35;
  g.add(bang);
  var lockL = new THREE.Mesh(getSph(0.05, 7, 6), hairMat);
  lockL.scale.y = 1.9; lockL.position.set(-0.145, 1.76, 0.06); g.add(lockL);
  var lockR = lockL.clone(); lockR.position.x = 0.145; g.add(lockR);
  /* 后发束 */
  var back = new THREE.Mesh(getSph(0.07, 8, 6), hairMat);
  back.scale.set(1, 2.2, 0.8); back.position.set(0, 1.7, -0.13); g.add(back);
  /* 动漫脸贴片 */
  var face = new THREE.Mesh(
    new THREE.PlaneGeometry(0.23, 0.21),
    new THREE.MeshBasicMaterial({ map: buildTextures().face, transparent: true, depthWrite: false })
  );
  face.position.set(0, 1.815, 0.157);
  g.add(face);

  /* 接触软阴影（贴地椭圆） */
  var blob = new THREE.Mesh(
    new THREE.CircleGeometry(0.3, 18),
    new THREE.MeshBasicMaterial({ color: 0x1c1433, transparent: true, opacity: 0.22, depthWrite: false })
  );
  blob.rotation.x = -Math.PI / 2;
  blob.position.y = 0.02;
  blob.scale.set(1, 0.85, 1);
  g.add(blob);
  /* 各部件投射软阴影 */
  g.traverse(function (o) { if (o.isMesh && o !== blob && o !== face) o.castShadow = true; });
  /* 原神式描边：每个 Toon 部件外套一层 BackSide 扩边壳（5.5% 扩张）。
     作为子节点挂在原部件下，继承其 transform；共享同一份 geometry 避免重复占用 */
  var outlineMat = getOutlineMat();
  g.traverse(function (o) {
    if (!o.isMesh || o === blob || o === face) return;
    var isToon = o.material && o.material.type === 'MeshToonMaterial';
    if (!isToon) return;
    var ol = new THREE.Mesh(o.geometry, outlineMat);
    ol.scale.multiplyScalar(1.055);
    ol.castShadow = false;
    ol.receiveShadow = false;
    ol.userData.isOutline = true;
    o.add(ol);
  });
  return { g: g, armL: armL, armR: armR, legL: legL, legR: legR };
}

function buildPlayer() {
  playerParts = makeFigure(0xe11d68, 0x4a3345);
  playerG = playerParts.g;
  var THREE = window.THREE;
  var ring = new THREE.Mesh(
    new THREE.RingGeometry(0.44, 0.56, 26),
    new THREE.MeshBasicMaterial({ color: 0xff2d78, transparent: true, opacity: 0.75, side: THREE.DoubleSide, depthWrite: false })
  );
  ring.rotation.x = -Math.PI / 2;
  ring.position.y = 0.05;
  playerG.add(ring);
  playerRing = ring;
  /* 标记程序化小人部件（模型形象启用时整体隐藏，选中环除外） */
  for (var i = 0; i < playerG.children.length; i++) {
    if (playerG.children[i] !== ring) playerG.children[i].userData._fig = true;
  }
  scene.add(playerG);
  /* 之前已加载过形象模型 → 重新挂回 */
  if (PMODEL.group && PMODEL.group.parent !== playerG) {
    playerG.add(PMODEL.group);
    setFigVisible(false);
  }
  fetchAvatar3D();
}

/* ---------- 自定义 3D 形象：加载 / 归一化 / 动画 / 许墨替换 ---------- */

function fetchAvatar3D() {
  /* 进入 3D 世界时拉取一次当前形象设置（玩家 / 许墨 双槽位独立） */
  if (PMODEL.stateFetched) return;
  PMODEL.stateFetched = true;
  try {
    fetch('/api/model/state').then(function (r) { return r.json(); }).then(function (d) {
      if (!d) return;
      var items = d.items || [];
      var pit = items.filter(function (x) { return x.id === d.active_id; })[0];
      var xit = items.filter(function (x) { return x.id === d.xumo_id; })[0];
      applyAvatar3D(pit ? pit.url : null, xit ? xit.url : null);
    }).catch(function () {});
  } catch (e) {}
}

function disposeModelGroup(g) {
  if (!g) return;
  g.traverse(function (o) {
    if (o.geometry && !o.geometry._shared) o.geometry.dispose();
    if (o.material) {
      var mats = Array.isArray(o.material) ? o.material : [o.material];
      for (var i = 0; i < mats.length; i++) {
        if (mats[i].dispose && !mats[i]._shared) mats[i].dispose();
      }
    }
  });
  if (g.parent) g.parent.remove(g);
}

/* 任意尺寸模型 → 统一高 1.8、脚贴地、水平居中 */
function prepModelScene(root) {
  var THREE = window.THREE;
  var wrap = new THREE.Group();
  var box = new THREE.Box3().setFromObject(root);
  if (!box.isEmpty()) {
    var size = new THREE.Vector3();
    box.getSize(size);
    var s = 1.8 / Math.max(size.y, 0.001);
    root.position.set(-(box.min.x + size.x / 2) * s, -box.min.y * s, -(box.min.z + size.z / 2) * s);
    root.scale.setScalar(s);
  }
  wrap.add(root);
  wrap.traverse(function (o) {
    if (o.isMesh) {
      o.castShadow = true;
      o.frustumCulled = false; /* 蒙皮网格包围盒漂移防闪灭 */
    }
  });
  return wrap;
}

/* 建立动画混合器：按名称挑 idle / walk（找不到就用首段） */
function setupModelAnims(entry, gltf) {
  entry.mixer = null; entry.idle = null; entry.walk = null; entry.cur = null;
  var clips = gltf.animations || [];
  if (!clips.length) return;
  entry.mixer = new window.THREE.AnimationMixer(gltf.scene);
  var walkI = -1, idleI = -1, i;
  for (i = 0; i < clips.length; i++) {
    var n = (clips[i].name || '').toLowerCase();
    if (walkI < 0 && /walk|run/.test(n)) walkI = i;
    if (idleI < 0 && /idle|stand|breath/.test(n)) idleI = i;
  }
  if (idleI < 0) idleI = (walkI > 0) ? 0 : (clips.length > 1 ? 1 : 0);
  if (walkI < 0) walkI = idleI;
  entry.idle = entry.mixer.clipAction(clips[idleI]);
  entry.walk = entry.mixer.clipAction(clips[walkI]);
  entry.idle.reset().play();
  entry.cur = entry.idle;
}

function modelAnimState(entry, wantWalk) {
  if (!entry || !entry.mixer) return;
  var next = wantWalk ? (entry.walk || entry.idle) : (entry.idle || entry.walk);
  if (!next || entry.cur === next) return;
  next.reset().play();
  try { next.crossFadeFrom(entry.cur, 0.25, false); }
  catch (e) { try { entry.cur.stop(); } catch (e2) {} }
  entry.cur = next;
}

function setFigVisible(v) {
  if (!playerG) return;
  for (var i = 0; i < playerG.children.length; i++) {
    if (playerG.children[i].userData._fig) playerG.children[i].visible = v;
  }
}

function clearAvatar3D() {
  disposeModelGroup(PMODEL.group);
  PMODEL.url = ''; PMODEL.group = null;
  PMODEL.mixer = null; PMODEL.idle = PMODEL.walk = PMODEL.cur = null;
  setFigVisible(true);
}

function clearXumoModel() {
  disposeModelGroup(XMODEL.group);
  XMODEL.url = ''; XMODEL.group = null;
  XMODEL.mixer = null; XMODEL.idle = XMODEL.walk = XMODEL.cur = null;
}

/* 许墨槽位独立管理：wantUrl 变化时加载/卸载；同一 URL 由浏览器缓存复用 */
function ensureXumoModel() {
  var wantUrl = XMODEL.wantUrl || '';
  if (!wantUrl) { clearXumoModel(); return; }
  if (XMODEL.group && XMODEL.url === wantUrl) return;
  clearXumoModel();
  if (!window.THREE.GLTFLoader) return;
  new window.THREE.GLTFLoader().load(wantUrl, function (gltf) {
    if (XMODEL.wantUrl !== wantUrl) return; /* 期间已切换/清空 */
    XMODEL.url = wantUrl;
    XMODEL.group = prepModelScene(gltf.scene);
    setupModelAnims(XMODEL, gltf);
  }, undefined, function () {});
}

var avatar3DReq = 0;
/* playerUrl / xumoUrl 均可独立传 null 恢复默认 */
function applyAvatar3D(playerUrl, xumoUrl) {
  var req = ++avatar3DReq;
  XMODEL.wantUrl = xumoUrl || '';
  ensureXumoModel();
  if (!playerUrl) { clearAvatar3D(); return; }
  if (PMODEL.url === playerUrl && PMODEL.group) return;
  if (!window.THREE.GLTFLoader) { console.warn('[world-3d] GLTFLoader 未加载，3D 形象不可用'); return; }
  clearAvatar3D();
  PMODEL.loading = true;
  new window.THREE.GLTFLoader().load(playerUrl, function (gltf) {
    if (req !== avatar3DReq) return; /* 已被后续请求取代（防旧回调覆盖新模型） */
    PMODEL.loading = false;
    clearAvatar3D();
    PMODEL.url = playerUrl;
    PMODEL.group = prepModelScene(gltf.scene);
    setupModelAnims(PMODEL, gltf);
    if (playerG) {
      playerG.add(PMODEL.group);
      setFigVisible(false);
    }
  }, undefined, function () {
    if (req === avatar3DReq) PMODEL.loading = false;
    console.warn('[world-3d] 形象模型加载失败', playerUrl);
  });
}

/* ---------- NPC / 残影 同步 ---------- */
function syncNpcs() {
  var list = E.npcAll();
  var seen = {};
  for (var i = 0; i < list.length; i++) {
    var e = list[i], id = e.def.id;
    seen[id] = 1;
    var rec = npcGroups[id];
    if (!rec) {
      var hsN = 0; for (var hcN = 0; hcN < id.length; hcN++) hsN = (hsN * 31 + id.charCodeAt(hcN)) >>> 0;
      var NPC_HAIRS = [0x3d3348, 0x1f1b2e, 0x6b4a35, 0x8a6248, 0x50394a, 0x2c3a52, 0x74513f, 0x9a7b5c, 0x4a2f3e];
      var fig = makeFigure(new THREE.Color(e.def.color || '#8b5cf6').getHex(), NPC_HAIRS[hsN % NPC_HAIRS.length]);
      var spr = null;
      if (e.def.avatar) spr = makeSprite(avatarTex(e.def.avatar), 0.95);
      else spr = makeSprite(emojiTex(e.def.emoji || '🙂'), 0.52);
      spr.position.y = 1.62;
      fig.g.add(spr);
      scene.add(fig.g);
      rec = npcGroups[id] = { fig: fig, spr: spr, lx: e.x, lz: e.y, ph: Math.random() * 6.28 };
    }
    var gy = groundTop(Math.floor(e.x), Math.floor(e.y));
    var walking = e.state === 'walk';
    var bob = walking ? Math.abs(Math.sin(tNow * 8 + rec.ph)) * 0.07 : Math.sin(tNow * 1.2 + rec.ph) * 0.015;
    rec.fig.g.position.set(e.x, gy + bob, e.y);
    var sw = walking ? Math.sin(tNow * 8 + rec.ph) * 0.55 : 0;
    rec.fig.armL.rotation.x = sw;
    rec.fig.armR.rotation.x = -sw;
    if (rec.fig.legL) {
      rec.fig.legL.rotation.x = -sw * 0.85;
      rec.fig.legR.rotation.x = sw * 0.85;
    }
    var vx = e.x - rec.lx, vz = e.y - rec.lz;
    if (vx * vx + vz * vz > 1e-6) rec.fig.g.rotation.y = Math.atan2(vx, vz);
    rec.lx = e.x; rec.lz = e.y;
    /* 许墨 NPC 使用「许墨槽位」上传模型（与玩家槽位独立） */
    if (id === 'xumo') {
      var xmOn = !!XMODEL.group;
      if (xmOn) {
        if (XMODEL.group.parent !== rec.fig.g) {
          for (var xr = 0; xr < rec.fig.g.children.length; xr++) rec.fig.g.children[xr].visible = true;
          rec.fig.g.add(XMODEL.group);
        }
        for (var xi = 0; xi < rec.fig.g.children.length; xi++) {
          rec.fig.g.children[xi].visible = (rec.fig.g.children[xi] === XMODEL.group);
        }
        modelAnimState(XMODEL, walking);
      } else if (XMODEL.group && XMODEL.group.parent === rec.fig.g) {
        rec.fig.g.remove(XMODEL.group);
        for (var xj = 0; xj < rec.fig.g.children.length; xj++) rec.fig.g.children[xj].visible = true;
      }
    }
  }
  for (var k in npcGroups) {
    if (!seen[k]) {
      scene.remove(npcGroups[k].fig.g);
      delete npcGroups[k];
    }
  }
  /* 异常残影 */
  var sh = E.shadowsAll();
  while (shadowPool.length < sh.length) {
    var g2 = new THREE.Group();
    var s = new THREE.Mesh(new THREE.SphereGeometry(0.5, 10, 8), new THREE.MeshBasicMaterial({ color: 0x38246e, transparent: true, opacity: 0.82 }));
    g2.add(s);
    var spr2 = makeSprite(emojiTex('👁'), 0.6);
    spr2.position.y = 0.1;
    g2.add(spr2);
    scene.add(g2);
    shadowPool.push(g2);
  }
  for (i = 0; i < shadowPool.length; i++) {
    var on = i < sh.length;
    shadowPool[i].visible = on;
    if (on) {
      var o = sh[i];
      shadowPool[i].position.set(o.x, groundTop(Math.floor(o.x), Math.floor(o.y)) + 0.75 + Math.sin(tNow * 2.4 + i) * 0.12, o.y);
    }
  }
}

function avatarTex(url) {
  if (IMG_TEX[url]) return IMG_TEX[url];
  var t = new THREE.TextureLoader().load(url, function () { t.needsUpdate = true; });
  if (THREE.sRGBEncoding) t.encoding = THREE.sRGBEncoding;
  IMG_TEX[url] = t;
  return t;
}

/* ---------- 交互物 sprite ---------- */
var wantKeep = {};
function syncInteractables() {
  var S = E.state();
  var want = {};
  var i, nd;
  var nodes = E.nodesAll();
  for (i = 0; i < nodes.length; i++) {
    nd = nodes[i];
    if (!E.nodeAvail(nd)) continue;
    if (!explored[nd.y * MWv + nd.x]) continue;
    want['nd_' + nd.id] = { ch: D.NODE_TYPES[nd.type].icon, x: nd.x + 0.5, y: 0, z: nd.y + 0.5, s: 0.62, by: 0.55 };
  }
  var st = E.staticsAll();
  for (i = 0; i < st.CHESTS.length; i++) {
    var ch = st.CHESTS[i];
    if (S.chests[ch.id]) continue;
    if (ch.id === 'c_clock' && !S.worldFlags.clock_open) continue;
    if (ch.id === 'c_dark' && !S.worldFlags.dark_open) continue;
    if (ch.id === 'c_roof' && !S.worldFlags.roof_open) continue;
    if (ch.id === 'c_temple' && !S.worldFlags.temple_open) continue;
    if (!explored[ch.y * MWv + ch.x]) continue;
    want['ch_' + ch.id] = { ch: '🧰', x: ch.x + 0.5, y: 0, z: ch.y + 0.5, s: 0.72, by: 0.5 };
  }
  if (S.mainStage >= 1) {
    for (i = 0; i < st.SHARDS.length; i++) {
      if (S.counters['shardTaken_' + i]) continue;
      var shd = st.SHARDS[i];
      want['sh_' + i] = { ch: '🔷', x: shd.x + 0.5, y: 0, z: shd.y + 0.5, s: 0.72, by: 0.7 };
    }
  }
  var s2q = S.sides['s2'];
  if (s2q && s2q.state === 1) {
    for (i = 0; i < st.PAGES.length; i++) {
      if (S.counters['pageTaken_' + i]) continue;
      var pg = st.PAGES[i];
      want['pg_' + i] = { ch: '📄', x: pg.x + 0.5, y: 0, z: pg.y + 0.5, s: 0.55, by: 0.5 };
    }
  }
  var s4q = S.sides['s4'];
  if (s4q && s4q.state === 1 && E.hasItem && E.hasItem('camera')) {
    for (i = 0; i < st.PHOTOS.length; i++) {
      var ph = st.PHOTOS[i];
      if (S.flags['photo_' + ph.id]) continue;
      want['ph_' + ph.id] = { ch: '📷', x: ph.x + 0.5, y: 0, z: ph.y + 0.5, s: 0.55, by: 0.5 };
    }
  }
  var pois = D.POIS;
  for (i = 0; i < pois.length; i++) {
    var poi = pois[i];
    if (poi.hidden && !S.worldFlags[poi.id + '_found']) {
      var dd = Math.hypot(poi.x - S.player.x, poi.y - S.player.y);
      if (dd > (E.hasSkill('per3') ? 12 : 3)) continue;
    }
    var py = poi.type === 'build' ? 3.9 : (poi.tall ? 6.6 : 1.9);
    want['poi_' + poi.id] = { ch: poi.icon || '📍', x: poi.x + (poi.w || 1) / 2, y: py, z: poi.y + (poi.h || 1) / 2, s: 0.95, by: 0, noBob: true };
  }
  for (var key in want) {
    var it = want[key];
    var rec = sprites[key];
    if (!rec) {
      var spr = makeSprite(emojiTex(it.ch), it.s);
      scene.add(spr);
      rec = sprites[key] = { spr: spr };
    }
    var gy2 = it.by ? groundTop(Math.floor(it.x), Math.floor(it.z)) + it.by : it.y;
    var bobY = it.noBob ? 0 : Math.sin(tNow * 2.6 + it.x * 3.1 + it.z * 1.7) * 0.08;
    rec.spr.position.set(it.x, gy2 + bobY, it.z);
    rec.spr.scale.set(it.s, it.s, 1);
    var wantTex = emojiTex(it.ch);
    if (rec.spr.material.map !== wantTex) {
      rec.spr.material.map = wantTex;
      rec.spr.material.needsUpdate = true;
    }
  }
  for (var k in sprites) {
    if (!want[k] && !wantKeep[k]) {
      scene.remove(sprites[k].spr);
      delete sprites[k];
    }
  }
}

/* ---------- 脉搏事件光柱 ---------- */
function pulseColor(r) {
  return r === 'epic' ? '#f43f5e' : r === 'rare' ? '#a855f7' : '#f59e0b';
}
function syncPulse() {
  var pd = E.pulseData();
  var evs = pd.events || [];
  while (beams.length < evs.length) {
    var g = new THREE.Group();
    var box = new THREE.BoxGeometry(1, 1, 1); box._shared = true;
    var beam = new THREE.Mesh(box, new THREE.MeshBasicMaterial({ color: 0xf59e0b, transparent: true, opacity: 0.35, depthWrite: false }));
    beam.scale.set(0.4, 3.2, 0.4); beam.position.y = 1.6;
    var ring = new THREE.Mesh(new THREE.RingGeometry(0.5, 0.66, 24), new THREE.MeshBasicMaterial({ color: 0xf59e0b, transparent: true, opacity: 0.7, side: THREE.DoubleSide, depthWrite: false }));
    ring.rotation.x = -Math.PI / 2; ring.position.y = 0.06;
    g.add(beam); g.add(ring);
    scene.add(g);
    beams.push({ g: g, beam: beam, ring: ring });
  }
  for (var i = 0; i < beams.length; i++) {
    var on = i < evs.length;
    beams[i].g.visible = on;
    if (!on) continue;
    var ev = evs[i];
    var col = pulseColor(ev.rarity || 'common');
    var gy = groundTop(ev.x, ev.y);
    beams[i].g.position.set(ev.x + 0.5, gy, ev.y + 0.5);
    beams[i].beam.material.color.set(col);
    beams[i].ring.material.color.set(col);
    var pp = 0.75 + Math.sin(tNow * 3 + i * 1.7) * 0.25;
    beams[i].beam.material.opacity = 0.22 + pp * 0.22;
    beams[i].beam.scale.y = (ev.rarity === 'epic' ? 4.2 : ev.rarity === 'rare' ? 3.4 : 2.6) * pp + 1.2;
    beams[i].beam.position.y = beams[i].beam.scale.y / 2;
    var key = 'pe_' + ev.id;
    var rec = sprites[key];
    if (!rec) {
      var spr = makeSprite(emojiTex(ev.emoji || '✨'), 0.85);
      scene.add(spr);
      rec = sprites[key] = { spr: spr };
    }
    rec.spr.position.set(ev.x + 0.5, gy + beams[i].beam.scale.y + 0.45, ev.y + 0.5);
    var ptex = emojiTex(ev.emoji || '✨');
    if (rec.spr.material.map !== ptex) {
      rec.spr.material.map = ptex;
      rec.spr.material.needsUpdate = true;
    }
    wantKeep[key] = 1;
  }
}

/* ---------- 光照 / 天空 ---------- */
function darknessOf(h) {
  if (h >= 19 && h < 21) return (h - 19) / 2 * 0.5;
  if (h >= 21 || h < 4.5) return 0.5;
  if (h >= 4.5 && h < 6.5) return (6.5 - h) / 2 * 0.5;
  return 0;
}
var skyDay = null, skyDusk = null, skyNight = null, tmpCol = null;
var topDay = null, topDusk = null, topNight = null, botTmp = null;
function updateLighting() {
  if (!skyDay) {
    skyDay = new THREE.Color('#8ec9ef');
    skyDusk = new THREE.Color('#f0a878');
    skyNight = new THREE.Color('#232c54');
    topDay = new THREE.Color('#2f6fd6');
    topDusk = new THREE.Color('#3a4a8e');
    topNight = new THREE.Color('#0a1030');
    tmpCol = new THREE.Color();
    botTmp = new THREE.Color();
  }
  var S = E.state();
  var h = (S.timeMin % 1440) / 60;
  var wd = D.WEATHERS[S.weather] || D.WEATHERS.clear;
  var darkness = darknessOf(h);
  var weatherDim = 0;
  if (wd.light < 0) weatherDim = Math.min(0.24, -wd.light / 120);
  darkness = clamp(darkness + weatherDim, 0, 0.62);

  /* 阴影相机跟随玩家（每帧更新，先于早退） */
  var ang = (h - 6) / 12 * Math.PI;
  var elev = Math.sin(ang);
  sun.position.set(camLook.x + Math.cos(ang) * 60, Math.max(6, elev * 70), camLook.z + 22);
  sun.target.position.set(camLook.x, 0, camLook.z);
  sun.target.updateMatrixWorld();

  if (Math.abs(darkness - lastDarkness) < 0.004 && S.weather === lastWeather) return;
  lastDarkness = darkness; lastWeather = S.weather;

  var dayF = clamp(elev * 1.6, 0, 1);
  sun.intensity = dayF * (1 - darkness * 1.1) * 1.05;
  sun.castShadow = dayF > 0.03 && darkness < 0.55;
  sun.color.setRGB(1, 0.88 + dayF * 0.1, 0.72 + dayF * 0.22);
  moon.intensity = darkness > 0.2 ? 0.34 : 0.1;
  hemi.intensity = 0.3 + (1 - darkness) * 0.58;
  playerLight.intensity = darkness > 0.18 ? 0.9 : 0;

  /* 窗光 / 路灯 */
  if (buildWallMat) buildWallMat.emissiveIntensity = darkness > 0.12 ? 1.15 : 0;
  var lampOn = darkness > 0.15;
  if (headMat) headMat.color.set(lampOn ? 0xffe6a3 : 0xd8d4e8);
  if (lampPoints) lampPoints.visible = lampOn;

  /* 天空穹顶三段色（昼/黄昏/夜按天顶角权重插值） */
  var kD = clamp(dayF * 2.4, 0, 1);
  var kN = clamp(-elev * 4 + 0.3, 0, 1);
  var kS = clamp(1 - kD - kN, 0, 1);
  var kSum = kD + kN + kS;
  if (kSum <= 0) { kD = 1; } else { kD /= kSum; kN /= kSum; kS /= kSum; }
  var mid = tmpCol;
  mid.setRGB(
    skyDay.r * kD + skyDusk.r * kS + skyNight.r * kN,
    skyDay.g * kD + skyDusk.g * kS + skyNight.g * kN,
    skyDay.b * kD + skyDusk.b * kS + skyNight.b * kN
  );
  if (weatherDim > 0) mid.lerp(col('#9a94ac'), weatherDim * 1.6);
  if (S.weather === 'fog') mid.lerp(col('#c9c4dc'), 0.5);
  if (skyUni) {
    var top = skyUni.topC.value;
    top.setRGB(
      topDay.r * kD + topDusk.r * kS + topNight.r * kN,
      topDay.g * kD + topDusk.g * kS + topNight.g * kN,
      topDay.b * kD + topDusk.b * kS + topNight.b * kN
    );
    if (weatherDim > 0) top.lerp(new THREE.Color('#6e6884'), weatherDim * 1.4);
    skyUni.midC.value.copy(mid);
    botTmp.set('#e8f4f8');
    skyUni.botC.value.copy(mid).lerp(botTmp, 0.32);
  }
  scene.background = mid;
  scene.fog.color = mid;
  var vis = wd.vis || 1;
  scene.fog.near = radius * (vis < 1 ? 0.35 : 1.8);
  scene.fog.far = radius * (vis < 1 ? 3.2 : 8);

  var starOn = (darkness > 0.25 || S.weather === 'starry') ? 1 : 0;
  starBaseO = starOn * clamp(darkness * 2, 0.35, 0.95);
  stars.material.opacity = starBaseO;
  stars.visible = starOn > 0;

  var lit = !!S.worldFlags.lighthouse_lit;
  if (lhBeamGroup) lhBeamGroup.visible = lit;
  if (lhGlow) lhGlow.visible = lit;
  /* 日月可见性 */
  sunSpr.visible = elev > -0.05;
  moonSpr.visible = elev < 0.1 && darkness > 0.1;
}

/* ---------- 天气粒子 ---------- */
function updateWeather(dt) {
  var S = E.state();
  var wd = D.WEATHERS[S.weather];
  /* 雨转晴 → 触发彩虹 */
  if (prevWeather3d && prevWeather3d !== S.weather) {
    var wasWet = prevWeather3d === 'rain' || prevWeather3d === 'storm';
    if (wasWet && S.weather === 'clear') rainbowUntil = tNow + 26;
  }
  prevWeather3d = S.weather;
  var rainOn = wd && (wd.particle === 'rain' || wd.particle === 'storm');
  var snowOn = wd && wd.particle === 'snow';
  rainPts.visible = rainOn;
  snowPts.visible = snowOn;
  var px = S.player.x, pz = S.player.y;
  if (rainOn) {
    var pos = rainPts.geometry.attributes.position;
    var spd = wd.particle === 'storm' ? 30 : 20;
    var wind = wd.particle === 'storm' ? -7 : -2.5;
    for (var i = 0; i < pos.count; i++) {
      var y = pos.getY(i) - spd * dt;
      if (y < 0) y += 18;
      pos.setY(i, y);
      pos.setX(i, pos.getX(i) + wind * dt);
    }
    pos.needsUpdate = true;
    rainPts.position.set(px, 0, pz);
  }
  if (snowOn) {
    var pos2 = snowPts.geometry.attributes.position;
    for (var j = 0; j < pos2.count; j++) {
      var y2 = pos2.getY(j) - 1.7 * dt;
      if (y2 < 0) y2 += 18;
      pos2.setY(j, y2);
      pos2.setX(j, pos2.getX(j) + Math.sin(tNow * 1.3 + j) * 0.35 * dt);
    }
    pos2.needsUpdate = true;
    snowPts.position.set(px, 0, pz);
  }
  if (wd && wd.particle === 'storm') {
    if (flash > 0) flash = Math.max(0, flash - dt * 2.4);
    else if (Math.random() < 0.005) flash = 1;
  } else flash = 0;
}

/* ---------- 探索雾更新（只重建雾实例，世界不重建） ---------- */
function updateExplored() {
  if (!fogMesh) return;
  var changed = false;
  for (var i = 0; i < explored.length; i++) {
    if (explored[i] && !exploredShadow[i]) {
      exploredShadow[i] = 1;
      changed = true;
    }
  }
  if (changed) rebuildFogMesh();
}

/* ---------- 追踪 / 定位环 ---------- */
function updateGuides() {
  if (!trackRing) {
    trackRing = new THREE.Mesh(
      new THREE.RingGeometry(0.55, 0.72, 26),
      new THREE.MeshBasicMaterial({ color: 0x9333ea, transparent: true, opacity: 0.85, side: THREE.DoubleSide, depthWrite: false })
    );
    trackRing.rotation.x = -Math.PI / 2;
    scene.add(trackRing);
    pulseRingM = trackRing.clone();
    pulseRingM.material = trackRing.material.clone();
    pulseRingM.material.color.set(0xf59e0b);
    scene.add(pulseRingM);
  }
  var tg = E.trackedGuide();
  if (tg) {
    trackRing.visible = true;
    trackRing.position.set(tg.x + 0.5, groundTop(Math.floor(clamp(tg.x, 0, MWv - 1)), Math.floor(clamp(tg.y, 0, MHv - 1))) + 0.1, tg.y + 0.5);
    var s = 1 + Math.sin(tNow * 4) * 0.14;
    trackRing.scale.set(s, s, 1);
  } else trackRing.visible = false;

  var pl = E.pulseLocateRef && E.pulseLocateRef();
  if (pl && Date.now() <= pl.until) {
    pulseRingM.visible = true;
    pulseRingM.position.set(pl.x + 0.5, groundTop(Math.floor(pl.x), Math.floor(pl.y)) + 0.11, pl.y + 0.5);
    var s2 = 1 + Math.sin(tNow * 5) * 0.18;
    pulseRingM.scale.set(s2, s2, 1);
  } else pulseRingM.visible = false;
}

/* ---------- 建造笔刷 ---------- */
function updateBrush() {
  if (!brushBox) {
    var geo = new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 0.3, 1));
    brushBox = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color: 0x9333ea }));
    scene.add(brushBox);
  }
  var bm = E.buildState();
  if (bm && bm.on && brushTile) {
    brushBox.visible = true;
    var r = bm.size || 1, r0 = Math.floor((r - 1) / 2);
    brushBox.scale.set(r, 1, r);
    brushBox.position.set(brushTile.x + r0 + r / 2, groundTop(clamp(brushTile.x, 0, MWv - 1), clamp(brushTile.y, 0, MHv - 1)) + 0.22, brushTile.y + r0 + r / 2);
  } else brushBox.visible = false;
}

/* ================= 覆盖层 ================= */
function roundRect(g, x, y, w2, h2, r) {
  g.beginPath();
  g.moveTo(x + r, y);
  g.arcTo(x + w2, y, x + w2, y + h2, r);
  g.arcTo(x + w2, y + h2, x, y + h2, r);
  g.arcTo(x, y + h2, x, y, r);
  g.arcTo(x, y, x + w2, y, r);
  g.closePath();
}
function project(wx, wy, wz) {
  tmpV.set(wx, wy, wz).project(cam);
  if (tmpV.z > 1) return null;
  return { x: (tmpV.x * 0.5 + 0.5) * w, y: (-tmpV.y * 0.5 + 0.5) * h };
}
function drawLabel(g, x, y, text, color, border) {
  g.font = '11px "PingFang SC","Microsoft YaHei",sans-serif';
  g.textAlign = 'center'; g.textBaseline = 'middle';
  var tw = g.measureText(text).width + 12;
  g.fillStyle = 'rgba(255,255,255,.93)';
  roundRect(g, x - tw / 2, y - 9, tw, 17, 8); g.fill();
  g.strokeStyle = border || 'rgba(124,58,237,.3)'; g.lineWidth = 1;
  roundRect(g, x - tw / 2 + .5, y - 8.5, tw - 1, 16, 7.5); g.stroke();
  g.fillStyle = color || '#4c1d95';
  g.fillText(text, x, y);
}
function drawOverlay() {
  var g = ovCtx;
  if (!g) return;
  g.clearRect(0, 0, w, h);
  var S = E.state();

  var pois = D.POIS;
  for (var i = 0; i < pois.length; i++) {
    var poi = pois[i];
    if (poi.hidden && !S.worldFlags[poi.id + '_found']) {
      var dd = Math.hypot(poi.x - S.player.x, poi.y - S.player.y);
      if (dd > (E.hasSkill('per3') ? 12 : 3)) continue;
    }
    var py = poi.type === 'build' ? 4.1 : (poi.tall ? 6.6 : 2.2);
    var p = project(poi.x + (poi.w || 1) / 2, py, poi.y + (poi.h || 1) / 2);
    if (!p || p.x < -90 || p.y < -40 || p.x > w + 90 || p.y > h + 40) continue;
    drawLabel(g, p.x, p.y, poi.name, poi.custom ? '#9333ea' : '#4c1d95');
  }
  var list = E.npcAll();
  for (i = 0; i < list.length; i++) {
    var e = list[i];
    if (Math.hypot(e.x - S.player.x, e.y - S.player.y) > 30) continue;
    var np = project(e.x, groundTop(Math.floor(e.x), Math.floor(e.y)) + 2.05, e.y);
    if (!np || np.x < -80 || np.y < -30 || np.x > w + 80 || np.y > h + 30) continue;
    var aff = S.npcAff[e.def.id] || 0;
    var lbl = e.def.name + (aff >= 15 ? ' ♡' + aff : '');
    drawLabel(g, np.x, np.y, lbl, e.def.important ? '#6d28d9' : '#6f6785');
  }
  var pp = project(S.player.x, groundTop(Math.floor(S.player.x), Math.floor(S.player.y)) + 1.95, S.player.y);
  if (pp) drawLabel(g, pp.x, pp.y, '你', '#db2777', 'rgba(219,39,119,.35)');

  /* 任务追踪 🎯 */
  var tg = E.trackedGuide();
  if (tg) {
    var tp = project(tg.x + 0.5, groundTop(Math.floor(clamp(tg.x, 0, MWv - 1)), Math.floor(clamp(tg.y, 0, MHv - 1))) + 1.2, tg.y + 0.5);
    if (tp && tp.x > -24 && tp.x < w + 24 && tp.y > -24 && tp.y < h + 24) {
      g.font = '16px "Segoe UI Emoji",sans-serif';
      g.textAlign = 'center'; g.textBaseline = 'middle';
      var pulse = 0.6 + Math.sin(tNow * 4) * 0.4;
      g.strokeStyle = 'rgba(147,51,234,.95)'; g.lineWidth = 2.5;
      g.setLineDash([6, 4]);
      g.beginPath(); g.arc(tp.x, tp.y, 14 + pulse * 5, 0, Math.PI * 2); g.stroke();
      g.setLineDash([]);
      g.fillText('🎯', tp.x, tp.y - 24);
    } else {
      var ang = tp ? Math.atan2(tp.y - h / 2, tp.x - w / 2) : Math.atan2(tg.y - S.player.y, tg.x - S.player.x);
      var cx = w / 2, cy = h / 2, m = 30;
      var ca = Math.cos(ang), sa = Math.sin(ang), len = 1e9;
      if (ca > 0.001) len = Math.min(len, (w - m - cx) / ca);
      if (ca < -0.001) len = Math.min(len, (m - cx) / ca);
      if (sa > 0.001) len = Math.min(len, (h - m - cy) / sa);
      if (sa < -0.001) len = Math.min(len, (m - cy) / sa);
      var ex = cx + ca * Math.max(0, len), ey = cy + sa * Math.max(0, len);
      g.save(); g.translate(ex, ey); g.rotate(ang);
      g.fillStyle = '#7c3aed'; g.strokeStyle = '#fff'; g.lineWidth = 1.5;
      g.beginPath(); g.moveTo(13, 0); g.lineTo(-8, -8); g.lineTo(-3, 0); g.lineTo(-8, 8); g.closePath(); g.fill(); g.stroke();
      g.restore();
      var dist = Math.round(Math.hypot(tg.x - S.player.x, tg.y - S.player.y) * 10);
      g.font = 'bold 11px sans-serif'; g.textAlign = 'center'; g.textBaseline = 'top';
      g.strokeStyle = 'rgba(255,255,255,.9)'; g.lineWidth = 3;
      g.strokeText(dist + 'm', ex, ey + 12);
      g.fillStyle = '#7c3aed'; g.fillText(dist + 'm', ex, ey + 12);
    }
  }
  var pl = E.pulseLocateRef && E.pulseLocateRef();
  if (pl && Date.now() <= pl.until) {
    var lp = project(pl.x + 0.5, 1.2, pl.y + 0.5);
    if (lp && lp.x > -24 && lp.x < w + 24 && lp.y > -24 && lp.y < h + 24) {
      g.font = '16px "Segoe UI Emoji",sans-serif';
      g.textAlign = 'center'; g.textBaseline = 'middle';
      g.fillText('🧭', lp.x, lp.y - 24);
    }
  }
  var wd = D.WEATHERS[S.weather];
  if (wd && wd.vis && wd.vis < 1) {
    var grd = ovCtx.createRadialGradient(w / 2, h / 2, h * 0.2, w / 2, h / 2, h * 0.72);
    grd.addColorStop(0, 'rgba(226,222,240,0)');
    grd.addColorStop(1, 'rgba(216,211,234,.72)');
    g.fillStyle = grd;
    g.fillRect(0, 0, w, h);
  }
  if (flash > 0) {
    g.fillStyle = 'rgba(255,255,255,' + flash * 0.45 + ')';
    g.fillRect(0, 0, w, h);
  }
  if (tNow < hintUntil) {
    g.font = '12px "PingFang SC",sans-serif';
    g.textAlign = 'center'; g.textBaseline = 'middle';
    var tip = '🧊 3D 体素视角 · 滚轮缩放 · 右键拖拽 / Q Z 旋转 · WASD 移动';
    var tw2 = g.measureText(tip).width + 24;
    g.fillStyle = 'rgba(30,20,60,.72)';
    roundRect(g, w / 2 - tw2 / 2, h - 46, tw2, 26, 13); g.fill();
    g.fillStyle = 'rgba(255,255,255,.95)';
    g.fillText(tip, w / 2, h - 33);
  }
}

/* ================= v6 大气生态 / 昼夜打磨 ================= */
var fireflyData = [];
var birdT = 0, birdSpawn = null;

/* 飞鸟 V 形贴图 */
function birdVTex() {
  var c = document.createElement('canvas');
  c.width = c.height = 64;
  var g = c.getContext('2d');
  g.strokeStyle = 'rgba(40,36,54,.92)';
  g.lineWidth = 7; g.lineCap = 'round';
  g.beginPath();
  g.moveTo(8, 24); g.quadraticCurveTo(20, 10, 32, 22);
  g.quadraticCurveTo(44, 10, 56, 24);
  g.stroke();
  var t = new THREE.CanvasTexture(c);
  t.minFilter = THREE.LinearFilter;
  return t;
}
/* 彩虹弧贴图（七色渐隐） */
function rainbowTex() {
  var c = document.createElement('canvas');
  c.width = 256; c.height = 128;
  var g = c.getContext('2d');
  var cols = ['rgba(214,64,64,', 'rgba(232,148,58,', 'rgba(240,220,96,', 'rgba(110,200,110,', 'rgba(96,168,232,', 'rgba(120,110,212,', 'rgba(176,110,206,'];
  for (var i = 0; i < 7; i++) {
    g.strokeStyle = cols[i] + '0.5)';
    g.lineWidth = 9;
    g.beginPath();
    g.arc(128, 132, 118 - i * 9, Math.PI, Math.PI * 2);
    g.stroke();
  }
  var t = new THREE.CanvasTexture(c);
  t.minFilter = THREE.LinearFilter;
  return t;
}
/* 月相贴图：p=0 新月 → 1 满月（带柔光晕） */
function moonPhaseTex(p) {
  var c = document.createElement('canvas');
  c.width = c.height = 128;
  var g = c.getContext('2d');
  var gr = g.createRadialGradient(64, 64, 20, 64, 64, 62);
  gr.addColorStop(0, 'rgba(215,224,248,.55)');
  gr.addColorStop(1, 'rgba(200,215,255,0)');
  g.fillStyle = gr; g.fillRect(0, 0, 128, 128);
  g.fillStyle = '#eef2fc';
  g.beginPath(); g.arc(64, 64, 26, 0, Math.PI * 2); g.fill();
  /* 阴影咬口：随相位偏移 */
  g.globalCompositeOperation = 'source-atop';
  g.fillStyle = 'rgba(16,20,44,.94)';
  g.beginPath(); g.arc(64 + 0.4 + p * 2.3 * 26 - 26 * 1.15, 64, 26.5, 0, Math.PI * 2); g.fill();
  g.globalCompositeOperation = 'source-over';
  var t = new THREE.CanvasTexture(c);
  t.minFilter = THREE.LinearFilter;
  return t;
}

function buildAmbient() {
  var i;
  /* 萤火虫（夜间） */
  var nF = 80, pf = new Float32Array(nF * 3);
  fireflyData = [];
  for (i = 0; i < nF; i++) {
    fireflyData.push({
      a: Math.random() * 6.283, r: 3 + Math.random() * 13,
      h: 0.5 + Math.random() * 1.6, s: 0.4 + Math.random() * 0.8, p: Math.random() * 6.283
    });
  }
  var gf = new THREE.BufferGeometry();
  gf.setAttribute('position', new THREE.BufferAttribute(pf, 3));
  fireflyPts = new THREE.Points(gf, new THREE.PointsMaterial({
    map: radialTex('rgba(222,255,150,1)', 'rgba(150,230,60,0)'), color: 0xd8ff9a,
    size: 0.36, transparent: true, opacity: 0, blending: THREE.AdditiveBlending,
    depthWrite: false, fog: false
  }));
  fireflyPts.frustumCulled = false; fireflyPts.visible = false;
  scene.add(fireflyPts);

  /* 蝴蝶（白昼）：双翼拍动 */
  var bCols = [0xf2a7c3, 0x9ad0f5, 0xf5d76e, 0xc9a3f2, 0xf5b8a0];
  for (i = 0; i < 7; i++) {
    var bg = new THREE.Group();
    var wingGeo = new THREE.PlaneGeometry(0.17, 0.12);
    var wmat = new THREE.MeshBasicMaterial({ color: bCols[i % bCols.length], transparent: true, opacity: 0.95, side: THREE.DoubleSide, depthWrite: false });
    var wL = new THREE.Mesh(wingGeo, wmat); wL.position.x = -0.085;
    var pivL = new THREE.Group(); pivL.add(wL);
    var wR = new THREE.Mesh(wingGeo, wmat); wR.position.x = 0.085;
    var pivR = new THREE.Group(); pivR.add(wR);
    bg.add(pivL); bg.add(pivR);
    bg.userData = {
      pivL: pivL, pivR: pivR, ph: Math.random() * 6.283,
      a: Math.random() * 6.283, r: 3 + Math.random() * 9,
      h: 0.6 + Math.random() * 1.1, sp: 0.3 + Math.random() * 0.5
    };
    bg.visible = false;
    scene.add(bg);
    butterflySprites.push(bg);
  }

  /* 飞鸟（掠空） */
  var bTex = birdVTex();
  for (i = 0; i < 6; i++) {
    var b = makeSprite(bTex, 0.8);
    b.material.fog = false;
    b.visible = false;
    scene.add(b);
    birdSprites.push(b);
  }

  /* 水面日辉光斑 */
  var nG = 56, gp = new Float32Array(nG * 3);
  var gg = new THREE.BufferGeometry();
  gg.setAttribute('position', new THREE.BufferAttribute(gp, 3));
  glintPts = new THREE.Points(gg, new THREE.PointsMaterial({
    map: radialTex('rgba(255,255,232,1)', 'rgba(255,240,180,0)'), color: 0xfff6c8,
    size: 0.55, transparent: true, opacity: 0, blending: THREE.AdditiveBlending,
    depthWrite: false, fog: false
  }));
  glintPts.frustumCulled = false; glintPts.visible = false;
  scene.add(glintPts);
  /* 水面 tile 收集 */
  waterTilesArr = [];
  for (i = 0; i < biomeArr.length; i++) {
    var bb = biomeArr[i];
    if (bb === B.WATER || bb === B.DEEP) waterTilesArr.push({ x: i % MWv, y: (i / MWv) | 0 });
  }

  /* 晨雾贴地板 */
  mistGroup = new THREE.Group();
  var mtex = radialTex('rgba(240,242,250,.5)', 'rgba(232,236,248,0)');
  for (i = 0; i < 10; i++) {
    var mp = new THREE.Mesh(
      new THREE.PlaneGeometry(28, 14),
      new THREE.MeshBasicMaterial({ map: mtex, transparent: true, opacity: 0, depthWrite: false, fog: false })
    );
    mp.rotation.x = -0.14;
    mp.userData = { ph: Math.random() * 6.283, ox: (Math.random() - 0.5) * 56, oz: (Math.random() - 0.5) * 56, sp: 0.3 + Math.random() * 0.5 };
    mistGroup.add(mp);
  }
  mistGroup.visible = false;
  scene.add(mistGroup);

  /* 彩虹 */
  rainbowMesh = new THREE.Mesh(
    new THREE.PlaneGeometry(110, 55),
    new THREE.MeshBasicMaterial({ map: rainbowTex(), transparent: true, opacity: 0, depthWrite: false, fog: false, side: THREE.DoubleSide })
  );
  rainbowMesh.visible = false;
  scene.add(rainbowMesh);

  /* 月相 8 档贴图 */
  moonPhaseTexs = [];
  for (i = 0; i < 8; i++) moonPhaseTexs.push(moonPhaseTex(i / 7));
}

function updateAmbient(dt) {
  var S = E.state();
  var h = (S.timeMin % 1440) / 60;
  var wd = D.WEATHERS[S.weather] || D.WEATHERS.clear;
  var wet = wd.particle === 'rain' || wd.particle === 'storm';
  var dark = lastDarkness >= 0 ? lastDarkness : darknessOf(h);
  var px = S.player.x, pz = S.player.y;
  var i, e;

  /* 风力：晴微风 / 雨中 / 风暴强风 */
  var wT = wd.particle === 'storm' ? 1 : wet ? 0.55 : wd.particle === 'snow' ? 0.45 : 0.16 + 0.1 * Math.sin(tNow * 0.13);
  WIND_U.uWind.value += (wT - WIND_U.uWind.value) * Math.min(1, dt * 0.8);

  /* 萤火虫：夜间 + 非雨 */
  if (fireflyPts) {
    var ffOn = dark > 0.5 && !wet;
    fireflyPts.visible = ffOn;
    if (ffOn) {
      var fp = fireflyPts.geometry.attributes.position;
      for (i = 0; i < fireflyData.length; i++) {
        var fd = fireflyData[i];
        var ft = tNow * fd.s + fd.p;
        var fx = px + Math.cos(fd.a + tNow * 0.05 * fd.s) * fd.r;
        var fz = pz + Math.sin(fd.a + tNow * 0.04 * fd.s) * fd.r;
        var fy = groundTop(clamp(Math.floor(fx), 0, MWv - 1), clamp(Math.floor(fz), 0, MHv - 1)) + fd.h + Math.sin(ft * 0.9) * 0.45;
        fp.setXYZ(i, fx, fy, fz);
      }
      fp.needsUpdate = true;
      fireflyPts.material.opacity = 0.5 + 0.45 * Math.sin(tNow * 2.2);
    }
  }

  /* 蝴蝶：白昼 + 非雨 */
  for (i = 0; i < butterflySprites.length; i++) {
    var bf = butterflySprites[i], ud = bf.userData;
    var bOn = dark < 0.28 && !wet;
    bf.visible = bOn;
    if (!bOn) continue;
    var bt = tNow * ud.sp + ud.ph;
    var bx = px + Math.cos(ud.a + bt * 0.3) * ud.r;
    var bz = pz + Math.sin(ud.a + bt * 0.26) * ud.r;
    bf.position.set(bx, groundTop(clamp(Math.floor(bx), 0, MWv - 1), clamp(Math.floor(bz), 0, MHv - 1)) + ud.h + Math.sin(bt * 2.2) * 0.3, bz);
    bf.rotation.y = -ud.a - bt * 0.3 + Math.PI / 2;
    var flap = Math.sin(bt * 16) * 1.05;
    ud.pivL.rotation.y = flap;
    ud.pivR.rotation.y = -flap;
  }

  /* 飞鸟：间隔掠空 */
  if (birdSprites.length) {
    var flockOn = birdSprites[0].visible;
    if (!flockOn) {
      birdTimer -= dt;
      if (birdTimer <= 0) {
        birdDir = Math.random() * Math.PI * 2;
        var sOff = px - Math.cos(birdDir) * 62, sOff2 = pz - Math.sin(birdDir) * 62;
        birdSpawn = { x: sOff, z: sOff2 };
        birdT = 0;
        for (i = 0; i < birdSprites.length; i++) {
          birdSprites[i].visible = true;
          birdSprites[i].position.set(sOff + (Math.random() - 0.5) * 7, 13 + Math.random() * 3.5, sOff2 + (Math.random() - 0.5) * 7);
        }
      }
    } else {
      birdT += dt;
      for (i = 0; i < birdSprites.length; i++) {
        var bd = birdSprites[i];
        bd.position.x += Math.cos(birdDir) * 7.5 * dt;
        bd.position.z += Math.sin(birdDir) * 7.5 * dt;
        bd.position.y += Math.sin(tNow * 2.6 + i * 1.7) * 0.28 * dt;
      }
      if (birdT > 17) {
        for (i = 0; i < birdSprites.length; i++) birdSprites[i].visible = false;
        birdTimer = 16 + Math.random() * 26;
      }
    }
  }

  /* 水面日辉：晴日波光 */
  if (glintPts) {
    var gOn = dark < 0.3 && !wet && waterTilesArr.length > 0;
    glintPts.visible = gOn;
    if (gOn) {
      if (tNow > glintScatterAt || Math.abs(px - glintAnchor.x) > 8 || Math.abs(pz - glintAnchor.y) > 8) {
        glintScatterAt = tNow + 0.55;
        glintAnchor.x = px; glintAnchor.y = pz;
        var gp2 = glintPts.geometry.attributes.position;
        var gi = 0;
        for (var tr = 0; tr < 160 && gi < gp2.count; tr++) {
          var wt = waterTilesArr[(Math.random() * waterTilesArr.length) | 0];
          var dxw = wt.x + 0.5 - px, dzw = wt.y + 0.5 - pz;
          if (dxw * dxw + dzw * dzw > 484) continue;
          gp2.setXYZ(gi, wt.x + 0.5, smoothTop(wt.x + 0.5, wt.y + 0.5) + 0.05, wt.y + 0.5);
          gi++;
        }
        for (; gi < gp2.count; gi++) gp2.setXYZ(gi, 0, -99, 0);
        gp2.needsUpdate = true;
      }
      glintPts.material.opacity = (0.22 + 0.34 * Math.abs(Math.sin(tNow * 2.3))) * (1 - dark * 2.2);
    }
  }

  /* 晨雾：黎明时段或雾天 */
  if (mistGroup) {
    var mTarget = (h >= 4.8 && h <= 8.2) || S.weather === 'fog' ? 1 : 0;
    mistOnCur += (mTarget - mistOnCur) * Math.min(1, dt * 0.5);
    mistGroup.visible = mistOnCur > 0.02;
    if (mistGroup.visible) {
      var mps = mistGroup.children;
      for (i = 0; i < mps.length; i++) {
        var mpp = mps[i], mu = mpp.userData;
        var mx = px + mu.ox + Math.sin(tNow * 0.07 * mu.sp + mu.ph) * 9;
        var mz = pz + mu.oz + Math.cos(tNow * 0.05 * mu.sp + mu.ph) * 9;
        mpp.position.set(mx, groundTop(clamp(Math.floor(mx), 0, MWv - 1), clamp(Math.floor(mz), 0, MHv - 1)) + 1.6, mz);
        mpp.lookAt(cam.position);
        mpp.material.opacity = mistOnCur * (0.16 + 0.08 * Math.sin(tNow * 0.4 + mu.ph));
      }
    }
  }

  /* 雨后彩虹 */
  if (rainbowMesh) {
    var rbOn = tNow < rainbowUntil;
    rainbowMesh.visible = rbOn;
    if (rbOn) {
      var left = rainbowUntil - tNow;
      var op = Math.min(1, (26 - left) / 3) * Math.min(1, left / 5);
      var ang2 = (h - 6) / 12 * Math.PI;
      rainbowMesh.position.set(px - Math.cos(ang2) * 34, 13, pz - Math.sin(ang2) * 34 + 8);
      rainbowMesh.lookAt(cam.position);
      rainbowMesh.material.opacity = op * 0.62;
    }
  }

  /* 月相：按游戏日轮换 */
  if (moonPhaseTexs && moonSpr) {
    var mDay = Math.floor(((S.day || 1) - 1) * 8 / 29.53) % 8;
    if (mDay !== lastMoonDay) {
      lastMoonDay = mDay;
      moonSpr.material.map = moonPhaseTexs[mDay];
      moonSpr.material.needsUpdate = true;
    }
  }

  /* 星光闪烁 */
  if (stars && stars.visible && starBaseO > 0) {
    stars.material.opacity = starBaseO * (0.78 + 0.22 * (0.5 + 0.5 * Math.sin(tNow * 2.7)));
  }

  /* 路灯渐亮 + 窗光闪烁 */
  var lampT = dark > 0.15 ? 1 : 0;
  lampValCur += (lampT - lampValCur) * Math.min(1, dt * 1.1);
  if (headMat) headMat.color.setHex(0xd8d4e8).lerp(col(0xffe6a3), lampValCur);
  if (lampPoints) {
    lampPoints.visible = lampValCur > 0.04;
    lampPoints.material.opacity = lampValCur * (0.82 + 0.18 * Math.sin(tNow * 3.7));
  }
  if (buildWallMat && buildWallMat.emissiveIntensity > 0) {
    buildWallMat.emissiveIntensity = 1.15 * (0.92 + 0.08 * Math.sin(tNow * 9.3)) * (0.94 + 0.06 * Math.sin(tNow * 23.7));
  }

  /* 云层压暗（雨/风暴） */
  if (cloudMat) {
    var cT = wet ? 0.85 : 0;
    cloudTintCur += (cT - cloudTintCur) * Math.min(1, dt * 0.6);
    if (cloudTintCur > 0.003) {
      cloudMat.color.setRGB(1 - 0.45 * cloudTintCur, 1 - 0.42 * cloudTintCur, 1 - 0.35 * cloudTintCur);
      cloudMat.emissiveIntensity = 0.3 * (1 - cloudTintCur * 0.8);
    }
  }
}

/* ================= 主帧 ================= */
var lastPX = 0, lastPY = 0;
function frame(dt) {
  if (!active || !ready) return;
  var S = E.state();
  if (!S) return;
  if (!sceneBuilt) {
    try { buildScene(); }
    catch (err) {
      console.error('[world-3d] buildScene:', err);
      active = false;
      /* 3D 场景构建失败：自动回退到 2D 渲染层，避免黑屏/空白覆盖 */
      try {
        E.setRenderMode('2d');
        var r = (cvEl && cvEl.parentElement) ? cvEl.parentElement.parentElement : null;
        if (r && r.classList) r.classList.remove('mode-3d');
      } catch (e) {}
      return;
    }
  }
  tNow += dt;
  WIND_U.uTime.value = tNow;

  theta += thetaV * dt; thetaV *= Math.pow(0.02, dt);
  /* 360° 全自由视角：phi 从俯视(≈0)到仰视(≈π)全程可转 */
  phi = clamp(phi + phiV * dt, 0.05, Math.PI - 0.05); phiV *= Math.pow(0.02, dt);
  radius = clamp(radius * (1 + radV * dt), 6, 46); radV *= Math.pow(0.02, dt);

  var p = S.player;
  camLook.x = lerp(camLook.x, p.x, 1 - Math.pow(0.001, dt));
  camLook.z = lerp(camLook.z, p.y, 1 - Math.pow(0.001, dt));
  var lookY = groundTop(Math.floor(p.x), Math.floor(p.y));
  camLook.y = lerp(camLook.y, lookY + 0.6, 0.1);
  var cp = Math.cos(phi), sp = Math.sin(phi);
  cam.position.set(camLook.x + Math.sin(theta) * radius * cp, camLook.y + sp * radius + lookY * 0.2, camLook.z + Math.cos(theta) * radius * cp);
  /* 仰角超过地平线时防止相机钻入地面/建筑地基 */
  var camMinY = Math.max(0.55, groundTop(Math.floor(cam.position.x), Math.floor(cam.position.z)) + 0.35);
  if (cam.position.y < camMinY) cam.position.y = camMinY;
  cam.lookAt(camLook.x, camLook.y, camLook.z);

  var cam2 = E.camRef && E.camRef();
  if (cam2) { cam2.x = camLook.x; cam2.y = camLook.z; }

  /* 玩家小人 */
  if (!playerG) return;
  var pgy = groundTop(Math.floor(p.x), Math.floor(p.y));
  var pvx = p.x - lastPX, pvz = p.y - lastPY;
  var moving = (pvx * pvx + pvz * pvz) > 1e-7;
  var bob = moving ? Math.abs(Math.sin(tNow * 10)) * 0.06 : Math.sin(tNow * 1.5) * 0.015;
  playerG.position.set(p.x, pgy + bob, p.y);
  if (moving) playerG.rotation.y = Math.atan2(pvx, pvz);
  var sw = moving ? Math.sin(tNow * 10) * 0.55 : 0;
  playerParts.armL.rotation.x = sw;
  playerParts.armR.rotation.x = -sw;
  if (playerParts.legL) {
    playerParts.legL.rotation.x = -sw * 0.85;
    playerParts.legR.rotation.x = sw * 0.85;
  }
  /* 上传模型形象：驱动动画混合器（无动画则沿用程序化 bob） */
  if (PMODEL.group) {
    if (PMODEL.mixer) {
      PMODEL.mixer.update(dt);
      modelAnimState(PMODEL, moving);
    }
  }
  lastPX = p.x; lastPY = p.y;
  playerRing.material.opacity = 0.55 + Math.sin(tNow * 3) * 0.2;
  playerLight.position.set(p.x, pgy + 2.2, p.y);

  syncNpcs();
  wantKeep = {};
  syncPulse();
  syncInteractables();
  updateLighting();
  if (!fireflyPts) {
    try { buildAmbient(); } catch (err) { console.error('[world-3d] buildAmbient:', err); }
  }
  updateWeather(dt);
  try { updateAmbient(dt); } catch (err) { console.error('[world-3d] updateAmbient:', err); }
  updateGuides();
  updateBrush();

  /* 水面 UV 流动（主层正向 / 高光层反向 → 波光粼粼）/ 云漂移 / 日月位置 / 灯塔旋转 */
  if (waterSurfMat && waterSurfMat.map) {
    waterSurfMat.map.offset.x = (tNow * 0.025) % 1;
    waterSurfMat.map.offset.y = (tNow * 0.011) % 1;
  }
  if (waterSurf2Mat && waterSurf2Mat.map) {
    waterSurf2Mat.map.offset.x = (-tNow * 0.018) % 1;
    waterSurf2Mat.map.offset.y = (tNow * 0.009 + 0.5) % 1;
  }
  var h24 = (S.timeMin % 1440) / 60;
  var ang = (h24 - 6) / 12 * Math.PI;
  sunSpr.position.set(camLook.x + Math.cos(ang) * 120, Math.max(4, Math.sin(ang) * 100) + 10, camLook.z + 40);
  moonSpr.position.set(camLook.x - Math.cos(ang) * 120, Math.max(4, -Math.sin(ang) * 100) + 10, camLook.z + 40);
  for (var ci = 0; ci < clouds.length; ci++) {
    var cg = clouds[ci];
    cg.g.position.x += cg.v * dt;
    /* 相对玩家区域回绕（x/z 双向），保证云始终在视野附近 */
    var dx = cg.g.position.x - camLook.x;
    if (dx > 55) cg.g.position.x -= 110; else if (dx < -55) cg.g.position.x += 110;
    var dz = cg.g.position.z - camLook.z;
    if (dz > 55) cg.g.position.z -= 110; else if (dz < -55) cg.g.position.z += 110;
  }
  if (lhBeamGroup && lhBeamGroup.visible) lhBeamGroup.rotation.y = tNow * 0.9;
  /* 天空穹顶与星层跟随相机水平位置 */
  if (skyDome) skyDome.position.set(camLook.x, 0, camLook.z);
  if (stars) stars.position.set(camLook.x, 0, camLook.z);

  exploreTimer += dt;
  if (exploreTimer > 0.4) {
    exploreTimer = 0;
    updateExplored();
  }
  if (dirtyEdit && tNow - lastRebuild > 0.25) {
    lastRebuild = tNow;
    dirtyEdit = dirtyExplore = false;
    try { rebuildWorld(); } catch (err) { console.error('[world-3d] rebuild:', err); }
  }

  drawOverlay();
  updateAdaptiveQuality(dt);
  /* 后处理出图（composer 在场则走 bloom + FinalGrade，否则直出回退） */
  if (composer) composer.render();
  else renderer.render(scene, cam);
}

/* ================= 输入 ================= */
var keysHeld = {};
function bindInputs() {
  cvEl.addEventListener('wheel', function (e) {
    if (!active) return;
    e.preventDefault();
    radV = clamp(radV + (e.deltaY > 0 ? 0.9 : -0.9), -3, 3);
  }, { passive: false });
  /* 双指捏合缩放：触屏没有 wheel 事件，补上 3D 视角变焦（张开=拉近） */
  var pinch = null;
  cvEl.addEventListener('touchstart', function (e) {
    if (!active || e.touches.length !== 2) { pinch = null; return; }
    var dx = e.touches[0].clientX - e.touches[1].clientX;
    var dy = e.touches[0].clientY - e.touches[1].clientY;
    pinch = Math.sqrt(dx * dx + dy * dy);
  }, { passive: true });
  cvEl.addEventListener('touchmove', function (e) {
    if (!active || !pinch || e.touches.length !== 2) return;
    var dx = e.touches[0].clientX - e.touches[1].clientX;
    var dy = e.touches[0].clientY - e.touches[1].clientY;
    var d = Math.sqrt(dx * dx + dy * dy);
    if (pinch > 0) radV = clamp(radV + (pinch - d) * 0.03, -3, 3);
    pinch = d;
  }, { passive: true });
  cvEl.addEventListener('touchend', function (e) { if (e.touches.length < 2) pinch = null; }, { passive: true });
  var rot = null;
  cvEl.addEventListener('contextmenu', function (e) { if (active) e.preventDefault(); });
  cvEl.addEventListener('pointerdown', function (e) {
    if (!active || e.button !== 2) return;
    rot = { x: e.clientX, y: e.clientY };
    try { cvEl.setPointerCapture(e.pointerId); } catch (err) {}
  });
  cvEl.addEventListener('pointermove', function (e) {
    if (!rot) return;
    theta -= (e.clientX - rot.x) * 0.006;
    phi = clamp(phi + (e.clientY - rot.y) * 0.005, 0.05, Math.PI - 0.05);
    rot.x = e.clientX; rot.y = e.clientY;
  });
  ['pointerup', 'pointercancel'].forEach(function (ev) {
    cvEl.addEventListener(ev, function () { rot = null; });
  });
  document.addEventListener('keydown', function (e) {
    if (!active) return;
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
    var k = e.key.toLowerCase();
    if (k === 'q') { thetaV = 1.6; keysHeld.q = true; e.preventDefault(); }
    if (k === 'z') { thetaV = -1.6; keysHeld.z = true; e.preventDefault(); }
    /* R 抬升视角（俯视）/ F 压低视角（仰视）——与 Q/Z 组成键盘 360° 环视 */
    if (k === 'r') { phiV = -1.2; keysHeld.r = true; e.preventDefault(); }
    if (k === 'f') { phiV = 1.2; keysHeld.f = true; e.preventDefault(); }
  });
  document.addEventListener('keyup', function (e) {
    var k = e.key.toLowerCase();
    if (k === 'q' || k === 'z') { thetaV = 0; keysHeld.q = keysHeld.z = false; }
    if (k === 'r' || k === 'f') { phiV = 0; keysHeld.r = keysHeld.f = false; }
  });
}

/* ================= 生命周期 ================= */
var _colCache = {};
function col(hex) {
  /* 帧内频繁 new THREE.Color 的替代：按色值缓存复用，消除每帧 GC 压力 */
  if (!_colCache[hex]) _colCache[hex] = new window.THREE.Color(hex);
  return _colCache[hex];
}
function init(cv, ov) {
  if (!available()) throw new Error('THREE 未加载');
  /* 幂等保护：重复进入世界 App 不得重复 new WebGLRenderer，
     否则旧上下文不释放（浏览器上限约 16 个）且事件监听器越积越多 */
  if (ready) { resize(); return; }
  var THREE = window.THREE;
  E = window.WORLD_ENG;
  D = E.D;
  B = D.B;
  cvEl = cv; ovEl = ov;
  ovCtx = ov.getContext('2d');
  renderer = new THREE.WebGLRenderer({ canvas: cvEl, antialias: true, alpha: true, powerPreference: 'high-performance' });
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  if (THREE.sRGBEncoding) renderer.outputEncoding = THREE.sRGBEncoding;
  if (THREE.ACESFilmicToneMapping) {
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.12;
  }
  scene = new THREE.Scene();
  cam = new THREE.PerspectiveCamera(46, 1, 0.1, 500);
  tmpM = new THREE.Matrix4();
  tmpC = new THREE.Color();
  tmpV = new THREE.Vector3();
  tmpQ = new THREE.Quaternion();
  tmpS = new THREE.Vector3();
  raycaster = new THREE.Raycaster();
  planeY0 = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  bindInputs();
  resize();
  /* 初始化后处理管线（若 postFX 库未加载则内部安全跳过，回退到直出渲染） */
  try { initPostFX(); } catch (err) { console.warn('[world-3d] postFX init:', err); }
  ready = true;
}

function resize() {
  if (!renderer || !cvEl) return;
  var rect = cvEl.parentElement.getBoundingClientRect();
  w = Math.max(320, Math.floor(rect.width));
  h = Math.max(240, Math.floor(rect.height));
  renderer.setSize(w, h, false);
  cam.aspect = w / h;
  cam.updateProjectionMatrix();
  /* 后处理管线随窗口尺寸同步 */
  if (composer) { composer.setSize(w, h); if (bloomPass) bloomPass.setSize(w, h); }
}

function setEnabled(on) {
  active = !!on;
  if (active) {
    resize();
    hintUntil = tNow + 6;
    var S = E && E.state();
    if (S) { camLook.x = S.player.x; camLook.z = S.player.y; }
  } else {
    if (ovCtx) ovCtx.clearRect(0, 0, w, h);
  }
}

function screenToTile(cx, cy) {
  if (!cvEl || !cam || !raycaster) return null;
  try {
    var rect = cvEl.getBoundingClientRect();
    var px = ((cx - rect.left) / rect.width) * 2 - 1;
    var py = -((cy - rect.top) / rect.height) * 2 + 1;
    if (px < -1 || px > 1 || py < -1 || py > 1) return null;
    raycaster.setFromCamera({ x: px, y: py }, cam);
    var hit = raycaster.ray.intersectPlane(planeY0, tmpV);
    if (!hit) return null;
    var tx = Math.floor(hit.x), ty = Math.floor(hit.z);
    if (tx < 0 || ty < 0 || tx >= MWv || ty >= MHv) return null;
    return { x: tx, y: ty };
  } catch (e) { return null; }
}

function inputAngle() { return theta; }
function setBrushCursorTile(t) { brushTile = t; }
function tileChanged() { dirtyEdit = true; }
function markTerrainDirty() { dirtyEdit = true; }
function rotateBy(a) { thetaV = clamp(a * 6, -6, 6); }

var ext = {
  available: available,
  init: init,
  ready: function () { return ready; },
  enabled: function () { return active; },
  frame: frame,
  resize: resize,
  setEnabled: setEnabled,
  screenToTile: screenToTile,
  inputAngle: inputAngle,
  setBrushCursorTile: setBrushCursorTile,
  tileChanged: tileChanged,
  markTerrainDirty: markTerrainDirty,
  rotateBy: rotateBy,
  /* 3D 形象：玩家 / 许墨双槽位独立，传 null 恢复各自默认形象 */
  setAvatar3D: function (playerUrl, xumoUrl) {
    PMODEL.stateFetched = true;
    applyAvatar3D(playerUrl || null, xumoUrl || null);
  },
  avatar3DActive: function () { return PMODEL.url; }
};

window.WORLD3D = { init: init, ext: ext, available: available, rotateBy: rotateBy,
  /* 建模扩展·v2：高程偏移已内嵌 groundTop，无需额外字段 */ };

})();
