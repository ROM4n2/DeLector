package org.delector.app;

/**
 * 启动就绪轮询策略（纯函数、零 Android 依赖）。
 *
 * 为什么单独抽类：轮询节奏以前是 {@code pollServerReadiness()} 里的字面量
 * （60 次 × 600 ms），既没法单测，也没法在评审里看见「到底等了多久」。抽成纯函数后
 * 由 javac 直编直跑断言，不引入 JUnit / Robolectric / Android SDK
 * （与本仓既有 {@link WebUrlPolicy} 同款形态）。
 *
 * 节奏：实测服务端约 2.3 s 就绪，600 ms 固定间隔意味着平均多等约 300 ms。
 * 前 50 次用 120 ms 快轮询（覆盖 6 s，足够覆盖正常启动与中低端机），之后退回
 * 600 ms 慢轮询；50×120 + 50×600 = 36 s，与改造前 60×600 的总预算一致，
 * 超时语义不变。
 */
public final class StartupReadinessPolicy {
    static final int FAST_INTERVAL_MS = 120;
    static final int SLOW_INTERVAL_MS = 600;
    static final int FAST_ATTEMPTS = 50;
    static final int SLOW_ATTEMPTS = 50;

    private StartupReadinessPolicy() {
    }

    /** 第 attempt 次失败后应等待的毫秒数（attempt 从 0 起）。 */
    public static int pollIntervalMs(int attempt) {
        return attempt < FAST_ATTEMPTS ? FAST_INTERVAL_MS : SLOW_INTERVAL_MS;
    }

    /** 轮询总次数上限：与改造前 36 s 的总等待预算对齐。 */
    public static int maxAttempts() {
        return FAST_ATTEMPTS + SLOW_ATTEMPTS;
    }

    /** 就绪判定：2xx/3xx 视为服务已可服务页面（与改造前口径一致）。 */
    public static boolean isReadyStatus(int httpCode) {
        return httpCode >= 200 && httpCode < 400;
    }
}
