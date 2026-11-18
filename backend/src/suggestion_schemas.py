from pydantic import BaseModel,Field,ConfigDict,field_validator

class ShadeSuggestionInput(BaseModel):
    model_config=ConfigDict(allow_inf_nan=False)
    complaint_id:int|None=Field(default=None,gt=0)
    target_l:float=Field(ge=0,le=100)
    target_a:float=Field(ge=-128,le=128)
    target_b:float=Field(ge=-128,le=128)
    cap_a:float=Field(gt=0,le=100)
    cap_b:float=Field(gt=0,le=100)
    cap_c:float=Field(gt=0,le=100)
    note:str=Field(default='',max_length=300)
    @field_validator('note')
    @classmethod
    def trim(cls,v):return v.strip()

class ShadeAdoptionInput(BaseModel):
    parent_recipe_id:int=Field(gt=0)
    reason:str=Field(default='',max_length=300)
    @field_validator('reason')
    @classmethod
    def trim(cls,v):return v.strip()
