package com.tencent.mm.plugin.base.stub;

/**
 * 兼容壳，唯一职责：占据步道乐跑内置 OpenSDK 写死的组件名
 * com.tencent.mm/plugin.base.stub.WXEntryActivity。
 *
 * 该字符串常量与包名一起固化在目标应用里：
 *   recovered1-verified.dex / recovered6-verified.dex 中的
 *   "com.tencent.mm.plugin.base.stub.WXEntryActivity"
 * 因此清单包名必须是 com.tencent.mm，类名也必须落在这条路径上。
 * 全部业务逻辑在 com.lptiyu.qrbridge.hc.QRBridgeActivity。
 */
public final class WXEntryActivity extends com.lptiyu.qrbridge.hc.QRBridgeActivity {
}
