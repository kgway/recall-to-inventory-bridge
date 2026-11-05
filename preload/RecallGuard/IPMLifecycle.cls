/// SPDX-License-Identifier: MPL-2.0
Include %occStatus

/// A Clean Invoke runs after resource processors have already seen the phase.
/// Reject removal before those processors can unconfigure the application paths.
Class RecallGuard.IPMLifecycle Extends %IPM.Lifecycle.Module
{
Method OnBeforeResourceProcessing(phase As %String, ByRef parameters) As %Status
{
    If (phase = "Clean")||(phase = "Unconfigure") {
        Quit ##class(RecallGuard.Package).BeforeRemove()
    }
    Quit ##super(phase, .parameters)
}
}
