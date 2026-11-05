/// SPDX-License-Identifier: MPL-2.0
Class RecallGuard.Backend Extends %RegisteredObject
{
ClassMethod Call(action As %String, payload As %String = "{}") As %String [ Language = python ]
{
    from recall_guard.runtime import invoke
    return invoke(action, payload)
}

ClassMethod FetchSources() As %String [ Language = python ]
{
    from recall_guard.runtime import fetch_sources
    return fetch_sources()
}

ClassMethod SourceAction(action As %String, payload As %String = "{}") As %String [ Language = python ]
{
    from recall_guard.runtime import source_action
    return source_action(action, payload)
}

ClassMethod Redact(message As %String) As %String [ Language = python ]
{
    from recall_guard.runtime import redact
    return redact(message)
}

ClassMethod Asset(name As %String) As %String [ Language = python ]
{
    from recall_guard.runtime import ROOT
    if name not in ("index.html", "app.js", "retailer-request.js", "style.css"):
        return ""
    path = ROOT / "web" / name
    return path.read_text(encoding="utf-8") if path.exists() else "Recall-to-Inventory Bridge UI is being prepared."
}
}
