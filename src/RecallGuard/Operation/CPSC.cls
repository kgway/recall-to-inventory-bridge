/// SPDX-License-Identifier: MPL-2.0
Include %occStatus

Class RecallGuard.Operation.CPSC Extends Ens.BusinessOperation
{
Parameter INVOCATION = "Queue";

Method Refresh(request As RecallGuard.Message.Request, Output response As RecallGuard.Message.Response) As %Status
{
    Set response = ##class(RecallGuard.Message.Response).%New()
    Try {
        If $ListFind($ListBuild("discover", "select_candidates", "audit_now", "audit_tick"), request.Action) {
            Set response.Payload = ##class(RecallGuard.Backend).SourceAction(request.Action, request.Payload)
        } Else {
            Set payload = ##class(RecallGuard.Backend).FetchSources()
            Set response.Payload = ##class(RecallGuard.Backend).Call("import_notices", payload)
        }
    } Catch ex {
        Set error = ##class(RecallGuard.Backend).Redact(ex.DisplayString())
        If request.Action = "refresh" {
            Set recorded = ##class(RecallGuard.Backend).Call("refresh_failed", {"error": (error)}.%ToJSON())
        } Else {
            Set recorded = ##class(RecallGuard.Backend).Call("source_action_failed", {"action": (request.Action), "error": (error)}.%ToJSON())
        }
        Set response.Payload = {"ok": false, "error": (error)}.%ToJSON()
    }
    Quit $$$OK
}

XData MessageMap
{
<MapItems><MapItem MessageType="RecallGuard.Message.Request"><Method>Refresh</Method></MapItem></MapItems>
}
}
