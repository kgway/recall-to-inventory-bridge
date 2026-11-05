/// SPDX-License-Identifier: MPL-2.0
Include %occStatus

/// Native messaging boundary. AI Hub workers never initialize Embedded Python.
Class RecallGuard.Gateway Extends %RegisteredObject
{
ClassMethod Call(action As %String, payload As %String = "{}") As %String
{
    Set request = ##class(RecallGuard.Message.Request).%New()
    Set request.Action = action, request.Payload = payload
    Set sc = ##class(Ens.Director).CreateBusinessService("API", .service)
    $$$ThrowOnError(sc)
    Set sc = service.ProcessInput(request, .response)
    $$$ThrowOnError(sc)
    Quit response.Payload
}
}
