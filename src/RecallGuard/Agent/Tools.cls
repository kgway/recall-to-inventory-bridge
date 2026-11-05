/// SPDX-License-Identifier: MPL-2.0
Class RecallGuard.Agent.Tools Extends %AI.ToolSet
{
XData Definition [ MimeType = application/xml ]
{
<ToolSet Name="RecallGuardContext">
    <Tool Name="ReadContext" Method="ReadContext"/>
</ToolSet>
}

/// Read complete official evidence snapshots and all scoped synthetic lot attributes for this run.
ClassMethod ReadContext(runid As %String) As %String
{
    Set data = ##class(RecallGuard.Gateway).Call("tool", {"run_id": (runid), "name": "ReadContext"}.%ToJSON())
    Quit "Investigation context JSON:"_$Char(10)_data
}
}
