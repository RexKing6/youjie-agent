"""Idempotently create the non-secret Youjie master data in a local OpenMES test instance."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PRODUCTS = (
    ("YOUJIE-PRD-CFG-1", "有界车型配置 1", "关键客户车辆配置；公开数据派生数量，测试主数据"),
    ("YOUJIE-PRD-CFG-2", "有界车型配置 2", "高优先级车辆配置；公开数据派生数量，测试主数据"),
    ("YOUJIE-PRD-CFG-3", "有界车型配置 3", "普通补货车辆配置；公开数据派生数量，测试主数据"),
)
STEPS = (
    ("车身与底盘上线", 45),
    ("座椅与内饰装配", 35),
    ("终检与质量放行", 25),
    ("下线交付确认", 15),
)


class Api:
    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(self.base_url + path, data=body, method=method, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")[:1200]
            raise RuntimeError(f"OpenMES {method} {path} returned HTTP {exc.code}: {message}") from None


def login(base_url: str) -> Api:
    username = os.environ.get("OPENMES_ADMIN_USERNAME")
    password = os.environ.get("OPENMES_ADMIN_PASSWORD")
    if not username or not password:
        raise RuntimeError("OPENMES_ADMIN_USERNAME and OPENMES_ADMIN_PASSWORD are required")
    anonymous = Api(base_url)
    payload = anonymous.request("POST", "/api/auth/login", {"username": username, "password": password})
    token = payload.get("data", {}).get("token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("OpenMES login did not return a token")
    return Api(base_url, token)


def find_by_code(rows: list[dict[str, Any]], code: str) -> dict[str, Any] | None:
    return next((row for row in rows if row.get("code") == code), None)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    args = parser.parse_args()
    api = login(args.base_url)

    lines = api.request("GET", "/api/v1/lines?include_inactive=1").get("data", [])
    line = find_by_code(lines, "YOUJIE-ASSEMBLY")
    if line is None:
        line = api.request("POST", "/api/v1/lines", {
            "code": "YOUJIE-ASSEMBLY",
            "name": "有界总装测试线",
            "description": "GOAI 复赛本机 OpenMES 测试主数据；不对应真实工厂或设备",
            "is_active": True,
        })["data"]

    product_ids = []
    for code, name, description in PRODUCTS:
        query = urlencode({"include_inactive": "1", "q": code})
        rows = api.request("GET", f"/api/v1/product-types?{query}").get("data", [])
        product = find_by_code(rows, code)
        if product is None:
            product = api.request("POST", "/api/v1/product-types", {
                "code": code,
                "name": name,
                "description": description,
                "unit_of_measure": "台",
                "is_active": True,
            })["data"]
        product_ids.append(int(product["id"]))
        templates = api.request(
            "GET",
            f"/api/v1/product-types/{product['id']}/process-templates?include_inactive=1",
        ).get("data", [])
        template = next((item for item in templates if item.get("name") == "有界整车恢复排程 v1"), None)
        if template is None:
            template = api.request(
                "POST",
                f"/api/v1/product-types/{product['id']}/process-templates",
                {"name": "有界整车恢复排程 v1", "version": 1, "is_active": True},
            )["data"]
        if not template.get("steps"):
            for step_number, (step_name, duration) in enumerate(STEPS, start=1):
                api.request(
                    "POST",
                    f"/api/v1/process-templates/{template['id']}/steps",
                    {
                        "step_number": step_number,
                        "name": step_name,
                        "instruction": "比赛测试流程；由人工在 OpenMES 中确认，不触发设备控制",
                        "estimated_duration_minutes": duration,
                    },
                )

    api.request(
        "POST",
        f"/api/v1/lines/{line['id']}/product-types",
        {"product_type_ids": product_ids},
    )
    print(json.dumps({
        "status": "ready",
        "line_code": line["code"],
        "product_codes": [item[0] for item in PRODUCTS],
        "credentials_exposed": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
