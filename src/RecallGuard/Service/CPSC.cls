/// SPDX-License-Identifier: MPL-2.0
Class RecallGuard.Service.CPSC Extends Ens.BusinessService
{
Parameter ADAPTER = "RecallGuard.Adapter.CPSCInbound";

Method OnProcessInput(input As RecallGuard.Message.Request, Output output As RecallGuard.Message.Response) As %Status
{
    Set sc = ..SendRequestAsync("Triage", input)
    // ProcessInput otherwise requests an immediate next OnTask to drain input.
    // This source is a timer, so process only one event per CallInterval.
    Set ..%WaitForNextCallInterval = 1
    Set output = ##class(RecallGuard.Message.Response).%New()
    Set output.Payload = {"ok": true, "accepted": true}.%ToJSON()
    Quit sc
}
}
