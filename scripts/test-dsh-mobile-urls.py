#!/usr/bin/env python3
"""Exercise both native DSH URL parsers without relaxing Bridge URL rules."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT/'.tmp/dsh-mobile-url-tests'
WORK.mkdir(parents=True, exist_ok=True)
JDK = Path(os.environ['JAVA_HOME']) if os.environ.get('JAVA_HOME') else next((ROOT/'.tmp/mobile-tools/jdk').glob('*/Contents/Home'))
cases = json.loads((ROOT/'mobile/tests/dsh-mobile-url-cases.json').read_text())
lines = ['import io.github.try2love.codexbridge.*;', 'class DshURLTests { public static void main(String[] args)throws Exception {']
for value, expected in cases['accepted']:
    lines.append(f'if(!DshMobileURL.connection({json.dumps(value)}).equals({json.dumps(expected)}))throw new AssertionError("URL preservation");')
    lines.append(f'if(DshMobileURL.display({json.dumps(value)}).matches(".*[?#].*"))throw new AssertionError("credential disclosure");')
for value in cases['rejected']:
    lines.append(f'try{{DshMobileURL.connection({json.dumps(value)});throw new AssertionError({json.dumps(value)});}}catch(Exception expected){{}}')
lines += ['String base="https://dsh.example/?auth=secret";',
          'if(!DshMobileURL.sameOrigin("https://dsh.example:443/chat",base))throw new AssertionError();',
          'for(String value:new String[]{"https://dsh.example:444/chat","https://dsh.example.evil/","https://user@dsh.example/"})if(DshMobileURL.sameOrigin(value,base))throw new AssertionError();',
          'try{GatewayURL.connection(base);throw new AssertionError("Bridge boundary changed");}catch(Exception expected){}',
          'System.out.println("Java DSH Mobile: full link preservation, credential redaction, transport and origin boundaries passed");}}']
(WORK/'DshURLTests.java').write_text('\n'.join(lines))
source = ROOT/'mobile/android/src/io/github/try2love/codexbridge'
subprocess.run([str(JDK/'bin/javac'), '-d', str(WORK), str(source/'GatewayURL.java'), str(source/'DshMobileURL.java'), str(WORK/'DshURLTests.java')], check=True)
subprocess.run([str(JDK/'bin/java'), '-cp', str(WORK), 'DshURLTests'], check=True)
subprocess.run(['xcrun','swiftc','-module-cache-path',str(WORK/'cache'),str(ROOT/'mobile/ios/BridgePreview/GatewayURL.swift'),str(ROOT/'mobile/ios/BridgePreview/DshMobileURL.swift'),str(ROOT/'mobile/tests/DshMobileURLTests.swift'),'-o',str(WORK/'swift-tests')],check=True)
subprocess.run([str(WORK/'swift-tests'),str(ROOT/'mobile/tests/dsh-mobile-url-cases.json')],check=True)
