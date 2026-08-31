import asyncio, os, json
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from lib.statistical_engine.peer_cohort import compute_peer_cohort

async def main():
    client = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = client[os.environ['DB_NAME']]
    project = await db.projects.find_one({'_id': ObjectId('69e7c10013506cc459fcd046')})
    result = await compute_peer_cohort(db, project)
    print(json.dumps(result, default=str, indent=2))

asyncio.run(main())
