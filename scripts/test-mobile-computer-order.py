"""Compile both apps' actual computer-ordering expressions against isolated records."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT/'.tmp/mobile-computer-order'
WORK.mkdir(parents=True, exist_ok=True)
JDK = Path(os.environ['JAVA_HOME']) if os.environ.get('JAVA_HOME') else next((ROOT/'.tmp/mobile-tools/jdk').glob('*/Contents/Home'))
android = (ROOT/'mobile/android/src/io/github/try2love/codexbridge/MainActivity.java').read_text()
method = next(line.strip() for line in android.splitlines() if line.startswith(' List<String> recentComputers()'))
java = '''import java.util.*;
class DshMobileStore {static List<String> ids(Object owner){return Arrays.asList("old","new");}}
class ComputerOrderTests {
 static class Prefs {Map<String,Long> values=new HashMap<>();long getLong(String key,long fallback){return values.getOrDefault(key,fallback);}}
 Prefs prefs=new Prefs();Set<String> saved(){return new HashSet<>(Arrays.asList("https://gateway-a","https://gateway-b"));}
 METHOD
 void expect(String... expected){if(!recentComputers().equals(Arrays.asList(expected)))throw new AssertionError(recentComputers());}
 public static void main(String[] args){ComputerOrderTests t=new ComputerOrderTests();
 t.prefs.values.put("last-opened:https://gateway-a",100L);t.prefs.values.put("last-opened:https://gateway-b",200L);t.prefs.values.put("last-opened:dsh:new",300L);
 t.expect("dsh:new","https://gateway-b","https://gateway-a","dsh:old");
 t.prefs.values.put("last-opened:https://gateway-a",400L);t.expect("https://gateway-a","dsh:new","https://gateway-b","dsh:old");
 t.prefs.values.put("last-opened:dsh:old",500L);t.expect("dsh:old","https://gateway-a","dsh:new","https://gateway-b");
 if(t.saved().size()!=2)throw new AssertionError("DSH must not enter gateway probe/notification storage");
 System.out.println("Android: mixed recent order, legacy entries and gateway isolation passed");}
}
'''.replace('METHOD', method)
(WORK/'ComputerOrderTests.java').write_text(java)
subprocess.run([str(JDK/'bin/javac'),'-d',str(WORK),str(WORK/'ComputerOrderTests.java')],check=True)
subprocess.run([str(JDK/'bin/java'),'-cp',str(WORK),'ComputerOrderTests'],check=True)
ios=(ROOT/'mobile/ios/BridgePreview/App.swift').read_text()
start=ios.index('    private var recentComputers: [String] {')
end=ios.index('    private func ',start)
prop=ios[start:end].replace('private var','var',1)
swift='''import Foundation
struct Defaults {var values: [String: Double] = [:];func double(forKey key: String) -> Double {values[key] ?? 0}}
enum DshMobileStore {static let ids = ["old", "new"]}
struct ComputerOrderTests {
 var saved = ["https://gateway-a", "https://gateway-b"]
 var defaults = Defaults()
 PROPERTY
}
var t=ComputerOrderTests()
t.defaults.values=["last-opened:https://gateway-a":100,"last-opened:https://gateway-b":200,"last-opened:dsh:new":300]
precondition(t.recentComputers == ["dsh:new","https://gateway-b","https://gateway-a","dsh:old"])
t.defaults.values["last-opened:https://gateway-a"]=400
precondition(t.recentComputers == ["https://gateway-a","dsh:new","https://gateway-b","dsh:old"])
t.defaults.values["last-opened:dsh:old"]=500
precondition(t.recentComputers == ["dsh:old","https://gateway-a","dsh:new","https://gateway-b"])
precondition(t.saved.count == 2)
print("iOS: mixed recent order, legacy entries and gateway isolation passed")
'''.replace('PROPERTY',prop)
(WORK/'main.swift').write_text(swift)
subprocess.run(['xcrun','swiftc','-module-cache-path',str(WORK/'cache'),str(WORK/'main.swift'),'-o',str(WORK/'swift-tests')],check=True)
subprocess.run([str(WORK/'swift-tests')],check=True)
