/// SPDX-License-Identifier: MPL-2.0
Include %occStatus

Class RecallGuard.Operation.Hold Extends Ens.BusinessOperation
{
Parameter INVOCATION = "Queue";

Method Apply(request As RecallGuard.Message.Request, Output response As RecallGuard.Message.Response) As %Status
{
    Set response = ##class(RecallGuard.Message.Response).%New()
    If request.Action = "complete_run" {
        Set result = ##class(%DynamicObject).%FromJSON(request.Payload)
        If 'result.%IsDefined("error") {
            If result.%IsDefined("assessments") {
                Set submitted = ##class(%DynamicObject).%FromJSON(##class(RecallGuard.Backend).Call("submit", request.Payload))
                If 'submitted.ok Set result.error = submitted.error
            } Else {
                Set result.error = "The agent did not return assessments."
            }
        }
        Do result.%Remove("assessments")
        Set response.Payload = ##class(RecallGuard.Backend).Call("finish_run", result.%ToJSON())
    } ElseIf $ListFind($ListBuild("prepare_run", "tool", "finish_run", "revalidate_run", "import_notices", "import_lots", "seed", "load_recorded_demo", "review", "preview_inventory", "import_inventory", "discovery_plan", "audit_configure"), request.Action) = 0 {
        Set response.Payload = {"ok": false, "error": "Unsupported inventory action."}.%ToJSON()
    } Else {
        Set response.Payload = ##class(RecallGuard.Backend).Call(request.Action, request.Payload)
    }
    Quit $$$OK
}

XData MessageMap
{
<MapItems><MapItem MessageType="RecallGuard.Message.Request"><Method>Apply</Method></MapItem></MapItems>
}
}
