from service.models.profile_models import UserProfileLogic
from service.services.profile.application.dto import ProfileOverviewResult


def to_profile_overview_result(profile: UserProfileLogic) -> ProfileOverviewResult:
    return ProfileOverviewResult(
        id=profile.id,
        email=profile.email,
        first_name=profile.first_name,
        timezone=profile.timezone,
        avatar_url=profile.avatar_url,
        # Метки времени → булевы. Отписка гасит всё, поэтому реклама «включена» только
        # когда согласие есть И человек не отписан: иначе тумблер обещал бы письма,
        # которых рассылка всё равно не отправит.
        marketing_emails=(
            profile.marketing_consent_at is not None and profile.unsubscribed_at is None
        ),
        service_emails=profile.unsubscribed_at is None,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )
