"""Resolve requirement specs to wheels and fetch them."""

from __future__ import annotations

import collections
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import importlib.metadata
from packaging.markers import Marker, default_environment
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.tags import Tag
from packaging.utils import canonicalize_name
from packaging.version import Version

from .errors import ResolutionError, WheelInstallError
from .extract import read_wheel_metadata
from .fetch import fetch_wheel, get_pypi_json, select_best_wheel


@dataclass(frozen=True, slots=True)
class ResolvedWheel:
    name: str
    version: Version
    wheel_path: Path


def _normalize_name(name: str) -> str:
    return canonicalize_name(name)


def _get_installed_distributions(target: Path) -> dict[str, Version]:
    installed: dict[str, Version] = {}
    try:
        for dist in importlib.metadata.distributions(path=[target]):
            name = _normalize_name(dist.metadata["Name"])
            try:
                installed[name] = Version(dist.metadata["Version"])
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    return installed


def _find_dist_info_dir(target: Path, name: str) -> Path | None:
    normalized = _normalize_name(name)
    for candidate in target.glob("*.dist-info"):
        if candidate.name.lower().startswith(normalized + "-"):
            return candidate
    return None


def _read_requires_dist_from_target(target: Path, name: str) -> tuple[str, ...]:
    dist_info = _find_dist_info_dir(target, name)
    if dist_info is None:
        return ()
    metadata_file = dist_info / "METADATA"
    if not metadata_file.exists():
        return ()
    try:
        content = metadata_file.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return ()
    return tuple(line[14:].strip() for line in content.splitlines() if line.startswith("Requires-Dist:"))


def _filter_marker(req_str: str, active_extras: frozenset[str]) -> bool:
    try:
        req = Requirement(req_str)
    except Exception:  # noqa: BLE001
        return True
    marker = req.marker
    if marker is None:
        return True
    references_extra = any(
        mt and hasattr(mt[0], "value") and mt[0].value == "extra"
        for mt in getattr(marker, "_markers", ())
    )
    if not references_extra:
        return marker.evaluate(default_environment())
    if not active_extras:
        return False
    env = default_environment()
    return any(marker.evaluate({**env, "extra": e}) for e in active_extras)


def _get_requires_dist(wheel_path: Path, active_extras: frozenset[str]) -> list[Requirement]:
    metadata = read_wheel_metadata(wheel_path)
    return [
        Requirement(req_str)
        for req_str in metadata.requires_dist
        if _filter_marker(req_str, active_extras)
    ]


def _get_requires_dist_from_installed(
    target: Path, name: str, active_extras: frozenset[str]
) -> list[Requirement]:
    return [
        Requirement(req_str)
        for req_str in _read_requires_dist_from_target(target, name)
        if _filter_marker(req_str, active_extras)
    ]


def resolve_and_fetch(
    specs: list[str],
    target: Path,
    tags: list[Tag],
    cache_dir: Path,
    log: Callable[[str], None] | None = None,
) -> list[ResolvedWheel]:
    queue: collections.deque[tuple[Requirement, frozenset[str]]] = collections.deque()
    for spec in specs:
        try:
            req = Requirement(spec)
        except Exception as exc:  # noqa: BLE001
            raise ResolutionError(f"无效的需求规格 {spec!r}：{exc}") from exc
        queue.append((req, frozenset(req.extras)))

    installed = _get_installed_distributions(target)
    resolved: dict[str, ResolvedWheel] = {}
    dep_graph: dict[str, set[str]] = collections.defaultdict(set)
    enqueued_satisfied: dict[str, SpecifierSet] = {}

    while queue:
        req, active_extras = queue.popleft()
        norm_name = _normalize_name(req.name)

        if norm_name in resolved:
            existing = resolved[norm_name]
            if existing.version in req.specifier:
                continue
            raise ResolutionError(f"依赖冲突：{norm_name} 已解析为 {existing.version}，但要求 {req.specifier}")

        if norm_name in installed and installed[norm_name] in req.specifier:
            if log:
                log(f"解析 {req.name} … (已安装 {installed[norm_name]})")
            for child_req in _get_requires_dist_from_installed(target, req.name, active_extras):
                child_norm = _normalize_name(child_req.name)
                dep_graph[norm_name].add(child_norm)
                if child_norm in resolved:
                    if resolved[child_norm].version not in child_req.specifier:
                        raise ResolutionError(f"依赖冲突：{child_norm} 已解析为 {resolved[child_norm].version}，但 {norm_name} 要求 {child_req.specifier}")
                    continue
                prev_spec = enqueued_satisfied.get(child_norm)
                if prev_spec is not None and installed.get(child_norm) in prev_spec:
                    continue
                enqueued_satisfied[child_norm] = child_req.specifier
                queue.append((child_req, frozenset(child_req.extras)))
            continue

        if log:
            log(f"解析 {req.name} …")
        json_data = get_pypi_json(req.name)
        file_info = select_best_wheel(json_data, req.specifier, tags)
        filename = file_info["filename"]
        url = file_info["url"]
        sha256 = file_info.get("digests", {}).get("sha256")
        if log:
            log(f"下载 {filename} …")
        wheel_path = fetch_wheel(url, cache_dir, sha256)

        metadata = read_wheel_metadata(wheel_path)
        actual_norm = _normalize_name(metadata.name)
        actual_version = Version(metadata.version)
        if actual_norm != norm_name:
            raise ResolutionError(f"wheel 名称不匹配：请求 {norm_name}，wheel 声明 {actual_norm}")
        if actual_version not in req.specifier:
            raise ResolutionError(f"wheel 版本不满足规格：{actual_version} 不在 {req.specifier}")

        resolved[norm_name] = ResolvedWheel(name=norm_name, version=actual_version, wheel_path=wheel_path)

        for child_req in _get_requires_dist(wheel_path, active_extras):
            child_norm = _normalize_name(child_req.name)
            dep_graph[norm_name].add(child_norm)
            if child_norm in resolved:
                if resolved[child_norm].version not in child_req.specifier:
                    raise ResolutionError(f"依赖冲突：{child_norm} 已解析为 {resolved[child_norm].version}，但 {norm_name} 要求 {child_req.specifier}")
                continue
            prev_spec = enqueued_satisfied.get(child_norm)
            if prev_spec is not None and installed.get(child_norm) in prev_spec:
                continue
            enqueued_satisfied[child_norm] = child_req.specifier
            queue.append((child_req, frozenset(child_req.extras)))

    # Topological sort (Kahn's algorithm) — stable, deterministic
    indegree: dict[str, int] = collections.defaultdict(int)
    all_nodes: set[str] = set(resolved.keys())
    rev_adj: dict[str, set[str]] = collections.defaultdict(set)
    for parent, children in dep_graph.items():
        all_nodes.add(parent)
        for child in children:
            all_nodes.add(child)
            rev_adj[child].add(parent)
            indegree[parent] += 1

    zero_queue = collections.deque(sorted(n for n in all_nodes if indegree[n] == 0))
    topo_order: list[str] = []
    while zero_queue:
        node = zero_queue.popleft()
        topo_order.append(node)
        for parent in sorted(rev_adj.get(node, ())):
            indegree[parent] -= 1
            if indegree[parent] == 0:
                zero_queue.append(parent)

    remaining = sorted(all_nodes - set(topo_order))
    topo_order.extend(remaining)

    return [resolved[name] for name in topo_order if name in resolved]