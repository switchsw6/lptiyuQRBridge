package com.lptiyu.qrbridge.hc;

import android.app.Activity;
import android.content.Intent;
import android.graphics.BitmapFactory;
import android.net.Uri;
import android.os.Bundle;
import android.util.Base64;
import android.util.Log;
import android.view.Gravity;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONObject;

/**
 * lptiyuQRBridge 的全部界面与协议逻辑。
 *
 * 包名 com.tencent.mm 与 com.tencent.mm.plugin.base.stub.WXEntryActivity 这两个字符串
 * 被步道乐跑内置的 ShareSDK / WeChat OpenSDK 写死（见 docs/verification-20261107.md），
 * 所以真正挂载到清单里的仍是 com.tencent.mm.plugin.base.stub.WXEntryActivity，
 * 它只是本类的 3 行转接壳；业务代码都在这里。
 */
public class QRBridgeActivity extends Activity {
    private static final String TARGET = "com.lptiyu.tanke";
    private static final String APPID = "wx5a2e1ff396785475";
    private static final String TAG = "LepaoQRBridge";
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private volatile int generation;
    private volatile boolean complete;
    private boolean authRequest;
    private Intent original;
    private TextView status;
    private ImageView qr;
    private Button refresh;
    private String bridgeToken;
    private volatile HttpURLConnection activeConnection;

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setGravity(Gravity.CENTER);
        layout.setPadding(36, 40, 36, 40);
        TextView title = new TextView(this);
        title.setText("步道乐跑 · 微信扫码授权");
        title.setTextSize(24);
        layout.addView(title);
        status = new TextView(this);
        status.setGravity(Gravity.CENTER);
        status.setTextSize(17);
        layout.addView(status, new LinearLayout.LayoutParams(-1, 180));
        qr = new ImageView(this);
        int size = Math.min(getResources().getDisplayMetrics().widthPixels - 100, 960);
        layout.addView(qr, new LinearLayout.LayoutParams(size, size));
        TextView info = new TextView(this);
        info.setText("请用手机微信扫一扫，核对授权应用为“步道乐跑”后确认。\n此助手不需要在模拟器中安装微信。");
        info.setGravity(Gravity.CENTER);
        info.setTextSize(16);
        layout.addView(info, new LinearLayout.LayoutParams(-1, 190));
        refresh = new Button(this);
        refresh.setText("刷新二维码");
        refresh.setOnClickListener(v -> begin());
        layout.addView(refresh);
        Button cancel = new Button(this);
        cancel.setText("取消并返回乐跑");
        cancel.setOnClickListener(v -> cancel());
        layout.addView(cancel);
        setContentView(layout);
        try (InputStream stream = getAssets().open("bridge.json")) {
            bridgeToken = new JSONObject(new String(read(stream), StandardCharsets.UTF_8)).getString("bridge_token");
        } catch (Exception e) {
            status.setText("助手配置缺失，请重新构建安装。");
            refresh.setEnabled(false);
            return;
        }
        accept(getIntent());
    }

    @Override public void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        accept(intent);
    }

    private void accept(Intent intent) {
        original = new Intent(intent);
        authRequest = false;
        complete = false;
        try {
            if (!TARGET.equals(intent.getStringExtra("_mmessage_appPackage")) ||
                intent.getIntExtra("_wxapi_command_type", 0) != 1 ||
                !"snsapi_userinfo".equals(intent.getStringExtra("_wxapi_sendauth_req_scope"))) {
                status.setText("请从适配版步道乐跑点击“微信登录”。\n电脑端扫码服务需要保持运行。");
                refresh.setEnabled(false);
                return;
            }
            byte[] caller = getPackageManager().getPackageInfo(TARGET, 64).signatures[0].toByteArray();
            byte[] own = getPackageManager().getPackageInfo(getPackageName(), 64).signatures[0].toByteArray();
            StringBuilder signer = new StringBuilder();
            for (byte b : MessageDigest.getInstance("SHA-256").digest(caller))
                signer.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
            if (!Arrays.equals(caller, own) && !"a6af18d3f047f3a210e9762f41b6f923f445151625fb5533c41748c7b02a6a24".equals(signer.toString()))
                throw new SecurityException("Target signer mismatch");
            byte[] supplied = intent.getByteArrayExtra("_mmessage_checksum");
            byte[] expected = checksum(intent.getStringExtra("_mmessage_content"), TARGET,
                                     intent.getIntExtra("_mmessage_sdkVersion", 0));
            if (supplied == null || !MessageDigest.isEqual(expected, supplied))
                throw new SecurityException("Request checksum mismatch");
            authRequest = true;
            Log.i(TAG, "AUTH_REQUEST_ACCEPTED");
            begin();
        } catch (Exception e) {
            status.setText("授权请求校验失败：" + e.getClass().getSimpleName());
            Log.e(TAG, "REQUEST_REJECTED " + e.getClass().getSimpleName());
            refresh.setEnabled(false);
        }
    }

    private void begin() {
        if (!authRequest || complete) return;
        final int attempt = ++generation;
        HttpURLConnection old = activeConnection;
        if (old != null) old.disconnect();
        status.setText("正在获取微信授权二维码…");
        qr.setImageDrawable(null);
        refresh.setEnabled(false);
        worker.execute(() -> {
            try {
                JSONObject input = new JSONObject().put("appid", APPID).put("scope", "snsapi_userinfo");
                JSONObject session = request("/session", input);
                byte[] png = Base64.decode(session.getString("png"), Base64.DEFAULT);
                runOnUiThread(() -> {
                    if (generation != attempt) return;
                    qr.setImageBitmap(BitmapFactory.decodeByteArray(png, 0, png.length));
                    status.setText("请扫描二维码，并在手机微信确认授权");
                    refresh.setEnabled(true);
                });
                Log.i(TAG, "QR_DISPLAYED");
                while (generation == attempt && !complete) {
                    JSONObject result = request("/poll?id=" + Uri.encode(session.getString("id")), null);
                    if (generation != attempt) return;
                    String state = result.getString("status");
                    if ("confirmed".equals(state)) {
                        String code = result.getString("code");
                        runOnUiThread(() -> { if (generation == attempt) deliver(0, code); });
                        return;
                    }
                    if ("expired".equals(state) || "canceled".equals(state) || "error".equals(state)) {
                        runOnUiThread(() -> status.setText("二维码已失效或授权已取消，请刷新重试。"));
                        return;
                    }
                    runOnUiThread(() -> status.setText("scanned".equals(state) ? "已扫码，等待手机微信确认…" : "等待扫码…"));
                    Thread.sleep(800);
                }
            } catch (Exception e) {
                Log.e(TAG, "BRIDGE_ERROR " + e.getClass().getSimpleName());
                runOnUiThread(() -> {
                    if (generation != attempt) return;
                    status.setText("扫码服务未连接或请求失败，请启动电脑端服务后刷新。\n" + e.getClass().getSimpleName());
                    refresh.setEnabled(true);
                });
            }
        });
    }

    private JSONObject request(String path, JSONObject input) throws Exception {
        HttpURLConnection connection = (HttpURLConnection)new URL("http://127.0.0.1:18371" + path).openConnection();
        activeConnection = connection;
        try {
            connection.setConnectTimeout(8000);
            connection.setReadTimeout(50000);
            connection.setRequestProperty("X-Bridge-Token", bridgeToken);
            if (input != null) {
                connection.setRequestMethod("POST");
                connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/json");
                try (java.io.OutputStream output = connection.getOutputStream()) {
                    output.write(input.toString().getBytes(StandardCharsets.UTF_8));
                }
            }
            if (connection.getResponseCode() != 200)
                throw new java.io.IOException("Bridge HTTP " + connection.getResponseCode());
            try (InputStream stream = connection.getInputStream()) {
                return new JSONObject(new String(read(stream), StandardCharsets.UTF_8));
            }
        } finally {
            if (activeConnection == connection) activeConnection = null;
            connection.disconnect();
        }
    }

    private void deliver(int error, String code) {
        if (!authRequest || complete) return;
        try {
            String state = original.getStringExtra("_wxapi_sendauth_req_state");
            String url = error == 0 ? "weixin://oauth?code=" + Uri.encode(code) + "&state=" + Uri.encode(state == null ? "" : state) : "";
            String content = "weixin://sendresp?appid=" + APPID;
            int sdk = 638058496;
            Intent callback = new Intent();
            callback.setClassName(TARGET, TARGET + ".wxapi.WXEntryActivity");
            callback.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
            callback.putExtra("wx_token_key", "com.tencent.mm.openapi.token");
            callback.putExtra("_mmessage_appPackage", "com.tencent.mm");
            callback.putExtra("_mmessage_content", content);
            callback.putExtra("_mmessage_sdkVersion", sdk);
            callback.putExtra("_mmessage_checksum", checksum(content, "com.tencent.mm", sdk));
            callback.putExtra("_wxapi_command_type", 1);
            callback.putExtra("_wxapi_baseresp_errcode", error);
            callback.putExtra("_wxapi_baseresp_transaction", original.getStringExtra("_wxapi_basereq_transaction"));
            callback.putExtra("_wxapi_sendauth_resp_token", code == null ? "" : code);
            callback.putExtra("_wxapi_sendauth_resp_state", state);
            callback.putExtra("_wxapi_sendauth_resp_url", url);
            callback.putExtra("_wxapi_sendauth_resp_auth_result", error == 0);
            callback.putExtra("_wxapi_sendauth_resp_lang", "zh_CN");
            callback.putExtra("_wxapi_sendauth_resp_country", "CN");
            startActivity(callback);
            complete = true;
            ++generation;
            Log.i(TAG, "CALLBACK_DISPATCHED error=" + error);
            finish();
        } catch (Exception e) {
            status.setText("返回乐跑失败：" + e.getClass().getSimpleName());
            Log.e(TAG, "CALLBACK_FAILED " + e.getClass().getSimpleName());
        }
    }

    private void cancel() {
        ++generation;
        if (authRequest) deliver(-2, null); else finish();
    }

    @Override public void onBackPressed() { cancel(); }
    @Override public void onDestroy() {
        ++generation;
        HttpURLConnection old = activeConnection;
        if (old != null) old.disconnect();
        worker.shutdownNow();
        super.onDestroy();
    }

    public static byte[] checksum(String content, String packageName, int sdk) throws Exception {
        String value = (content == null ? "" : content) + sdk + packageName + "mMcShCsTr";
        byte[] digest = MessageDigest.getInstance("MD5").digest(value.substring(1, 9).getBytes(StandardCharsets.UTF_8));
        StringBuilder hex = new StringBuilder();
        for (byte b : digest) hex.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
        return hex.toString().getBytes(StandardCharsets.US_ASCII);
    }

    private static byte[] read(InputStream stream) throws java.io.IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        for (int n; (n = stream.read(buffer)) != -1;) output.write(buffer, 0, n);
        return output.toByteArray();
    }
}
