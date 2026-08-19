(function(global){
  'use strict';

  var DOMAINS = [
    {id:'relationship', label:'关系', description:'关系进展、长期记忆与日常联系', apps:'affinity ourstory moments memory quotes promises xumodiary review dates chathist diary letter habits together achv pet wish phone sms timebox'.split(' ')},
    {id:'life', label:'生活', description:'共同生活、媒体陪伴与日常工具', apps:'notes ledger together-shop clock weather listen photos codraw watch wardrobe radio planner work clip browser go lab'.split(' ')},
    {id:'growth', label:'成长', description:'学习、创作与可交付成果', apps:'words coach video solve reading cowrite img2img spark'.split(' ')},
    {id:'world', label:'世界', description:'角色世界、故事与探索体验', apps:'world dream pverse astro bsfile'.split(' ')},
    {id:'wellbeing', label:'心境', description:'情绪支持、自我理解与决策反思', apps:'mind bfly deep debate oracle sos lifeline div'.split(' ')},
    {id:'lab', label:'实验', description:'低频新奇玩法与主题化生成体验', apps:'timecall nradio pmail telepathy fate pulse subconscious capsule empath noracle whisper mixer rtm fusion theater fateecho vault pulselab rift wager relic symbiote dreamloom emoweather parallel puzzle dradio garden mirror weaver alchemy compass dreamlab'.split(' ')},
    {id:'platform', label:'平台', description:'配置、管理与能力扩展', apps:'settings extensions'.split(' ')}
  ];

  var EXPERIMENT_THEMES = [
    {id:'dream', label:'梦境与潜意识', description:'探索梦境、潜意识与内在映射', icon:'/static/img/icons/t/dreamlab.png?v=3', apps:'dreamlab dreamloom subconscious theater mirror'.split(' ')},
    {id:'fate', label:'命运与平行线', description:'推演选择、分岔与平行可能', icon:'/static/img/icons/t/pmail.png?v=3', apps:'pmail parallel fate weaver rift wager'.split(' ')},
    {id:'memory', label:'记忆与时间', description:'保存、修复与重组共同记忆', icon:'/static/img/icons/t/t_capsule.png?v=3', apps:'capsule rtm vault relic puzzle garden'.split(' ')},
    {id:'emotion', label:'情绪与共感', description:'感知情绪、共鸣与无声表达', icon:'/static/img/icons/t/t_emoweather.png?v=3', apps:'emoweather empath whisper dradio nradio'.split(' ')},
    {id:'relation', label:'关系测量', description:'观察默契、心跳与关系变化', icon:'/static/img/icons/t/telepathy.png?v=3', apps:'telepathy pulse mixer pulselab fusion alchemy symbiote'.split(' ')},
    {id:'symbol', label:'预言与象征', description:'解读预言、回声与象征线索', icon:'/static/img/icons/t/t_oracle7.png?v=3', apps:'noracle fateecho compass timecall'.split(' ')}
  ];

  /*
   * 高频业务域里的相似 App 共用一个桌面入口。这里只合并“入口”，不改 App key、
   * API 或存储文件，因此搜索、推荐、历史深链与已有用户数据仍可直接打开原功能。
   * 实验域继续使用上面的主题分组，避免同一个 App 同时落入两套入口。
   */
  var FEATURE_GROUPS = [
    {id:'chronicle', domain:'relationship', label:'共同回忆', description:'故事、记忆、日记与阶段回顾', icon:'/static/img/icons/t/story_main.png?v=3', apps:'ourstory memory quotes xumodiary review chathist diary'.split(' ')},
    {id:'commitments', domain:'relationship', label:'约定与心愿', description:'承诺、习惯和共同心愿', icon:'/static/img/icons/t/promises.png?v=3', apps:'promises habits wish'.split(' ')},
    {id:'milestones', domain:'relationship', label:'关系里程碑', description:'约会、合影、成就与纪念日', icon:'/static/img/icons/t/dates.png?v=3', apps:'dates together achv timebox'.split(' ')},
    {id:'contact', domain:'relationship', label:'联系许墨', description:'电话、短信与书信', icon:'/static/img/icons/t/dialpad.png?v=3', apps:'phone sms letter'.split(' ')},
    {id:'organize', domain:'life', label:'计划与整理', description:'记录、规划、工作整理与素材收集', icon:'/static/img/icons/t/planner.svg?v=1', apps:'notes planner work clip'.split(' ')},
    {id:'audio', domain:'life', label:'声音陪伴', description:'一起听音乐与许墨电台', icon:'/static/img/icons/t/listen.png?v=3', apps:'listen radio'.split(' ')},
    {id:'visual-life', domain:'life', label:'影像与装扮', description:'相册、共同绘画与衣橱', icon:'/static/img/icons/t/photos.png?v=3', apps:'photos codraw wardrobe'.split(' ')},
    {id:'daily-tools', domain:'life', label:'日常工具', description:'时钟、天气与共同记账', icon:'/static/img/icons/t/clock.png?v=3', apps:'clock weather ledger'.split(' ')},
    {id:'learning', domain:'growth', label:'学习空间', description:'单词、专注、解题与共读', icon:'/static/img/icons/t/coach_a.png?v=3', apps:'words coach solve reading'.split(' ')},
    {id:'writing', domain:'growth', label:'写作与灵感', description:'共同写作与灵感捕捉', icon:'/static/img/icons/t/cowrite_article.svg?v=1', apps:'cowrite spark'.split(' ')},
    {id:'reflection', domain:'wellbeing', label:'自我探索', description:'心智观察、深度共鸣与观点辩论', icon:'/static/img/icons/t/mind.png?v=3', apps:'mind deep debate'.split(' ')},
    {id:'support', domain:'wellbeing', label:'情绪照护', description:'温柔陪伴与即时情绪支持', icon:'/static/img/icons/t/bfly.png?v=3', apps:'bfly sos'.split(' ')},
    {id:'decisions', domain:'wellbeing', label:'选择与推演', description:'决策分析、占卜象征与人生模拟', icon:'/static/img/icons/t/oracle.png?v=3', apps:'oracle div lifeline'.split(' ')}
  ];

  var experimentThemeByApp = {};
  EXPERIMENT_THEMES.forEach(function(theme){
    theme.apps.forEach(function(app){ experimentThemeByApp[app] = theme; });
  });
  var featureGroupByApp = {};
  FEATURE_GROUPS.forEach(function(group){
    group.apps.forEach(function(app){ featureGroupByApp[app] = group; });
  });

  var DEFAULTS = {
    relationship:{tier:'核心', frequency:'高频', interaction:'陪伴', maturity:'稳定'},
    life:{tier:'留存', frequency:'中频', interaction:'共同任务', maturity:'稳定'},
    growth:{tier:'价值', frequency:'中频', interaction:'任务', maturity:'稳定'},
    world:{tier:'差异化', frequency:'中频', interaction:'探索', maturity:'成长中'},
    wellbeing:{tier:'信任', frequency:'按需', interaction:'引导', maturity:'成长中'},
    lab:{tier:'实验', frequency:'低频', interaction:'生成', maturity:'试验中'},
    platform:{tier:'基础', frequency:'按需', interaction:'配置', maturity:'成长中'}
  };

  var OVERRIDES = {
    moments:{interaction:'社交'}, phone:{interaction:'联系'}, sms:{interaction:'联系'},
    notes:{interaction:'记录'}, ledger:{interaction:'记录'}, clock:{interaction:'工具'}, weather:{interaction:'工具'},
    listen:{interaction:'媒体'}, photos:{interaction:'媒体'}, watch:{interaction:'媒体'}, radio:{interaction:'媒体'},
    browser:{interaction:'工具'}, clip:{interaction:'工具'}, work:{interaction:'任务'}, planner:{interaction:'任务'},
    words:{interaction:'学习'}, coach:{interaction:'学习'}, reading:{interaction:'学习'}, solve:{interaction:'学习'},
    video:{interaction:'生成'}, cowrite:{interaction:'创作'}, img2img:{interaction:'创作'}, spark:{interaction:'创作'},
    world:{interaction:'探索'}, pverse:{interaction:'叙事'}, dream:{interaction:'叙事'}, bsfile:{interaction:'收集'},
    sos:{tier:'信任', interaction:'支持'}, deep:{interaction:'引导'},
    settings:{interaction:'配置', maturity:'稳定'}, extensions:{interaction:'构建'},
    go:{frequency:'低频'}, lab:{frequency:'低频'}, wardrobe:{frequency:'低频'}
  };

  var TAGS = {
    affinity:'关系 阶段 亲密', ourstory:'故事 事件 时间线 回忆 翻页', moments:'动态 点赞 评论 社交', memory:'记忆 长期 上下文', quotes:'收藏 语录',
    promises:'约定 提醒', xumodiary:'日记 许墨视角', review:'总结 回顾', dates:'约会', chathist:'聊天 历史 存档',
    diary:'恋爱 日记', letter:'来信', habits:'打卡 习惯', together:'合影 日历', achv:'成就 徽章', pet:'宠物 养成',
    wish:'许愿', phone:'电话 通话', sms:'短信 联系', timebox:'纪念 时间',
    words:'单词 测验 错题', coach:'专注 学习 番茄钟', video:'视频 总结', solve:'题目 讲解', reading:'读书 共读',
    cowrite:'文章 写作 润色', img2img:'图片 重绘', spark:'灵感', world:'3D 地图 恋语市',
    sos:'情绪 急救 支持', extensions:'AI 扩展 工作流', settings:'设置 偏好 管理'
  };

  var byApp = {};
  DOMAINS.forEach(function(domain){
    domain.apps.forEach(function(app){
      var base = DEFAULTS[domain.id];
      var override = OVERRIDES[app] || {};
      byApp[app] = {
        app:app,
        domain:domain.id,
        domainLabel:domain.label,
        domainDescription:domain.description,
        tier:override.tier || base.tier,
        frequency:override.frequency || base.frequency,
        interaction:override.interaction || base.interaction,
        maturity:override.maturity || base.maturity,
        tags:(TAGS[app] || '') + (experimentThemeByApp[app] ? ' ' + experimentThemeByApp[app].label : ''),
        experimentTheme:experimentThemeByApp[app] ? experimentThemeByApp[app].id : '',
        experimentThemeLabel:experimentThemeByApp[app] ? experimentThemeByApp[app].label : '',
        featureGroup:featureGroupByApp[app] ? featureGroupByApp[app].id : '',
        featureGroupLabel:featureGroupByApp[app] ? featureGroupByApp[app].label : ''
      };
    });
  });

  var DIMENSIONS = {
    tier:['核心','留存','价值','差异化','信任','实验','基础'],
    frequency:['高频','中频','按需','低频'],
    interaction:['陪伴','社交','联系','记录','共同任务','媒体','工具','任务','学习','生成','创作','探索','叙事','收集','引导','支持','配置','构建'],
    maturity:['稳定','成长中','试验中']
  };

  function get(app){
    return byApp[app] || {
      app:app, domain:'uncategorized', domainLabel:'待分类', domainDescription:'尚未纳入分类系统',
      tier:'实验', frequency:'低频', interaction:'其他', maturity:'试验中', tags:''
    };
  }

  function matches(meta, filters){
    filters = filters || {};
    return (!filters.domain || filters.domain === '*' || meta.domain === filters.domain) &&
      (!filters.tier || filters.tier === '*' || meta.tier === filters.tier) &&
      (!filters.frequency || filters.frequency === '*' || meta.frequency === filters.frequency) &&
      (!filters.interaction || filters.interaction === '*' || meta.interaction === filters.interaction) &&
      (!filters.maturity || filters.maturity === '*' || meta.maturity === filters.maturity);
  }

  function themeFor(app){
    return experimentThemeByApp[app] || null;
  }

  function groupFor(app){
    return featureGroupByApp[app] || null;
  }

  global.XUMO_APP_TAXONOMY = {
    version:4,
    domains:DOMAINS,
    featureGroups:FEATURE_GROUPS,
    experimentThemes:EXPERIMENT_THEMES,
    dimensions:DIMENSIONS,
    apps:byApp,
    get:get,
    matches:matches,
    themeFor:themeFor,
    groupFor:groupFor
  };
})(window);
