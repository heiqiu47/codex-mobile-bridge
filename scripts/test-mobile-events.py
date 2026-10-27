#!/usr/bin/env python3
"""Run real Android event HTTP and polling code against isolated local fixtures."""
import hashlib
import os
import urllib.request
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.tmp/mobile-inbox-tests'
WORK.mkdir(parents=True, exist_ok=True)
stubs = {
'android/util/Log.java': 'package android.util;public class Log {public static final java.util.List<String> messages=new java.util.concurrent.CopyOnWriteArrayList<>();public static int w(String tag,String message){messages.add(message);return 0;}public static int i(String tag,String message){messages.add(message);return 0;}}',
'android/webkit/CookieManager.java': r'''package android.webkit;
public class CookieManager {
 private static final CookieManager instance=new CookieManager();
 public volatile String value="codex_mobile_session=fixture";
 public static CookieManager getInstance(){return instance;}
 public String getCookie(String url){return value;}
 public void setCookie(String url,String header){value=header.split(";",2)[0];}
 public void flush(){}
}''',
'android/content/Context.java': r'''package android.content;
public abstract class Context {public abstract SharedPreferences getSharedPreferences(String name,int mode);}''',
'android/content/SharedPreferences.java': r'''package android.content;
import java.util.*;
public interface SharedPreferences {boolean getBoolean(String k,boolean d);String getString(String k,String d);long getLong(String k,long d);Set<String> getStringSet(String k,Set<String> d);Editor edit();interface Editor{Editor putString(String k,String v);Editor putBoolean(String k,boolean v);Editor putLong(String k,long v);boolean commit();void apply();}}''',
'io/github/try2love/codexbridge/MobileStrings.java': 'package io.github.try2love.codexbridge;final class MobileStrings {static String text(android.content.Context c,String s){return s;}}',
}
stubs['io/github/try2love/codexbridge/TaskNotifications.java'] = r'''package io.github.try2love.codexbridge;
final class TaskNotifications {static long fail=-1;static void show(android.content.Context context,String origin,String stream,org.json.JSONObject event,String channel)throws Exception {if(event.getLong("sequence")==fail)throw new java.io.IOException("Delivery unavailable");MobileEventTests.delivered.add(origin+":"+stream+":"+event.getLong("sequence"));}}
'''
for name, source in stubs.items():
    path = WORK / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
# org.json on the JVM exercises real serialized checkpoints and HTTP payloads.
jar = ROOT / '.tmp/mobile-tools/json-20240303.jar'
jar.parent.mkdir(parents=True, exist_ok=True)
if not jar.exists():
    urllib.request.urlretrieve('https://repo.maven.apache.org/maven2/org/json/json/20240303/json-20240303.jar', jar)
assert hashlib.sha256(jar.read_bytes()).hexdigest() == '3cf6cd6892e32e2b4c1c39e0f52f5248a2f5b37646fdfbb79a66b46b618414ed'
java_home = os.environ.get('JAVA_HOME')

def java_tool(name):
    return str(Path(java_home) / 'bin' / name) if java_home else shutil.which(name)

source = ROOT / 'mobile/android/src/io/github/try2love/codexbridge'
subprocess.run([java_tool('javac'), '-encoding', 'UTF-8', '-cp', str(jar), '-d', str(WORK),
               *[str(WORK / name) for name in stubs],
               *[str(source / (name + '.java')) for name in
                 ('NotificationReceiver', 'NotificationCheckpoint', 'GatewayURL', 'EventClient', 'ComputerNotifications')],
               str(ROOT / 'mobile/tests/MobileEventTests.java')], check=True)
subprocess.run([java_tool('java'), '-Dsun.net.http.allowRestrictedHeaders=true', '-cp',
                str(WORK) + os.pathsep + str(jar), 'io.github.try2love.codexbridge.MobileEventTests'], check=True)
