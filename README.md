# 许墨 · Lucien 智能体

一个以许墨为角色核心的沉浸式 AI 陪伴应用，包含长期记忆、文字与语音互动、社交陪伴、学习工具、故事世界、3D 恋语市，以及 90+ 个手机应用。

## 快速开始

### Windows 一键启动

双击项目根目录的 `启动器.bat`。启动器会检查服务并打开应用页面。

### 命令行启动

1. 安装 Python 依赖：

   ```powershell
   python -m pip install -r requirements.txt
   ```

2. 复制 `.env.example` 为 `.env`，至少填写 `OPENAI_API_KEY`，并按服务商设置 `OPENAI_BASE_URL` 与 `MODEL`。

3. 启动服务：

   ```powershell
   python app.py
   ```

4. 在浏览器访问 `http://127.0.0.1:8000/`。端口可通过 `.env` 中的 `PORT` 修改。

> 请勿提交 `.env`、访问口令、API Key 或用户数据。示例配置只应保留占位值。

## 第一次使用

首次进入主页面会自动出现新手导览。之后可随时从聊天顶部的「❓ 引导」，或「设置 → 功能引导」重新打开。

- 在主聊天室输入内容，按 `Enter` 发送，`Shift+Enter` 换行。
- 输入栏与回复下方的「许墨建议」会结合当前话题、使用习惯、时段和反馈推荐功能；推荐卡会说明原因，可选择「有帮助」或「不感兴趣」。
- 在手机区域先按“关系、生活、成长、世界、心境、实验、平台”浏览，再按层级、频率、交互方式与成熟度组合筛选。相近的稳定功能合并为 13 个功能组，实验类 33 项收拢为 6 个主题；默认桌面因此从 93 个 App 精简为 36 个入口。进入功能组后仍可选择具体模式，搜索、推荐和历史链接也仍可直达任一原功能。
- 点击消息气泡右上角的 `☆` 收藏内容，之后可在「语录」中查看。
- 语音能力仅对已授权的主人模式开放；局域网麦克风需要 HTTPS 安全连接。

完整用户教程：

- `/tutorial.html`：完整版本
- `/tutorial_novoice.html`：纯文字体验版本

## 常用入口

- `/`：主应用
- `/register.html`：注册与资料设置
- `/tutorial.html`：完整使用教程
- `/map.html`：恋语市地图
- `/story.html`：故事页
- `/wonder.html`：奇想页

## 配置说明

主要配置都在 `.env`：

- `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`MODEL`：对话模型
- `IMAGE_API_KEY`、`IMAGE_BASE_URL`、`IMAGE_MODEL`：可选的图像模型
- `PORT`：Web 服务端口，默认 `8000`
- 图像配额与付费配置：详见 `.env.example` 内的注释

修改配置后请重启服务。若页面仍显示旧资源，可强制刷新浏览器缓存。

## 项目结构

- `app.py`：FastAPI 主服务与 API
- `static/index.html`：主应用界面和内置功能引导
- `static/tutorial*.html`：用户教程
- `*_apps.py`：各类扩展应用模块
- `static/`：页面、样式、脚本、图标与静态资源
- `docs/`：设计与优化记录
