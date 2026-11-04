package org.delector.app;

/**
 * WebUrlPolicy 的零依赖单测（JUnit-free）。
 *
 * 为什么不用 JUnit / Robolectric：本仓没有 androidx.test 与 Robolectric 依赖，
 * CI 也不跑 Android unit test 任务；而 WebUrlPolicy 刻意零 Android 依赖，
 * 所以 javac 直接编译 + java 直接执行就够了。编译与退出码断言由
 * tests/test_android_webview_policy.py 负责，输出格式固定为
 * "PASS/FAIL <name> url=<url> -> <bool>" 与末行 "checks=N failed=M"。
 *
 * 输出刻意保持 ASCII：Windows 控制台默认字符集不是 UTF-8，中文会被拆成乱码。
 */
public final class WebUrlPolicyTest {
    private static int total = 0;
    private static int failed = 0;

    private WebUrlPolicyTest() {
    }

    public static void main(String[] args) {
        // ---- 站内：必须留在 WebView ----
        expect("null", false, null);
        expect("empty", false, "");
        expect("blank", false, "   ");
        expect("loopback-ipv4", false, "http://127.0.0.1:8000/");
        expect("loopback-localhost", false, "http://localhost:8000/reader");
        expect("loopback-ipv6", false, "http://[::1]:8000/");
        expect("loopback-zero", false, "http://0.0.0.0:8000/");
        expect("relative-abs-path", false, "/static/js/app.js");
        expect("relative-file", false, "reader.html");
        expect("relative-hash", false, "#settings");
        expect("protocol-relative", false, "//127.0.0.1:8000/static/index.html");
        expect("file-scheme", false, "file:///android_asset/index.html");

        // ---- 站外：交给系统 ----
        expect("external-github", true, "https://github.com/ROM4n2/DeLector/releases");
        expect("external-https", true, "https://example.com/x");
        expect("external-lan-desktop", true, "http://192.168.1.10:8000/");
        expect("external-mailto", true, "mailto:support@example.com");

        // ---- 不许外跳 ----
        expect("blocked-javascript", false, "javascript:alert(1)");
        expect("blocked-data", false, "data:text/html,<b>x</b>");
        expect("blocked-blob", false, "blob:https://example.com/abc");
        expect("blocked-about", false, "about:blank");

        // ---- 非法 URL：解析失败即不外跳 ----
        expect("invalid-bare-scheme", false, "http://");
        expect("invalid-space", false, "http://exa mple.com");
        expect("invalid-scheme-char", false, "ht!tp://example.com");

        // ---- scheme 大小写 ----
        expect("uppercase-scheme-loopback", false, "HTTP://127.0.0.1:8000/");
        expect("uppercase-scheme-external", true, "HTTPS://github.com/ROM4n2/DeLector/releases");

        System.out.println("checks=" + total + " failed=" + failed);
        if (failed > 0) {
            System.exit(1);
        }
    }

    private static void expect(String name, boolean expected, String url) {
        total++;
        boolean actual;
        try {
            actual = WebUrlPolicy.shouldOpenExternally(url);
        } catch (Throwable t) {
            System.out.println("FAIL " + name + " url=" + url + " threw=" + t.getClass().getSimpleName());
            failed++;
            return;
        }
        if (actual != expected) {
            System.out.println("FAIL " + name + " url=" + url + " expected=" + expected + " actual=" + actual);
            failed++;
            return;
        }
        System.out.println("PASS " + name + " url=" + url + " -> " + actual);
    }
}
