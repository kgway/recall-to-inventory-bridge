/// SPDX-License-Identifier: MPL-2.0
Include %occStatus

/// Loaded by IPM's root preload phase before the application resources.
/// Installs into one dedicated namespace without changing an account password.
Class RecallGuard.Package Extends %RegisteredObject
{
ClassMethod Preflight() As %Status
{
    If $Namespace '= "RECALLGUARD" Quit $$$ERROR($$$GeneralError, "Install into a dedicated Interoperability-enabled RECALLGUARD namespace.")
    If '##class(%Dictionary.CompiledClass).%ExistsId("%AI.Agent") Quit $$$ERROR($$$GeneralError, "An actual IRIS AI Hub build is required; plain IRIS is not sufficient.")
    If ##class(Ens.Director).IsProductionRunning() Quit $$$ERROR($$$GeneralError, "Stop the Production before installing or changing this package.")
    New $Namespace
    Set $Namespace = "%SYS"
    Set guard = $$$OK
    For app = "/recall-guard", "/recall-guard/auth" {
        If ##class(Security.Applications).Exists(app) {
            Kill properties
            Set sc = ##class(Security.Applications).Get(app, .properties)
            $$$ThrowOnError(sc)
            If $Get(properties("NameSpace")) '= "RECALLGUARD" Set guard = $$$ERROR($$$GeneralError, "A web application at this path belongs to another namespace; it was preserved.")
            If (app = "/recall-guard")&&($Get(properties("DispatchClass")) '= "RecallGuard.Api") Set guard = $$$ERROR($$$GeneralError, "The existing web application has a different dispatch class; it was preserved.")
        }
    }
    Quit guard
}

ClassMethod Configure() As %Status
{
    Set sc = ..Preflight()
    $$$ThrowOnError(sc)
    Set state = ##class(%DynamicObject).%FromJSON($ClassMethod("RecallGuard.Backend", "Call", "state"))
    If 'state.ok Quit $$$ERROR($$$GeneralError, "The installed Embedded Python backend could not be loaded.")
    If state.result.backend '= "intersystems-iris" Quit $$$ERROR($$$GeneralError, "A real IRIS backend was not confirmed.")
    If $Find($ClassMethod("RecallGuard.Backend", "Asset", "index.html"), "<!doctype html>") = 0 Quit $$$ERROR($$$GeneralError, "The installed web assets were not found.")
    Quit $ClassMethod("RecallGuard.Setup", "ConfigureWeb")
}

ClassMethod Start() As %Status
{
    Set sc = ..Configure()
    $$$ThrowOnError(sc)
    Quit ##class(Ens.Director).StartProduction("RecallGuard.Production")
}

/// Refuse ordinary removal when it could take away persisted application records.
ClassMethod BeforeRemove() As %Status
{
    If $Namespace '= "RECALLGUARD" Quit $$$ERROR($$$GeneralError, "Removal must run in the installation namespace.")
    If ##class(Ens.Director).IsProductionRunning() Quit $$$ERROR($$$GeneralError, "Stop the Production before package removal.")
    If ##class(%Dictionary.CompiledClass).%ExistsId("RecallGuard.Data.Record") {
        Set statement = ##class(%SQL.Statement).%New()
        Set sc = statement.%Prepare("SELECT COUNT(*) AS N FROM RecallGuard_Data.Record")
        $$$ThrowOnError(sc)
        Set result = statement.%Execute()
        If result.%Next() {
            If result.%Get("N") > 0 Quit $$$ERROR($$$GeneralError, "Application records exist. Back up and plan data retention before removing this package.")
        }
    }
    Quit $$$OK
}
}
