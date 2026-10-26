package io.github.try2love.codexbridge;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.json.JSONObject;

/** A durable inbox position belongs to one authenticated computer binding. */
final class NotificationCheckpoint {
  final String stream;
  final long cursor;

  NotificationCheckpoint(String stream, long cursor) {
    this.stream = stream;
    this.cursor = cursor;
  }

  static NotificationCheckpoint empty() { return new NotificationCheckpoint("", 0); }

  static NotificationCheckpoint restore(String saved, String binding) {
    if (saved == null || saved.length() > 2048) return empty();
    try {
      JSONObject value = new JSONObject(saved);
      if (value.getInt("version") != 1 || !hash(binding).equals(value.getString("binding"))) return empty();
      return read(value);
    } catch (Exception invalid) { return empty(); }
  }

  static NotificationCheckpoint read(JSONObject value) throws Exception {
    String stream = value.getString("streamId");
    long cursor = value.getLong("cursor");
    if (stream.isEmpty() || stream.length() > 128 || cursor < 0) throw new java.io.IOException("Invalid inbox checkpoint");
    return new NotificationCheckpoint(stream, cursor);
  }

  boolean follows(NotificationCheckpoint previous) {
    return !previous.stream.isEmpty() && stream.equals(previous.stream) && cursor >= previous.cursor;
  }

  String encode(String binding) throws Exception {
    return new JSONObject().put("version", 1).put("binding", hash(binding))
        .put("streamId", stream).put("cursor", cursor).toString();
  }

  private static String hash(String binding) throws Exception {
    byte[] bytes = MessageDigest.getInstance("SHA-256").digest(binding.getBytes(StandardCharsets.UTF_8));
    StringBuilder result = new StringBuilder();
    for (byte value : bytes) result.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
    return result.toString();
  }
}
