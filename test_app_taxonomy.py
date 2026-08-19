import re
from pathlib import Path


ROOT = Path(__file__).parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
TAXONOMY = (ROOT / "static" / "app-taxonomy.js").read_text(encoding="utf-8")


def _main_apps():
    match = re.search(
        r'<div class="icon-grid" id="iconGrid">([\s\S]*?)</div>\s*<div class="dock">([\s\S]*?)</div>',
        INDEX,
    )
    assert match, "主应用网格或 dock 未找到"
    return set(re.findall(r'data-app="([^"]+)"', match.group(0)))


def _taxonomy_apps():
    domains = TAXONOMY.split("var EXPERIMENT_THEMES", 1)[0]
    groups = re.findall(r"apps:'([^']+)'\.split\(' '\)", domains)
    assert len(groups) == 7, "业务域数量应为 7"
    apps = [app for group in groups for app in group.split()]
    assert len(apps) == len(set(apps)), "一个 App 不能属于多个主业务域"
    return set(apps)


def test_taxonomy_covers_every_visible_app():
    assert _taxonomy_apps() == _main_apps()


def test_multidimensional_filters_are_wired_to_ui():
    assert '/static/app-taxonomy.js?v=4' in INDEX
    assert 'id="facetBar"' in INDEX
    for dimension in ("tier", "frequency", "interaction", "maturity"):
        assert f"{dimension}:[" in TAXONOMY
        assert f"data-{dimension}" in INDEX


def test_compact_filter_toolbar_uses_progressive_disclosure():
    assert 'id="mobileDomainSelect"' in INDEX
    assert 'id="mobileFacetToggle"' in INDEX
    assert 'aria-controls="facetBar"' in INDEX
    assert '.facet-bar{display:none;grid-template-columns:repeat(2,minmax(0,1fr))' in INDEX
    assert ".facet-bar.mobile-open{display:grid}" in INDEX
    assert "facetBar.classList.toggle('mobile-open', open)" in INDEX


def test_expected_portfolio_shape():
    domains = TAXONOMY.split("var EXPERIMENT_THEMES", 1)[0]
    groups = re.findall(r"\{id:'([^']+)', label:'([^']+)'[^\n]+apps:'([^']+)'", domains)
    counts = {domain: len(apps.split()) for domain, _, apps in groups}
    assert counts == {
        "relationship": 20,
        "life": 17,
        "growth": 8,
        "world": 5,
        "wellbeing": 8,
        "lab": 33,
        "platform": 2,
    }


def test_experiment_features_are_grouped_into_six_complete_themes():
    section = TAXONOMY.split("var EXPERIMENT_THEMES", 1)[1].split("var FEATURE_GROUPS", 1)[0]
    groups = re.findall(r"\{id:'([^']+)', label:'([^']+)'[^\n]+apps:'([^']+)'", section)
    assert len(groups) == 6
    themed_apps = [app for _, _, apps in groups for app in apps.split()]
    assert len(themed_apps) == 33
    assert len(themed_apps) == len(set(themed_apps))
    assert {label: apps.split() for _, label, apps in groups} == {
        "梦境与潜意识": ["dreamlab", "dreamloom", "subconscious", "theater", "mirror"],
        "命运与平行线": ["pmail", "parallel", "fate", "weaver", "rift", "wager"],
        "记忆与时间": ["capsule", "rtm", "vault", "relic", "puzzle", "garden"],
        "情绪与共感": ["emoweather", "empath", "whisper", "dradio", "nradio"],
        "关系测量": ["telepathy", "pulse", "mixer", "pulselab", "fusion", "alchemy", "symbiote"],
        "预言与象征": ["noracle", "fateecho", "compass", "timecall"],
    }
    lab = next(apps for domain, _, apps in re.findall(r"\{id:'([^']+)', label:'([^']+)'[^\n]+apps:'([^']+)'", TAXONOMY.split("var EXPERIMENT_THEMES", 1)[0]) if domain == "lab")
    assert set(themed_apps) == set(lab.split())
    assert 'className = \'app-icon experiment-hub\'' in INDEX
    assert "state.experimentTheme = theme.id" in INDEX


def test_similar_stable_features_share_thirteen_desktop_entries():
    section = TAXONOMY.split("var FEATURE_GROUPS", 1)[1].split("var experimentThemeByApp", 1)[0]
    groups = re.findall(
        r"\{id:'([^']+)', domain:'([^']+)', label:'([^']+)'[^\n]+apps:'([^']+)'",
        section,
    )
    assert len(groups) == 13
    grouped_apps = [app for _, _, _, apps in groups for app in apps.split()]
    assert len(grouped_apps) == 43
    assert len(grouped_apps) == len(set(grouped_apps))
    taxonomy_apps = _taxonomy_apps()
    assert set(grouped_apps) <= taxonomy_apps

    domain_apps = {
        domain: set(apps.split())
        for domain, _, apps in re.findall(
            r"\{id:'([^']+)', label:'([^']+)'[^\n]+apps:'([^']+)'",
            TAXONOMY.split("var EXPERIMENT_THEMES", 1)[0],
        )
    }
    for _, domain, _, apps in groups:
        assert set(apps.split()) <= domain_apps[domain]

    # 93 个原 App 保持可直达，桌面默认只呈现 36 个清晰入口。
    standalone = len(taxonomy_apps) - len(grouped_apps) - 33
    assert standalone + len(groups) + 6 == 36
    assert "state.featureGroup = group.id" in INDEX
    assert "meta.featureGroup === state.featureGroup" in INDEX
    assert "else if(state.featureGroup !== '*')" in INDEX


def test_recommendation_domains_cover_taxonomy():
    from recommendation_engine import APP_DOMAIN

    # 设置页不应主动推荐，其他可见 App 都必须具备推荐业务域。
    assert _taxonomy_apps() - {"settings"} <= set(APP_DOMAIN)
