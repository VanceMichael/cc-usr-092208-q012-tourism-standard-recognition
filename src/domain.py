"""读取并检查共享的领域资料。"""

import json
from datetime import date
from pathlib import Path

# 各认定等级对应的核验方式：等级越高，所需的核验越严格
LEVEL_VERIFICATION = {
    "self-declaration": frozenset({"self-declaration"}),
    "third-party-certification": frozenset({"third-party", "on-site"}),
    "formal-mutual-recognition": frozenset({"on-site"}),
}

# 升级到各等级时必须具备的核验记录类型
LEVEL_REQUIRED_KIND = {
    "third-party-certification": "third-party",
    "formal-mutual-recognition": "on-site",
}

# 会触发在售产品更新的变更事件类型
CHANGE_EVENT_TYPES = frozenset({
    "standard-revised",
    "certification-suspended",
    "spot-check-failed",
    "body-exited",
    "cross-border-revoked",
})

_BASIC_REQUIRED = {"domain", "version", "sample_id", "actors", "facts", "constraints"}
_STRUCTURED_REQUIRED = {
    "service_items",
    "regions",
    "recognition_levels",
    "standards",
    "certification_bodies",
    "regional_profiles",
    "marks",
    "verification_records",
    "change_events",
}


def load_domain(path: Path) -> dict:
    """返回字段完整且带版本的业务资料。"""
    return validate_domain(json.loads(path.read_text(encoding="utf-8")))


def validate_domain(value: dict) -> dict:
    """校验共享资料的结构与引用完整性，返回资料本身。"""
    _check_basic(value)
    _check_integrity(value)
    return value


def recognition_rank(domain: dict, level_id: str) -> int:
    """认定等级的排序值，越高代表核验越严格。"""
    for level in domain["recognition_levels"]:
        if level["id"] == level_id:
            return level["rank"]
    raise KeyError(f"未知认定等级：{level_id}")


def mark_scope(domain: dict, mark_id: str) -> dict:
    """标识对游客展示的范围：服务项目、适用地区、有效时间与认定等级。"""
    mark = _find_mark(domain, mark_id)
    service_names = {item["id"]: item["name"] for item in domain["service_items"]}
    region_names = {region["id"]: region["name"] for region in domain["regions"]}
    return {
        "mark_id": mark["id"],
        "product_id": mark["product_id"],
        "product_name": mark["product_name"],
        "supplier": mark["supplier"],
        "services": [service_names[item] for item in mark["service_items"]],
        "regions": [region_names[region] for region in mark["regions"]],
        "valid_from": mark["valid_from"],
        "valid_to": mark["valid_to"],
        "recognition_level": mark["recognition_level"],
        "status": mark["status"],
    }


def trace_mark(domain: dict, mark_id: str) -> dict:
    """从标识追到核验记录与责任主体。"""
    _find_mark(domain, mark_id)
    records = [dict(item) for item in domain["verification_records"] if item["mark_id"] == mark_id]
    records.sort(key=lambda item: item["date"])
    return {
        "mark_id": mark_id,
        "records": records,
        "responsible_parties": sorted({item["responsible_party"] for item in records}),
    }


def affected_marks(domain: dict, event_id: str) -> list:
    """变更事件发生后，需要准确更新的在售标识。"""
    event = None
    for item in domain["change_events"]:
        if item["id"] == event_id:
            event = item
            break
    if event is None:
        raise KeyError(f"未知变更事件：{event_id}")
    marks = {mark["id"]: mark for mark in domain["marks"]}
    hit = set()
    if "standard_version" in event:
        hit |= {mark["id"] for mark in marks.values() if mark["standard_version"] == event["standard_version"]}
    if "certification_body" in event:
        body = event["certification_body"]
        hit |= {
            record["mark_id"]
            for record in domain["verification_records"]
            if record["certification_body"] == body and record["result"] == "pass"
        }
    if "mark_ids" in event:
        hit |= set(event["mark_ids"])
    if "regions" in event:
        regions = set(event["regions"])
        hit |= {mark["id"] for mark in marks.values() if regions & set(mark["regions"])}
    return sorted(mark_id for mark_id in hit if marks[mark_id]["status"] == "active")


def supplier_gap(domain: dict, mark_id: str, target_level: str) -> dict:
    """企业整改视角：达到目标认定等级还缺哪些证据与核验。"""
    mark = _find_mark(domain, mark_id)
    level_ids = {level["id"] for level in domain["recognition_levels"]}
    if target_level not in level_ids:
        raise KeyError(f"未知认定等级：{target_level}")
    profiles = {profile["region"]: profile for profile in domain["regional_profiles"]}
    required = set()
    for region in mark["regions"]:
        required |= set(profiles[region]["evidence_requirements"])
    records = [item for item in domain["verification_records"] if item["mark_id"] == mark_id]
    covered = set()
    for record in records:
        if record["result"] == "pass":
            covered |= set(record["covers"])
    missing_verification = None
    current = mark["recognition_level"]
    if recognition_rank(domain, target_level) > recognition_rank(domain, current):
        needed_kinds = LEVEL_VERIFICATION[target_level]
        backed = any(
            record["kind"] in needed_kinds and record["result"] == "pass" for record in records
        )
        if not backed:
            missing_verification = LEVEL_REQUIRED_KIND.get(target_level)
    status_by_version = {item["version"]: item["status"] for item in domain["standards"]}
    return {
        "mark_id": mark_id,
        "current_level": current,
        "target_level": target_level,
        "missing_evidence": sorted(required - covered),
        "missing_verification": missing_verification,
        "standard_outdated": status_by_version[mark["standard_version"]] != "current",
    }


def _check_basic(value: dict) -> None:
    if not _BASIC_REQUIRED.issubset(value):
        raise ValueError("共享资料缺少必要字段")
    if (
        value["version"] < 1
        or len(value["actors"]) < 2
        or len(value["facts"]) < 2
        or len(value["constraints"]) < 2
    ):
        raise ValueError("共享资料内容不完整")
    if not _STRUCTURED_REQUIRED.issubset(value):
        raise ValueError("共享资料缺少结构化栏目")


def _check_integrity(value: dict) -> None:
    service_ids = _unique_ids(value["service_items"], "服务项目")
    region_ids = _unique_ids(value["regions"], "适用地区")
    body_ids = _unique_ids(value["certification_bodies"], "认证机构")

    levels = value["recognition_levels"]
    level_ids = _unique_ids(levels, "认定等级")
    _require(
        set(level_ids) == set(LEVEL_VERIFICATION),
        "认定等级必须覆盖自我声明、第三方认证与正式互认",
    )
    ranks = [level["rank"] for level in levels]
    _require(len(ranks) == len(set(ranks)), "认定等级排序重复")

    standard_versions = [item["version"] for item in value["standards"]]
    _require(len(standard_versions) == len(set(standard_versions)), "标准版本重复")
    standard_version_set = set(standard_versions)

    for body in value["certification_bodies"]:
        _require(
            set(body["regions"]) <= region_ids,
            f"认证机构{body['id']}关联了未知地区",
        )

    profiles = {}
    for profile in value["regional_profiles"]:
        region = profile["region"]
        _require(region in region_ids, f"地区资料关联了未知地区{region}")
        _require(region not in profiles, f"地区{region}存在多份地区资料")
        _require(
            set(profile["certification_bodies"]) <= body_ids,
            f"地区{region}关联了未知认证机构",
        )
        profiles[region] = profile

    marks = value["marks"]
    mark_ids = _unique_ids(marks, "服务标识")
    for mark in marks:
        _require(
            bool(mark["service_items"]) and set(mark["service_items"]) <= service_ids,
            f"标识{mark['id']}关联了未知服务项目",
        )
        _require(
            bool(mark["regions"]) and set(mark["regions"]) <= region_ids,
            f"标识{mark['id']}关联了未知地区",
        )
        _require(
            set(mark["regions"]) <= set(profiles),
            f"标识{mark['id']}的适用地区缺少地区资料",
        )
        _require(mark["recognition_level"] in level_ids, f"标识{mark['id']}的认定等级未知")
        _require(
            mark["standard_version"] in standard_version_set,
            f"标识{mark['id']}的标准版本未知",
        )
        start = _parse_date(mark["valid_from"], f"标识{mark['id']}的生效日期")
        end = _parse_date(mark["valid_to"], f"标识{mark['id']}的失效日期")
        _require(start <= end, f"标识{mark['id']}的有效期起止颠倒")

    records = value["verification_records"]
    _unique_ids(records, "核验记录")
    marks_by_id = {mark["id"]: mark for mark in marks}
    for record in records:
        mark = marks_by_id.get(record["mark_id"])
        _require(mark is not None, f"核验记录{record['id']}关联了未知标识")
        _require(
            record["kind"] in {"self-declaration", "third-party", "on-site"},
            f"核验记录{record['id']}的核验方式未知",
        )
        if record["kind"] == "self-declaration":
            _require(record["certification_body"] is None, "自我声明不应关联认证机构")
            _require(record["result"] == "declared", "自我声明的结果应为declared")
        else:
            _require(
                record["certification_body"] in body_ids,
                f"核验记录{record['id']}关联了未知认证机构",
            )
            _require(record["result"] in {"pass", "fail"}, f"核验记录{record['id']}的结果未知")
        _require(
            record["region"] in set(mark["regions"]),
            f"核验记录{record['id']}的地区超出标识适用范围",
        )
        allowed = set(profiles[record["region"]]["evidence_requirements"])
        _require(
            set(record["covers"]) <= allowed,
            f"核验记录{record['id']}覆盖了地区未要求的证据",
        )
        _require(bool(record["responsible_party"]), f"核验记录{record['id']}缺少责任主体")
        _parse_date(record["date"], f"核验记录{record['id']}的日期")

    for mark in marks:
        own = [record for record in records if record["mark_id"] == mark["id"]]
        _require(bool(own), f"标识{mark['id']}缺少核验记录，无法追溯")
        level = mark["recognition_level"]
        if level == "self-declaration":
            _require(
                any(record["kind"] == "self-declaration" for record in own),
                f"标识{mark['id']}缺少自我声明记录",
            )
        else:
            _require(
                any(
                    record["kind"] in LEVEL_VERIFICATION[level] and record["result"] == "pass"
                    for record in own
                ),
                f"标识{mark['id']}的认定等级缺少合格核验支撑",
            )

    _unique_ids(value["change_events"], "变更事件")
    for event in value["change_events"]:
        _require(event["type"] in CHANGE_EVENT_TYPES, f"变更事件{event['id']}类型未知")
        _parse_date(event["date"], f"变更事件{event['id']}的日期")
        scopes = 0
        if "standard_version" in event:
            _require(
                event["standard_version"] in standard_version_set,
                f"变更事件{event['id']}关联了未知标准版本",
            )
            scopes += 1
        if "certification_body" in event:
            _require(
                event["certification_body"] in body_ids,
                f"变更事件{event['id']}关联了未知认证机构",
            )
            scopes += 1
        if "mark_ids" in event:
            _require(
                set(event["mark_ids"]) <= mark_ids,
                f"变更事件{event['id']}关联了未知标识",
            )
            scopes += 1
        if "regions" in event:
            _require(
                set(event["regions"]) <= region_ids,
                f"变更事件{event['id']}关联了未知地区",
            )
            scopes += 1
        _require(scopes >= 1, f"变更事件{event['id']}缺少影响范围")


def _find_mark(domain: dict, mark_id: str) -> dict:
    for mark in domain["marks"]:
        if mark["id"] == mark_id:
            return mark
    raise KeyError(f"未知标识：{mark_id}")


def _unique_ids(items: list, label: str) -> set:
    ids = [item["id"] for item in items]
    _require(len(ids) == len(set(ids)), f"{label}存在重复标识")
    return set(ids)


def _parse_date(raw: str, field: str) -> date:
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"日期格式无效：{field}") from exc


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)
