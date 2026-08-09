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
src/resources/templates.py - Architecture template definitions.

Implements §9.4 of the implementation guide:
LayeredArchitectureTemplate with three layers (Presentation, Business Logic, Data Access).
"""

from pydantic import BaseModel, Field


class LayerDefinition(BaseModel):
    name: str
    description: str
    components: list[str]
    patterns: list[str]


class LayeredArchitectureTemplate(BaseModel):
    name: str = "layered-architecture"
    description: str = "N-tier layered architecture template"
    layers: list[LayerDefinition] = Field(
        default_factory=lambda: [
            LayerDefinition(
                name="Presentation Layer",
                description="Handles user interface and API exposure",
                components=["Web UI", "REST API", "WebSocket Handler"],
                patterns=["MVC", "Front Controller"],
            ),
            LayerDefinition(
                name="Business Logic Layer",
                description="Contains core application logic and rules",
                components=["Services", "Domain Models", "Validators"],
                patterns=["Transaction Script", "Domain Model", "Service Layer"],
            ),
            LayerDefinition(
                name="Data Access Layer",
                description="Manages data persistence and retrieval",
                components=["Repositories", "ORM", "Query Builders"],
                patterns=["Repository", "Unit of Work", "Data Mapper"],
            ),
        ]
    )
    best_practices: list[str] = Field(
        default_factory=lambda: [
            "Layer dependencies should only go downward",
            "Each layer should have minimal knowledge of adjacent layers",
            "Use dependency injection to decouple layers",
            "Keep business logic free of infrastructure concerns",
        ]
    )


RESOURCES: dict[str, BaseModel] = {
    "layered-architecture-template": LayeredArchitectureTemplate(),
}
