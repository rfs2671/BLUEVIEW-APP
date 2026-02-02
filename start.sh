#!/bin/bash
cd backend
python -m uvicorn server:app --host 0.0.0.0 --port $PORT
```

Push this file to your repo, Railway will auto-redeploy and it should work.

OR create `Procfile` in root:
```
web: cd backend && python -m uvicorn server:app --host 0.0.0.0 --port $PORT
