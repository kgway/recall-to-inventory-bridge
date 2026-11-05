# SPDX-License-Identifier: MPL-2.0
"""Check the real local IRIS backend; does not call an LLM or change inventory."""
import json
import sys

from iris_client import IrisCheckError, IrisClient


def main():
    try:
        state = IrisClient().state()
    except IrisCheckError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps({"backend": state["backend"], "iris_version": state["iris_version"],
                      "ai_hub_agent_class_present": True, "notices": len(state["notices"]),
                      "lots": len(state["lots"]), "agent_runs": len(state["runs"]),
                      "llm_called_by_this_check": False}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
