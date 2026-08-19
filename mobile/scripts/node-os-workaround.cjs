// Node 24 can report uv_os_get_passwd/ENOMEM in some restricted Windows
// environments. Capacitor only needs the shell name, so provide a safe
// fallback while leaving normal environments untouched.
const os = require('node:os');

try {
  os.userInfo();
} catch {
  os.userInfo = () => ({
    uid: -1,
    gid: -1,
    username: process.env.USERNAME || 'android-builder',
    homedir: process.env.USERPROFILE || '',
    shell: process.env.ComSpec || 'cmd.exe'
  });
}
