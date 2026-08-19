import type { CapacitorConfig } from '@capacitor/cli';

const configuredUrl = process.env.CAPACITOR_SERVER_URL?.trim();
const serverUrl = configuredUrl || 'http://10.0.2.2:8000';

const config: CapacitorConfig = {
  appId: 'com.xumo.companion',
  appName: '许墨',
  webDir: 'www',
  server: {
    url: serverUrl,
    cleartext: serverUrl.startsWith('http://'),
    androidScheme: 'https'
  },
  android: {
    allowMixedContent: false,
    captureInput: true,
    webContentsDebuggingEnabled: process.env.CAPACITOR_DEBUG === '1'
  }
};

export default config;
