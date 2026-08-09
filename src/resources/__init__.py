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
src/resources/__init__.py - Public exports for the resources package.

Re-exports all public types so callers can import from a single place:
    from src.resources import PatternResource, RESOURCES, LayeredArchitectureTemplate, ...

Note: COMPONENT_BLUEPRINTS is NOT a module-level constant because it requires
a live PatternLoader instance to build. Use build_component_blueprints(loader)
to construct it at server startup inside the lifespan context.
"""

from src.resources.components import (
    ComponentDefinition,
    build_component_blueprints,
)
from src.resources.patterns import PatternResource
from src.resources.templates import (
    RESOURCES,
    LayerDefinition,
    LayeredArchitectureTemplate,
)

__all__ = [
    "RESOURCES",
    "ComponentDefinition",
    "LayerDefinition",
    "LayeredArchitectureTemplate",
    "PatternResource",
    "build_component_blueprints",
]
