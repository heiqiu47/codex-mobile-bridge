package io.github.try2love.codexbridge;

import android.content.Context;
import android.content.res.TypedArray;
import android.graphics.drawable.GradientDrawable;
import android.content.res.ColorStateList;
import android.graphics.Rect;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.RippleDrawable;
import android.view.Gravity;
import android.view.View;
import android.view.accessibility.AccessibilityNodeInfo;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.PopupWindow;
import android.widget.ScrollView;
import android.widget.TextView;
import org.json.JSONObject;

final class GatewayMenu extends PopupWindow {
 private final Context context;
 private final ScrollView scroll;
 private final LinearLayout content;
 private int surface,text,muted,line,pressed;

 GatewayMenu(Context context) {
  super(context);
  this.context=context;
  TypedArray colors=context.obtainStyledAttributes(new int[]{android.R.attr.colorBackground,android.R.attr.textColorPrimary,android.R.attr.textColorSecondary,android.R.attr.colorControlHighlight});
  try{
   surface=colors.getColor(0,0xffffffff);text=colors.getColor(1,0xff24262b);muted=colors.getColor(2,0xff777d88);pressed=colors.getColor(3,0x18000000);
  }finally{colors.recycle();}
  line=(text&0x00ffffff)|0x20000000;
  content=column();
  content.setPadding(dp(6),dp(6),dp(6),dp(6));
  scroll=new ScrollView(context);
  scroll.setFillViewport(false);
  scroll.setBackground(face(surface,18));
  scroll.setClipToOutline(true);
  scroll.addView(content);
  setContentView(scroll);
  setBackgroundDrawable(face(surface,18));
  setElevation(dp(12));
  setFocusable(true);
  setOutsideTouchable(true);
  setInputMethodMode(INPUT_METHOD_NOT_NEEDED);
 }

 private int dp(float value){return Math.round(context.getResources().getDisplayMetrics().density*value);}
 private LinearLayout column(){LinearLayout view=new LinearLayout(context);view.setOrientation(LinearLayout.VERTICAL);return view;}
 private GradientDrawable face(int color,int radius){GradientDrawable shape=new GradientDrawable();shape.setColor(color);shape.setCornerRadius(dp(radius));return shape;}
 private TextView label(String title){TextView view=new TextView(context);view.setText(MobileStrings.text(context,title));view.setTextSize(15);view.setTextColor(text);view.setIncludeFontPadding(false);return view;}

 LinearLayout add(String title,String icon,Runnable action) {
  LinearLayout row=new LinearLayout(context);
  row.setGravity(Gravity.CENTER_VERTICAL);
  row.setMinimumHeight(dp(48));
  row.setPadding(dp(14),dp(12),dp(14),dp(12));
  ImageView image=new ImageView(context);
  image.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
  row.addView(image,new LinearLayout.LayoutParams(dp(20),dp(20)));
  TextView label=label(title);
  LinearLayout.LayoutParams labels=new LinearLayout.LayoutParams(0,-2,1);
  labels.setMarginStart(dp(14));
  row.addView(label,labels);
  update(row,title,icon);
  row.setBackground(rowBackground());
  row.setFocusable(true);
  row.setAccessibilityDelegate(new View.AccessibilityDelegate(){
   @Override public void onInitializeAccessibilityNodeInfo(View host,AccessibilityNodeInfo info){
    super.onInitializeAccessibilityNodeInfo(host,info);info.setClassName(Button.class.getName());
   }
  });
  row.setOnClickListener(v->{dismiss();action.run();});
  content.addView(row,new LinearLayout.LayoutParams(-1,-2));
  return row;
 }

 void update(LinearLayout row,String title,String icon) {
  ((TextView)row.getChildAt(1)).setText(MobileStrings.text(context,title));
  Drawable drawable=context.getDrawable(context.getResources().getIdentifier(icon,"drawable",context.getPackageName())).mutate();
  drawable.setTint(muted);
  ((ImageView)row.getChildAt(0)).setImageDrawable(drawable);
 }

 void separator() {
  View line=new View(context);line.setBackgroundColor(this.line);
  LinearLayout.LayoutParams layout=new LinearLayout.LayoutParams(-1,Math.max(1,dp(.5f)));
  layout.setMargins(dp(14),dp(6),dp(14),dp(6));content.addView(line,layout);
 }

 private Drawable rowBackground() {
  return new RippleDrawable(ColorStateList.valueOf(pressed),new ColorDrawable(0),face(0xffffffff,10));
 }

 void palette(String value) {
  try{
   JSONObject colors=new JSONObject(value);
   String[] names={"surface","text","muted","line","pressed"};int[] parsed=new int[names.length];
   for(int i=0;i<names.length;i++){
    String color=colors.getString(names[i]);if(!color.matches("#[0-9a-fA-F]{6}"))return;
    parsed[i]=android.graphics.Color.parseColor(color);
   }
   surface=parsed[0];text=parsed[1];muted=parsed[2];line=parsed[3];pressed=parsed[4];
  }catch(org.json.JSONException e){return;}
  ((GradientDrawable)scroll.getBackground()).setColor(surface);
  ((GradientDrawable)getBackground()).setColor(surface);
  for(int i=0;i<content.getChildCount();i++){
   View child=content.getChildAt(i);
   if(child instanceof LinearLayout){
    LinearLayout row=(LinearLayout)child;
    ((TextView)row.getChildAt(1)).setTextColor(text);
    ((ImageView)row.getChildAt(0)).setImageTintList(ColorStateList.valueOf(muted));
    row.setBackground(rowBackground());
   }else child.setBackgroundColor(line);
  }
 }

 private int[] size(View anchor) {
  Rect frame=new Rect();anchor.getWindowVisibleDisplayFrame(frame);
  int desired=0;
  for(int i=0;i<content.getChildCount();i++){
   View child=content.getChildAt(i);
   if(!(child instanceof LinearLayout)||child.getVisibility()==View.GONE)continue;
   LinearLayout row=(LinearLayout)child;TextView label=(TextView)row.getChildAt(1);
   LinearLayout.LayoutParams layout=(LinearLayout.LayoutParams)label.getLayoutParams();
   int textWidth=(int)Math.ceil(android.text.Layout.getDesiredWidth(label.getText(),label.getPaint()));
   desired=Math.max(desired,row.getPaddingLeft()+row.getPaddingRight()+row.getChildAt(0).getLayoutParams().width+layout.getMarginStart()+layout.getMarginEnd()+label.getTotalPaddingLeft()+label.getTotalPaddingRight()+textWidth);
  }
  int width=Math.min(desired+content.getPaddingLeft()+content.getPaddingRight(),Math.min(dp(300),frame.width()-dp(24)));
  int[] location=new int[2];anchor.getLocationOnScreen(location);
  int available=Math.max(location[1]-frame.top,frame.bottom-location[1]-anchor.getHeight())-dp(12);
  if(width<=0||available<=0)return null;
  content.measure(View.MeasureSpec.makeMeasureSpec(width,View.MeasureSpec.EXACTLY),View.MeasureSpec.makeMeasureSpec(0,View.MeasureSpec.UNSPECIFIED));
  return new int[]{width,Math.min(content.getMeasuredHeight(),available)};
 }

 void show(View anchor) {
  int[] size=size(anchor);if(size==null)return;
  setWidth(size[0]);setHeight(size[1]);
  showAsDropDown(anchor,0,dp(4),Gravity.END);
 }

 void resize(View anchor) {
  if(!isShowing()||!anchor.isAttachedToWindow())return;
  int[] size=size(anchor);if(size!=null)update(anchor,0,dp(4),size[0],size[1]);
 }
}
