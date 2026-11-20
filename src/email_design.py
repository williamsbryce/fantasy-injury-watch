"""Readable, mobile-first Fantasy Injury Watch emails.

Uses table layout and inline CSS for Gmail, Outlook, and iPhone mail.
All dynamic copy is escaped. Text alternative is always sent too.
"""
from datetime import datetime, timezone
from html import escape
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Regina")
DASHBOARD_URL = "https://williamsbryce.github.io/fantasy-injury-watch/"


def _safe(value):
    return escape(str(value if value is not None else ""), quote=True)


def _local_time(value):
    try:
        dt = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return "Time unavailable"
        local = dt.astimezone(TZ)
        hour = local.hour % 12 or 12
        return f"{local.strftime('%a, %b')} {local.day}, {local.year} at {hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'} SK"
    except (ValueError, TypeError, OverflowError):
        return "Time unavailable"


def _roles(document):
    """Group actual injury items, not the complete fantasy roster."""
    groups = {"starter": [], "bench": [], "unknown": []}
    for league in document.get("leagues", []):
        for player in league.get("alerts", []):
            if not isinstance(player, dict):
                continue
            role = str(player.get("lineup_role", "unknown"))
            groups[role if role in groups else "unknown"].append(player)
    for group in groups.values():
        group.sort(key=lambda a: (
            0 if a.get("group") == "action" else 1,
            str(a.get("name", "")).casefold()
        ))
    return groups


def _lineup_notes(document):
    notes = []
    for league in document.get("leagues", []):
        lineup = league.get("lineup") or {}
        if lineup.get("warning"):
            notes.append(str(lineup["warning"]))
        elif lineup.get("state") == "submitted":
            notes.append("17 selected starters confirmed by MFL")
        elif lineup.get("state") == "unknown":
            notes.append("Starting lineup could not be verified")
    return notes


def _body_title(title):
    return str(title or "Injury summary")


def email_text(document, title):
    groups = _roles(document)
    lines = [
        "BAWs Fantasy Injury Watch",
        _body_title(title),
        "",
        "Last injury sync: " + _local_time(document.get("synced_at")),
    ]
    for league in document.get("leagues", []):
        lines.append(f"{league.get('name', 'MFL League')} | {league.get('players_checked', 0)} rostered players checked")
    for note in _lineup_notes(document):
        lines.append(note)
    lines.append("")
    labels = [
        ("starter", "INJURED STARTERS"),
        ("bench", "INJURED BENCH PLAYERS"),
        ("unknown", "LINEUP POSITION UNVERIFIED"),
    ]
    total = sum(len(rows) for rows in groups.values())
    if total == 0:
        lines.append("No active injury designations reported in the latest MFL sync.")
        lines.append("")
    for key, heading in labels:
        if not groups[key]:
            continue
        lines.append(f"{heading} ({len(groups[key])})")
        for player in groups[key]:
            team = " · ".join(str(v) for v in
                            (player.get("position"), player.get("nfl_team")) if v)
            details = str(player.get("details") or "").strip()
            line = (f"- {player.get('name', 'Unknown player')}"
                    + (f" ({team})" if team else "")
                    + f" | {player.get('status', 'Unspecified')}"
                    + (f" | {details}" if details else ""))
            lines.append(line)
        lines.append("")
    lines.extend([
        f"{total} reported injury item(s).",
        "View dashboard: " + DASHBOARD_URL,
        "",
        "Source: MyFantasyLeague. Designations are not official NFL inactive confirmations.",
    ])
    return "\n".join(lines)


def _player_row(player):
    action = player.get("group") == "action"
    status_bg, status_text, status_border = (
        ("#FDECEC", "#9A2833", "#F3CCD0") if action
        else ("#FFF5E5", "#8D5E21", "#F3E1C4")
    )
    name = _safe(player.get("name", "Unknown player"))
    meta = " · ".join(_safe(x) for x in
                      (player.get("position"), player.get("nfl_team")) if x)
    details = _safe(player.get("details") or "")
    status = _safe(player.get("status") or "Unspecified")
    return (
        '<tr><td style="padding:13px 0;border-bottom:1px solid #E8EDF2;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        '<tr><td valign="top" style="padding:0 10px 0 0;">'
        f'<div style="font-family:Arial,sans-serif;color:#1D2938;font-size:15px;font-weight:bold;line-height:20px;">{name}</div>'
        f'<div style="font-family:Arial,sans-serif;color:#687587;font-size:12px;line-height:19px;margin-top:2px;">{meta}</div>'
        '</td><td width="105" align="right" valign="top">'
        f'<span style="display:inline-block;padding:4px 7px;background-color:{status_bg};'
        f'border:1px solid {status_border};border-radius:4px;color:{status_text};'
        f'font-family:Arial,sans-serif;font-size:11px;font-weight:bold;line-height:15px;">{status}</span>'
        '</td></tr>'
        + (f'<tr><td colspan="2" style="padding-top:6px;font-family:Arial,sans-serif;'
           f'font-size:13px;line-height:19px;color:#4B586B;">{details}</td></tr>' if details else "")
        + '</table></td></tr>'
    )


def _section(heading, items):
    if not items:
        return ""
    rows = "".join(_player_row(a) for a in items)
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="margin-top:23px;">'
        '<tr><td style="padding-bottom:3px;font-family:Arial,sans-serif;'
        'font-size:16px;font-weight:bold;line-height:22px;color:#1D2938;">'
        + _safe(heading)
        + f' <span style="font-size:12px;font-weight:normal;color:#687587;">({len(items)})</span>'
        + '</td></tr><tr><td>'
        + '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        + rows + '</table></td></tr></table>'
    )


def _shell(heading, subtitle, content, footer):
    return (
        '<!doctype html><html lang="en"><head>'
        '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light">'
        '<title>BAWs Fantasy Injury Watch</title>'
        '</head><body style="margin:0;padding:0;background-color:#F3F5F8;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="background-color:#F3F5F8;">'
        '<tr><td align="center" style="padding:20px 10px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="max-width:600px;background-color:#FFFFFF;border:1px solid #E2E7EE;">'
        '<tr><td bgcolor="#182435" style="background-color:#182435;padding:20px 24px;">'
        '<div style="font-family:Arial,sans-serif;font-size:12px;line-height:17px;letter-spacing:1px;'
        'font-weight:bold;color:#AEBBD0;">BAW · INJURY WATCH</div>'
        f'<div style="font-family:Arial,sans-serif;font-size:22px;font-weight:bold;line-height:28px;color:#FFFFFF;margin-top:5px;">{_safe(heading)}</div>'
        '</td></tr><tr><td style="padding:21px 24px 18px;">'
        f'<div style="font-family:Arial,sans-serif;font-size:12px;line-height:19px;color:#667487;">{_safe(subtitle)}</div>'
        + content +
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-top:24px;">'
        '<tr><td bgcolor="#1E3A58" style="background-color:#1E3A58;border-radius:5px;">'
        f'<a href="{DASHBOARD_URL}" style="display:inline-block;padding:12px 18px;'
        'font-family:Arial,sans-serif;color:#FFFFFF;text-decoration:none;font-size:13px;'
        'font-weight:bold;line-height:19px;">Open injury dashboard</a></td></tr></table>'
        '</td></tr>'
        '<tr><td style="padding:14px 24px 20px;border-top:1px solid #E5E9EF;'
        'font-family:Arial,sans-serif;font-size:11px;line-height:17px;color:#708096;">'
        + _safe(footer) +
        '</td></tr></table></td></tr></table>'
        '</body></html>'
    )


def email_html(document, title):
    groups = _roles(document)
    total = sum(len(rows) for rows in groups.values())
    leagues = document.get("leagues", [])
    subtitle = "Last successful injury sync: " + _local_time(document.get("synced_at"))
    content = ""
    if leagues:
        for league in leagues:
            content += (
                '<div style="font-family:Arial,sans-serif;font-size:13px;line-height:21px;'
                'color:#334155;margin-top:10px;">'
                f'<strong>{_safe(league.get("name", "MFL League"))}</strong>'
                f' &nbsp;·&nbsp; {_safe(league.get("players_checked", 0))} rostered players checked'
                '</div>'
            )
    warnings = [(l.get("lineup") or {}).get("warning") for l in leagues]
    for warning in warnings:
        if warning:
            content += (
                '<div style="padding:11px 13px;margin-top:13px;background-color:#FFF7E8;'
                'border:1px solid #ECD9B7;color:#80521B;font-family:Arial,sans-serif;'
                f'font-size:13px;line-height:20px;">{_safe(warning)}</div>'
            )
    if total:
        stats = []
        if groups["starter"]:
            stats.append(f'{len(groups["starter"])} injured starter(s)')
        if groups["bench"]:
            stats.append(f'{len(groups["bench"])} injured bench player(s)')
        if groups["unknown"]:
            stats.append(f'{len(groups["unknown"])} with unverified lineup position')
        content += (
            '<div style="margin-top:14px;font-family:Arial,sans-serif;'
            'font-size:13px;font-weight:bold;line-height:20px;color:#324256;">'
            + _safe(" · ".join(stats)) + '</div>'
        )
        content += _section("Starting lineup", groups["starter"])
        content += _section("Bench", groups["bench"])
        content += _section("Lineup position unverified", groups["unknown"])
    else:
        content += (
            '<p style="font-family:Arial,sans-serif;font-size:14px;line-height:21px;'
            'color:#35465B;margin:18px 0 0;">'
            'No active injury designations reported in the latest MFL sync.</p>'
        )
    return _shell(
        _body_title(title), subtitle, content,
        "Injury designations are reported by MyFantasyLeague and are not "
        "official NFL inactive confirmations. Player status may change after this email."
    )


def message_html(title, message):
    """Use the same readable style for non-digest lineup warnings."""
    paragraphs = [p.strip() for p in str(message).splitlines() if p.strip()]
    content = "".join(
        '<p style="font-family:Arial,sans-serif;font-size:14px;line-height:22px;'
        f'color:#35465B;margin:14px 0 0;overflow-wrap:anywhere;">{_safe(p)}</p>'
        for p in paragraphs
    )
    return _shell(title, "Action may be required before kickoff.", content,
                  "Confirm your starting lineup in MyFantasyLeague before the applicable game.")
