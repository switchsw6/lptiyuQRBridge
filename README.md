# lptiyuQRBridge

> 本项目基于 **vibe coding** 模式开发：人和 AI 结对迭代，跑通即交付。

模拟器里没装微信，也能让步道乐跑完成微信登录：装一个「扫码步道乐跑」助手，授权请求被它接住，电脑端向微信要一张真正的扫码授权二维码，你用手机扫一下并确认，授权码原样回投给应用，登录由应用自己完成。搭配https://github.com/switchsw6/fklptiyu项目使用更佳。

## 用法

```text
1. 打开模拟器（Android 8+，能 adb root），里面装好步道乐跑 4.2.0
2. 双击 run.cmd，按提示选模拟器
3. 手机微信扫码并在手机上确认
```

**解压即用**：包里的 `credentials.private.json` 已经配好，不需要你去弄 AppSecret、也不用任何登录或注册。

`run.cmd` 会自动检查两个 App（缺失就装助手；步道乐跑请先自己装好）、打通端口环回、准备 frida-server、起授权服务、装上证书钩子，最后启动步道乐跑并提示你点击微信登录。整个过程脚本不会替你点屏幕，扫码确认由你完成。

- 停止：双击 `stop.cmd`
- 日志：`.state\server.log`、`.state\hook.log`

## 它做了什么

- 助手包名固定 `com.tencent.mm`，用来占住 ShareSDK/OpenSDK 里写死的包名与组件名；业务代码都在 `com.lptiyu.qrbridge.hc`
- 微信签名由 `system_server` 里的运行时钩子提供，**步道乐跑本体一个字节不改**
- 授权码只在本机环回（`adb reverse`）里传输；服务端日志只记状态，不记授权码

## 前置条件

- Windows + Python 3.11+（没有 frida 16 会自动建 `venv` 装好）
- 模拟器已开启 root（`adb root` 可用）
- 手机装了微信
- 步道乐跑 4.2.0 官方包，自己装进模拟器

## 常见问题

| 现象 | 处理 |
|---|---|
| 应用提示"微信未安装" | 钩子没装上，重跑 `run.cmd` |
| 二维码过期 | 助手界面点「刷新二维码」 |
| 首次启动崩溃一次 | 原包已知问题，再启动一次即可 |
| 端口 18371 被占用 | 关掉占用程序再跑 |
| 装助手报签名冲突 | 模拟器里有真微信，先 `adb uninstall com.tencent.mm` |

## 目录

```text
run.cmd / stop.cmd           一键部署与停止
scripts/deploy_local.py      部署编排（设备选择、安装检查、自动进登录页）
scripts/build_qr_bridge.py   构建助手 APK（自签、产物自检）
scripts/qr_login/            证书钩子与调试脚本
src/lepao_qr_bridge/         电脑端授权服务 + 助手源码（Java）
```

## 边界

不改步道乐跑、不写微信数据、不抓第三方流量，仅在本机环回内工作。请只在你自己的设备上使用，并遵守步道乐跑与微信的用户协议。
