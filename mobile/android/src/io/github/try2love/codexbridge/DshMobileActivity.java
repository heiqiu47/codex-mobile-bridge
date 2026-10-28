package io.github.try2love.codexbridge;

import android.app.*;
import android.content.*;
import android.net.Uri;
import android.os.*;
import android.view.*;
import android.webkit.*;
import android.widget.*;

/** Separate process and WebView store: third-party pages never receive Bridge native APIs. */
public final class DshMobileActivity extends Activity {
 private static boolean initialized;
 private WebView web;private String entry;private ValueCallback<Uri[]> files;private String filePage;
 @Override public void onCreate(Bundle state){
  super.onCreate(state);
  if(Build.VERSION.SDK_INT<28){finish();return;}
  if(!initialized){WebView.setDataDirectorySuffix("dsh-mobile");initialized=true;}
  try{entry=DshMobileURL.connection(getIntent().getStringExtra("url"));}catch(Exception invalid){finish();return;}
  android.content.res.Configuration configuration=new android.content.res.Configuration(getResources().getConfiguration());String theme=getIntent().getStringExtra("theme");
  if("dark".equals(theme)||"light".equals(theme))configuration.uiMode=(configuration.uiMode&~android.content.res.Configuration.UI_MODE_NIGHT_MASK)|("dark".equals(theme)?android.content.res.Configuration.UI_MODE_NIGHT_YES:android.content.res.Configuration.UI_MODE_NIGHT_NO);
  ContextThemeWrapper themed=new ContextThemeWrapper(this,0);themed.applyOverrideConfiguration(configuration);themed.setTheme(getResources().getIdentifier("SettingsTheme","style",getPackageName()));
  SettingsUi ui=new SettingsUi(themed);LinearLayout root=ui.column();root.setBackgroundColor(ui.page);
  LinearLayout bar=new LinearLayout(ui.context);bar.setGravity(Gravity.CENTER_VERTICAL);
  Button close=new Button(ui.context);close.setText(MobileStrings.text(this,"我的电脑"));close.setOnClickListener(v->finish());bar.addView(close);
  TextView title=ui.text("DSH Mobile",16,ui.text);bar.addView(title,new LinearLayout.LayoutParams(0,-2,1));
  Button reload=new Button(ui.context);reload.setText(MobileStrings.text(this,"刷新"));reload.setOnClickListener(v->web.reload());bar.addView(reload);root.addView(bar);
  web=new WebView(ui.context);web.setBackgroundColor(ui.page);root.addView(web,new LinearLayout.LayoutParams(-1,0,1));setContentView(root);
  new SystemBars(this,root,()->{}).update(ui.page,ui.page);
  WebSettings settings=web.getSettings();settings.setJavaScriptEnabled(true);settings.setDomStorageEnabled(true);settings.setAllowFileAccess(false);settings.setAllowContentAccess(false);settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);CookieManager.getInstance().setAcceptThirdPartyCookies(web,false);
  web.setWebViewClient(new WebViewClient(){
   @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request){
    String target=request.getUrl().toString();if(DshMobileURL.sameOrigin(target,entry))return false;
    if(request.isForMainFrame()&&request.hasGesture()&&("https".equals(request.getUrl().getScheme())||"http".equals(request.getUrl().getScheme())))new AlertDialog.Builder(ui.context).setMessage(MobileStrings.text(DshMobileActivity.this,"在浏览器打开外部链接？\n")+request.getUrl().getHost()).setPositiveButton(MobileStrings.text(DshMobileActivity.this,"打开"),(d,w)->{try{startActivity(new Intent(Intent.ACTION_VIEW,request.getUrl()));}catch(ActivityNotFoundException ignored){}}).setNegativeButton(MobileStrings.text(DshMobileActivity.this,"取消"),null).show();return true;
   }
   @Override public void onPageStarted(WebView view,String url,android.graphics.Bitmap icon){if(files!=null){files.onReceiveValue(null);files=null;}}
   @Override public void onPageFinished(WebView view,String url){CookieManager.getInstance().flush();}
   @Override public void onReceivedError(WebView view,WebResourceRequest request,WebResourceError error){if(request.isForMainFrame())Toast.makeText(DshMobileActivity.this,MobileStrings.text(DshMobileActivity.this,"连接失败，请刷新重试"),Toast.LENGTH_LONG).show();}
  });
  web.setWebChromeClient(new WebChromeClient(){
   @Override public boolean onShowFileChooser(WebView view,ValueCallback<Uri[]> callback,FileChooserParams params){
    if(!DshMobileURL.sameOrigin(view.getUrl(),entry)||!hasWindowFocus())return false;
    if(files!=null)files.onReceiveValue(null);files=callback;filePage=view.getUrl();
    Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*").putExtra(Intent.EXTRA_ALLOW_MULTIPLE,params.getMode()==FileChooserParams.MODE_OPEN_MULTIPLE);
    try{startActivityForResult(intent,1);}catch(ActivityNotFoundException unavailable){files.onReceiveValue(null);files=null;}return true;
   }
  });
  if(Build.VERSION.SDK_INT>=33)getOnBackInvokedDispatcher().registerOnBackInvokedCallback(android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT,this::back);
  web.loadUrl(entry);
 }
 private void back(){if(web!=null&&web.canGoBack())web.goBack();else finish();}
 @Override public void onBackPressed(){back();}
 @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);if(request==1&&files!=null){ValueCallback<Uri[]> callback=files;files=null;Uri[] selected=result==RESULT_OK&&web!=null&&filePage.equals(web.getUrl())?WebChromeClient.FileChooserParams.parseResult(result,data):null;callback.onReceiveValue(selected);}}
 @Override protected void onDestroy(){if(files!=null)files.onReceiveValue(null);if(web!=null){((android.view.ViewGroup)web.getParent()).removeView(web);web.destroy();web=null;}super.onDestroy();}
}
