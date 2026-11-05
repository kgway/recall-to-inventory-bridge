/// SPDX-License-Identifier: MPL-2.0
Include %occStatus

Class RecallGuard.Api Extends %CSP.REST
{
Parameter UseSession = 1;
Parameter CHARSET = "utf-8";
Parameter CONVERTINPUTSTREAM = 1;

XData UrlMap [ XMLNamespace = "http://www.intersystems.com/urlmap" ]
{
<Routes>
    <Route Url="/" Method="GET" Call="Index"/>
    <Route Url="/assets/:name" Method="GET" Call="Asset"/>
    <Route Url="/api/state" Method="GET" Call="State"/>
    <Route Url="/api/advisories/:format" Method="GET" Call="Advisories"/>
    <Route Url="/api/:action" Method="POST" Call="Submit"/>
</Routes>
}

ClassMethod Index() As %Status
{
    Set %response.ContentType = "text/html", %response.CharSet = "utf-8"
    Write ##class(RecallGuard.Backend).Asset("index.html")
    Quit $$$OK
}

ClassMethod Asset(name As %String) As %Status
{
    If (name '= "app.js")&&(name '= "retailer-request.js")&&(name '= "style.css") {
        Set %response.Status = "404 Not Found"
        Quit $$$OK
    }
    Set %response.ContentType = $Select(name = "style.css": "text/css", 1: "text/javascript"), %response.CharSet = "utf-8"
    Write ##class(RecallGuard.Backend).Asset(name)
    Quit $$$OK
}

ClassMethod State() As %Status
{
    Set %response.ContentType = "application/json", %response.CharSet = "utf-8"
    Do %response.SetHeader("Cache-Control", "no-store")
    Set data = ##class(%DynamicObject).%FromJSON(##class(RecallGuard.Backend).Call("state"))
    If data.ok {
        Do data.result.%Set("iris_version", $ZVersion)
        Do data.result.%Set("ai_hub_agent_class_present", ##class(%Dictionary.CompiledClass).%ExistsId("%AI.Agent"), "boolean")
        Do data.result.%Set("production_running", ##class(Ens.Director).IsProductionRunning(), "boolean")
    }
    Write data.%ToJSON()
    Quit $$$OK
}

ClassMethod Submit(action As %String) As %Status
{
    Set %response.ContentType = "application/json", %response.CharSet = "utf-8"
    Do %response.SetHeader("Cache-Control", "no-store")
    If $ListFind($ListBuild("seed", "load_recorded_demo", "investigate", "transact", "refresh", "import_lots", "review", "preview_inventory", "import_inventory", "discovery_plan", "discover", "select_candidates", "audit_now", "audit_configure"), action) = 0 {
        Set %response.Status = "404 Not Found"
        Write {"ok": false, "error": "Unknown action."}.%ToJSON()
        Quit $$$OK
    }
    If $Piece($Get(%request.CgiEnvs("CONTENT_TYPE")), ";") '= "application/json" {
        Set %response.Status = "415 Unsupported Media Type"
        Write {"ok": false, "error": "Use application/json."}.%ToJSON()
        Quit $$$OK
    }
    If +$Get(%request.CgiEnvs("CONTENT_LENGTH")) > 200000 {
        Set %response.Status = "413 Payload Too Large"
        Quit $$$OK
    }
    Try {
        Set body = ""
        While '%request.Content.AtEnd {
            Set body = body_%request.Content.Read(32000)
            If $Length(body) > 200000 Throw ##class(%Exception.General).%New("Request is too large.")
        }
        If body = "" Set body = "{}"
        Set parsed = ##class(%DynamicObject).%FromJSON(body)
        If 'parsed.%IsA("%Library.DynamicObject") Throw ##class(%Exception.General).%New("The request body must be a JSON object.")
        If $ListFind($ListBuild("investigate", "refresh", "discover", "select_candidates", "audit_now"), action) {
            Set current = ##class(%DynamicObject).%FromJSON(##class(RecallGuard.Backend).Call("state"))
            If current.ok, current.result.meta.%Get("experience_mode") = "recorded-demo" Throw ##class(%Exception.General).%New("Recorded demo evidence is fixed. Use a separate empty instance for live investigations or source refresh.")
        }
        If action = "review" Do parsed.%Set("authenticated_reviewer", $Username)
        Set input = ##class(RecallGuard.Message.Request).%New()
        Set input.Action = action, input.Payload = parsed.%ToJSON()
        Set sc = ##class(Ens.Director).CreateBusinessService("API", .service)
        $$$ThrowOnError(sc)
        Set sc = service.ProcessInput(input, .output)
        $$$ThrowOnError(sc)
        Set returned = ##class(%DynamicObject).%FromJSON(output.Payload)
        If returned.%IsDefined("ok"), 'returned.ok {
            Set %response.Status = $Select(returned.%Get("error_type") = "InventoryConflict": "409 Conflict", 1: "400 Bad Request")
        } ElseIf $ListFind($ListBuild("investigate", "refresh", "discover", "select_candidates", "audit_now"), action) {
            Set %response.Status = "202 Accepted"
        }
        Write output.Payload
    } Catch ex {
        Set %response.Status = "400 Bad Request"
        Set message = ##class(RecallGuard.Backend).Redact(ex.DisplayString())
        Write {"ok": false, "error": (message)}.%ToJSON()
    }
    Quit $$$OK
}

ClassMethod Advisories(format As %String) As %Status
{
    If (format '= "json")&&(format '= "csv") {
        Set %response.Status = "400 Bad Request"
        Quit $$$OK
    }
    Set result = ##class(%DynamicObject).%FromJSON(##class(RecallGuard.Backend).Call("advisory_feed", {"format": (format)}.%ToJSON()))
    Do %response.SetHeader("Cache-Control", "no-store")
    If 'result.ok {
        Set %response.Status = "400 Bad Request", %response.ContentType = "application/json"
        Write result.%ToJSON()
        Quit $$$OK
    }
    Set %response.ContentType = result.result.%Get("content_type"), %response.CharSet = "utf-8"
    Do %response.SetHeader("Content-Disposition", "attachment; filename="_result.result.filename)
    Write result.result.content
    Quit $$$OK
}
}
