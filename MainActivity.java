package com.manmulsang.app;

import android.os.Bundle;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import androidx.appcompat.app.AppCompatActivity;

public class MainActivity extends AppCompatActivity {
    private WebView webView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        
        webView = new WebView(this);
        setContentView(webView);

        WebSettings settings = webView.getSettings();
        // 온라인 앱에 필요한 필수 설정
        settings.setJavaScriptEnabled(true);        // JS 실행 허용 (API 호출용)
        settings.setDomStorageEnabled(true);        // LocalStorage 허용 (로그인/토큰 저장용)
        settings.setDatabaseEnabled(true);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);

        webView.setWebViewClient(new WebViewClient()); // 외부 브라우저 열림 방지

        // 온라인 서버 주소 호출
        webView.loadUrl("http://manmulsang-rpg.kro.kr/");
    }

    // 뒤로가기 버튼 누를 때 앱 종료 대신 이전 화면 이동
    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}