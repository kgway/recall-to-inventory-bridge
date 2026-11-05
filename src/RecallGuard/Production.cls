/// SPDX-License-Identifier: MPL-2.0
Class RecallGuard.Production Extends Ens.Production
{
XData ProductionDefinition
{
<Production Name="RecallGuard.Production" TestingEnabled="true" LogGeneralTraceEvents="true">
    <Description>Read-only inventory snapshots, recurring CPSC audits and evidence-backed AI Hub advisories.</Description>
    <Item Name="API" Category="Input" ClassName="RecallGuard.Service.API" PoolSize="0" Enabled="true" Foreground="false" Comment="REST gateway to Production" LogTraceEvents="true"/>
    <Item Name="CPSCPoller" Category="Input" ClassName="RecallGuard.Service.CPSC" PoolSize="1" Enabled="true" Foreground="false" LogTraceEvents="true">
        <Setting Target="Adapter" Name="CallInterval">60</Setting>
        <Setting Target="Adapter" Name="PollEnabled">0</Setting>
    </Item>
    <Item Name="Triage" Category="Workflow" ClassName="RecallGuard.Process.Triage" PoolSize="1" Enabled="true" Foreground="false" LogTraceEvents="true"/>
    <Item Name="Agent" Category="Decision" ClassName="RecallGuard.Operation.Agent" PoolSize="1" Enabled="true" Foreground="false" LogTraceEvents="true"/>
    <Item Name="Hold" Category="Action" ClassName="RecallGuard.Operation.Hold" PoolSize="1" Enabled="true" Foreground="false" LogTraceEvents="true"/>
    <Item Name="Retailer" Category="Action" ClassName="RecallGuard.Operation.Retailer" PoolSize="1" Enabled="true" Foreground="false" LogTraceEvents="true"/>
    <Item Name="CPSCRefresh" Category="Input" ClassName="RecallGuard.Operation.CPSC" PoolSize="1" Enabled="true" Foreground="false" LogTraceEvents="true"/>
</Production>
}
}
