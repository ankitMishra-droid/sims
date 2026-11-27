from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies.authorization import BusinessContext, require_permission
from ..schemas.business_schema import OnboardingProgressOut, OnboardingStepSaveRequest
from ..services.onboarding import OnboardingService

router = APIRouter(prefix="/api/onboarding", tags=["Guided Onboarding"])


@router.get("/progress", response_model=OnboardingProgressOut)
def get_onboarding_progress(
    ctx: BusinessContext = Depends(require_permission("onboarding.manage")),
    db: Session = Depends(get_db),
):
    """Fetch persisted guided onboarding progress for the active workspace."""
    return OnboardingService.get_progress(db, ctx.business, ctx.user.id)


@router.post("/step", response_model=OnboardingProgressOut)
def save_onboarding_step(
    payload: OnboardingStepSaveRequest,
    ctx: BusinessContext = Depends(require_permission("onboarding.manage")),
    db: Session = Depends(get_db),
):
    """Validate, persist, skip, or step back through business-type-specific onboarding."""
    return OnboardingService.save_step(db, ctx.business, ctx.user, payload)
