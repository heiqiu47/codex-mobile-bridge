package io.github.try2love.codexbridge;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.*;
import javax.crypto.*;
import javax.crypto.spec.GCMParameterSpec;

/** Credential-bearing URLs are encrypted; only opaque IDs enter the computer list. */
final class DshMobileStore {
 private static SharedPreferences prefs(Context c){return c.getSharedPreferences("dsh-mobile-connections",0);}
 private static SecretKey key()throws Exception {
  String alias="codex-bridge-dsh-mobile-v1";KeyStore store=KeyStore.getInstance("AndroidKeyStore");store.load(null);SecretKey key=(SecretKey)store.getKey(alias,null);if(key!=null)return key;
  KeyGenerator generator=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");generator.init(new KeyGenParameterSpec.Builder(alias,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256).build());return generator.generateKey();
 }
 static List<String> ids(Context c){List<String> ids=new ArrayList<>(prefs(c).getAll().keySet());Collections.sort(ids);return ids;}
 static String save(Context c,String input)throws Exception {
  String url=DshMobileURL.connection(input),id=null;for(String candidate:ids(c))if(url.equals(load(c,candidate))){id=candidate;break;}if(id==null)id=UUID.randomUUID().toString();
  Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,key());cipher.updateAAD(id.getBytes(StandardCharsets.UTF_8));byte[] encrypted=cipher.doFinal(url.getBytes(StandardCharsets.UTF_8)),iv=cipher.getIV(),result=new byte[iv.length+encrypted.length];System.arraycopy(iv,0,result,0,iv.length);System.arraycopy(encrypted,0,result,iv.length,encrypted.length);
  if(!prefs(c).edit().putString(id,Base64.encodeToString(result,Base64.NO_WRAP)).commit())throw new Exception("无法保存 DSH Mobile 连接");return id;
 }
 static String load(Context c,String id){try{byte[] bytes=Base64.decode(prefs(c).getString(id,""),Base64.NO_WRAP);if(bytes.length<29||bytes.length>32768)return null;Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,key(),new GCMParameterSpec(128,bytes,0,12));cipher.updateAAD(id.getBytes(StandardCharsets.UTF_8));return DshMobileURL.connection(new String(cipher.doFinal(bytes,12,bytes.length-12),StandardCharsets.UTF_8));}catch(Exception invalid){return null;}}
 static void remove(Context c,String id){prefs(c).edit().remove(id).commit();}
}
