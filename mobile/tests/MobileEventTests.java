package io.github.try2love.codexbridge;

import android.content.SharedPreferences;
import android.webkit.CookieManager;
import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

/** Production inbox receiver and transport against independent loopback computers. */
public final class MobileEventTests {
 static final List<String> logs=android.util.Log.messages;
 static final List<String> delivered=new CopyOnWriteArrayList<>();
 static final List<JSONObject> deliveredEvents=new CopyOnWriteArrayList<>();
 static final class Prefs implements SharedPreferences,SharedPreferences.Editor {
  final Map<String,Object> values=new ConcurrentHashMap<>();
  final AtomicInteger commits=new AtomicInteger();
  public boolean getBoolean(String k,boolean d){return (boolean)values.getOrDefault(k,d);}public String getString(String k,String d){return (String)values.getOrDefault(k,d);}public long getLong(String k,long d){return ((Number)values.getOrDefault(k,d)).longValue();}
  @SuppressWarnings("unchecked") public Set<String> getStringSet(String k,Set<String> d){return (Set<String>)values.getOrDefault(k,d);}
  public Editor edit(){return new Editor(){
   final Map<String,Object> staged=new HashMap<>();
   public Editor putString(String k,String v){staged.put(k,v);return this;}public Editor putBoolean(String k,boolean v){staged.put(k,v);return this;}public Editor putLong(String k,long v){staged.put(k,v);return this;}
   public boolean commit(){if(!writable)return false;staged.forEach((k,v)->{if(v==null)values.remove(k);else values.put(k,v);});commits.incrementAndGet();return true;}public void apply(){staged.forEach((k,v)->{if(v==null)values.remove(k);else values.put(k,v);});}
  };}public Editor putString(String k,String v){values.put(k,v);return this;}public Editor putBoolean(String k,boolean v){values.put(k,v);return this;}public Editor putLong(String k,long v){values.put(k,v);return this;}public volatile boolean writable=true;public boolean commit(){return writable;}public void apply(){}
 }
 static final class Gateway implements AutoCloseable {
  final ServerSocket socket=new ServerSocket(0,16,InetAddress.getByName("127.0.0.1"));
  final ExecutorService workers=Executors.newCachedThreadPool();
  final List<String> targets=new CopyOnWriteArrayList<>();
  final List<Integer> responseBytes=new CopyOnWriteArrayList<>();
  volatile String stream="fixture-stream";volatile int cursor=200,status=200,unread=-1;volatile boolean enabled=true,longPoll;
  synchronized void advance(int value){cursor=value;notifyAll();}
  volatile CountDownLatch received,release;final AtomicBoolean slow=new AtomicBoolean();
  Gateway()throws Exception {workers.submit(()->{while(!socket.isClosed())try{Socket client=socket.accept();workers.submit(()->serve(client));}catch(IOException ignored){}});}
  String origin(){return "http://127.0.0.1:"+socket.getLocalPort();}
  void hold(){received=new CountDownLatch(1);release=new CountDownLatch(1);slow.set(true);}
  void serve(Socket client){try(client){
   ByteArrayOutputStream raw=new ByteArrayOutputStream();int c;while((c=client.getInputStream().read())!=-1){raw.write(c);byte[] b=raw.toByteArray();int n=b.length;if(n>=4&&b[n-4]==13&&b[n-3]==10&&b[n-2]==13&&b[n-1]==10)break;}
   String headers=raw.toString("UTF-8"),target=headers.split(" ")[1];targets.add(target);
   check(headers.toLowerCase(Locale.ROOT).contains("origin: "+origin()),"Origin header retained");check(headers.contains(EventClient.USER_AGENT),"Native user agent retained");
   if(slow.compareAndSet(true,false)){received.countDown();release.await(5,TimeUnit.SECONDS);}
   long after=target.contains("?after=")?Long.parseLong(target.split("\\?after=")[1].split("&")[0]):0;
   synchronized(this){
    while(longPoll&&target.contains("&wait=60")&&cursor==after&&target.contains("&streamId="+stream+"&")&&!socket.isClosed())wait(60000);
   }
   // Keep events and metadata on one cursor while the test thread advances it.
   int responseCursor=cursor;
   JSONArray events=new JSONArray();for(int i=Math.max(1,responseCursor-199);i<=responseCursor;i++)if(i>after)events.put(new JSONObject().put("id","event-"+i).put("sequence",i).put("threadId","thread").put("host","local").put("kind",i==201?"attention":i%2==0?"request":"completion").put("title",i==201?"Codex 需要你处理":"任务提醒").put("body","消息内容".repeat(30)));
   JSONArray summary=new JSONArray().put(new JSONObject().put("provider","claude").put("kind",responseCursor%2==0?"request":"completion").put("sequence",responseCursor));
   JSONObject value=new JSONObject().put("clients",new JSONArray().put(new JSONObject().put("id","claude").put("enabled",true).put("unread",enabled?(unread<0?responseCursor:unread):0))).put("summary",summary).put("streamId",stream).put("cursor",responseCursor).put("events",events).put("enabled",enabled);
   if(longPoll)value.put("longPoll",60).put("revision",String.format("%032x",responseCursor));
   byte[] body=value.toString().getBytes(StandardCharsets.UTF_8);
   String head="HTTP/1.1 "+status+" OK\r\nContent-Type: application/json\r\nContent-Length: "+body.length+"\r\nConnection: close\r\n\r\n";
   client.getOutputStream().write(head.getBytes(StandardCharsets.UTF_8));client.getOutputStream().write(body);responseBytes.add(body.length);
  }catch(Exception ignored){}}
  public synchronized void close()throws Exception {socket.close();notifyAll();if(release!=null)release.countDown();workers.shutdownNow();}
 }
 static void check(boolean v,String message){if(!v)throw new AssertionError(message);}
 static final AtomicInteger statusChanges=new AtomicInteger();
 static final List<NotificationReceiver> receivers=new ArrayList<>();
 static NotificationReceiver receiver(App app){NotificationReceiver receiver=new NotificationReceiver(app,statusChanges::incrementAndGet);receivers.add(receiver);return receiver;}
 static final class App extends android.content.Context {
  final Prefs prefs=new Prefs();
  public SharedPreferences getSharedPreferences(String name,int mode){return prefs;}
 }
 static void until(java.util.function.BooleanSupplier predicate,String message)throws Exception {
  long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(5);
  while(!predicate.getAsBoolean()&&System.nanoTime()<deadline)Thread.sleep(10);
  check(predicate.getAsBoolean(),message);
 }
 static long cursor(App app,String address){
  return NotificationCheckpoint.restore(app.prefs.getString("notificationCheckpoint:"+address,null),
   EventClient.tokenValue(EventClient.sessionCookie(CookieManager.getInstance().getCookie(address+"/"),address))).cursor;
 }
 static void poll(NotificationReceiver receiver,App app,String address,long expected)throws Exception {
  until(()->{receiver.refresh();return cursor(app,address)==expected;},"Checkpoint reaches "+expected);
 }
 static void count(NotificationReceiver receiver,Gateway gateway,int before)throws Exception {
  until(()->{receiver.refresh();return gateway.responseBytes.size()>before;},"Request completed");
  Thread.sleep(50);
 }
 static void awaitHeld(NotificationReceiver receiver,Gateway gateway,String message)throws Exception {
  // A checkpoint can become visible before the previous read finishes cleanup.
  until(()->{receiver.refresh();return gateway.received.getCount()==0;},message);
 }
 static void status(NotificationReceiver receiver,NotificationReceiver.Status expected)throws Exception {
  until(()->receiver.status()==expected,"Reception status reaches "+expected);
 }
 public static void main(String[] args)throws Exception {
  App app=new App();Prefs prefs=app.prefs;prefs.putBoolean("alerts",true);
  try(Gateway first=new Gateway();Gateway second=new Gateway()){
   String address=first.origin();prefs.values.put("origins",Set.of(address));
   first.hold();NotificationReceiver receiver=receiver(app);receiver.configure(true,true);
   check(receiver.status()==NotificationReceiver.Status.RETRYING,"Initial connection remains pending until a successful read");first.release.countDown();
   poll(receiver,app,address,200);check(delivered.isEmpty(),"Initial baseline suppresses history");
   status(receiver,NotificationReceiver.Status.RECEIVING);int changes=statusChanges.get();
   int writes=prefs.commits.get(),requests=first.responseBytes.size();count(receiver,first,requests);
   check(prefs.commits.get()==writes,"Unchanged reads avoid synchronous checkpoint writes");
   check(statusChanges.get()==changes,"Unchanged reads avoid redundant status updates");
   check(first.targets.get(first.targets.size()-1).endsWith("?after=200"),"Incremental cursor");
   check(first.responseBytes.get(first.responseBytes.size()-1)<500,"Idle polls avoid downloading old messages");
   first.cursor=201;poll(receiver,app,address,201);check(delivered.size()==1,"Attention delivered");
   check(deliveredEvents.get(0).getString("kind").equals("attention")&&deliveredEvents.get(0).getString("title").equals("Codex 需要你处理"),"Attention copy reaches the original notification route");
   check(logs.stream().anyMatch(line->line.contains("requestMs=")&&line.contains("serverWaitMs=")&&line.contains("overheadMs=")),"Request stages are measured without clock subtraction");
   check(logs.stream().anyMatch(line->line.contains("receiveToPostMs=")&&line.contains("serverAgeMs=")),"System handoff stage is measured");
   check(logs.stream().noneMatch(line->line.contains("消息内容")||line.contains("任务提醒")||line.contains("codex_mobile_session")),"Timing logs omit notification content and credentials");
   requests=first.responseBytes.size();count(receiver,first,requests);check(delivered.size()==1,"Same cursor deduplicated");
   prefs.putLong("cleared:"+address+":"+first.stream,202);first.cursor=202;poll(receiver,app,address,202);check(delivered.size()==1,"Cleared event suppressed");
   first.status=401;first.cursor=203;requests=first.responseBytes.size();count(receiver,first,requests);check(cursor(app,address)==202,"Expired login preserves checkpoint");
   status(receiver,NotificationReceiver.Status.SIGN_IN_REQUIRED);
   first.status=403;requests=first.responseBytes.size();count(receiver,first,requests);
   status(receiver,NotificationReceiver.Status.RETRYING);
   check(logs.stream().anyMatch(line->line.contains("http=403")),"Access failure details remain in logs");
   first.status=503;requests=first.responseBytes.size();count(receiver,first,requests);
   status(receiver,NotificationReceiver.Status.RETRYING);check(cursor(app,address)==202,"Failed reads retain the inbox cursor");
   check(logs.stream().anyMatch(line->line.contains("http=503")),"Changed failure details remain in logs");
   first.status=200;first.enabled=false;requests=first.responseBytes.size();count(receiver,first,requests);
   status(receiver,NotificationReceiver.Status.RETRYING);
   first.enabled=true;poll(receiver,app,address,203);status(receiver,NotificationReceiver.Status.RECEIVING);check(delivered.size()==2,"Reconnect catches up");
   receiver.close();first.cursor=205;receiver=receiver(app);receiver.configure(true,true);
   poll(receiver,app,address,205);check(delivered.size()==4,"Service recreation resumes persisted cursor");
   first.stream="replacement-stream";first.cursor=1;poll(receiver,app,address,1);check(delivered.size()==4,"Stream replacement establishes baseline");
   first.cursor=2;poll(receiver,app,address,2);check(delivered.size()==5,"New stream remains live");
   prefs.putBoolean("alerts",false);first.cursor=3;poll(receiver,app,address,3);check(delivered.size()==5,"Muted reception still updates cursor");
   check(ComputerNotifications.clients(app,address).getJSONObject(0).optLong("unread")==3,"Computer badges continue updating");prefs.putBoolean("alerts",true);
   first.hold();first.cursor=4;awaitHeld(receiver,first,"Delayed request started");
   CookieManager.getInstance().value="codex_mobile_session=replaced-account";first.release.countDown();Thread.sleep(80);
   check(cursor(app,address)==0&&delivered.size()==5,"Previous login cannot deliver or restore a checkpoint");
   receiver.configure(true,true);poll(receiver,app,address,4);status(receiver,NotificationReceiver.Status.RECEIVING);check(delivered.size()==5,"New login baselines independently");
   first.hold();awaitHeld(receiver,first,"Removal request started");
   prefs.values.put("origins",Set.of());prefs.values.remove("notificationCheckpoint:"+address);receiver.configure(true,true);first.release.countDown();Thread.sleep(80);
   status(receiver,NotificationReceiver.Status.SIGN_IN_REQUIRED);
   check(!prefs.values.containsKey("notificationCheckpoint:"+address),"Removed connection never resurrects");
   prefs.values.put("origins",Set.of(address,second.origin()));receiver.configure(true,true);
   poll(receiver,app,address,4);poll(receiver,app,second.origin(),200);
   first.status=503;requests=first.responseBytes.size();count(receiver,first,requests);
   check(receiver.status()==NotificationReceiver.Status.RECEIVING,"A failed saved address must not hide reception from a healthy computer");
   first.status=401;requests=first.responseBytes.size();count(receiver,first,requests);
   check(receiver.status()==NotificationReceiver.Status.RECEIVING,"A stale login on another address leaves healthy reception visible");
   first.status=200;requests=first.responseBytes.size();count(receiver,first,requests);
   status(receiver,NotificationReceiver.Status.RECEIVING);
   first.hold();awaitHeld(receiver,first,"One computer blocks");
   second.cursor=201;poll(receiver,app,second.origin(),201);check(delivered.size()==6,"Other computer delivers independently");
   first.release.countDown();receiver.configure(false,true);Thread.sleep(80);
   requests=first.targets.size()+second.targets.size();receiver.refresh();Thread.sleep(100);
   check(first.targets.size()+second.targets.size()==requests,"Paused receiver schedules no reads");
   receiver.close();prefs.values.put("origins",Set.of(address));first.cursor=10;
   receiver=receiver(app);receiver.configure(true,false);poll(receiver,app,address,10);
   check(delivered.size()==6,"Foreground-only return baselines rather than replaying background history");
   final NotificationReceiver receiverForRefresh=receiver;
   TaskNotifications.fail=12;first.cursor=12;
   until(()->{receiverForRefresh.refresh();return cursor(app,address)==11;},"Successful event is committed before a later delivery fails");
   status(receiver,NotificationReceiver.Status.RETRYING);
   TaskNotifications.fail=-1;poll(receiver,app,address,12);
   int beforeFailure=delivered.size();prefs.writable=false;first.cursor=13;
   requests=first.responseBytes.size();count(receiver,first,requests);
   check(cursor(app,address)==12&&delivered.size()>beforeFailure,"Storage failure keeps the durable cursor behind the event");
   status(receiver,NotificationReceiver.Status.RETRYING);
   prefs.writable=true;poll(receiver,app,address,13);
   first.cursor=12;requests=first.responseBytes.size();count(receiver,first,requests);
   check(cursor(app,address)==13,"Same-stream regression never rewinds the cursor");
   status(receiver,NotificationReceiver.Status.RETRYING);
   receiver.close();
   String encoded=new NotificationCheckpoint("saved-stream",42).encode("binding");
   check(NotificationCheckpoint.restore(encoded,"other").cursor==0,"Persisted checkpoint isolates accounts");
   check(NotificationCheckpoint.restore("malformed","binding").cursor==0,"Corrupt checkpoint safely baselines");
   longPolling();
   sourceSelection();
   System.out.println("PASS inbox baseline, incremental reads, deduplication, clear/mute, reconnect, process recreation, stream reset, login/removal races, parallel computers, pause and reception status transitions; long-poll capability, four concurrent computers, cancellation and network recovery");
  }finally{for(NotificationReceiver receiver:receivers)receiver.close();}
 }
 static void longPolling()throws Exception {
  try(Gateway a=new Gateway();Gateway b=new Gateway();Gateway c=new Gateway();Gateway d=new Gateway();Gateway legacy=new Gateway()){
   List<Gateway> gateways=List.of(a,b,c,d);
   App app=new App();Set<String> origins=new HashSet<>();
   for(Gateway gateway:gateways){gateway.longPoll=true;origins.add(gateway.origin());}
   origins.add(legacy.origin());app.prefs.values.put("origins",origins);app.prefs.putBoolean("alerts",true);
   CookieManager.getInstance().value="codex_mobile_session=long-poll-account";
   NotificationReceiver receiver=receiver(app);receiver.configure(true,true);
   until(()->gateways.stream().allMatch(g->g.targets.size()>=2)&&legacy.targets.size()==1,"Every computer reaches its own wait");
   for(Gateway gateway:gateways){check(!gateway.targets.get(0).contains("wait="),"Capability discovery is immediate");check(gateway.targets.get(1).contains("wait=60&streamId=fixture-stream&revision="),"Wait carries cursor, stream and revision");}
   int before=delivered.size();d.advance(201);
   until(()->cursor(app,d.origin())==201,"Fourth computer delivers while the others wait");
   check(delivered.size()==before+1,"Incremental event delivered once");
   until(()->d.targets.size()>=3,"Success immediately starts the next wait");
   Thread.sleep(100);check(legacy.targets.size()==1,"Older gateways retain the 15-second interval");
   int requests=a.targets.size();receiver.reconnect();
   until(()->a.targets.size()>requests,"Network availability restarts a pending read immediately");
   receiver.configure(false,true);Thread.sleep(100);
   int stopped=gateways.stream().mapToInt(g->g.targets.size()).sum();before=delivered.size();
   for(Gateway gateway:gateways)gateway.advance(202);
   receiver.refresh();Thread.sleep(100);
   check(gateways.stream().mapToInt(g->g.targets.size()).sum()==stopped&&delivered.size()==before,"Pause cancels pending waits and ignores late results");
   receiver.close();
  }
 }
 static void sourceSelection()throws Exception {
  try(Gateway a=new Gateway();Gateway b=new Gateway();Gateway c=new Gateway();Gateway d=new Gateway()){
   List<Gateway> gateways=List.of(a,b,c,d);App app=new App();Set<String> origins=new HashSet<>();
   for(Gateway gateway:gateways)origins.add(gateway.origin());
   app.prefs.values.put("origins",origins);app.prefs.putBoolean("alerts",true);
   NotificationReceiver reader=receiver(app);reader.configure(true,true);
   for(Gateway gateway:gateways)poll(reader,app,gateway.origin(),200);
   int before=delivered.size();for(Gateway gateway:gateways){gateway.cursor=201;poll(reader,app,gateway.origin(),201);}
   check(delivered.size()==before+4,"Four saved addresses default to enabled");
   for(Gateway gateway:List.of(b,c,d))sourceEnabled(app,gateway.origin(),false);
   reader.configure(true,true);for(Gateway gateway:gateways)poll(reader,app,gateway.origin(),201);
   before=delivered.size();for(Gateway gateway:gateways){gateway.cursor=202;poll(reader,app,gateway.origin(),202);}
   check(delivered.size()==before+1&&delivered.get(before).startsWith(a.origin()+":"),"Only the selected address alerts; other inboxes still advance");
   check(ComputerNotifications.clients(app,b.origin()).getJSONObject(0).optLong("unread")==202,"Muted address keeps its inbox badge");
   reader.close();reader=receiver(app);reader.configure(true,true);b.cursor=203;poll(reader,app,b.origin(),203);
   check(delivered.size()==before+1,"Source mute survives service recreation");
   b.hold();b.cursor=204;awaitHeld(reader,b,"Muted response remains in flight");
   sourceEnabled(app,b.origin(),true);sourceEnabled(app,b.origin(),false);sourceEnabled(app,b.origin(),true);
   reader.configure(true,true);b.release.countDown();poll(reader,app,b.origin(),204);
   check(delivered.size()==before+1,"Rapid toggles retire old responses and do not replay muted backlog");
   b.cursor=205;poll(reader,app,b.origin(),205);check(delivered.size()==before+2,"Re-enabled source alerts for new events");
   b.hold();b.cursor=206;awaitHeld(reader,b,"Enabled response remains in flight");
   sourceEnabled(app,b.origin(),false);reader.configure(true,true);b.release.countDown();poll(reader,app,b.origin(),206);
   check(delivered.size()==before+2,"Disabling an address rejects its in-flight alert");reader.close();
  }
 }
 static void sourceEnabled(App app,String origin,boolean enabled){NotificationSources.setEnabled(app.prefs,origin,enabled);}
}
