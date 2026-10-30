"""READ-ONLY (find only): every schedule record of the Boyland project."""
import json, os, sys, collections
from pymongo import MongoClient
PID = "6a5f63bc147407d3261df2c7"
db = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=15000)[os.environ["DB_NAME"]]
rows = list(db.plan_records.find({"project_id": PID, "record_type": "schedule"}, {"embedding": 0}))
out = [json.loads(json.dumps(r, default=str)) for r in rows]
json.dump(out, open(sys.argv[1], "w"))
print(len(out), collections.Counter(r.get("sheet_number") for r in out).most_common(60))
