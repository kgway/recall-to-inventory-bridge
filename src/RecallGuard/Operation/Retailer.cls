/// SPDX-License-Identifier: MPL-2.0
Include %occStatus

Class RecallGuard.Operation.Retailer Extends Ens.BusinessOperation
{
Parameter INVOCATION = "Queue";

Method Execute(request As RecallGuard.Message.Request, Output response As RecallGuard.Message.Response) As %Status
{
    Set response = ##class(RecallGuard.Message.Response).%New()
    Set response.Payload = ##class(RecallGuard.Backend).Call("transact", request.Payload)
    Quit $$$OK
}

XData MessageMap
{
<MapItems><MapItem MessageType="RecallGuard.Message.Request"><Method>Execute</Method></MapItem></MapItems>
}
}
