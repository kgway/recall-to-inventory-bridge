# 初回体験：在庫スナップショットから確認業務へ

モデルAPIキーなしで、模擬在庫の取り込みから実CPSC検索・助言出力まで試す手順です。
以下は審査員・開発者が新規導入するときの手順です。109が既定で、Windows start.ps1も同じキーなし環境を起動します。

先に[98秒の実操作デモ](https://www.youtube.com/watch?v=kQNJ_kUx9tA)で流れを確認できます。
英語字幕付きで、最後のAI部分は別途保存した実行結果の閲覧と明記しています。

取込後の **4. Keep checking for changes** では、その場の監査と定期確認を試せます。
APIキーなしでも在庫起点の再検索・選択原文の更新確認・差分履歴まで動きます。
AI評価が残るとPARTIALと表示されます。原文確認だけで回収対象や対象外を確定しません。
自動AIは別の明示設定で、既存の上限を増やさず1周期1回まで。環境停止後は定期確認も止まります。
詳細は[監査の契約](recurring-audit.md)を参照してください。

既存システムの在庫を置き換えず、CSV/JSONのコピーを取り込んでCPSC候補と助言を返す。
このコースはモデルAPIキーを必要としない。実CPSC APIを使うため候補検索にはnetwork接続が必要。
輸入・販売・出荷・既存システムの在庫変更は実行しない。

## 空の109環境を起動する

Docker、Pythonと、InterSystemsから各自が非公開で取得したAI Hub Community
`2027.1.0AI.109.0`が必要。取得したEAP/派生imageは配布しない。

```bash
docker image load -i /path/to/iris-community-2027.1.0AI.109.0-docker.tar.gz
docker image ls
docker tag <loaded-image-name> recall-guard-aihub:2027.1.0AI.109.0
python scripts/init_env.py
python scripts/judge_demo.py start --iris-build 109 --build
```

[アプリ](http://localhost:52773/recall-guard/auth/RecallGuard.Home.cls)を開き、SuperUserと
ローカル.envのIRIS_PASSWORDでログインする。実際のcontainerではモデルキーが空になり、
AGENT_MODE=disabledとなる。既存の.envのkeyやlive設定は書き換えない。

このコースには専用project・data volumeを使う。既存の記録済みデモを取り込んだvolumeに
snapshotを混在させることはできない。やり直し用の自動削除・補充・resetは行わない。
初回buildにはbase image展開サイズ＋2 GiB、既存imageの起動には2 GiB以上のDocker空き容量が必要。
後の起動では--buildを省略できる。ソース更新後は明示的に--buildを使う。

## 5〜10分のコース

1. **Load sample export**を押す。例はDREO、Hatch、Ankerの模擬在庫CSVで、実在庫ではない。
   Source systemとsource record IDを見て、**Preview import**で認識した列と行を確認する。
2. **Import previewed snapshot**を押す。SKU・外部IDの先頭ゼロ、倉庫、ロット、報告数量を保つ。
   sale/shipボタンがないことを確認する。これは参照snapshotで、書込権限を持つ在庫管理画面ではない。
3. **Review search terms**を押す。CPSCへ送る項目・値を読み、**Search CPSC with these terms**を押す。
   少し待つと候補が表示される。検索はAIを呼ばず、部分一致・件数上限による限界も表示する。
4. DREOの候補で**Load official evidence**を選ぶ。公式のAPIと詳細ページを取り込み、Recall evidenceで確認する。
   新規AI評価はdisabledのままなので、未評価を回収対象や対象外と断言しない。
5. **Download advisory JSON**またはCSVを取得する。CANDIDATES_FOUND、外部ID、告知URL、未評価・範囲の情報を
   既存の確認業務へ渡せる。authority=ADVISORY_ONLY、external_inventory_updated=falseを確認する。

候補0件は「安全」ではない。NO_MATCH_IN_SELECTED_NOTICESも選択告知だけの結果。
query失敗や省略、古い在庫版を黙って全件照合済みとして扱わない。

## 受信側の例

既存システムからCSVを出す想定の[CLI例と連携契約](inventory-integration.ja.md)を用意している。
サンプル受信側は取得した助言をlocal review worklistへ変換する。実ERPへの書込connectorではない。
同一import_idの再送、別内容との衝突、更新順序、column mappingもこの契約で確認できる。

## 実AIの結果をキーなしで見る別コース

空インスタンスの**Optional: recorded AI and downstream simulator**を選ぶと、保存済みの実native v6提案を
その場のIRISで再検証できる。これは別のcourseで、snapshot取り込み後には混在できない。
元のCPSC原文・入力版・ReadContext hashを照合し、記録済み提案36件と根拠を確認する。
`RECORDED INVESTIGATION DEMO`の表示と、元のrun/usageを新規推論と区別する。

この別コースのSale/Shipはlocal synthetic consumer simulatorで、対象品を拒否し、許可した模擬取引だけ
模擬数量を消費する。外部在庫は変更しない。製造月の境界、早い製造月、日付不明、部品識別の4ボタンで根拠へ移動できる。
このcourseの受入確認には`verify_recorded_demo.py --iris-build 109`を使う。5新規模擬要求で1模擬unitを消費するため、
実行先を確認し、毎回新しい--output名を使う。これは新しいAI Hub実行を証明する検証ではない。

## 停止

```bash
python scripts/judge_demo.py stop --iris-build 109
```

Codespace使用時はその後Codespaceとport forwardingも停止する。
[build別の検証範囲](build-compatibility.md)と[検証記録](verification.md)を参照。
