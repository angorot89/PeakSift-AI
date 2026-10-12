import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Project, ProjectStatus, User


def make_user(email: str = "creator@example.com") -> User:
    return User(email=email, password_hash="not-a-real-hash")


def test_user_gets_uuid_and_timezone_aware_created_at(db_session: Session):
    user = make_user()
    db_session.add(user)
    db_session.commit()

    assert isinstance(user.id, uuid.UUID)
    assert user.created_at is not None
    assert user.created_at.tzinfo is not None


def test_email_must_be_unique(db_session: Session):
    db_session.add(make_user("dupe@example.com"))
    db_session.commit()

    db_session.add(make_user("dupe@example.com"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_project_belongs_to_user_and_defaults_to_created(db_session: Session):
    user = make_user()
    project = Project(name="Stream highlights", owner=user)
    db_session.add(user)
    db_session.commit()

    assert project.user_id == user.id
    assert project.status == ProjectStatus.CREATED == "created"
    assert project.created_at.tzinfo is not None
    assert project.updated_at is not None
    assert project.updated_at >= project.created_at


def test_user_projects_relationship(db_session: Session):
    user = make_user()
    user.projects.extend([Project(name="First"), Project(name="Second")])
    db_session.add(user)
    db_session.commit()
    db_session.expire_all()

    reloaded = db_session.scalar(select(User).where(User.id == user.id))
    assert reloaded is not None
    assert sorted(p.name for p in reloaded.projects) == ["First", "Second"]
    assert all(p.owner is reloaded for p in reloaded.projects)


def test_deleting_user_deletes_their_projects(db_session: Session):
    user = make_user()
    user.projects.append(Project(name="Orphan candidate"))
    db_session.add(user)
    db_session.commit()
    project_id = user.projects[0].id

    db_session.delete(user)
    db_session.commit()

    assert db_session.get(Project, project_id) is None
