/// SPDX-License-Identifier: MPL-2.0
Class RecallGuard.Service.API Extends Ens.BusinessService
{
Parameter ADAPTER = "";

Method OnProcessInput(input As RecallGuard.Message.Request, Output output As RecallGuard.Message.Response) As %Status
{
    If $ListFind($ListBuild("investigate", "refresh", "audit_now"), input.Action) {
        Set output = ##class(RecallGuard.Message.Response).%New()
        Set sc = ..SendRequestAsync("Triage", input)
        Set output.Payload = {"ok": true, "accepted": true, "action": (input.Action)}.%ToJSON()
    } Else {
        Set sc = ..SendRequestSync("Triage", input, .output, 25)
    }
    Quit sc
}
}
