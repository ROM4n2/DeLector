# DeLector Android 独立离线单机版 (路线 B - Standalone Offline APK) 构建指南

本指南记录如何将 **DeLector v3.5.0** 打包为包含**嵌入式 Python 运行时 + spaCy 德语模型 + 原生 WebView 交互**的 100% 离线单机 Android APK。

---

## 📱 架构设计 (Architecture)

```
┌─────────────────────────────────────────────────────────────┐
│                    DeLector Android APK                     │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │           Android 原生容器 (Native Java / Kotlin)       │  │
│  │  - MainActivity: 全屏沉浸式 WebView                     │  │
│  │  - Android Service: 后台 Python FastAPI 服务守护进程   │  │
│  └───────────────────────────┬───────────────────────────┘  │
│                              │ 本地回环 127.0.0.1:8000       │
│  ┌───────────────────────────▼───────────────────────────┐  │
│  │         嵌入式 Python 运行时 (Chaquopy 引擎)            │  │
│  │  - Python 3.10+ / 3.11                                │  │
│  │  - FastAPI + Uvicorn + SQLite (delector.db)           │  │
│  │  - spaCy + de_core_news_sm 离线模型                   │  │
│  │  - 0ms 歌德核心词库 + 556+ 三态表 + 拓扑句法树 AST     │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 🛠️ 项目工程配置 (Android Studio / Gradle + Chaquopy)

### 1. 根目录 `build.gradle` (Project)

```groovy
buildscript {
    repositories {
        google()
        mavenCentral()
        maven { url "https://chaquo.com/maven" }
    }
    dependencies {
        classpath 'com.android.tools.build:gradle:8.2.0'
        classpath 'com.chaquo.python:gradle:15.0.1'
    }
}
```

### 2. 应用层 `app/build.gradle` (Module)

```groovy
plugins {
    id 'com.android.application'
    id 'com.chaquo.python'
}

android {
    namespace 'org.delector.app'
    compileSdk 34

    defaultConfig {
        applicationId "org.delector.app"
        minSdk 24
        targetSdk 34
        versionCode 350
        versionName "3.5.0"

        ndk {
            abiFilters "arm64-v8a", "armeabi-v7a", "x86_64"
        }

        python {
            version "3.10"
            pip {
                install "fastapi"
                install "uvicorn"
                install "httpx"
                install "genanki"
                install "spacy"
                // 安装德语离线小型模型 wheel
                install "https://github.com/explosion/spacy-models/releases/download/de_core_news_sm-3.7.0/de_core_news_sm-3.7.0-py3-none-any.whl"
            }
        }
    }
}
```

### 3. 主活动 `MainActivity.java` (启动嵌入式服务并加载页面)

```java
package org.delector.app;

import android.os.Bundle;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import androidx.appcompat.app.AppCompatActivity;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

public class MainActivity extends AppCompatActivity {
    private WebView webView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // 1. 初始化嵌入式 Python
        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(this));
        }

        // 2. 在后台子线程中启动 FastAPI 后端服务
        new Thread(() -> {
            Python py = Python.getInstance();
            py.getModule("start").callAttr("main");
        }).start();

        // 3. 配置全屏 WebView
        webView = new WebView(this);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(true);

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
                // 等待后端启动完成时重试
                view.postDelayed(() -> view.loadUrl("http://127.0.0.1:8000"), 1000);
            }
        });

        setContentView(webView);
        webView.loadUrl("http://127.0.0.1:8000");
    }

    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
```

---

## 📦 APK 一键构建输出

在 Android Studio 中点击 **Build > Build Bundle(s) / APK(s) > Build APK(s)** 或运行：

```bash
./gradlew assembleRelease
```

输出包路径：`app/build/outputs/apk/release/DeLector-v3.5.0-release.apk`（约 85MB-120MB，包含全套 Python 运行时与离线模型）。
