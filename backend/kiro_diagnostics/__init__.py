"""KIRO diagnostics: an admin-only user card tab that gathers VPN health data.

The route lives under ``/api/admin`` so Core's admin middleware resolves the
caller's role before the handler runs. The handler only reads: it never
mutates panel users or shop data.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aiohttp import web
from sqlalchemy import text

from bot.app.web.context import get_panel_service, get_session_factory
from bot.plugins.spec import WEB_SCOPE_WEBAPP, Plugin, PluginContext

logger = logging.getLogger(__name__)

PLUGIN_ID = "kiro-diagnostics"
ROUTE = "/api/admin/kiro-diagnostics/users/{ref}"
GIB = 1024**3


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
    return str(value)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _response(data: Any) -> Any:
    """Unwrap Remnawave's ``{"response": ...}`` envelope."""
    if isinstance(data, dict) and not data.get("error") and "response" in data:
        return data["response"]
    return None


async def _load_shop(session_factory: Any, ref: str) -> dict[str, Any] | None:
    column = "minishop_id" if ref.startswith("ms_") else "user_id"
    value: Any = ref if column == "minishop_id" else int(ref)
    async with session_factory() as session:
        user = (
            await session.execute(
                text(
                    "select user_id, minishop_id, telegram_id, username, first_name, "
                    "panel_user_uuid, is_banned, registration_date "
                    f"from users where {column} = :v"
                ),
                {"v": value},
            )
        ).mappings().first()
        if user is None:
            return None
        subscription = (
            await session.execute(
                text(
                    "select subscription_id, tariff_key, is_active, start_date, end_date, "
                    "status_from_panel, traffic_limit_bytes, traffic_used_bytes, is_throttled, "
                    "premium_used_bytes, premium_baseline_bytes, premium_topup_balance_bytes, "
                    "premium_topup_used_bytes, premium_bonus_bytes, premium_is_limited, "
                    "premium_unlimited_override, tariff_managed_squad_uuids, "
                    "hwid_device_limit, extra_hwid_devices, auto_renew_enabled, provider "
                    "from subscriptions where user_id = :u "
                    "order by is_active desc, end_date desc nulls last limit 1"
                ),
                {"u": user["user_id"]},
            )
        ).mappings().first()
        payments = (
            await session.execute(
                text(
                    "select payment_id, provider, funding_source, amount, currency, status, "
                    "description, sale_mode, created_at "
                    "from payments where user_id = :u order by payment_id desc limit 5"
                ),
                {"u": user["user_id"]},
            )
        ).mappings().all()
    return {
        "user": dict(user),
        "subscription": dict(subscription) if subscription else None,
        "payments": [dict(row) for row in payments],
    }


async def _panel_call(label: str, coro: Any) -> Any:
    try:
        return await asyncio.wait_for(coro, timeout=12)
    except Exception:  # noqa: BLE001 - one failing panel call must not hide the others
        logger.warning("kiro-diagnostics: panel call %s failed", label)
        return None


async def _load_panel(panel: Any, user_uuid: str) -> dict[str, Any]:
    now = datetime.now(UTC)
    month_start = now.replace(day=1).strftime("%Y-%m-%d")
    week_start = (now - timedelta(days=6)).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")
    results = await asyncio.gather(
        _panel_call("user", panel.get_user_by_uuid(user_uuid, use_cache=False)),
        _panel_call("devices", panel.get_user_devices(user_uuid, force_refresh=True)),
        _panel_call(
            "bandwidth_month",
            panel.get_user_bandwidth_stats(user_uuid, start=month_start, end=today),
        ),
        _panel_call(
            "bandwidth_week",
            panel.get_user_bandwidth_stats(user_uuid, start=week_start, end=today),
        ),
        _panel_call("nodes", panel._request("GET", "/nodes")),
        _panel_call("accessible", panel._request("GET", f"/users/{user_uuid}/accessible-nodes")),
        _panel_call(
            "history",
            panel._request("GET", f"/users/{user_uuid}/subscription-request-history"),
        ),
    )
    user, devices, bw_month, bw_week, nodes, accessible, history = results
    return {
        "user": user,
        "devices": devices,
        "bandwidth_month": bw_month,
        "bandwidth_week": bw_week,
        "nodes": _response(nodes),
        "accessible": _response(accessible),
        "history": _response(history),
    }


def _node_usage(stats: Any) -> list[dict[str, Any]]:
    if not isinstance(stats, dict):
        return []
    rows = []
    for series in stats.get("series") or stats.get("topNodes") or []:
        if not isinstance(series, dict):
            continue
        rows.append(
            {
                "name": series.get("name") or series.get("nodeName") or "?",
                "country": series.get("countryCode") or "",
                "bytes": int(series.get("total") or 0),
                "daily": [int(x or 0) for x in series.get("data") or []],
            }
        )
    rows.sort(key=lambda row: row["bytes"], reverse=True)
    return rows


def _build(shop: dict[str, Any], panel: dict[str, Any] | None) -> dict[str, Any]:
    now = datetime.now(UTC)
    warnings: list[dict[str, str]] = []

    def warn(level: str, message: str) -> None:
        warnings.append({"level": level, "text": message})

    user = shop["user"]
    sub = shop["subscription"]
    out: dict[str, Any] = {
        "generated_at": now.isoformat(),
        "shop": {
            "user_id": user["user_id"],
            "minishop_id": user["minishop_id"],
            "telegram_id": user["telegram_id"],
            "username": user["username"],
            "first_name": user["first_name"],
            "panel_user_uuid": user["panel_user_uuid"],
            "is_banned": bool(user["is_banned"]),
            "registered_at": _iso(user["registration_date"]),
        },
        "subscription": None,
        "payments": [
            {**row, "created_at": _iso(row["created_at"]), "amount": float(row["amount"] or 0)}
            for row in shop["payments"]
        ],
    }
    if user["is_banned"]:
        warn("error", "Пользователь заблокирован в магазине")

    if sub:
        premium_limit = sum(
            int(sub[key] or 0)
            for key in (
                "premium_baseline_bytes",
                "premium_topup_balance_bytes",
                "premium_topup_used_bytes",
                "premium_bonus_bytes",
            )
        )
        out["subscription"] = {
            "tariff": sub["tariff_key"],
            "active": bool(sub["is_active"]),
            "end_date": _iso(sub["end_date"]),
            "panel_status": sub["status_from_panel"],
            "traffic_limit": int(sub["traffic_limit_bytes"] or 0),
            "traffic_used": int(sub["traffic_used_bytes"] or 0),
            "throttled": bool(sub["is_throttled"]),
            "premium_used": int(sub["premium_used_bytes"] or 0),
            "premium_limit": premium_limit,
            "premium_limited": bool(sub["premium_is_limited"]),
            "premium_unlimited": bool(sub["premium_unlimited_override"]),
            "hwid_limit": int(sub["hwid_device_limit"] or 0) + int(sub["extra_hwid_devices"] or 0),
            "auto_renew": bool(sub["auto_renew_enabled"]),
            "provider": sub["provider"],
        }
        end = _parse_dt(sub["end_date"])
        if not sub["is_active"] or (end and end < now):
            warn("error", "Подписка неактивна или истекла")
        elif end and end - now < timedelta(days=3):
            warn("warn", "Подписка заканчивается менее чем через 3 дня")
        if sub["is_throttled"]:
            warn("warn", "Скорость ограничена (throttled)")
        limit = int(sub["traffic_limit_bytes"] or 0)
        if limit and int(sub["traffic_used_bytes"] or 0) >= limit * 0.9:
            warn("warn", "Израсходовано больше 90% основного трафика")
        if premium_limit and not sub["premium_unlimited_override"]:
            if int(sub["premium_used_bytes"] or 0) >= premium_limit:
                warn("error", "Premium-трафик исчерпан: бот убирает premium-сквад")
            elif sub["premium_is_limited"] and int(sub["premium_used_bytes"] or 0) >= premium_limit * 0.8:
                warn("warn", "Израсходовано больше 80% Premium-трафика")
    else:
        warn("error", "У пользователя нет подписки в магазине")

    if not user["panel_user_uuid"]:
        warn("error", "Пользователь не связан с панелью Remnawave")
        return {**out, "panel": None, "warnings": warnings}
    if panel is None or panel.get("user") is None:
        warn("error", "Панель не вернула данные пользователя")
        return {**out, "panel": None, "warnings": warnings}

    pu = panel["user"]
    traffic = pu.get("userTraffic") or {}
    nodes = {
        str(node.get("uuid")): node for node in (panel.get("nodes") or []) if isinstance(node, dict)
    }
    last_node_uuid = traffic.get("lastConnectedNodeUuid") or pu.get("lastConnectedNodeUuid")
    last_node = nodes.get(str(last_node_uuid)) if last_node_uuid else None
    online_at = _parse_dt(traffic.get("onlineAt") or pu.get("onlineAt"))
    squads = [
        squad.get("name") for squad in pu.get("activeInternalSquads") or [] if isinstance(squad, dict)
    ]
    devices = [
        {
            "platform": device.get("platform"),
            "os": device.get("osVersion"),
            "model": device.get("deviceModel"),
            "app": device.get("userAgent"),
            "first_seen": device.get("createdAt"),
            "last_seen": device.get("updatedAt"),
        }
        for device in panel.get("devices") or []
        if isinstance(device, dict)
    ]
    history_raw = panel.get("history")
    if isinstance(history_raw, dict):
        history_raw = history_raw.get("records") or history_raw.get("history") or []
    history = [
        {"at": row.get("requestAt"), "ip": row.get("requestIp"), "app": row.get("userAgent")}
        for row in (history_raw or [])[:8]
        if isinstance(row, dict)
    ]
    accessible = []
    raw_accessible = panel.get("accessible")
    if isinstance(raw_accessible, dict):
        for node in raw_accessible.get("activeNodes") or []:
            inbounds = sorted(
                {
                    inbound
                    for squad in node.get("activeSquads") or []
                    for inbound in squad.get("activeInbounds") or []
                }
            )
            accessible.append(
                {
                    "name": node.get("nodeName"),
                    "country": node.get("countryCode"),
                    "inbounds": inbounds,
                    "online": bool(nodes.get(str(node.get("uuid")), {}).get("isConnected", True)),
                }
            )

    panel_out = {
        "username": pu.get("username"),
        "short_uuid": pu.get("shortUuid"),
        "status": pu.get("status"),
        "expire_at": pu.get("expireAt"),
        "traffic_used": int(traffic.get("usedTrafficBytes") or pu.get("usedTrafficBytes") or 0),
        "traffic_lifetime": int(
            traffic.get("lifetimeUsedTrafficBytes") or pu.get("lifetimeUsedTrafficBytes") or 0
        ),
        "traffic_limit": int(pu.get("trafficLimitBytes") or 0),
        "online_at": _iso(online_at),
        "first_connected_at": traffic.get("firstConnectedAt") or pu.get("firstConnectedAt"),
        "last_node": (
            {
                "name": last_node.get("name"),
                "country": last_node.get("countryCode"),
                "online": bool(last_node.get("isConnected")),
            }
            if last_node
            else None
        ),
        "hwid_limit": pu.get("hwidDeviceLimit"),
        "sub_revoked_at": pu.get("subRevokedAt"),
        "squads": squads,
        "accessible_nodes": accessible,
        "usage_month": _node_usage(panel.get("bandwidth_month")),
        "usage_week": _node_usage(panel.get("bandwidth_week")),
        "devices": devices,
        "sub_requests": history,
    }

    status = str(pu.get("status") or "").upper()
    if status and status != "ACTIVE":
        warn("error", f"Статус в панели: {status}")
    if not squads:
        warn("error", "В панели нет ни одного сквада: подключаться некуда")
    if not accessible and isinstance(raw_accessible, dict):
        warn("error", "Нет доступных нод (ни один сквад не активен на нодах)")
    offline = [node["name"] for node in accessible if not node["online"]]
    if offline:
        warn("warn", "Недоступны ноды: " + ", ".join(str(n) for n in offline))
    if last_node and not last_node.get("isConnected"):
        warn("warn", "Последняя нода пользователя сейчас не на связи")
    if online_at is None:
        warn("warn", "Пользователь ни разу не подключался")
    elif now - online_at > timedelta(days=3):
        warn("info", f"Не подключался {(now - online_at).days} дн.")
    hwid_limit = pu.get("hwidDeviceLimit")
    if hwid_limit and len(devices) >= int(hwid_limit):
        warn("warn", f"Достигнут лимит устройств ({len(devices)}/{hwid_limit})")
    if not history:
        warn("info", "Нет запросов подписки: клиент мог не добавить ссылку")
    else:
        last_request = _parse_dt(history[0]["at"])
        if last_request and now - last_request > timedelta(days=7):
            warn("info", "Подписка не обновлялась больше недели")
    return {**out, "panel": panel_out, "warnings": warnings}


async def _handle(request: web.Request) -> web.Response:
    if not request.get("admin_authorized", False):
        return web.json_response({"ok": False, "error": "forbidden"}, status=403)
    ref = request.match_info["ref"]
    if not (ref.isdigit() or (ref.startswith("ms_") and ref[3:].isalnum() and len(ref) <= 35)):
        return web.json_response({"ok": False, "error": "invalid_user"}, status=400)
    try:
        shop = await _load_shop(get_session_factory(request), ref)
    except Exception:  # noqa: BLE001
        logger.exception("kiro-diagnostics: shop lookup failed")
        return web.json_response({"ok": False, "error": "shop_lookup_failed"}, status=500)
    if shop is None:
        return web.json_response({"ok": False, "error": "user_not_found"}, status=404)
    panel_data = None
    panel = get_panel_service(request)
    uuid = shop["user"]["panel_user_uuid"]
    if panel is not None and uuid:
        panel_data = await _load_panel(panel, str(uuid))
    body = _build(shop, panel_data)
    return web.json_response(
        {"ok": True, **body}, headers={"Cache-Control": "no-store"}, dumps=_dumps
    )


def _dumps(value: Any) -> str:
    import json

    return json.dumps(value, default=str, ensure_ascii=False)


class KiroDiagnosticsPlugin(Plugin):
    name = PLUGIN_ID
    version = "1.0.1"
    plugin_api_min_version = 1
    plugin_api_max_version = 1

    def setup_web(self, ctx: PluginContext, app: web.Application, *, scope: str) -> None:
        if scope != WEB_SCOPE_WEBAPP:
            return
        app.router.add_get(ROUTE, _handle)

    def locales_dir(self) -> Path | None:
        # Package layout: <release>/backend/kiro_diagnostics/__init__.py and <release>/locales/
        path = Path(__file__).resolve().parents[2] / "locales"
        return path if path.is_dir() else None


plugin = KiroDiagnosticsPlugin()
