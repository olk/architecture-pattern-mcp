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
Component and relationship schemas for architecture designs.

Defines the structural components of an architecture and their interactions.
"""

from pydantic import BaseModel, Field

from src.schemas.contracts import ApiContract, DataModel


class Component(BaseModel):
    """
    Architecture component definition.

    Represents a deployable unit with responsibilities, interfaces, and technology choices.
    """

    id: str = Field(
        ...,
        pattern=r"^[a-z][a-z0-9_-]*$",
        description="Unique component identifier (kebab-case)"
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Human-readable component name"
    )
    type: str = Field(
        ...,
        min_length=1,
        description="Component type (e.g. 'service', 'gateway', 'database')"
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Component description"
    )
    responsibilities: list[str] = Field(
        ...,
        min_length=1,
        description="Key responsibilities"
    )
    interfaces: list[str] = Field(
        default_factory=list,
        description="Exposed interfaces (e.g. ['REST', 'gRPC', 'Events'])"
    )
    technology_stack: list[str] = Field(
        default_factory=list,
        description="Technologies used (e.g. ['FastAPI', 'PostgreSQL', 'Redis'])"
    )
    api_contract: ApiContract | None = Field(
        default=None,
        description="REST API contract with endpoints, schemas, and auth"
    )
    data_models: list[DataModel] = Field(
        default_factory=list,
        description="Data models specific to this component"
    )
    config_requirements: list[str] = Field(
        default_factory=list,
        description="Required environment variables (e.g. ['DATABASE_URL', 'REDIS_URL'])"
    )


class Relationship(BaseModel):
    """
    Directed relationship between two components.
    """

    source: str = Field(
        ...,
        description="Source component ID"
    )
    target: str = Field(
        ...,
        description="Target component ID"
    )
    type: str = Field(
        ...,
        description="Relationship type (e.g. 'sync', 'async', 'data-flow')"
    )
    description: str = Field(
        ...,
        description="Human-readable description of the interaction"
    )
