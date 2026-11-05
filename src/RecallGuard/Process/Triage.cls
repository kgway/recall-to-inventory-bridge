/// SPDX-License-Identifier: MPL-2.0
Include %occStatus

Class RecallGuard.Process.Triage Extends Ens.BusinessProcess
{
Method OnRequest(request As RecallGuard.Message.Request, Output response As RecallGuard.Message.Response) As %Status
{
    Set response = ##class(RecallGuard.Message.Response).%New()
    Set response.Payload = {"ok": true, "accepted": true}.%ToJSON()
    If request.Action = "investigate" {
        Quit ..SendRequestAsync("Agent", request, 1, "agent")
    }
    If $ListFind($ListBuild("audit_now", "audit_tick"), request.Action) {
        Quit ..SendRequestAsync("CPSCRefresh", request, 1, "audit")
    }
    If $ListFind($ListBuild("refresh", "discover", "select_candidates"), request.Action) {
        Quit ..SendRequestAsync("CPSCRefresh", request, 1, "refresh")
    }
    If request.Action = "transact" {
        Quit ..SendRequestSync("Retailer", request, .response, 20)
    }
    Quit ..SendRequestSync("Hold", request, .response, 20)
}

Method OnResponse(request As RecallGuard.Message.Request, ByRef response As RecallGuard.Message.Response, callrequest As RecallGuard.Message.Request, callresponse As RecallGuard.Message.Response, completionKey As %String) As %Status
{
    If completionKey = "audit" {
        Set audited = ##class(%DynamicObject).%FromJSON(callresponse.Payload)
        If audited.ok, audited.result.%IsDefined("ai_notice_id") {
            Set investigation = ##class(RecallGuard.Message.Request).%New()
            Set investigation.Action = "investigate"
            Set investigation.Payload = {"notice_id": (audited.result.%Get("ai_notice_id")), "audit_cycle_id": (audited.result.%Get("cycle_id"))}.%ToJSON()
            Quit ..SendRequestAsync("Agent", investigation, 1, "agent")
        }
    }
    If completionKey = "agent" {
        Set result = ##class(%DynamicObject).%FromJSON(callresponse.Payload)
        If result.%IsDefined("run_id") {
            Set apply = ##class(RecallGuard.Message.Request).%New()
            Set apply.Action = "complete_run", apply.Payload = callresponse.Payload
            Quit ..SendRequestAsync("Hold", apply, 1, "hold")
        }
    }
    Set response = callresponse
    Quit $$$OK
}
}
