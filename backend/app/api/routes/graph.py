"""Graph data aggregation API — returns nodes + edges for the knowledge graph visualization."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.boq_item import BoqItem
from app.models.entity_tag import EntityTag
from app.models.knowledge_link import KnowledgeLink
from app.models.line_item_quota_binding import LineItemQuotaBinding
from app.models.material_price import MaterialPrice
from app.models.project import Project
from app.models.quota_item import QuotaItem
from app.models.quota_resource_detail import QuotaResourceDetail
from app.models.quota_resource_material_mapping import QuotaResourceMaterialMapping
from app.models.rule_package import RulePackage
from app.models.tag import Tag
from app.schemas.knowledge_graph import GraphDataOut, GraphEdge, GraphNode

router = APIRouter(tags=["graph"])


def _node_id(entity_type: str, entity_id: int) -> str:
    return f"{entity_type}:{entity_id}"


@router.get("/graph/data", response_model=GraphDataOut)
def get_graph_data(
    scope: str = Query("global", description="global | project | entity"),
    project_id: int | None = Query(None),
    entity_type: str | None = Query(None),
    entity_id: int | None = Query(None),
    depth: int = Query(2, ge=1, le=3),
    types: str | None = Query(None, description="Comma-separated node types to include"),
    tag_filter: str | None = Query(None, description="Comma-separated tag names to filter by"),
    db: Session = Depends(get_db),
):
    """Build a graph of nodes and edges from the database.

    Scope controls the starting point:
    - global: all projects (limited to keep graph manageable)
    - project: a single project and its descendants
    - entity: a single entity and its neighbours up to `depth` hops
    """
    allowed_types = set(types.split(",")) if types else None
    tag_names = set(tag_filter.split(",")) if tag_filter else None

    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    def _add_node(ntype: str, nid: int, label: str, props: dict | None = None):
        if allowed_types and ntype not in allowed_types:
            return
        key = _node_id(ntype, nid)
        if key not in nodes:
            nodes[key] = GraphNode(id=key, type=ntype, label=label, properties=props or {})

    def _add_edge(src_type: str, src_id: int, tgt_type: str, tgt_id: int, etype: str, label: str = ""):
        src_key = _node_id(src_type, src_id)
        tgt_key = _node_id(tgt_type, tgt_id)
        if src_key in nodes and tgt_key in nodes:
            edges.append(GraphEdge(source=src_key, target=tgt_key, type=etype, label=label))

    # ── 1. Collect projects ──────────────────────────────────────────────
    if scope == "project" and project_id:
        projects = db.query(Project).filter(Project.id == project_id).all()
    elif scope == "entity" and entity_type == "project" and entity_id:
        projects = db.query(Project).filter(Project.id == entity_id).all()
    else:
        projects = db.query(Project).limit(50).all()

    for p in projects:
        _add_node("project", p.id, p.name, {"region": p.region, "standard_type": p.standard_type, "currency": p.currency})

    project_ids = [p.id for p in projects]
    if not project_ids:
        return GraphDataOut(nodes=list(nodes.values()), edges=edges)

    # ── 2. BOQ items ─────────────────────────────────────────────────────
    boq_items = db.query(BoqItem).filter(BoqItem.project_id.in_(project_ids)).all()
    for b in boq_items:
        _add_node("boq_item", b.id, f"{b.code} {b.name}", {"unit": b.unit, "quantity": b.quantity, "division": b.division})

    # Project → BoqItem edges
    for b in boq_items:
        _add_edge("project", b.project_id, "boq_item", b.id, "fk", "包含")

    boq_ids = [b.id for b in boq_items]

    # ── 3. Bindings (BoqItem ↔ QuotaItem) ────────────────────────────────
    if boq_ids:
        bindings = db.query(LineItemQuotaBinding).filter(LineItemQuotaBinding.boq_item_id.in_(boq_ids)).all()
        quota_ids_from_bindings = list({b.quota_item_id for b in bindings})

        quotas = db.query(QuotaItem).filter(QuotaItem.id.in_(quota_ids_from_bindings)).all() if quota_ids_from_bindings else []
        for q in quotas:
            _add_node("quota_item", q.id, f"{q.quota_code} {q.name}", {"unit": q.unit, "chapter": q.chapter, "base_price": q.base_price})

        for b in bindings:
            _add_edge("boq_item", b.boq_item_id, "quota_item", b.quota_item_id, "binding", f"系数:{b.coefficient}")
    else:
        quota_ids_from_bindings = []

    # ── 4. Quota resource details → materials (depth >= 2) ───────────────
    if depth >= 2 and quota_ids_from_bindings:
        resources = db.query(QuotaResourceDetail).filter(
            QuotaResourceDetail.quota_item_id.in_(quota_ids_from_bindings)
        ).all()

        # Collect material_price_ids from mappings
        resource_ids = [r.id for r in resources]
        mappings = (
            db.query(QuotaResourceMaterialMapping)
            .filter(QuotaResourceMaterialMapping.resource_detail_id.in_(resource_ids))
            .all()
        ) if resource_ids else []

        mat_price_ids = list({m.material_price_id for m in mappings})
        mat_prices = db.query(MaterialPrice).filter(MaterialPrice.id.in_(mat_price_ids)).all() if mat_price_ids else []

        for mp in mat_prices:
            _add_node("material_price", mp.id, f"{mp.name} ({mp.spec})", {
                "unit": mp.unit, "unit_price": mp.unit_price, "region": mp.region, "source": mp.source,
            })

        # Edges: quota → material (via resource details + mapping)
        res_to_quota = {r.id: r.quota_item_id for r in resources}
        for m in mappings:
            qid = res_to_quota.get(m.resource_detail_id)
            if qid:
                _add_edge("quota_item", qid, "material_price", m.material_price_id, "resource", "使用材料")

    # ── 5. Rule packages ─────────────────────────────────────────────────
    rp_ids = list({p.rule_package_id for p in projects if p.rule_package_id})
    if rp_ids:
        rps = db.query(RulePackage).filter(RulePackage.id.in_(rp_ids)).all()
        for rp in rps:
            _add_node("rule_package", rp.id, rp.name, {"region": rp.region, "tax_rate": rp.tax_rate})
        for p in projects:
            if p.rule_package_id:
                _add_edge("project", p.id, "rule_package", p.rule_package_id, "fk", "适用规则")

    # ── 6. Tags ──────────────────────────────────────────────────────────
    all_entity_keys = list(nodes.keys())
    if all_entity_keys:
        # Build (type, id) pairs for existing nodes
        entity_pairs = []
        for key in all_entity_keys:
            parts = key.split(":", 1)
            if len(parts) == 2:
                entity_pairs.append((parts[0], int(parts[1])))

        # Fetch entity_tags for all collected entities
        entity_tags = db.query(EntityTag, Tag).join(Tag, EntityTag.tag_id == Tag.id).all()
        for et, tag in entity_tags:
            nkey = _node_id(et.entity_type, et.entity_id)
            if nkey in nodes:
                # Add tag node
                tag_key = _node_id("tag", tag.id)
                if tag_key not in nodes:
                    if not allowed_types or "tag" in allowed_types:
                        nodes[tag_key] = GraphNode(
                            id=tag_key, type="tag", label=tag.name,
                            properties={"color": tag.color, "category": tag.category},
                        )
                # Add tag edge
                if tag_key in nodes:
                    edges.append(GraphEdge(source=nkey, target=tag_key, type="tag", label=""))
                # Annotate node with tag names
                nodes[nkey].tags.append(tag.name)

    # ── 7. Knowledge links (soft associations) ───────────────────────────
    k_links = db.query(KnowledgeLink).all()
    for kl in k_links:
        src_key = _node_id(kl.source_type, kl.source_id)
        tgt_key = _node_id(kl.target_type, kl.target_id)
        if src_key in nodes and tgt_key in nodes:
            edges.append(GraphEdge(
                source=src_key, target=tgt_key,
                type="knowledge_link", label=kl.label or kl.link_type,
            ))

    # ── 8. Optional tag filter ───────────────────────────────────────────
    if tag_names:
        keep_keys = {k for k, n in nodes.items() if n.type == "tag" or (set(n.tags) & tag_names)}
        nodes = {k: v for k, v in nodes.items() if k in keep_keys}
        edges = [e for e in edges if e.source in nodes and e.target in nodes]

    return GraphDataOut(nodes=list(nodes.values()), edges=edges)
