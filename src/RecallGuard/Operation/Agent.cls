/// SPDX-License-Identifier: MPL-2.0
Include %occStatus

Class RecallGuard.Operation.Agent Extends Ens.BusinessOperation
{
Parameter INVOCATION = "Queue";

Method Investigate(request As RecallGuard.Message.Request, Output response As RecallGuard.Message.Response) As %Status
{
    Set response = ##class(RecallGuard.Message.Response).%New()
    Set prepared = ##class(%DynamicObject).%FromJSON(##class(RecallGuard.Gateway).Call("prepare_run", request.Payload))
    If 'prepared.ok {
        Set response.Payload = prepared.%ToJSON()
        Quit $$$OK
    }
    If 'prepared.result.allowed {
        Set response.Payload = prepared.result.%ToJSON()
        Quit $$$OK
    }
    Set run = prepared.result, result = {"run_id": (run.%Get("run_id"))}
    Try {
        Set agent = ##class(RecallGuard.Agent.Investigator).%New()
        Set sc = agent.%Init()
        $$$ThrowOnError(sc)
        Set rounds = +$System.Util.GetEnviron("MAX_AGENT_ROUNDS")
        If (rounds < 1)!(rounds > 6) Set rounds = 4
        Set session = agent.CreateSession({"max_iterations": (rounds), "max_tokens": 12000, "temperature": 0})
        Set prompt = "Investigate run_id "_run.%Get("run_id")_" for notice "_run.%Get("notice_id")_". Call ReadContext once, then return only the final JSON assessment array for every scoped lot."
        Set answer = agent.Chat(session, prompt)
        // Only provider-returned usage is stored. No invented token totals.
        If $IsObject(answer.Usage) Set result.usage = answer.Usage
        Set result.assessments = ##class(%DynamicArray).%FromJSON(answer.Content)
    } Catch ex {
        // Keep Python out of the AI Hub process, including error handling.
        Set message = ex.DisplayString()
        For name = "GEMINI_API_KEY", "IRIS_PASSWORD" {
            Set value = $System.Util.GetEnviron(name)
            If value '= "" Set message = $Replace(message, value, "[REDACTED]")
        }
        Set result.error = $Extract(message, 1, 500)
    }
    // Triage sends this result to Hold, which activates a successful assessment.
    Set response.Payload = result.%ToJSON()
    Quit $$$OK
}

XData MessageMap
{
<MapItems><MapItem MessageType="RecallGuard.Message.Request"><Method>Investigate</Method></MapItem></MapItems>
}
}
