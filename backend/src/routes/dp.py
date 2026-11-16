from fastapi import APIRouter, Depends
from fastapi.responses import Response

from src.config.database import get_db
from src.controllers import dp_controller as controller
from src.schemas.dp import DpBudgetInput, DpBudgetOut, DpReleaseInput, DpReleaseOut
from src.utils.auth import admin, current_user, editor

router = APIRouter(prefix='/dp', tags=['dp'])


@router.get('/budgets', response_model=list[DpBudgetOut])
def budgets(db=Depends(get_db), user=Depends(current_user)):
    return controller.budgets(db)


@router.post('/budgets', response_model=DpBudgetOut)
def set_budget(data: DpBudgetInput, db=Depends(get_db), user=Depends(admin)):
    return controller.set_budget(db, data, user)


@router.get('/releases', response_model=list[DpReleaseOut])
def releases(study_id: int | None = None, db=Depends(get_db), user=Depends(current_user)):
    return controller.releases(db, study_id)


@router.get('/names')
def names(db=Depends(get_db), user=Depends(current_user)):
    return controller.names(db)


@router.post('/releases', response_model=DpReleaseOut, status_code=201)
def create(data: DpReleaseInput, db=Depends(get_db), user=Depends(editor)):
    return controller.create(db, data, user)


@router.get('/releases/{id}', response_model=DpReleaseOut)
def detail(id: int, db=Depends(get_db), user=Depends(current_user)):
    return controller.detail(db, id)


@router.post('/releases/{id}/retry', response_model=DpReleaseOut)
def retry(id: int, db=Depends(get_db), user=Depends(editor)):
    return controller.retry(db, id)


@router.get('/releases/{id}/export')
def export(id: int, db=Depends(get_db), user=Depends(current_user)):
    return Response(controller.export(db, id), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="dp-publication-{id}.csv"'})
