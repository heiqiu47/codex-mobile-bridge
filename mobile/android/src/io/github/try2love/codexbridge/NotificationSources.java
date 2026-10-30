package io.github.try2love.codexbridge;

import android.content.SharedPreferences;

/** Local alert choices belong to saved addresses, not gateway names or servers. */
final class NotificationSources {
  static boolean enabled(SharedPreferences prefs, String origin) {
    return !prefs.getBoolean("notificationsMuted:" + origin, false);
  }

  static long revision(SharedPreferences prefs, String origin) {
    return prefs.getLong("notificationSourceRevision:" + origin, 0);
  }

  static void setEnabled(SharedPreferences prefs, String origin, boolean enabled) {
    synchronized (EventClient.class) {
      if (enabled(prefs, origin) == enabled) return;
      prefs.edit().putBoolean("notificationsMuted:" + origin, !enabled)
          .putLong("notificationSourceRevision:" + origin, revision(prefs, origin) + 1)
          // A new reader baselines; it must not replay the muted interval.
          .putString("notificationCheckpoint:" + origin, null).apply();
    }
  }
}
