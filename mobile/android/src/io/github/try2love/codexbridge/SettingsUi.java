package io.github.try2love.codexbridge;

import android.content.Context;
import android.content.res.Configuration;
import android.animation.ValueAnimator;
import android.graphics.*;
import android.graphics.drawable.*;
import android.view.*;
import android.widget.*;

/** Colors and controls are scoped to the settings window, leaving the live chat intact. */
final class SettingsUi {
 final Context context;
 final int page, surface, pressed, line, muted, text, accent, danger, track;
 SettingsUi(Context context) {
  this.context=context;
  page=color("settings_page");surface=color("settings_surface");pressed=color("settings_pressed");
  line=color("settings_line");muted=color("settings_muted");text=color("settings_text");
  accent=color("settings_accent");danger=color("settings_danger");track=color("settings_track");
 }
 static String theme(Context context) {
  String value=context.getSharedPreferences("bridge",0).getString("settingsTheme","system");
  return "light".equals(value)||"dark".equals(value)?value:"system";
 }
 static Context themed(Context owner) {
  Configuration config=new Configuration();
  String value=theme(owner);
  if(!"system".equals(value))config.uiMode=(owner.getResources().getConfiguration().uiMode&~Configuration.UI_MODE_NIGHT_MASK)|("dark".equals(value)?Configuration.UI_MODE_NIGHT_YES:Configuration.UI_MODE_NIGHT_NO);
  ContextThemeWrapper wrapper=new ContextThemeWrapper(owner,0);
  wrapper.applyOverrideConfiguration(config);
  wrapper.setTheme(wrapper.getResources().getIdentifier("SettingsTheme","style",owner.getPackageName()));
  return wrapper;
 }
 int dp(float value){return Math.round(context.getResources().getDisplayMetrics().density*value);}
 private int color(String name){return context.getColor(context.getResources().getIdentifier(name,"color",context.getPackageName()));}
 String L(String value){return MobileStrings.text(context,value);}
 LinearLayout column(){LinearLayout view=new LinearLayout(context);view.setOrientation(LinearLayout.VERTICAL);return view;}
 TextView text(String value,int size,int color){TextView view=new TextView(context);view.setText(L(value));view.setTextSize(size);view.setTextColor(color);view.setIncludeFontPadding(false);return view;}
 GradientDrawable face(int color,int radius){GradientDrawable shape=new GradientDrawable();shape.setColor(color);shape.setCornerRadius(dp(radius));return shape;}
 void clickable(View view,Runnable action){view.setBackground(new RippleDrawable(android.content.res.ColorStateList.valueOf(pressed),face(Color.TRANSPARENT,0),null));view.setFocusable(true);view.setOnClickListener(v->action.run());}
 LinearLayout section(LinearLayout parent,String name){
  LinearLayout group=column();LinearLayout.LayoutParams layout=new LinearLayout.LayoutParams(-1,-2);layout.topMargin=dp(parent.getChildCount()==0?8:24);parent.addView(group,layout);
  TextView title=text(name,12,muted);title.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));
  LinearLayout.LayoutParams heading=new LinearLayout.LayoutParams(-1,-2);heading.setMargins(dp(16),0,dp(16),dp(8));group.addView(title,heading);
  LinearLayout list=column();list.setBackground(face(surface,12));list.setClipToOutline(true);group.addView(list);return list;
 }
 void append(LinearLayout list,View row){
  if(list.getChildCount()>0){View divider=new View(context){private final Paint paint=new Paint();@Override protected void onDraw(Canvas canvas){paint.setColor(line);canvas.drawRect(0,0,getWidth(),getResources().getDisplayMetrics().density*.5f,paint);}};
   LinearLayout.LayoutParams layout=new LinearLayout.LayoutParams(-1,Math.max(1,dp(.5f)));layout.setMargins(dp(16),0,dp(16),0);list.addView(divider,layout);}
  list.addView(row,new LinearLayout.LayoutParams(-1,-2));
 }
 LinearLayout row(String title,String detail){
  LinearLayout row=new LinearLayout(context);row.setGravity(Gravity.CENTER_VERTICAL);row.setPadding(dp(16),dp(14),dp(16),dp(14));row.setMinimumHeight(dp(detail.isEmpty()?56:80));
  LinearLayout labels=column();labels.addView(text(title,15,text));
  if(!detail.isEmpty()){TextView description=text(detail,12,muted);LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.topMargin=dp(4);labels.addView(description,p);}
  row.addView(labels,new LinearLayout.LayoutParams(0,-2,1));return row;
 }
 TextView value(LinearLayout row,String value){TextView view=text(value,12,muted);view.setGravity(Gravity.END);view.setMaxWidth(Math.round((context.getResources().getDisplayMetrics().widthPixels-dp(72))*.42f));LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-2,-2);p.setMarginStart(dp(12));row.addView(view,p);return view;}
 LinearLayout action(LinearLayout list,String title,String value,Runnable action){LinearLayout row=row(title,"");if(!value.isEmpty())value(row,value);row.addView(icon("chevron",muted),new LinearLayout.LayoutParams(dp(24),dp(24)));clickable(row,action);append(list,row);return row;}
 void hint(LinearLayout row,String description,Runnable action){
  LinearLayout labels=(LinearLayout)row.getChildAt(0);TextView title=(TextView)labels.getChildAt(0);labels.removeView(title);
  LinearLayout heading=new LinearLayout(context);heading.setGravity(Gravity.CENTER_VERTICAL);
  heading.addView(title,new LinearLayout.LayoutParams(-2,-2,1));
  View info=icon("info",muted);info.setContentDescription(L(description));clickable(info,action);
  heading.addView(info,new LinearLayout.LayoutParams(dp(44),dp(44)));labels.addView(heading,0,new LinearLayout.LayoutParams(-2,-2));
  row.setPadding(dp(16),dp(6),dp(16),dp(6));
 }
 ToggleRow toggle(LinearLayout list,String title,boolean checked,Runnable action){
  LinearLayout row=row(title,"");row.setPadding(dp(16),dp(6),dp(16),dp(6));((TextView)((LinearLayout)row.getChildAt(0)).getChildAt(0)).setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));
  AnimatedSwitch toggle=new AnimatedSwitch(checked);
  row.addView(toggle,new LinearLayout.LayoutParams(dp(48),dp(44)));
  row.setAccessibilityDelegate(new View.AccessibilityDelegate(){@Override public void onInitializeAccessibilityNodeInfo(View host,android.view.accessibility.AccessibilityNodeInfo info){super.onInitializeAccessibilityNodeInfo(host,info);info.setClassName(Switch.class.getName());info.setCheckable(true);info.setChecked(toggle.isChecked());}});
  clickable(row,action);append(list,row);ToggleRow result=new ToggleRow(row,toggle,title);result.checked(checked);return result;
 }
 final class ToggleRow {
  final LinearLayout row;private final AnimatedSwitch toggle;private final String title;
  ToggleRow(LinearLayout row,AnimatedSwitch toggle,String title){this.row=row;this.toggle=toggle;this.title=title;}
  void checked(boolean checked){toggle.setChecked(checked);row.setContentDescription(L(title)+", "+L(checked?"已开启":"已关闭"));}
 }
 private final class AnimatedSwitch extends Switch {
  private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
  private final android.animation.ArgbEvaluator colors=new android.animation.ArgbEvaluator();
  private ValueAnimator animator;private float position;private boolean ready;
  AnimatedSwitch(boolean checked){super(context);setShowText(false);setThumbDrawable(null);setTrackDrawable(null);setClickable(false);setFocusable(false);setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);super.setChecked(checked);position=checked?1:0;ready=true;}
  @Override public void setChecked(boolean checked){
   boolean changed=checked!=isChecked();super.setChecked(checked);jumpDrawablesToCurrentState();
   if(!ready)return;
   if(!changed)return;
   if(animator!=null)animator.cancel();float start=position,target=checked?1:0;
   if(!isLaidOut()||!isShown()||!SettingsMotion.enabled()){position=target;invalidate();return;}
   animator=SettingsMotion.animate(SettingsMotion.TOGGLE,f->{position=start+(target-start)*f;invalidate();},()->animator=null);
  }
  @Override protected void onDraw(Canvas canvas){
   float center=getHeight()/2f;paint.setColor((Integer)colors.evaluate(position,track,accent));canvas.drawRoundRect(0,center-dp(14),getWidth(),center+dp(14),dp(14),dp(14),paint);
   paint.setColor(Color.WHITE);canvas.drawCircle(dp(14)+(getWidth()-dp(28))*position,center,dp(10),paint);
  }
  @Override protected void onDetachedFromWindow(){if(animator!=null){animator.cancel();animator=null;}position=isChecked()?1:0;super.onDetachedFromWindow();}
 }
 View icon(String kind,int color){return new View(context){private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);@Override protected void onDraw(Canvas canvas){
  canvas.save();canvas.translate(getWidth()/2f,getHeight()/2f);canvas.scale(dp(1),dp(1));paint.setColor(color);paint.setStyle(Paint.Style.STROKE);paint.setStrokeWidth(1.5f);paint.setStrokeCap(Paint.Cap.ROUND);paint.setStrokeJoin(Paint.Join.ROUND);
  Path path=new Path();
  if("back".equals(kind)){path.moveTo(3,-6);path.lineTo(-3,0);path.lineTo(3,6);path.moveTo(-3,0);path.lineTo(8,0);canvas.drawPath(path,paint);}
  else if("info".equals(kind)){canvas.drawCircle(0,0,7,paint);canvas.drawLine(0,-3,0,1,paint);paint.setStyle(Paint.Style.FILL);canvas.drawCircle(0,4,0.8f,paint);}
  else {path.moveTo(-2,-4);path.lineTo(2,0);path.lineTo(-2,4);canvas.drawPath(path,paint);}canvas.restore();
 }};}
}
