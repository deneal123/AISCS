from __future__ import annotations

# ruff: noqa: E501 - инлайн-стили писем длинные по своей природе; перенос внутри HTML
# ломает вёрстку почтовых клиентов.

"""Письма о состоянии аккаунта и реактивации.

Формулировки — намеренно сдержанные. «У вас сгорают кредиты, скорее вернитесь!» это уже
реклама с давлением; мы сообщаем факт и даём ссылку. Разница не косметическая: сервисные
письма шлём всем, и они не должны выглядеть как то, на что нужно отдельное согласие.

В КАЖДОМ письме — ссылка отписки. Не только потому что так требует закон, а потому что без
неё единственный способ прекратить рассылку — пометить нас спамом.
"""

_ACCENT = "#2D5BFF"


def _wrap(
    title: str, body_html: str, cta_text: str, cta_url: str, unsubscribe_url: str | None
) -> str:
    # Транзакционные письма (подтверждение оплаты) ссылки отписки не несут: от чека за
    # деньги нельзя «отписаться». unsubscribe_url=None → нейтральный служебный футер.
    if unsubscribe_url:
        footer = (
            "Это письмо отправлено на адрес, указанный при регистрации в GPTHub.<br>"
            f'<a href="{unsubscribe_url}" style="color:#7d879b;">Отписаться от писем</a>'
        )
    else:
        footer = "Это служебное письмо об операции в вашем аккаунте GPTHub."
    return f"""\
<!DOCTYPE html>
<html lang="ru"><body style="margin:0;padding:0;background:#0b0d12;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#0b0d12;padding:32px 16px;">
  <tr><td align="center">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:#12151d;border:1px solid #1e2430;border-radius:14px;">
      <tr><td style="padding:28px 28px 8px 28px;">
        <div style="font:600 13px/1.4 -apple-system,Segoe UI,Roboto,sans-serif;color:{_ACCENT};letter-spacing:.04em;text-transform:uppercase;">GPTHub</div>
        <h1 style="margin:12px 0 0 0;font:600 20px/1.35 -apple-system,Segoe UI,Roboto,sans-serif;color:#e8ecf4;">{title}</h1>
      </td></tr>
      <tr><td style="padding:12px 28px 4px 28px;font:400 15px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;color:#a7b0c0;">
        {body_html}
      </td></tr>
      <tr><td style="padding:20px 28px 28px 28px;">
        <a href="{cta_url}" style="display:inline-block;padding:11px 20px;background:{_ACCENT};color:#fff;text-decoration:none;border-radius:8px;font:600 14px/1 -apple-system,Segoe UI,Roboto,sans-serif;">{cta_text}</a>
      </td></tr>
      <tr><td style="padding:0 28px 24px 28px;border-top:1px solid #1e2430;">
        <p style="margin:16px 0 0 0;font:400 12px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;color:#5d6779;">
          {footer}
        </p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""


def _text(title: str, body: str, cta_text: str, cta_url: str, unsubscribe_url: str | None) -> str:
    tail = f"Отписаться от писем: {unsubscribe_url}\n" if unsubscribe_url else ""
    return f"{title}\n\n{body}\n\n{cta_text}: {cta_url}\n\n— Команда GPTHub · InCellCorp\n{tail}"


def subscription_expiring(*, days_left: int, plan: str, app_url: str, unsubscribe_url: str):
    title = "Подписка скоро закончится"
    body = (
        f"Тариф «{plan}» действует ещё {days_left} "
        f"{'день' if days_left == 1 else 'дня' if days_left < 5 else 'дней'}. "
        "После этого доступ переключится на бесплатный тариф."
    )
    url = f"{app_url}/profile"
    return (
        title,
        _wrap(title, f"<p style='margin:0;'>{body}</p>", "Продлить подписку", url, unsubscribe_url),
        _text(title, body, "Продлить подписку", url, unsubscribe_url),
    )


def low_credits(*, remaining: int, app_url: str, unsubscribe_url: str):
    title = "Кредиты почти закончились"
    body = (
        f"На балансе осталось {remaining:,} кредитов".replace(",", " ")
        + ". Когда они закончатся, запросы перестанут обрабатываться."
    )
    url = f"{app_url}/profile"
    return (
        title,
        _wrap(title, f"<p style='margin:0;'>{body}</p>", "Пополнить баланс", url, unsubscribe_url),
        _text(title, body, "Пополнить баланс", url, unsubscribe_url),
    )


def payment_failed(*, amount_rub: float | None, app_url: str, unsubscribe_url: str):
    title = "Платёж не прошёл"
    # Суммы в таблице платежей нет — она выводится из прайса. Не нашли → пишем письмо БЕЗ
    # суммы: выдумывать цифру в письме о деньгах нельзя.
    amount = f" на сумму {amount_rub:.0f} ₽" if amount_rub else ""
    body = (
        f"Оплата{amount} была отклонена. "
        "Подписка не продлена — проверьте данные карты и попробуйте снова."
    )
    url = f"{app_url}/profile"
    return (
        title,
        _wrap(title, f"<p style='margin:0;'>{body}</p>", "Повторить оплату", url, unsubscribe_url),
        _text(title, body, "Повторить оплату", url, unsubscribe_url),
    )


def payment_succeeded(
    *,
    credits: int,
    amount_rub: float,
    plan: str | None = None,
    app_url: str,
    receipt_by_email: bool = False,
):
    """Транзакционное подтверждение успешной оплаты (шлётся всегда, без отписки).

    ``plan`` задан для подписки (иначе — докупка кредитов). ``receipt_by_email`` —
    добавить строку про фискальный чек, если ЮKassa шлёт его отдельным письмом.
    """
    title = "Оплата прошла"
    credits_str = f"{credits:,}".replace(",", " ")
    amount_str = f"{amount_rub:.0f}"
    if plan:
        lead = f"Подписка «{plan}» активна. Начислено {credits_str} кредитов."
    else:
        lead = f"На баланс начислено {credits_str} кредитов."
    receipt_line = (
        "<br><br>Фискальный чек придёт отдельным письмом от ЮKassa." if receipt_by_email else ""
    )
    body_html = f"<p style='margin:0;'>Спасибо за оплату{f' на сумму {amount_str} ₽' if amount_rub else ''}. {lead}{receipt_line}</p>"
    body_text = f"Спасибо за оплату{f' на сумму {amount_str} ₽' if amount_rub else ''}. {lead}" + (
        " Фискальный чек придёт отдельным письмом от ЮKassa." if receipt_by_email else ""
    )
    url = f"{app_url}/chat"
    return (
        title,
        _wrap(title, body_html, "Перейти в чат", url, None),
        _text(title, body_text, "Перейти в чат", url, None),
    )


def reactivation(*, credits: int, days_idle: int, app_url: str, unsubscribe_url: str):
    """Единственное МАРКЕТИНГОВОЕ письмо — уходит только при marketing_consent_at."""
    title = "Ваши кредиты на месте"
    body = (
        f"Вы не заходили {days_idle} дней, а на балансе всё ещё {credits:,} кредитов".replace(
            ",", " "
        )
        + ". Они никуда не денутся — просто напоминаем, что ими можно пользоваться."
    )
    url = f"{app_url}/chat"
    return (
        title,
        _wrap(title, f"<p style='margin:0;'>{body}</p>", "Открыть чат", url, unsubscribe_url),
        _text(title, body, "Открыть чат", url, unsubscribe_url),
    )
