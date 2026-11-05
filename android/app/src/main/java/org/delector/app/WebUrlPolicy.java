package org.delector.app;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;

/**
 * WebView 导航的单一判定出口：这个 URL 是否必须交给 WebView 之外的 App。
 *
 * 刻意零 Android 依赖（只用 java.net.URI）：本机没有 Android SDK，只有这样才能用
 * javac 直接编译并执行行为单测（android/app/src/test/java/.../WebUrlPolicyTest.java）。
 *
 * 判定口径（与 tests/test_android_webview_policy.py 的用例一一对应）：
 * <ul>
 *   <li>回环地址（127.0.0.1 / localhost / ::1 / 0.0.0.0）→ false。那是 App 自己拉起的
 *       本地服务，留在 WebView 里；外跳会把工作台换成浏览器标签页。</li>
 *   <li>相对路径、锚点、null、空串 → false。源码里的 href 大多是站内相对路径。</li>
 *   <li>非法 URL（URI 解析失败）→ false。解析不出来就绝不外跳，宁可让 WebView 自己失败。</li>
 *   <li>file:// → false。APK 解包出来的静态资产。</li>
 *   <li>http/https 且非回环 → true。更新 chip 指向的 GitHub Releases 页属于这一类；
 *       局域网桌面地址（http://192.168.x.x:8000）也归这里，交给系统浏览器更合适。</li>
 *   <li>mailto: → true。只有系统邮件 App 能处理，WebView 自己处理不了。</li>
 *   <li>javascript: / data: / blob: / about: → false。这些是 WebView 内部语义，
 *       外跳没有任何 App 能解释；其中 javascript: 更不应被当成可外发的链接。</li>
 *   <li>其它未知 scheme → false。不把无法预测的 scheme 塞给 Intent（大概率无 handler），
 *       交给 WebView 的默认处理，避免出现"点了完全没反应"的外部跳转。</li>
 * </ul>
 */
public final class WebUrlPolicy {
    private WebUrlPolicy() {
    }

    public static boolean shouldOpenExternally(String url) {
        if (url == null) {
            return false;
        }
        String trimmed = url.trim();
        if (trimmed.isEmpty()) {
            return false;
        }

        URI uri;
        try {
            uri = new URI(trimmed);
        } catch (URISyntaxException e) {
            return false;
        }

        String scheme = uri.getScheme();
        if (scheme == null) {
            return false;   // 相对路径 / 锚点 / 协议相对引用
        }
        scheme = scheme.toLowerCase(Locale.ROOT);

        if (scheme.equals("file")) {
            return false;
        }
        if (scheme.equals("http") || scheme.equals("https")) {
            String host = uri.getHost();
            if (host == null) {
                return false;   // 形如 http:foo 的不完整引用，不当外站
            }
            return !isLoopbackHost(host);
        }
        if (scheme.equals("mailto")) {
            return true;
        }
        return false;
    }

    private static boolean isLoopbackHost(String host) {
        String h = host.toLowerCase(Locale.ROOT);
        if (h.startsWith("[") && h.endsWith("]")) {
            h = h.substring(1, h.length() - 1);   // IPv6 字面量
        }
        return h.equals("127.0.0.1")
                || h.equals("localhost")
                || h.equals("::1")
                || h.equals("0.0.0.0");
    }
}
