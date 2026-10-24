#!/usr/bin/env python3
"""Compile native Android entry method against isolated platform storage/queue stubs."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.tmp/mobile-connection-entry'
WORK.mkdir(parents=True, exist_ok=True)
parser = argparse.ArgumentParser()
parser.add_argument('--baseline', action='store_true')
args = parser.parse_args()
relative = 'mobile/android/src/io/github/try2love/codexbridge/MainActivity.java'
source = subprocess.check_output(['git', 'show', 'HEAD:' + relative], cwd=ROOT, text=True) if args.baseline else (ROOT / relative).read_text()
start = source.index(' void loadWithRecovery(')
opening = source.index('{', start)
end, depth = opening + 1, 1
while depth:
    if source[end] == '{': depth += 1
    elif source[end] == '}': depth -= 1
    end += 1
entry = source[start:end]
harness = r'''
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Consumer;
public class EntryTests {
 final ExecutorService worker=Executors.newSingleThreadExecutor();Future<?> connectionTask;
 final BlockingQueue<Runnable> ui=new LinkedBlockingQueue<>();int generation=1;
 String origin="https://one.example";WebView web=new WebView();Prefs prefs=new Prefs();
 Set<String> saved(){return new HashSet<>(Arrays.asList("https://one.example","https://two.example"));}
 void runOnUiThread(Runnable action){ui.add(action);}
 void drain()throws Exception{worker.submit(()->{}).get(2,TimeUnit.SECONDS);Runnable action;while((action=ui.poll())!=null)action.run();}
 void close(){worker.shutdownNow();}
''' + entry + r'''
 static void check(boolean valid,String message){if(!valid)throw new AssertionError(message);}
 static void reset(){CookieManager.instance.value="cookie=current";CookieManager.instance.sets=0;DeviceBinding.value=new DeviceBinding.Credential("cookie","current");DeviceBinding.gate=null;DeviceBinding.entered=null;DeviceBinding.checks=0;}
 public static void main(String[] args)throws Exception {
  boolean baseline=args.length>0;reset();EntryTests f=new EntryTests();CountDownLatch occupied=new CountDownLatch(1),release=new CountDownLatch(1);
  final CountDownLatch initiallyOccupied=occupied,initialRelease=release;
  try{
   f.worker.execute(()->{initiallyOccupied.countDown();try{initialRelease.await();}catch(InterruptedException ignored){}});check(occupied.await(1,TimeUnit.SECONDS),"fixture worker occupied");
   long began=System.nanoTime();f.loadWithRecovery(f.origin,f.origin+"/",f.web,1);long elapsed=TimeUnit.NANOSECONDS.toMillis(System.nanoTime()-began);
   check(f.web.loads.size()==(baseline?0:1),"matching binding navigation must bypass occupied worker");
   check(DeviceBinding.checks==0,"matching cookie must not run network preflight");
   System.out.println((baseline?"Baseline reproduced: matching-cookie navigation queued behind blocked network worker":"Fixed: matching-cookie navigation proceeded while network worker remained blocked")+"; call elapsed "+elapsed+" ms");
  }finally{release.countDown();f.close();}
  if(baseline)return;
  reset();f=new EntryTests();try{WebView stale=f.web;f.generation++;f.loadWithRecovery(f.origin,f.origin+"/",stale,1);check(stale.loads.isEmpty(),"fast path cannot enter with stale generation");}finally{f.close();}
  reset();f=new EntryTests();try{DeviceBinding.value=null;f.loadWithRecovery(f.origin,f.origin+"/",f.web,1);check(f.web.loads.size()==1,"no backup must navigate directly to live auth");}finally{f.close();}
  reset();f=new EntryTests();try{
   DeviceBinding.value=new DeviceBinding.Credential("cookie","backup");DeviceBinding.gate=new CountDownLatch(1);DeviceBinding.entered=new CountDownLatch(1);
   WebView stale=f.web;f.loadWithRecovery(f.origin,f.origin+"/",stale,1);check(DeviceBinding.entered.await(1,TimeUnit.SECONDS),"verification started");
   f.generation++;f.origin="https://two.example";f.web=new WebView();DeviceBinding.gate.countDown();f.drain();
   check(stale.loads.isEmpty()&&f.web.loads.isEmpty()&&CookieManager.instance.sets==0,"late verification must not load or restore across computer identity");
  }finally{DeviceBinding.gate.countDown();f.close();}
  reset();f=new EntryTests();try{
   DeviceBinding.value=new DeviceBinding.Credential("cookie","backup");f.loadWithRecovery(f.origin,f.origin+"/",f.web,1);f.drain();
   check(f.web.loads.size()==1&&CookieManager.instance.value.equals("cookie=backup")&&CookieManager.instance.sets==1,"verified backup restores once");
  }finally{f.close();}
  reset();f=new EntryTests();occupied=new CountDownLatch(1);release=new CountDownLatch(1);final CountDownLatch ready=occupied,unlock=release;
  try{
   f.worker.execute(()->{ready.countDown();try{unlock.await();}catch(InterruptedException ignored){}});check(occupied.await(1,TimeUnit.SECONDS),"fixture queue occupied");
   DeviceBinding.value=new DeviceBinding.Credential("cookie","backup");f.loadWithRecovery(f.origin,f.origin+"/",f.web,1);Future<?> pending=f.connectionTask;
   CookieManager.instance.value="cookie=backup";f.loadWithRecovery(f.origin,f.origin+"/",f.web,1);
   check(pending.isCancelled(),"direct reentry cancels obsolete queued verification");release.countDown();f.drain();check(DeviceBinding.checks==0&&f.web.loads.size()==1,"cancelled recovery cannot verify or replay navigation");
  }finally{release.countDown();f.close();}
  System.out.println("Android entry: matching/no-backup fast paths, stale identity rejection, verified restore, queued cancellation passed");
 }
}
class WebView{final List<String> loads=new ArrayList<>();void loadUrl(String url){loads.add(url);}}
class CookieManager{
 static final CookieManager instance=new CookieManager();String value;int sets;static CookieManager getInstance(){return instance;}
 String getCookie(String url){return value;}void setCookie(String url,String header){value=header.split(";",2)[0];sets++;}
 void setCookie(String url,String header,Consumer<Boolean> callback){setCookie(url,header);callback.accept(true);}void flush(){}
}
class DeviceBinding{
 static Credential value;static CountDownLatch gate,entered;static int checks;
 static class Credential{final String name,token;Credential(String n,String t){name=n;token=t;}String cookie(){return name+"="+token;}}
 static Credential load(Object context,String address){return value;}static void clear(Object c,String address){value=null;}
 static Boolean verify(String address,Credential credential){checks++;if(entered!=null)entered.countDown();if(gate!=null)try{gate.await(1,TimeUnit.SECONDS);}catch(InterruptedException interrupted){Thread.currentThread().interrupt();return null;}return credential.token.equals("backup");}
}
class EventClient{static String sessionCookie(String cookie,String address){return cookie==null?"":cookie;}static void setName(String a,String n){}}
class GatewayURL{static String cookiePath(String address){return "/";}}
class MonitorService{static void bindingsChanged(){}}
class Prefs{Prefs edit(){return this;}Prefs putString(String k,String v){return this;}void apply(){}}
'''
(WORK / 'EntryTests.java').write_text(harness)
java_home = os.environ.get('JAVA_HOME')
def tool(name):
    return str(Path(java_home) / 'bin' / name) if java_home else shutil.which(name)
subprocess.run([tool('javac'), '-d', str(WORK), str(WORK / 'EntryTests.java')], check=True)
subprocess.run([tool('java'), '-cp', str(WORK), 'EntryTests', *(['baseline'] if args.baseline else [])], check=True, timeout=15)
