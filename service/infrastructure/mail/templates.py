from __future__ import annotations

# ruff: noqa: E501 - inline-стили писем длинные по своей природе; переносить их
# внутри HTML-строк ломает читаемость и рискует сломать вёрстку почтовых клиентов.

# Брендовое письмо с кодом подтверждения (InCellCorp / GPTHub, синий #2D5BFF).
# Table-вёрстка + инлайновые стили ради совместимости с почтовыми клиентами
# (JS и внешние ресурсы в письмах недоступны). Код выводится КАК ЕСТЬ (без
# литеральных пробелов) — визуальный отступ даёт letter-spacing, поэтому
# копирование/вставка даёт чистые цифры.

_SUBJECTS = {
    "register": "Подтверждение регистрации в GPTHub",
    "login": "Код для входа в GPTHub",
}
_INTRO = {
    "register": "Спасибо за регистрацию в GPTHub. Введите код ниже, чтобы подтвердить почту.",
    "login": "Используйте этот код, чтобы завершить вход в GPTHub.",
}


def _subject(purpose: str) -> str:
    return _SUBJECTS.get(purpose, "Код подтверждения GPTHub")


def _intro(purpose: str) -> str:
    return _INTRO.get(purpose, "Ваш код подтверждения GPTHub.")


def build_verification_email(code: str, purpose: str, ttl_minutes: int) -> tuple[str, str, str]:
    """Вернуть (subject, html, text) письма с кодом подтверждения."""
    subject = _subject(purpose)
    intro = _intro(purpose)

    text = (
        f"{intro}\n\n"
        f"Код подтверждения: {code}\n\n"
        f"Код действует {ttl_minutes} мин. "
        f"Если вы не запрашивали это письмо — просто проигнорируйте его.\n\n"
        f"— Команда GPTHub · InCellCorp"
    )

    # Скрытый preheader — превью в списке входящих.
    preheader = f"Ваш код подтверждения: {code}"

    html = f"""\
<!doctype html>
<html lang="ru">
  <head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
  <body style="margin:0;padding:0;background:#05060b;">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:#05060b;font-size:1px;line-height:1px;">{preheader}</div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background:#05060b;padding:36px 12px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
                 style="max-width:464px;background:#0e111b;border:1px solid rgba(140,160,255,0.16);
                        border-radius:20px;overflow:hidden;">
            <!-- иридесцентная линия-акцент у верхней кромки -->
            <tr><td style="height:3px;line-height:3px;font-size:3px;
                       background:linear-gradient(90deg,#3DD9BC,#5E7BFF,#B45CFF,#FF7AD9);">&nbsp;</td></tr>

            <!-- лого-локап -->
            <tr>
              <td style="padding:28px 32px 6px;">
                <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <!-- Знак повторяет public/gpthub-logo.svg (тёмный квадрат + «GH» +
                         синяя точка). SVG/внешние картинки в письмах ненадёжны
                         (Gmail/Outlook их режут), поэтому знак собран табличной
                         вёрсткой — рендерится одинаково везде, без загрузки картинок. -->
                    <td style="width:38px;height:38px;background:#101012;
                               background-image:linear-gradient(135deg,#1b1b1b,#0a0a0a);
                               border:1px solid rgba(255,255,255,0.22);border-radius:10px;">
                      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="38" height="38" style="width:38px;height:38px;">
                        <tr><td align="right" valign="top" style="padding:6px 6px 0 0;line-height:0;font-size:0;">
                          <span style="display:inline-block;width:7px;height:7px;background:#2D5BFF;border-radius:50%;"></span>
                        </td></tr>
                        <tr><td align="center" valign="top" style="padding:0 0 8px;">
                          <span style="color:#ffffff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;font-size:15px;font-weight:800;letter-spacing:0.3px;line-height:1;">GH</span>
                        </td></tr>
                      </table>
                    </td>
                    <td style="padding-left:12px;" valign="middle">
                      <div style="color:#ffffff;font-size:17px;font-weight:800;letter-spacing:-0.01em;line-height:1;">GPTHub</div>
                      <div style="color:#6685FF;font-size:9px;font-weight:700;letter-spacing:0.18em;text-transform:uppercase;padding-top:3px;">AI Workspace</div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- интро -->
            <tr>
              <td style="padding:18px 32px 0;color:#c7cbd6;font-size:15px;line-height:1.6;">{intro}</td>
            </tr>

            <!-- код -->
            <tr>
              <td style="padding:20px 32px 6px;">
                <div style="color:#6685FF;font-size:10px;font-weight:700;letter-spacing:0.16em;
                            text-transform:uppercase;padding-bottom:8px;">Код подтверждения</div>
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td align="center" style="background:#05060b;border:1px solid rgba(45,91,255,0.38);
                               border-radius:14px;padding:18px 12px;">
                      <span style="display:inline-block;color:#ffffff;font-size:34px;font-weight:700;
                                   letter-spacing:12px;text-indent:12px;
                                   font-family:'SFMono-Regular',ui-monospace,Menlo,Consolas,'Courier New',monospace;">{code}</span>
                    </td>
                  </tr>
                </table>
                <div style="color:#8a90a2;font-size:12px;line-height:1.5;padding-top:10px;text-align:center;">
                  Выделите код и скопируйте — на телефоне нажмите и удерживайте.
                </div>
              </td>
            </tr>

            <!-- TTL -->
            <tr>
              <td style="padding:12px 32px 4px;color:#8a90a2;font-size:13px;line-height:1.6;">
                Код действует {ttl_minutes} мин. Если вы не запрашивали это письмо — просто проигнорируйте его.
              </td>
            </tr>

            <!-- футер -->
            <tr>
              <td style="padding:20px 32px 26px;">
                <div style="border-top:1px solid rgba(255,255,255,0.07);padding-top:16px;
                            color:#5c6376;font-size:12px;line-height:1.5;">
                  GPTHub — продукт InCellCorp. Это письмо отправлено автоматически, не отвечайте на него.
                </div>
              </td>
            </tr>
          </table>

          <div style="max-width:464px;color:#3a3f52;font-size:11px;padding:16px 8px 0;text-align:center;">
            © InCellCorp
          </div>
        </td>
      </tr>
    </table>
  </body>
</html>"""

    return subject, html, text
