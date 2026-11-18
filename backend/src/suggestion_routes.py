from fastapi import APIRouter,Depends
from sqlalchemy import select
from .database import session
from .auth import current,editor,admin
from .suggestion_models import ShadeSuggestion,ShadeSuggestionAdoption
from .suggestion_schemas import ShadeSuggestionInput,ShadeAdoptionInput
from . import suggestion_service
router=APIRouter()
@router.get('/shade-suggestions')
def suggestions(user=Depends(current),db=Depends(session)):return db.scalars(select(ShadeSuggestion).order_by(ShadeSuggestion.id.desc())).all()
@router.post('/shade-suggestions')
def create(p:ShadeSuggestionInput,user=Depends(editor),db=Depends(session)):return suggestion_service.create(db,p,user)
@router.post('/shade-suggestions/{key}/retry')
def retry(key:int,user=Depends(editor),db=Depends(session)):return suggestion_service.retry(db,key,user)
@router.post('/shade-suggestions/{key}/adopt')
def adopt(key:int,p:ShadeAdoptionInput,user=Depends(admin),db=Depends(session)):return suggestion_service.adopt(db,key,p,user)
@router.get('/shade-suggestion-adoptions')
def adoptions(user=Depends(current),db=Depends(session)):return db.scalars(select(ShadeSuggestionAdoption).order_by(ShadeSuggestionAdoption.id.desc())).all()
