"""Quick import and smoke-test for all new backend modules. Writes result to check_result.txt"""
import sys, traceback, os

results = []

checks = [
    ("backend.optimizer.chat",     ["chat"]),
    ("backend.green.rapl",         ["measure", "to_dict"]),
    ("backend.green.carbon",       ["estimate", "to_dict"]),
    ("backend.green.pinpoint",     ["analyse", "to_dict"]),
    ("backend.green.energy_viz",   ["record", "get_chart_data", "summary", "clear"]),
]

errors = []
for module, names in checks:
    try:
        mod = __import__(module, fromlist=names)
        for name in names:
            getattr(mod, name)
        results.append(f"  OK   {module}")
    except Exception as e:
        tb = traceback.format_exc()
        results.append(f"  FAIL {module}: {e}")
        errors.append(tb)

all_ok = all(r.startswith("  OK") for r in results)
verdict = "ALL IMPORTS SUCCESSFUL" if all_ok else "SOME IMPORTS FAILED"

output = "\nImport check results:\n" + "\n".join(results) + "\n\n" + verdict + "\n"
if errors:
    output += "\n--- Tracebacks ---\n" + "\n".join(errors)

outfile = os.path.join(os.path.dirname(__file__), "check_result.txt")
with open(outfile, "w") as f:
    f.write(output)

print(output)
sys.exit(0 if all_ok else 1)
