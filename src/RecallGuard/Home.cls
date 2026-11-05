/// SPDX-License-Identifier: MPL-2.0
Include %occStatus

/// Standard CSP login establishes the session used by the REST UI and API.
Class RecallGuard.Home Extends %CSP.Page
{
ClassMethod OnPreHTTP() As %Boolean [ ServerOnly = 1 ]
{
    Set %response.Redirect = "/recall-guard/"
    Quit 1
}

ClassMethod OnPage() As %Status [ ServerOnly = 1 ]
{
    Quit $$$OK
}
}
