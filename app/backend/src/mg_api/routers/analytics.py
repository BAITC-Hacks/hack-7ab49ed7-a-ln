from typing import Literal

from fastapi import APIRouter, Depends, Query

from ..analytics import graphops, views
from ..analytics.graphops import OverviewFilter
from ..analytics.views import SORTABLE, NodeQuery
from ..errors import NotFound, ValidationFailed
from ..schemas import (
    Cluster,
    ClusterPage,
    CounterpartyPage,
    DataRequestPage,
    HydrateRequest,
    NodeDetail,
    NodePage,
    Overview,
    PathResult,
    Role,
    SearchResult,
    Subgraph,
    TopList,
    TransactionPage,
)
from ..services import Services, get_services, node_id, require_auth

router = APIRouter(prefix="/runs/{run_id}", tags=["analytics"], dependencies=[Depends(require_auth)])

SortField = Literal[SORTABLE]


@router.get("/overview", response_model=Overview)
def overview(run_id: str, services: Services = Depends(get_services)) -> dict:
    meta = services.run_data(run_id).meta
    return {
        "summary": meta["summary"],
        "model": meta["model"],
        "resilience": meta["resilience"],
        "data_requests": meta["data_requests"],
        "warnings": meta["warnings"],
        "params": meta["params"],
    }


@router.get("/graph", response_model=Subgraph)
def graph(
    run_id: str,
    role: list[Role] | None = Query(None),
    cluster_id: int | None = None,
    min_priority: float | None = Query(None, ge=0, le=1),
    hide_peripheral: bool = False,
    max_nodes: int = Query(5000, ge=1, le=20000),
    max_edges: int = Query(20000, ge=0, le=50000),
    services: Services = Depends(get_services),
) -> dict:
    return graphops.overview(
        services.run_data(run_id), OverviewFilter(role, cluster_id, min_priority, hide_peripheral), max_nodes, max_edges
    )


@router.post("/graph/nodes", response_model=Subgraph)
def hydrate(run_id: str, body: HydrateRequest, services: Services = Depends(get_services)) -> dict:
    if not all(i.isdigit() for i in body.ids):
        raise ValidationFailed("Идентификаторы узлов должны состоять из цифр")
    return graphops.hydrate(services.run_data(run_id), [int(i) for i in body.ids], body.include_edges)


@router.get("/nodes", response_model=NodePage)
def nodes(
    run_id: str,
    q: str | None = Query(None, min_length=3, pattern=r"^\d+$"),
    role: list[Role] | None = Query(None),
    cluster_id: int | None = None,
    is_seed: bool | None = None,
    flag: str | None = None,
    sort_by: SortField = "priority_score",
    sort_order: Literal["desc", "asc"] = "desc",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    services: Services = Depends(get_services),
) -> dict:
    query = NodeQuery(q, role, cluster_id, is_seed, flag, sort_by, sort_order == "desc", limit, offset)
    return views.node_page(services.run_data(run_id), query)


@router.get("/search", response_model=SearchResult)
def search(
    run_id: str,
    q: str = Query(..., min_length=3, pattern=r"^\d+$"),
    limit: int = Query(20, ge=1, le=100),
    services: Services = Depends(get_services),
) -> dict:
    return views.search(services.run_data(run_id), q, limit)


@router.get("/nodes/{gid}", response_model=NodeDetail)
def node(run_id: str, gid: str, services: Services = Depends(get_services)) -> dict:
    data = services.run_data(run_id)
    return views.node_detail(data, node_id(data, gid))


@router.get("/nodes/{gid}/counterparties", response_model=CounterpartyPage)
def counterparties(
    run_id: str,
    gid: str,
    direction: Literal["in", "out"],
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    services: Services = Depends(get_services),
) -> dict:
    data = services.run_data(run_id)
    return views.counterparties(data, node_id(data, gid), direction, limit, offset)


@router.get("/nodes/{gid}/transactions", response_model=TransactionPage)
def transactions(
    run_id: str,
    gid: str,
    counterparty: str | None = Query(None, pattern=r"^\d+$"),
    direction: Literal["in", "out", "both"] = "both",
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    services: Services = Depends(get_services),
) -> dict:
    data = services.run_data(run_id)
    other = int(counterparty) if counterparty is not None else None
    return views.transactions(data, node_id(data, gid), other, direction, limit, offset)


@router.get("/nodes/{gid}/neighborhood", response_model=Subgraph)
def neighborhood(
    run_id: str,
    gid: str,
    depth: int = Query(1, ge=1, le=3),
    direction: Literal["in", "out", "both"] = "both",
    max_nodes: int = Query(300, ge=1, le=5000),
    max_edges: int = Query(1000, ge=0, le=20000),
    services: Services = Depends(get_services),
) -> dict:
    data = services.run_data(run_id)
    return graphops.neighborhood(data, node_id(data, gid), depth, direction, max_nodes, max_edges)


@router.get("/nodes/{gid}/trace", response_model=Subgraph)
def trace(
    run_id: str,
    gid: str,
    direction: Literal["up", "down"],
    max_hops: int = Query(4, ge=1, le=6),
    max_nodes: int = Query(500, ge=1, le=5000),
    services: Services = Depends(get_services),
) -> dict:
    data = services.run_data(run_id)
    return graphops.trace(data, node_id(data, gid), direction, max_hops, max_nodes)


@router.get("/path", response_model=PathResult)
def path(run_id: str, source: str, target: str, services: Services = Depends(get_services)) -> dict:
    data = services.run_data(run_id)
    return graphops.shortest_path(data, node_id(data, source), node_id(data, target))


@router.get("/top", response_model=TopList)
def top(run_id: str, limit: int = Query(50, ge=1, le=500), services: Services = Depends(get_services)) -> dict:
    return {"items": services.run_data(run_id).top[:limit]}


@router.get("/clusters", response_model=ClusterPage)
def clusters(
    run_id: str,
    sort_by: Literal["max_priority", "n_nodes", "n_seed"] = "max_priority",
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    services: Services = Depends(get_services),
) -> dict:
    items = sorted(services.run_data(run_id).clusters, key=lambda c: (-c[sort_by], c["cluster_id"]))
    return {"items": items[offset : offset + limit], "total": len(items)}


@router.get("/clusters/{cluster_id}", response_model=Cluster)
def cluster(run_id: str, cluster_id: int, services: Services = Depends(get_services)) -> dict:
    found = next((c for c in services.run_data(run_id).clusters if c["cluster_id"] == cluster_id), None)
    if found is None:
        raise NotFound("Кластер не найден")
    return found


@router.get("/data-requests", response_model=DataRequestPage)
def data_requests(
    run_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    services: Services = Depends(get_services),
) -> dict:
    services.run_data(run_id)
    return views.data_requests(services.run_dir(run_id) / "current" / "out" / "data_requests.csv", limit, offset)
