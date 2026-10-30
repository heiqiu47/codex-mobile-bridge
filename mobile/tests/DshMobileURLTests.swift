import Foundation
@main struct DshMobileURLTests {
    static func main() throws {
        let cases = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))) as! [String: Any]
        for pair in cases["accepted"] as! [[String]] {
            let url = try DshMobileURL.connection(pair[0]); precondition(url.absoluteString == pair[1], pair[0])
            precondition(!DshMobileURL.display(url).contains("auth=")); precondition(!DshMobileURL.display(url).contains("token="))
        }
        for value in cases["rejected"] as! [String] { precondition((try? DshMobileURL.connection(value)) == nil, value) }
        let base = URL(string: "https://dsh.example/?auth=secret")!
        for value in ["https://dsh.example:443/chat", "https://dsh.example/?auth=other"] { precondition(DshMobileURL.same(URL(string: value)!, base)) }
        for value in ["https://dsh.example:444/chat", "https://dsh.example.evil/", "https://user@dsh.example/"] { precondition(!DshMobileURL.same(URL(string: value)!, base)) }
        precondition((try? GatewayURL.connection(base.absoluteString)) == nil)
        print("Swift DSH Mobile: full link preservation, credential redaction, transport and origin boundaries passed")
    }
}
