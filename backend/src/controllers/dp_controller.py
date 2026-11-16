from src.services import dp_service as service


def budgets(db):
    return service.list_budgets(db)


def set_budget(db, data, user):
    return service.set_budget(db, data, user)


def releases(db, study_id):
    return service.list_releases(db, study_id)


def names(db):
    return service.list_release_names(db)


def create(db, data, user):
    return service.create_release(db, data, user)


def detail(db, id):
    return service.get_release(db, id)


def retry(db, id):
    return service.retry_release(db, id)


def export(db, id):
    return service.export_release(db, id)
