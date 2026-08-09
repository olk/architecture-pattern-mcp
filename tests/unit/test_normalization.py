# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""
Unit tests for src/design_normalization.py.

Verifies denormalize_contracts: flattening component.api_contract and
component.data_models (is_shared=True) into top-level lists.
"""


from src.design_normalization import denormalize_contracts
from src.schemas import ArchitectureDesign
from src.schemas.components import Component, Relationship
from src.schemas.contracts import (
    ApiContract,
    DataModel,
    EventContract,
    ModelField,
)
from src.schemas.design import ArchitectureOverview
from src.schemas.enums import ArchitectureStyle, PatternCategory


def _make_design(
    *,
    api_contracts: list[ApiContract] | None = None,
    shared_data_models: list[DataModel] | None = None,
    event_contracts: list[EventContract] | None = None,
    components: list[Component] | None = None,
    relationships: list[Relationship] | None = None,
) -> ArchitectureDesign:
    """Helper: build a minimal ArchitectureDesign for testing."""
    return ArchitectureDesign(
        overview=ArchitectureOverview(
            style=ArchitectureStyle.MICROSERVICES,
            category=PatternCategory.STRUCTURAL,
            principles=["single responsibility"],
        ),
        components=components or [
            Component(
                id="svc",
                name="Service",
                type="service",
                description="A service",
                responsibilities=["process"],
            )
        ],
        relationships=relationships or [],
        patterns=[],
        quality_attributes={},
        api_contracts=api_contracts or [],
        shared_data_models=shared_data_models or [],
        event_contracts=event_contracts or [],
    )


class TestDenormalizeApiContracts:
    def test_promotes_component_api_contract(self):
        """Empty top-level + component with api_contract → promoted to top-level."""
        comp = Component(
            id="user-service",
            name="User Service",
            type="service",
            description="User service",
            responsibilities=["user management"],
            api_contract=ApiContract(
                component_id="user-service",
                base_path="/api/v1/users",
                endpoints=[],
            ),
        )
        design = _make_design(components=[comp])
        result = denormalize_contracts(design)

        assert len(result.api_contracts) == 1
        assert result.api_contracts[0].component_id == "user-service"
        assert result.api_contracts[0].base_path == "/api/v1/users"

    def test_top_level_wins_on_collision(self):
        """Top-level entry preserved when both top-level and component have same component_id."""
        top_level = ApiContract(
            component_id="user-service",
            base_path="/api/v1/users-explicit",
            endpoints=[],
        )
        comp = Component(
            id="user-service",
            name="User Service",
            type="service",
            description="User service",
            responsibilities=["user management"],
            api_contract=ApiContract(
                component_id="user-service",
                base_path="/api/v1/users-from-component",
                endpoints=[],
            ),
        )
        design = _make_design(api_contracts=[top_level], components=[comp])
        result = denormalize_contracts(design)

        assert len(result.api_contracts) == 1
        assert result.api_contracts[0].base_path == "/api/v1/users-explicit"

    def test_dedupes_duplicate_top_level_entries(self):
        """Two top-level entries with same component_id → one kept."""
        entry = ApiContract(
            component_id="user-service",
            base_path="/api/v1/users",
            endpoints=[],
        )
        design = _make_design(api_contracts=[entry, entry])
        result = denormalize_contracts(design)

        assert len(result.api_contracts) == 1

    def test_no_component_contract_skipped(self):
        """Component without api_contract → skipped silently."""
        comp = Component(
            id="monitoring",
            name="Monitoring",
            type="monitoring",
            description="Monitoring",
            responsibilities=["monitor"],
        )
        design = _make_design(components=[comp])
        result = denormalize_contracts(design)

        assert result.api_contracts == []


class TestDenormalizeSharedDataModels:
    def test_promotes_shared_data_model(self):
        """Empty top-level + component with is_shared=True → promoted."""
        comp = Component(
            id="user-service",
            name="User Service",
            type="service",
            description="User service",
            responsibilities=["user management"],
            data_models=[
                DataModel(
                    name="User",
                    is_shared=True,
                    fields=[ModelField(name="id", type="str", required=True)],
                )
            ],
        )
        design = _make_design(components=[comp])
        result = denormalize_contracts(design)

        assert len(result.shared_data_models) == 1
        assert result.shared_data_models[0].name == "User"

    def test_local_model_not_promoted(self):
        """component data_model with is_shared=False → stays local (not in top-level)."""
        comp = Component(
            id="order-service",
            name="Order Service",
            type="service",
            description="Order service",
            responsibilities=["order management"],
            data_models=[
                DataModel(
                    name="OrderItem",
                    is_shared=False,
                    fields=[ModelField(name="qty", type="int", required=True)],
                )
            ],
        )
        design = _make_design(components=[comp])
        result = denormalize_contracts(design)

        assert result.shared_data_models == []

    def test_dedupes_shared_models_by_name_and_is_shared(self):
        """Same name with different is_shared → both kept as separate entries."""
        m1 = DataModel(
            name="User",
            is_shared=False,
            fields=[ModelField(name="id", type="str", required=True)],
        )
        m2 = DataModel(
            name="User",
            is_shared=True,
            fields=[ModelField(name="id", type="str", required=True)],
        )
        design = _make_design(shared_data_models=[m1, m2])
        result = denormalize_contracts(design)

        assert len(result.shared_data_models) == len([m1, m2])

    def test_top_level_wins_on_shared_model_collision(self):
        """Top-level shared model preserved when component also has same (name, is_shared)."""
        shared = DataModel(
            name="User",
            is_shared=True,
            fields=[ModelField(name="id", type="str", required=True)],
        )
        comp = Component(
            id="order-service",
            name="Order Service",
            type="service",
            description="Order service",
            responsibilities=["order management"],
            data_models=[shared],
        )
        design = _make_design(shared_data_models=[shared], components=[comp])
        result = denormalize_contracts(design)

        assert len(result.shared_data_models) == 1


class TestDenormalizeEventContracts:
    def test_dedupes_event_contracts_by_name(self):
        """Duplicate event_name → one kept."""
        ec = EventContract(
            event_name="user.created",
            payload_schema={"type": "object"},
            published_by="user-service",
        )
        design = _make_design(event_contracts=[ec, ec])
        result = denormalize_contracts(design)

        assert len(result.event_contracts) == 1
        assert result.event_contracts[0].event_name == "user.created"


class TestDenormalizeIdempotency:
    def test_idempotent_under_repeated_application(self):
        """Two consecutive calls yield the same result."""
        comp = Component(
            id="user-service",
            name="User Service",
            type="service",
            description="User service",
            responsibilities=["user management"],
            api_contract=ApiContract(
                component_id="user-service",
                base_path="/api/v1/users",
                endpoints=[],
            ),
        )
        design = _make_design(components=[comp])
        first = denormalize_contracts(design)
        second = denormalize_contracts(first)

        assert first.api_contracts == second.api_contracts
        assert first.shared_data_models == second.shared_data_models
        assert first.event_contracts == second.event_contracts

    def test_round_trip_through_model_dump_and_validate(self):
        """model_dump → model_validate preserves promoted lists."""
        comp = Component(
            id="user-service",
            name="User Service",
            type="service",
            description="User service",
            responsibilities=["user management"],
            api_contract=ApiContract(
                component_id="user-service",
                base_path="/api/v1/users",
                endpoints=[],
            ),
            data_models=[
                DataModel(
                    name="User",
                    is_shared=True,
                    fields=[ModelField(name="id", type="str", required=True)],
                )
            ],
        )
        design = _make_design(components=[comp])
        result = denormalize_contracts(design)

        dumped = result.model_dump()
        revalidated = ArchitectureDesign.model_validate(dumped)

        assert len(revalidated.api_contracts) == len(result.api_contracts)
        assert len(revalidated.shared_data_models) == len(result.shared_data_models)


class TestDenormalizeNoOp:
    def test_no_op_when_no_component_contracts(self):
        """Empty components + empty top-level → unchanged (empty lists)."""
        design = _make_design(
            api_contracts=[],
            shared_data_models=[],
            event_contracts=[],
        )
        result = denormalize_contracts(design)

        assert result.api_contracts == []
        assert result.shared_data_models == []
        assert result.event_contracts == []


class TestDenormalizePreservesOtherFields:
    def test_preserves_other_fields_unchanged(self):
        """overview, components, relationships, patterns untouched."""
        comp = Component(
            id="user-service",
            name="User Service",
            type="service",
            description="User service",
            responsibilities=["user management"],
            api_contract=ApiContract(
                component_id="user-service",
                base_path="/api/v1/users",
                endpoints=[],
            ),
        )
        rel = Relationship(
            source="api-gateway",
            target="user-service",
            type="http",
            description="Proxies to user service",
        )
        design = _make_design(
            components=[comp],
            relationships=[rel],
        )
        result = denormalize_contracts(design)

        assert result.overview.style == ArchitectureStyle.MICROSERVICES
        assert len(result.components) == 1
        assert len(result.relationships) == 1
        assert result.relationships[0].source == "api-gateway"


class TestDenormalizeMultipleComponents:
    def test_multiple_components_promote_distinct_ids(self):
        """Two components with distinct api_contracts → two top-level entries."""
        comp_a = Component(
            id="user-service",
            name="User Service",
            type="service",
            description="User service",
            responsibilities=["user management"],
            api_contract=ApiContract(
                component_id="user-service",
                base_path="/api/v1/users",
                endpoints=[],
            ),
        )
        comp_b = Component(
            id="order-service",
            name="Order Service",
            type="service",
            description="Order service",
            responsibilities=["order management"],
            api_contract=ApiContract(
                component_id="order-service",
                base_path="/api/v1/orders",
                endpoints=[],
            ),
        )
        design = _make_design(components=[comp_a, comp_b])
        result = denormalize_contracts(design)

        assert len(result.api_contracts) == len([comp_a, comp_b])
        ids = {ac.component_id for ac in result.api_contracts}
        assert ids == {"user-service", "order-service"}
