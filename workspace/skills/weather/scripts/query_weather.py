from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any


LOCATION_ALIASES = {
    "武汉": "Wuhan",
    "北京": "Beijing",
    "上海": "Shanghai",
    "广州": "Guangzhou",
    "深圳": "Shenzhen",
    "杭州": "Hangzhou",
    "南京": "Nanjing",
    "成都": "Chengdu",
    "重庆": "Chongqing",
    "西安": "Xian",
    "天津": "Tianjin",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Query wttr.in weather and print a compact JSON summary."
    )
    parser.add_argument(
        "location",
        nargs="?",
        default="Wuhan",
        help="City or region, for example Wuhan, Beijing, or 武汉.",
    )
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()

    requested_location = str(args.location or "Wuhan").strip() or "Wuhan"
    query_location = LOCATION_ALIASES.get(requested_location, requested_location)
    payload = fetch_weather(
        query_location,
        requested_location=requested_location,
        timeout=max(1.0, args.timeout),
        retries=max(0, args.retries),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def fetch_weather(
    location: str,
    *,
    requested_location: str,
    timeout: float,
    retries: int,
) -> dict[str, Any]:
    quoted_location = urllib.parse.quote(location)
    url = f"https://wttr.in/{quoted_location}?format=j1"
    last_error = ""

    for attempt in range(retries + 1):
        try:
            data = request_json(url, timeout=timeout)
            return build_summary(
                data,
                requested_location=requested_location,
                query_location=location,
                source_url=url,
            )
        except Exception as exc:
            last_error = str(exc)
            if attempt < retries:
                time.sleep(min(1.0 + attempt, 3.0))

    return {
        "status": "error",
        "requested_location": requested_location,
        "query_location": location,
        "source": "wttr.in",
        "source_url": url,
        "error": last_error or "Unknown weather query error.",
        "retrieved_at": datetime.now().isoformat(timespec="seconds"),
        "suggestion": "请检查网络连接，或换用城市拼音/英文名后重试。",
    }


def request_json(url: str, *, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "MiniAgentWeatherSkill/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        text = response.read().decode(charset, errors="replace")
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Weather response is not a JSON object.")
    return parsed


def build_summary(
    data: dict[str, Any],
    *,
    requested_location: str,
    query_location: str,
    source_url: str,
) -> dict[str, Any]:
    current = first_dict(data.get("current_condition"))
    today = first_dict(data.get("weather"))
    nearest_area = first_dict(data.get("nearest_area"))
    area_name = text_value(first_dict(nearest_area.get("areaName"))) if nearest_area else ""
    country = text_value(first_dict(nearest_area.get("country"))) if nearest_area else ""

    hourly = today.get("hourly") if isinstance(today, dict) else []
    rain_chance = max_int(
        [
            item.get("chanceofrain")
            for item in hourly
            if isinstance(item, dict) and item.get("chanceofrain") is not None
        ]
    )

    return {
        "status": "success",
        "requested_location": requested_location,
        "query_location": query_location,
        "resolved_location": join_non_empty([area_name, country]),
        "source": "wttr.in",
        "source_url": source_url,
        "retrieved_at": datetime.now().isoformat(timespec="seconds"),
        "current": {
            "description": text_value(first_dict(current.get("weatherDesc"))),
            "temperature_c": current.get("temp_C"),
            "feels_like_c": current.get("FeelsLikeC"),
            "humidity_percent": current.get("humidity"),
            "wind_kmph": current.get("windspeedKmph"),
            "wind_direction": current.get("winddir16Point"),
            "visibility_km": current.get("visibility"),
        },
        "today": {
            "date": today.get("date"),
            "max_temp_c": today.get("maxtempC"),
            "min_temp_c": today.get("mintempC"),
            "avg_temp_c": today.get("avgtempC"),
            "max_chance_of_rain_percent": rain_chance,
            "sunrise": text_value(first_dict(today.get("astronomy")).get("sunrise"))
            if first_dict(today.get("astronomy"))
            else "",
            "sunset": text_value(first_dict(today.get("astronomy")).get("sunset"))
            if first_dict(today.get("astronomy"))
            else "",
        },
        "summary": build_human_summary(current, today, rain_chance),
    }


def build_human_summary(
    current: dict[str, Any],
    today: dict[str, Any],
    rain_chance: int | None,
) -> str:
    description = text_value(first_dict(current.get("weatherDesc"))) or "未知天气"
    temp = current.get("temp_C") or "未知"
    feels = current.get("FeelsLikeC") or "未知"
    humidity = current.get("humidity") or "未知"
    wind = current.get("windspeedKmph") or "未知"
    max_temp = today.get("maxtempC") or "未知"
    min_temp = today.get("mintempC") or "未知"
    rain_text = f"{rain_chance}%" if rain_chance is not None else "未知"
    return (
        f"当前{description}，气温{temp}°C，体感{feels}°C，湿度{humidity}%，"
        f"风速{wind}km/h。今日气温约{min_temp}-{max_temp}°C，"
        f"最高降雨概率{rain_text}。"
    )


def first_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return value[0]
    if isinstance(value, dict):
        return value
    return {}


def text_value(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("value") or "").strip()
    return str(value or "").strip()


def max_int(values: list[Any]) -> int | None:
    parsed: list[int] = []
    for value in values:
        try:
            parsed.append(int(value))
        except (TypeError, ValueError):
            continue
    return max(parsed) if parsed else None


def join_non_empty(parts: list[str]) -> str:
    return ", ".join(part for part in parts if part)


if __name__ == "__main__":
    raise SystemExit(main())
