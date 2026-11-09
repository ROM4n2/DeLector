package org.delector.app;

/**
 * StartupReadinessPolicy 的零依赖单测（JUnit-free）。
 *
 * 与 WebUrlPolicyTest 同款：本仓没有 androidx.test / Robolectric，CI 也不跑 Android
 * unit test 任务；策略类刻意零 Android 依赖，javac 直接编译 + java 直接执行即可。
 * 编译与退出码断言由 tests/test_android_startup_readiness_policy.py 负责，
 * 输出格式固定为 "PASS/FAIL <name>" 与末行 "checks=N failed=0"。
 *
 * 输出保持 ASCII：Windows 控制台默认字符集不是 UTF-8。
 */
public final class StartupReadinessPolicyTest {
    private static int total = 0;
    private static int failed = 0;

    private StartupReadinessPolicyTest() {
    }

    public static void main(String[] args) {
        // ---- 快轮询窗口：前 50 次 120ms ----
        expectInt("interval-0", 120, StartupReadinessPolicy.pollIntervalMs(0));
        expectInt("interval-1", 120, StartupReadinessPolicy.pollIntervalMs(1));
        expectInt("interval-49", 120, StartupReadinessPolicy.pollIntervalMs(49));
        // ---- 慢轮询窗口：第 50 次起 600ms ----
        expectInt("interval-50", 600, StartupReadinessPolicy.pollIntervalMs(50));
        expectInt("interval-99", 600, StartupReadinessPolicy.pollIntervalMs(99));
        // ---- 总次数：50 + 50 = 100 ----
        expectInt("max-attempts", 100, StartupReadinessPolicy.maxAttempts());
        // ---- 总预算与改造前 60×600=36000ms 对齐 ----
        expectInt("total-budget-ms", 36000, totalBudgetMs());
        // ---- 就绪判定口径与改造前一致 ----
        expectBool("status-199-not-ready", false, StartupReadinessPolicy.isReadyStatus(199));
        expectBool("status-200-ready", true, StartupReadinessPolicy.isReadyStatus(200));
        expectBool("status-302-ready", true, StartupReadinessPolicy.isReadyStatus(302));
        expectBool("status-399-ready", true, StartupReadinessPolicy.isReadyStatus(399));
        expectBool("status-400-not-ready", false, StartupReadinessPolicy.isReadyStatus(400));
        expectBool("status-500-not-ready", false, StartupReadinessPolicy.isReadyStatus(500));

        System.out.println("checks=" + total + " failed=" + failed);
        if (failed > 0) {
            System.exit(1);
        }
    }

    private static int totalBudgetMs() {
        int sum = 0;
        for (int i = 0; i < StartupReadinessPolicy.maxAttempts(); i++) {
            sum += StartupReadinessPolicy.pollIntervalMs(i);
        }
        return sum;
    }

    private static void expectInt(String name, int expected, int actual) {
        total++;
        if (expected == actual) {
            System.out.println("PASS " + name + " expected=" + expected + " actual=" + actual);
        } else {
            failed++;
            System.out.println("FAIL " + name + " expected=" + expected + " actual=" + actual);
        }
    }

    private static void expectBool(String name, boolean expected, boolean actual) {
        total++;
        if (expected == actual) {
            System.out.println("PASS " + name + " expected=" + expected + " actual=" + actual);
        } else {
            failed++;
            System.out.println("FAIL " + name + " expected=" + expected + " actual=" + actual);
        }
    }
}
