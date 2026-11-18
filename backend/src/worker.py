import os,time,json,traceback
from pathlib import Path
import redis
from sqlalchemy import select
from .database import Session
from .models import Swatch
from .atlas import calculate_atlas
from .suggestion_service import QUEUE_KEY,compute
queue=redis.Redis.from_url(os.getenv('REDIS_URL','redis://redis:6379/0'),decode_responses=True)

def atlas_job(jobid):
    with Session() as db:
        swatches=db.scalars(select(Swatch).where(Swatch.measured==True)).all()
        result=calculate_atlas([{'id':s.id,'lot':s.lot,'recipe_id':s.recipe_id,'spectrum':s.spectrum} for s in swatches])
    Path('/artifacts').mkdir(exist_ok=True)
    Path(f'/artifacts/{jobid}.json').write_text(json.dumps(result))
    queue.set('atlas:result:'+jobid,json.dumps({'state':'done','result':result}),ex=86400)

def suggestion_job(key):
    with Session() as db:
        compute(db,int(key))

while True:
    Path('/tmp/worker-heartbeat').touch()
    job=queue.blpop(['atlas:queue',QUEUE_KEY],timeout=3)
    if not job:continue
    channel,payload=job
    try:
        if channel=='atlas:queue':atlas_job(payload)
        else:suggestion_job(payload)
    except Exception as e:
        if channel=='atlas:queue':
            queue.set('atlas:result:'+payload,json.dumps({'state':'failed','error':str(e)}),ex=86400)
        # Suggestion failures are persisted on the row by suggestion_service.compute,
        # so the operator can retry from the page without duplicating finished work.
        traceback.print_exc()
