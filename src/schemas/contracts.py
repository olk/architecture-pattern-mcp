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
API, data, and event contract schemas for architecture designs.

These models define the structure of contracts between components:
- ApiEndpoint / ApiContract: REST API interfaces
- ModelField / DataModel: data entity definitions
- EventContract: async event/message interfaces
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ApiEndpoint(BaseModel):
    """
    Single REST API endpoint definition.

    Used within ApiContract.endpoints to describe each operation.
    """

    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"] = Field(
        ...,
        description="HTTP method"
    )
    path: str = Field(
        ...,
        description="Endpoint path, e.g. '/users/{user_id}'"
    )
    summary: str = Field(
        default="",
        description="Brief endpoint description"
    )
    request_schema: dict[str, Any] | None = Field(
        default=None,
        description="JSON Schema for request body"
    )
    response_schema: dict[str, Any] | None = Field(
        default=None,
        description="JSON Schema for response body"
    )
    auth_required: bool = Field(
        default=True,
        description="Whether authentication is required"
    )
    tags: list[str] = Field(
        default_factory=list,
        description="OpenAPI tags for grouping"
    )


class ApiContract(BaseModel):
    """
    REST API contract for a component.

    Collects all endpoints under a shared base_path.
    """

    component_id: str = Field(
        ...,
        description="Reference to component this API belongs to"
    )
    base_path: str = Field(
        ...,
        description="Base path for all endpoints, e.g. '/api/v1/users'"
    )
    endpoints: list[ApiEndpoint] = Field(
        default_factory=list,
        description="List of endpoint definitions"
    )
    description: str = Field(
        default="",
        description="Overall API description"
    )


class ModelField(BaseModel):
    """
    Single field within a DataModel.
    """

    name: str = Field(
        ...,
        description="Field name"
    )
    type: str = Field(
        ...,
        description="Field type (str, int, float, bool, datetime, list, dict)"
    )
    required: bool = Field(
        default=True,
        description="Whether field is required"
    )
    description: str = Field(
        default="",
        description="Field description"
    )
    default: Any | None = Field(
        default=None,
        description="Default value if any"
    )


class DataModel(BaseModel):
    """
    Data entity definition shared across components.
    """

    name: str = Field(
        ...,
        description="Model name, e.g. 'User', 'Order'"
    )
    fields: list[ModelField] = Field(
        default_factory=list,
        description="Model fields"
    )
    description: str = Field(
        default="",
        description="Model description"
    )
    is_shared: bool = Field(
        default=False,
        description="Whether this model is shared across components"
    )


class EventContract(BaseModel):
    """
    Async event/message contract between components.

    Published by one component, consumed by one or more others.
    """

    event_name: str = Field(
        ...,
        description="Event name, e.g. 'user.created', 'order.completed'"
    )
    payload_schema: dict[str, Any] = Field(
        ...,
        description="JSON Schema for event payload"
    )
    published_by: str = Field(
        ...,
        description="Component ID that publishes this event"
    )
    consumed_by: list[str] = Field(
        default_factory=list,
        description="Component IDs that consume this event"
    )
    description: str = Field(
        default="",
        description="Event description"
    )

