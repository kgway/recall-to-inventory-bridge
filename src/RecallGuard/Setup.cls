/// SPDX-License-Identifier: MPL-2.0
Include %occStatus

Class RecallGuard.Setup Extends %RegisteredObject
{
ClassMethod ConfigureWeb() As %Status
{
    Set previousNamespace = $Namespace
    New $Namespace
    Set $Namespace = "%SYS"
    Set properties("NameSpace") = "RECALLGUARD"
    Set properties("DispatchClass") = "RecallGuard.Api"
    Set properties("Enabled") = 1
    Set properties("AutheEnabled") = 32
    Set properties("LoginPage") = "%CSP.Login.cls"
    Set properties("CookiePath") = "/recall-guard/"
    If ##class(Security.Applications).Exists("/recall-guard") {
        Set sc = ##class(Security.Applications).Modify("/recall-guard", .properties)
    } Else {
        Set sc = ##class(Security.Applications).Create("/recall-guard", .properties)
    }
    $$$ThrowOnError(sc)
    Kill properties
    Set properties("NameSpace") = "RECALLGUARD", properties("Enabled") = 1
    Set properties("AutheEnabled") = 32, properties("LoginPage") = "%CSP.Login.cls"
    Set properties("CookiePath") = "/recall-guard/", properties("CSRFToken") = 1
    If ##class(Security.Applications).Exists("/recall-guard/auth") {
        Quit ##class(Security.Applications).Modify("/recall-guard/auth", .properties)
    }
    Quit ##class(Security.Applications).Create("/recall-guard/auth", .properties)
}

ClassMethod Start() As %Status
{
    Set password = $System.Util.GetEnviron("IRIS_PASSWORD")
    If $Length(password) < 12 Quit $$$ERROR($$$GeneralError, "Set IRIS_PASSWORD to at least 12 characters in .env.")
    New $Namespace
    Set $Namespace = "%SYS"
    Set properties("Password") = password
    Set sc = ##class(Security.Users).Modify("SuperUser", .properties)
    $$$ThrowOnError(sc)
    Set $Namespace = "RECALLGUARD"
    Set sc = ..ConfigureWeb()
    $$$ThrowOnError(sc)
    Quit ##class(Ens.Director).StartProduction("RecallGuard.Production")
}
}
