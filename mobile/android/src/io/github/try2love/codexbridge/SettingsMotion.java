package io.github.try2love.codexbridge;

import android.animation.*;
import android.app.Dialog;
import android.content.Context;
import android.graphics.*;
import android.view.*;
import android.view.animation.PathInterpolator;
import java.util.function.Consumer;

final class SettingsMotion {
 static final int ENTER=220, EXIT=180, TOGGLE=160, LAYOUT=180, SHEET=200, THEME=180;
 static final PathInterpolator EASE=new PathInterpolator(.2f,0,0,1);
 static boolean enabled(){return ValueAnimator.areAnimatorsEnabled();}
 static ValueAnimator animate(int duration,Consumer<Float> frame,Runnable complete){
  if(!enabled()){frame.accept(1f);if(complete!=null)complete.run();return null;}
  ValueAnimator animator=ValueAnimator.ofFloat(0,1);animator.setDuration(duration);animator.setInterpolator(EASE);
  animator.addUpdateListener(value->frame.accept((Float)value.getAnimatedValue()));
  animator.addListener(new AnimatorListenerAdapter(){private boolean cancelled;
   @Override public void onAnimationCancel(Animator animation){cancelled=true;}
   @Override public void onAnimationEnd(Animator animation){if(!cancelled&&complete!=null)complete.run();}
  });animator.start();return animator;
 }
 static Bitmap capture(View view){
  if(!enabled()||view.getWidth()==0||view.getHeight()==0)return null;
  // Bound the temporary native-page snapshot independently of screen resolution.
  float scale=Math.min(1f,(float)Math.sqrt(1200000d/((double)view.getWidth()*view.getHeight())));
  Bitmap bitmap=null;
  try{bitmap=Bitmap.createBitmap(Math.max(1,Math.round(view.getWidth()*scale)),Math.max(1,Math.round(view.getHeight()*scale)),Bitmap.Config.ARGB_8888);Canvas canvas=new Canvas(bitmap);canvas.scale(scale,scale);view.draw(canvas);return bitmap;}
  catch(OutOfMemoryError|RuntimeException unavailable){if(bitmap!=null)bitmap.recycle();return null;}
 }
 static final class Sheet extends Dialog {
  private final View content;
  private final int distance;
  private ValueAnimator animator;
  private boolean closing;
  Sheet(Context context,View content,int distance){
   super(context);this.content=content;this.distance=distance;requestWindowFeature(Window.FEATURE_NO_TITLE);setContentView(content);setCanceledOnTouchOutside(true);
   Window window=getWindow();window.setBackgroundDrawableResource(android.R.color.transparent);window.addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND);window.setDimAmount(0);window.setGravity(Gravity.BOTTOM);window.setWindowAnimations(0);
  }
  @Override public void show(){
   closing=false;content.setAlpha(enabled()?0:1);content.setTranslationY(enabled()?distance:0);super.show();getWindow().setLayout(-1,-2);
   animator=animate(SHEET,f->{content.setAlpha(f);content.setTranslationY(distance*(1-f));getWindow().setDimAmount(.32f*f);},()->animator=null);
  }
  void close(Runnable complete){
   if(closing||!isShowing())return;closing=true;if(animator!=null)animator.cancel();
   float alpha=content.getAlpha(),position=content.getTranslationY(),dim=getWindow().getAttributes().dimAmount;
   animator=animate(EXIT,f->{content.setAlpha(alpha*(1-f));content.setTranslationY(position+(distance-position)*f);getWindow().setDimAmount(dim*(1-f));},()->{animator=null;dismiss();if(complete!=null)complete.run();});
  }
  @Override public void cancel(){close(null);}
  @Override public void onBackPressed(){close(null);}
  @Override public boolean dispatchTouchEvent(MotionEvent event){return closing||super.dispatchTouchEvent(event);}
  @Override public void dismiss(){if(animator!=null){animator.cancel();animator=null;}super.dismiss();}
 }
}
