package io.github.try2love.codexbridge;

import java.net.URI;
import java.net.InetAddress;
import java.util.Locale;

/** Native DSH links retain their own route and credentials, never enter GatewayURL. */
public final class DshMobileURL {
 public static String connection(String input)throws Exception {
  String value=input.trim();
  if(value.length()>8192||value.matches("(?s).*[\\x00-\\x20\\x7f\\\\].*"))throw new Exception("DSH Mobile 地址无效");
  URI u=new URI(value);String host=u.getHost(),scheme=u.getScheme();
  if(host==null||u.getRawUserInfo()!=null||u.getPort()==0||u.getPort()>65535)throw new Exception("DSH Mobile 地址无效");
  scheme=scheme==null?"":scheme.toLowerCase(Locale.ROOT);
  if(!scheme.equals("https")&&!(scheme.equals("http")&&local(host)))throw new Exception("公网地址必须使用 HTTPS；HTTP 仅限局域网");
  return scheme+"://"+u.getRawAuthority().toLowerCase(Locale.ROOT)+(u.getRawPath().isEmpty()?"/":u.getRawPath())+(u.getRawQuery()==null?"":"?"+u.getRawQuery())+(u.getRawFragment()==null?"":"#"+u.getRawFragment());
 }
 static boolean local(String host){
  if(GatewayURL.local(host))return true;
  if(host.startsWith("[")&&host.endsWith("]")&&!host.contains("%"))try{byte[] ip=InetAddress.getByName(host).getAddress();return ip.length==16&&((ip[0]&254)==252||(ip[0]&255)==254&&(ip[1]&192)==128);}catch(Exception ignored){}
  return false;
 }
 public static String display(String input)throws Exception {URI u=new URI(connection(input));return u.getScheme()+"://"+u.getRawAuthority();}
 public static boolean sameOrigin(String target,String base){try{URI a=new URI(connection(target)),b=new URI(connection(base));return a.getScheme().equals(b.getScheme())&&a.getHost().equals(b.getHost())&&port(a)==port(b);}catch(Exception invalid){return false;}}
 private static int port(URI u){return u.getPort()<0?(u.getScheme().equals("https")?443:80):u.getPort();}
}
