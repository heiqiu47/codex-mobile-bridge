package io.github.try2love.codexbridge;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.net.*;
import android.os.*;

/** Owns the user-selected foreground service; inbox state belongs to the receiver. */
public final class MonitorService extends Service {
  static volatile boolean visible;
  private static volatile MonitorService service;
  private static final int ONGOING = -17021;
  private final Handler main = new Handler(Looper.getMainLooper());
  private NotificationReceiver receiver;
  private ConnectivityManager network;
  private volatile boolean foreground;
  private String foregroundText;
  private boolean destroyed;

  static boolean backgroundRunning() { MonitorService current = service; return current != null && current.foreground; }

  static java.util.Map<String,NotificationReceiver.Status> connectionStates() {
    MonitorService current=service;
    return current==null||current.receiver==null?java.util.Collections.emptyMap():current.receiver.connectionStates();
  }

  static void setVisible(boolean value) {
    visible = value;
    ComputerNotifications.stale();
    refresh();
  }

  static void bindingsChanged() { ComputerNotifications.clear(); refresh(); }

  static void refresh() {
    MonitorService current = service;
    if (current != null) current.main.post(() -> {
      if (!current.destroyed) { current.configure(); current.receiver.refresh(); }
    });
  }

  static boolean startBackground(Context context) {
    if (!context.getSharedPreferences("bridge", 0).getBoolean("backgroundNotifications", false)) return true;
    try {
      context.startForegroundService(new Intent(context, MonitorService.class));
      return true;
    } catch (RuntimeException denied) {
      context.getSharedPreferences("bridge", 0).edit().putBoolean("backgroundNotifications", false).apply();
      refresh();
      return false;
    }
  }

  private final ConnectivityManager.NetworkCallback networkCallback = new ConnectivityManager.NetworkCallback() {
    @Override public void onAvailable(Network value) { refresh(); }
  };

  @Override public void onCreate() {
    super.onCreate();
    receiver = new NotificationReceiver(this, () -> main.post(() -> {
      if (!destroyed && foreground) promote();
    }));
    service = this;
    network = (ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
    network.registerDefaultNetworkCallback(networkCallback);
    configure();
  }

  @Override public int onStartCommand(Intent intent, int flags, int startId) {
    SharedPreferences prefs = getSharedPreferences("bridge", 0);
    if (intent != null && "pause".equals(intent.getAction()))
      prefs.edit().putBoolean("backgroundNotifications", false).apply();
    if (prefs.getBoolean("backgroundNotifications", false)
        && prefs.getBoolean("alerts", false)
        && ((NotificationManager) getSystemService(NOTIFICATION_SERVICE)).areNotificationsEnabled()) {
      try { promote(); }
      catch (RuntimeException denied) { prefs.edit().putBoolean("backgroundNotifications", false).apply(); }
    }
    configure();
    if (!foreground) stopSelf(startId);
    return foreground ? START_STICKY : START_NOT_STICKY;
  }

  private void configure() {
    SharedPreferences prefs = getSharedPreferences("bridge", 0);
    boolean background = prefs.getBoolean("backgroundNotifications", false)
        && prefs.getBoolean("alerts", false)
        && ((NotificationManager) getSystemService(NOTIFICATION_SERVICE)).areNotificationsEnabled();
    if (!background) {
      if (foreground) { stopForeground(STOP_FOREGROUND_REMOVE); foreground = false; stopSelf(); }
    }
    receiver.configure(visible || foreground, background);
  }

  private void promote() {
    NotificationReceiver.Status status = receiver.status();
    String text = L(statusText(status));
    if (foreground && text.equals(foregroundText)) return;
    String channel = "background-monitor";
    NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
    if (manager.getNotificationChannel(channel) == null) {
      NotificationChannel value = new NotificationChannel(channel, L("后台通知"), NotificationManager.IMPORTANCE_LOW);
      value.setSound(null, null);
      value.setShowBadge(false);
      manager.createNotificationChannel(value);
    }
    PendingIntent open = PendingIntent.getActivity(this, ONGOING,
        new Intent(this, MainActivity.class), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    PendingIntent pause = PendingIntent.getService(this, ONGOING,
        new Intent(this, MonitorService.class).setAction("pause"), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    Notification notification = new Notification.Builder(this, channel)
        .setSmallIcon(getResources().getIdentifier("ic_notification", "drawable", getPackageName()))
        .setContentTitle(L("后台通知运行中")).setContentText(text)
        .setOngoing(true).setOnlyAlertOnce(true).setVisibility(Notification.VISIBILITY_PUBLIC)
        .setContentIntent(open)
        .addAction(new Notification.Action.Builder(null, L("暂停后台通知"), pause).build()).build();
    if (foreground) manager.notify(ONGOING, notification);
    else if (Build.VERSION.SDK_INT >= 34) startForeground(ONGOING, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
    else startForeground(ONGOING, notification);
    foreground = true;
    foregroundText = text;
  }

  private static String statusText(NotificationReceiver.Status status) {
    switch (status) {
      case RECEIVING: return "正在接收任务提醒";
      case RETRYING: return "正在重试";
      default: return "请重新登录";
    }
  }

  private String L(String value) { return MobileStrings.text(this, value); }

  @Override public IBinder onBind(Intent intent) { return new Binder(); }

  @Override public void onDestroy() {
    destroyed = true;
    if (service == this) service = null;
    network.unregisterNetworkCallback(networkCallback);
    receiver.close();
    super.onDestroy();
  }
}
