import os
from datetime import datetime,timedelta
import redis
from sqlalchemy import select,update
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from .models import DyeRecipe,Swatch
from .production_models import RecipeRevision
from .fulfillment_models import ShadeComplaint
from .suggestion_models import ShadeSuggestion,ShadeSuggestionAdoption
from .recipe_service import log
from . import shade_model

queue=redis.Redis.from_url(os.getenv('REDIS_URL','redis://redis:6379/0'),decode_responses=True)
QUEUE_KEY='suggest:queue'
# A worker that dies mid-computation leaves a running row behind. After this
# grace period the operator may retry it; a live worker that later finishes is
# still fenced out by the per-attempt publish guard in compute().
STALE_RUNNING=timedelta(minutes=5)

def _enqueue(db,item):
    key=item.id
    try:
        queue.rpush(QUEUE_KEY,str(key))
    except Exception:
        # The intake snapshot is already committed; surface the queue failure so
        # the operator can retry instead of waiting on an item nobody will pick.
        db.rollback()
        db.execute(update(ShadeSuggestion).where(ShadeSuggestion.id==key)
                   .values(state='failed',error='计算队列暂时不可用，请重试'))
        db.commit()
        raise HTTPException(503,'计算队列暂时不可用，建议已受理，请稍后重试')

def _snapshot(db):
    rows=db.execute(select(Swatch,DyeRecipe).join(DyeRecipe,Swatch.recipe_id==DyeRecipe.id).where(Swatch.measured==True).order_by(Swatch.id)).all()
    samples=[{'group':recipe.code,'lot':swatch.lot,'dye_a':recipe.dye_a,'dye_b':recipe.dye_b,'dye_c':recipe.dye_c,
              'l':swatch.l,'a':swatch.a,'b':swatch.b} for swatch,recipe in rows]
    groups={}
    for sample in samples:groups.setdefault(sample['group'],[]).append(sample['lot'])
    return {'captured_at':datetime.utcnow().isoformat(timespec='seconds'),'samples':samples,
            'groups':[{'group':code,'lots':lots,'count':len(lots)} for code,lots in sorted(groups.items())]}

def get_suggestion(db,key,lock=True):
    item=db.scalar(select(ShadeSuggestion).where(ShadeSuggestion.id==key).with_for_update() if lock else select(ShadeSuggestion).where(ShadeSuggestion.id==key))
    if not item:raise HTTPException(404,'补染建议不存在')
    return item

def create(db,payload,user):
    if payload.complaint_id is not None and not db.get(ShadeComplaint,payload.complaint_id):
        raise HTTPException(404,'关联的色差客诉不存在')
    snapshot=_snapshot(db)
    if len({g['group'] for g in snapshot['groups']})<shade_model.MIN_GROUPS:
        raise HTTPException(409,f'已测量配方组不足 {shade_model.MIN_GROUPS} 组，无法学习浓度关系')
    item=ShadeSuggestion(complaint_id=payload.complaint_id,target_l=payload.target_l,target_a=payload.target_a,target_b=payload.target_b,
                         cap_a=payload.cap_a,cap_b=payload.cap_b,cap_c=payload.cap_c,note=payload.note,requested_by=user.email,
                         training_snapshot=snapshot,training_count=len(snapshot['samples']),group_count=len(snapshot['groups']))
    db.add(item);db.flush();log(db,user,f'受理补染建议 #{item.id} 固定{len(snapshot["samples"])}张染样/{len(snapshot["groups"])}组');db.commit()
    _enqueue(db,item)
    return item

def retry(db,key,user):
    item=get_suggestion(db,key)
    if item.state=='done':raise HTTPException(409,'建议已完成，不重复计算')
    if item.state=='queued':raise HTTPException(409,'建议已在排队，不重复入队')
    if item.state=='running':
        if not item.claimed_at or datetime.utcnow()-item.claimed_at<STALE_RUNNING:
            raise HTTPException(409,'worker 正在计算，请稍后查看；超过五分钟无结果可重试')
    item.state='queued';item.error='';item.claimed_at=None
    log(db,user,f'重试补染建议 #{item.id}');db.commit();_enqueue(db,item);return item

def claim(db,key):
    """Atomically move a queued suggestion to running; completed work is never redone.

    The conditional UPDATE is a single statement, so two workers (or a retried
    queue message) cannot both claim the same row: only one sees rowcount 1.
    The returned attempt number fences the publisher, so an operator retry that
    requeues a stale row cannot be overwritten by the abandoned first attempt.
    """
    claimed=db.execute(update(ShadeSuggestion).where(ShadeSuggestion.id==key,ShadeSuggestion.state=='queued')
                       .values(state='running',attempts=ShadeSuggestion.attempts+1,claimed_at=datetime.utcnow()))
    db.commit()
    if not claimed.rowcount:return None
    item=db.get(ShadeSuggestion,key);db.refresh(item);return item

def compute(db,key):
    item=claim(db,key)
    if not item:return None
    attempt=item.attempts
    try:
        result=shade_model.evaluate(item.training_snapshot['samples'],
                                    {'l':item.target_l,'a':item.target_a,'b':item.target_b},
                                    {'dye_a':item.cap_a,'dye_b':item.cap_b,'dye_c':item.cap_c})
    except Exception as error:
        db.rollback()
        db.execute(update(ShadeSuggestion).where(ShadeSuggestion.id==key,ShadeSuggestion.state=='running',
                                                 ShadeSuggestion.attempts==attempt)
                   .values(state='failed',error=str(error)[:500]))
        db.commit();raise
    # Only the worker holding the current attempt may publish a result; a stale
    # duplicate message cannot overwrite done work or a newer retry's outcome.
    finished=db.execute(update(ShadeSuggestion).where(ShadeSuggestion.id==key,ShadeSuggestion.state=='running',
                                                      ShadeSuggestion.attempts==attempt)
                        .values(result=result,verdict=result['verdict'],state='done',completed_at=datetime.utcnow(),error=''))
    db.commit()
    if not finished.rowcount:return None
    item=db.get(ShadeSuggestion,key);db.refresh(item);return item

def _existing_adoption(db,item):
    return db.scalar(select(ShadeSuggestionAdoption).where(ShadeSuggestionAdoption.suggestion_id==item.id))

def adopt(db,key,payload,user):
    item=get_suggestion(db,key)
    existing=_existing_adoption(db,item)
    if existing:return existing
    if item.state!='done' or item.verdict!='suggested' or not item.result or not item.result.get('prediction'):
        raise HTTPException(409,'仅训练完成且给出浓度的建议可以采纳')
    parent=db.scalar(select(DyeRecipe).where(DyeRecipe.id==payload.parent_recipe_id).with_for_update())
    if not parent:raise HTTPException(404,'父配方不存在')
    if not parent.locked:raise HTTPException(409,'只能采纳为已冻结配方的待审子版')
    if parent.code not in {g['group'] for g in item.training_snapshot['groups']}:
        raise HTTPException(409,'父配方不在该建议的实测训练组内，不能采纳')
    # The child code is derived from the suggestion and parent, so a retry after
    # an interrupted write or a concurrent adoption converges on the same version.
    code=f'{parent.code}-S{item.id:03d}'
    prediction=item.result['prediction']
    try:
        child=db.scalar(select(DyeRecipe).where(DyeRecipe.code==code).with_for_update())
        if child:
            # A previous attempt committed the child but not the adoption row.
            # Reuse that exact version instead of creating a second one.
            revision=db.scalar(select(RecipeRevision).where(RecipeRevision.child_recipe_id==child.id))
            if not revision:raise HTTPException(409,'建议子版编号已存在且无修订记录，请人工核对')
            if revision.parent_recipe_id!=parent.id:raise HTTPException(409,'建议子版已挂到其他父配方，不能重复采纳')
        else:
            child=DyeRecipe(code=code,name=f'{parent.name} · 补染建议#{item.id}',dye_a=prediction['dye_a'],dye_b=prediction['dye_b'],dye_c=prediction['dye_c'],locked=False)
            db.add(child);db.flush()
            snapshot={k:getattr(parent,k) for k in ['code','name','dye_a','dye_b','dye_c','locked']}
            snapshot['suggestion']={'id':item.id,'target':{'l':item.target_l,'a':item.target_a,'b':item.target_b},
                                    'caps':{'dye_a':item.cap_a,'dye_b':item.cap_b,'dye_c':item.cap_c},
                                    'predicted_delta_e':item.result['predicted_delta_e'],'holdout_max_delta_e':(item.result.get('holdout') or {}).get('max_delta_e'),
                                    'prediction':{k:prediction[k] for k in ['dye_a','dye_b','dye_c','predicted_l','predicted_a','predicted_b']}}
            reason=payload.reason or f'采纳补染建议 #{item.id}：{parent.code} 待审子版'
            revision=RecipeRevision(parent_recipe_id=parent.id,child_recipe_id=child.id,reason=reason,parent_snapshot=snapshot)
            db.add(revision);db.flush()
        adoption=ShadeSuggestionAdoption(suggestion_id=item.id,parent_recipe_id=parent.id,child_recipe_id=child.id,revision_id=revision.id,adopted_by=user.email)
        db.add(adoption);log(db,user,f'采纳补染建议 #{item.id} 为 {parent.code} 待审子版 {code}')
        db.commit()
    except IntegrityError:
        # A concurrent caller already wrote the same child/adoption. Both
        # requests must resolve to that one version, so return the stored row.
        db.rollback()
        existing=_existing_adoption(db,item)
        if not existing:raise HTTPException(409,'并发采纳冲突，请刷新后查看同一子版')
        return existing
    return adoption
