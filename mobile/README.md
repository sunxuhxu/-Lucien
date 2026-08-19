# 许墨 Android 客户端

这是现有 FastAPI 网站的 Capacitor Android 容器。APK 不保存 `.env` 或 AI API Key，网页和 API 由同一个远程服务提供，因此现有的相对路径 `/api/*` 与 Cookie 登录可以继续工作。

## 环境

- Node.js 20 或更高
- JDK 17
- Android SDK（当前工程使用 Capacitor 6，以匹配 JDK 17）

应用声明了录音和相机权限，分别用于网页语音输入和图片选择/拍摄。权限只在网页实际请求时弹窗。

## 调试构建

Android 模拟器默认通过 `http://10.0.2.2:8000` 访问电脑上的服务。

```powershell
cd mobile
npm install
npm run build:debug
```

真机测试时，将地址改为电脑的局域网 IP：

```powershell
$env:CAPACITOR_SERVER_URL = 'http://192.168.1.10:8000'
npm run build:debug
```

正式版必须使用稳定的 HTTPS 域名：

```powershell
$env:CAPACITOR_SERVER_URL = 'https://example.com'
npm run build:release
```

调试构建允许局域网 HTTP；正式构建会禁止明文 HTTP。

调试 APK 位于 `android/app/build/outputs/apk/debug/app-debug.apk`。正式 AAB 需先配置 Android 签名，不要将密钥库或口令提交到 Git。
