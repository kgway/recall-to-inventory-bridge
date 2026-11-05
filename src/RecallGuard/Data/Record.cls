/// SPDX-License-Identifier: MPL-2.0
Include %occStatus

Class RecallGuard.Data.Record Extends %Persistent
{
Property RecordKey As %String(MAXLEN = 240) [ Required ];
Property Kind As %String(MAXLEN = 40) [ Required ];
Property Payload As %Stream.GlobalCharacter;
Index RecordKeyIndex On RecordKey [ IdKey ];
Index KindIndex On Kind;

ClassMethod ReadJSON(key As %String) As %String
{
    Set record = ..%OpenId(key)
    If '$IsObject(record) Quit ""
    Do record.Payload.Rewind()
    Set result = ""
    While 'record.Payload.AtEnd { Set result = result_record.Payload.Read(32000) }
    Quit result
}

ClassMethod WriteJSON(key As %String, kind As %String, payload As %String) As %Status
{
    Set record = ..%OpenId(key)
    If '$IsObject(record) {
        Set record = ..%New()
        Set record.RecordKey = key
        Set record.Kind = kind
    }
    Set record.Payload = ##class(%Stream.GlobalCharacter).%New()
    Do record.Payload.Write(payload)
    Quit record.%Save()
}

ClassMethod ListKeys(kind As %String) As %String
{
    Set statement = ##class(%SQL.Statement).%New()
    Set sc = statement.%Prepare("SELECT RecordKey FROM RecallGuard_Data.Record WHERE Kind = ? ORDER BY RecordKey")
    If $$$ISERR(sc) Throw ##class(%Exception.StatusException).CreateFromStatus(sc)
    Set rows = statement.%Execute(kind), result = []
    While rows.%Next() { Do result.%Push(rows.%Get("RecordKey")) }
    Quit result.%ToJSON()
}
}
