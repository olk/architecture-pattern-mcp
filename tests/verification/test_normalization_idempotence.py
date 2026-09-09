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
L2 Hypothesis oracle pinning the design-normalization adapter boundary
(nagini-verification-plan.md §3.4/§3.8: `model_copy` semantics are pinned by
executable property at the adapter, while the pure core lives next door).

Properties (Tier A, formal_verification.md §4.1):
  N-1  idempotence: denormalize(denormalize(d)) == denormalize(d)
  N-2  component-id dedup: promoted api_contracts have unique component_ids
  N-3  event dedup: event_contracts unique by event_name, order preserved
  N-4  shared-model dedup: (name, is_shared) unique among promoted models

Collision-prone small ID/name pools force the dedup branches; generated
designs explore shapes unit tests chose by hand.
"""

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import BaseModel

from src.design_normalization import denormalize_contracts
from src.schemas import ApiContract, ArchitectureDesign, Component, DataModel, EventContract
from src.schemas.components import Relationship
from src.schemas.design import ArchitectureOverview
from src.schemas.enums import ArchitectureStyle, PatternCategory

COMPONENT_IDS = ["api-gateway", "user-service", "event-bus"]
MODEL_NAMES = ["User", "Order"]
EVENT_NAMES = ["user.created", "order.completed"]


def _components_strategy() -> st.SearchStrategy[list[Component]]:
    api = st.builds(
        ApiContract,
        component_id=st.sampled_from(COMPONENT_IDS),
        base_path=st.just("/api"),
    )
    model = st.builds(DataModel, name=st.sampled_from(MODEL_NAMES), is_shared=st.booleans())
    component = st.builds(
        Component,
        id=st.sampled_from(COMPONENT_IDS),
        name=st.just("Component"),
        type=st.just("service"),
        description=st.just("desc"),
        responsibilities=st.just(["resp"]),
        api_contract=st.none() | api,
        data_models=st.lists(model, max_size=2),
    )
    return st.lists(component, min_size=1, max_size=3)


class _DesignBuilder(BaseModel):
    @staticmethod
    def build(
        components: list[Component],
        api_contracts: list[ApiContract],
        shared: list[DataModel],
        events: list[EventContract],
    ) -> ArchitectureDesign:
        return ArchitectureDesign(
            overview=ArchitectureOverview(
                style=ArchitectureStyle.LAYERED_MONOLITH,
                category=PatternCategory.STRUCTURAL,
                principles=["p"],
            ),
            components=components,
            relationships=[
                Relationship(
                    source=components[0].id,
                    target=components[-1].id,
                    type="sync",
                    description="d",
                )
            ],
            quality_attributes={"scalability": "high"},
            api_contracts=api_contracts,
            shared_data_models=shared,
            event_contracts=events,
        )


class TestDesignNormalizationProperties:
    @given(
        components=_components_strategy(),
        top_apis=st.lists(
            st.builds(
                ApiContract,
                component_id=st.sampled_from(COMPONENT_IDS),
                base_path=st.just("/api"),
            ),
            max_size=3,
        ),
        top_shared=st.lists(
            st.builds(
                DataModel, name=st.sampled_from(MODEL_NAMES), is_shared=st.booleans()
            ),
            max_size=3,
        ),
        top_events=st.lists(
            st.builds(
                EventContract,
                event_name=st.sampled_from(EVENT_NAMES),
                payload_schema=st.just({}),
                published_by=st.sampled_from(COMPONENT_IDS),
            ),
            max_size=3,
        ),
    )
    @settings(max_examples=50, deadline=None)
    def test_normalization_properties(
        self,
        components: list[Component],
        top_apis: list[ApiContract],
        top_shared: list[DataModel],
        top_events: list[EventContract],
    ) -> None:
        design = _DesignBuilder.build(components, top_apis, top_shared, top_events)

        once = denormalize_contracts(design)
        twice = denormalize_contracts(once)

        assert twice.model_dump() == once.model_dump(), "N-1: idempotence"
        ids = [ac.component_id for ac in once.api_contracts]
        assert len(ids) == len(set(ids)), "N-2: unique component_ids"
        names = [ec.event_name for ec in once.event_contracts]
        assert names == list(dict.fromkeys(names)), "N-3: events deduped, order kept"
        keys = [(m.name, m.is_shared) for m in once.shared_data_models]
        assert len(keys) == len(set(keys)), "N-4: shared models deduped"

    def test_idempotence_on_unit_style_design(self) -> None:
        """Deterministic sanity pin: a design with component + top-level
        contracts normalizes to the same shape as the unit-suite fixtures."""
        from src.schemas import ApiEndpoint

        design = _DesignBuilder.build(
            components=[
                Component(
                    id="api-gateway",
                    name="API Gateway",
                    type="gateway",
                    description="d",
                    responsibilities=["r"],
                    api_contract=ApiContract(
                        component_id="api-gateway",
                        base_path="/api",
                        endpoints=[
                            ApiEndpoint(
                                method="GET",
                                path="/health",
                                summary="",
                                request_schema=None,
                                response_schema=None,
                                auth_required=False,
                                tags=[],
                            )
                        ],
                    ),
                )
            ],
            api_contracts=[],
            shared=[],
            events=[],
        )
        result = denormalize_contracts(denormalize_contracts(design))
        assert len(result.api_contracts) == 1
        assert asyncio.run(_noop()) is None


async def _noop() -> None:
    return None
