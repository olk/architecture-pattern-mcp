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
Architecture design schemas.

Defines the complete architecture design output including overview, components,
relationships, and deployment strategy.
"""

from pydantic import BaseModel, Field

from src.schemas.components import Component, Relationship
from src.schemas.contracts import ApiContract, DataModel, EventContract
from src.schemas.enums import ArchitectureStyle, PatternCategory


class ArchitectureOverview(BaseModel):
    """
    Top-level architecture overview.

    Summarises the style, category, guiding principles, and constraints.
    """

    style: ArchitectureStyle = Field(
        ...,
        description="Architecture style from ArchitectureStyle enum (§4.2.2)"
    )
    category: PatternCategory = Field(
        ...,
        description="Pattern category (messaging, structural, cloud, data, ai_cognitive, specialized, api_gateway, coordination, dataflow, presentation)"
    )
    principles: list[str] = Field(
        ...,
        min_length=1,
        description="Guiding architectural principles"
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Architectural constraints and requirements"
    )


class ArchitectureDesign(BaseModel):
    """
    Complete architecture design output.

    Contains all structural, contractual, and deployment information for
    a generated architecture.
    """

    overview: ArchitectureOverview = Field(
        ...,
        description="Architecture overview"
    )
    components: list[Component] = Field(
        ...,
        min_length=1,
        description="Architecture components"
    )
    relationships: list[Relationship] = Field(
        default_factory=list,
        description="Component relationships"
    )
    quality_attributes: dict[str, str] = Field(
        default_factory=dict,
        description="Quality attribute annotations"
    )
    api_contracts: list[ApiContract] = Field(
        default_factory=list,
        description="REST API contracts for code generation"
    )
    shared_data_models: list[DataModel] = Field(
        default_factory=list,
        description="Data models shared across components"
    )
    event_contracts: list[EventContract] = Field(
        default_factory=list,
        description="Event contracts for async communication"
    )
