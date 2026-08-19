import re
from pathlib import Path

# Extract all icon references from tutorial.html
tutorial_path = Path("G:/xumo/static/tutorial.html")
tutorial_content = tutorial_path.read_text(encoding="utf-8")

# Find all icon references
icon_pattern = r'src="/static/img/icons/t/([^"]+\.png)'
icons_in_html = set(re.findall(icon_pattern, tutorial_content))

# Check which icons exist
icons_dir = Path("G:/xumo/static/img/icons/t")
existing_icons = set([f.name for f in icons_dir.glob("*.png")])

# Find missing icons
missing_icons = icons_in_html - existing_icons

print(f"Total icons referenced in HTML: {len(icons_in_html)}")
print(f"Total icons existing in directory: {len(existing_icons)}")
print(f"Missing icons: {len(missing_icons)}")
print("\nMissing icons:")
for icon in sorted(missing_icons):
    print(f"  - {icon}")

# Also check for emojis that could be used as fallback
print("\nPotential emoji replacements:")
emoji_mapping = {
    "review.png": "📖",
    "mic.png": "🎤",
    "speaker.png": "🔊",
    "radio.png": "📻",
    "bgm.png": "🎵",
    "screen.png": "🖥️",
    "history.png": "📜",
    "sms.png": "💬",
    "dialpad.png": "🔢",
    "chat_text.png": "💭",
    "world_map.png": "🗺️",
    "heart.png": "❤️",
    "moments.png": "📸",
    "quotes.png": "💭",
    "memory.png": "🧠",
    "notes.png": "📝",
    "promises.png": "🤝",
    "xumodiary.png": "📔",
    "ledger.png": "📒",
    "clock.png": "⏰",
    "weather.png": "🌤️",
    "settings.png": "⚙️",
    "avatar.png": "👤",
    "bgimg.png": "🖼️",
}

for icon in sorted(missing_icons):
    if icon in emoji_mapping:
        print(f"  - {icon} -> {emoji_mapping[icon]}")
