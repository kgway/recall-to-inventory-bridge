/// SPDX-License-Identifier: MPL-2.0
Class RecallGuard.Message.Request Extends Ens.Request
{
Property Action As %String;
Property Payload As %String(MAXLEN = 1000000);
}
