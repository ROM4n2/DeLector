package org.delector.app;

import android.annotation.SuppressLint;
import android.os.Bundle;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import androidx.appcompat.app.AppCompatActivity;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

public class MainActivity extends AppCompatActivity {
    private WebView webView;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // 1. Start embedded Chaquopy Python runtime
        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(this));
        }

        // 2. Launch FastAPI service on localhost in background thread
        new Thread(() -> {
            try {
                Python py = Python.getInstance();
                py.getModule("start").callAttr("main");
            } catch (Exception e) {
                e.printStackTrace();
            }
        }).start();

        // 3. Setup immersive WebView
        webView = new WebView(this);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(true);
        settings.setMediaPlaybackRequiresUserGesture(false);

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
                // Retry while background python server boots up
                view.postDelayed(() -> view.loadUrl("http://127.0.0.1:8000"), 1200);
            }
        });

        setContentView(webView);
        webView.loadUrl("http://127.0.0.1:8000");
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
