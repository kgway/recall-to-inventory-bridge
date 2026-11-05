# SPDX-License-Identifier: MPL-2.0
"""Example ERP/WMS boundary: snapshot input and advisory output, never stock writeback."""
import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from iris_client import IrisClient, IrisCheckError


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iris-build",type=int,choices=(109,154),default=109)
    sub=parser.add_subparsers(dest="command",required=True)
    imp=sub.add_parser("import",help="Preview and atomically import a local UTF-8 snapshot.")
    imp.add_argument("--file",type=Path,required=True)
    imp.add_argument("--source-system",required=True)
    imp.add_argument("--import-id",required=True,help="Stable ID for this capture; reuse it for a retry.")
    imp.add_argument("--mapping",type=Path)
    imp.add_argument("--delimiter",choices=(",",";","tab"),default=",")
    imp.add_argument("--example",action="store_true",help="Explicitly label the input as synthetic example data.")
    imp.add_argument("--preview-only",action="store_true")
    out=sub.add_parser("export",help="Pull advice to a local file; no receiving system is modified.")
    out.add_argument("--format",choices=("json","csv"),default="json")
    out.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    try:
        client=IrisClient(expected_build=args.iris_build)
        client.state()
        if args.command=="import":
            if args.file.stat().st_size>100000:raise ValueError("File exceeds 100,000 bytes.")
            payload={"format":"json" if args.file.suffix.lower()==".json" else "csv",
                     "source_system":args.source_system,"content":args.file.read_text(encoding="utf-8-sig"),
                     "delimiter":"\t" if args.delimiter=="tab" else args.delimiter,
                     "mapping":json.loads(args.mapping.read_text(encoding="utf-8-sig")) if args.mapping else {},
                     "data_classification":"synthetic-example" if args.example else "user-provided"}
            preview=client.request("preview_inventory",payload)
            if not preview["valid"] or args.preview_only:
                print(json.dumps(preview,ensure_ascii=False,indent=2))
                return 0 if preview["valid"] else 1
            result=client.request("import_inventory",payload|{"import_id":args.import_id,
                                  "preview_hash":preview["preview_hash"],"workspace_revision":preview["workspace_revision"]})
            print(json.dumps(result,ensure_ascii=False,indent=2))
        else:
            request=urllib.request.Request("http://127.0.0.1:52773/recall-guard/api/advisories/"+args.format,
                                          headers={"Authorization":client.authorization})
            with client.opener.open(request,timeout=30) as response:raw=response.read(10_000_001)
            if len(raw)>10_000_000:raise ValueError("Export exceeds this evaluation client's 10 MB limit.")
            with args.output.open("xb") as file:file.write(raw)
            print("Advisory file saved. External inventory was not modified.")
        return 0
    except (OSError,ValueError,IrisCheckError,urllib.error.URLError) as error:
        print("Bridge synchronization failed: "+str(error)+" No external inventory write was attempted.",file=sys.stderr)
        return 1


if __name__=="__main__":sys.exit(main())
