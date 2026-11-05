/// SPDX-License-Identifier: MPL-2.0
Include %occStatus

Class RecallGuard.Adapter.CPSCInbound Extends Ens.InboundAdapter
{
Property PollEnabled As %Boolean [ InitialExpression = 0 ];
Parameter SETTINGS = "PollEnabled:Basic";

Method OnTask() As %Status
{
    Try {
        Set sc = $$$OK, auditQueued = 0
        // Cheap local due check; only an explicitly enabled snapshot policy queues work.
        Set due = ##class(%DynamicObject).%FromJSON(##class(RecallGuard.Backend).Call("audit_due"))
        If due.ok, due.result.due {
            Set tick = ##class(RecallGuard.Message.Request).%New()
            Set tick.Action = "audit_tick", tick.Payload = "{}"
            Set sc = ..BusinessHost.ProcessInput(tick), auditQueued = 1
        }
        If ('auditQueued)&&..PollEnabled {
            Set input = ##class(RecallGuard.Message.Request).%New()
            Set input.Action = "import_notices", input.Payload = ##class(RecallGuard.Backend).FetchSources()
            Set sc = ..BusinessHost.ProcessInput(input)
        }
    } Catch ex {
        Set error = ##class(RecallGuard.Backend).Redact(ex.DisplayString())
        Set recorded = ##class(RecallGuard.Backend).Call("refresh_failed", {"error": (error)}.%ToJSON())
        Set sc = $$$ERROR($$$GeneralError, error)
    }
    Quit sc
}
}
