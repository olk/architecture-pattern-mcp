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

# Tests for QualityMetrics schema
# Validates: FR-17, FR-18, IC-10, IC-11
# Test scenarios: SCEN-3, SCEN-4
# Acceptance criteria: AC-18

import pytest
from pydantic import ValidationError

from src.schemas.quality import QualityMetrics


class TestQualityMetrics:
    """Test suite for QualityMetrics Pydantic model.
    
    Validates requirements:
    - FR-17: ArchitecturePipeline uses QualityMetrics
    - FR-18: testability property with default value 7.0
    - IC-10: 5 required properties with values in range 0-10
    - IC-11: testability property defaults to 7.0
    
    Test scenarios:
    - SCEN-3: QualityMetrics validates 5 required properties
    - SCEN-4: testability defaults to 7.0
    """

    # SCEN-3: QualityMetrics validates 5 required properties
    def test_quality_metrics_5_required_properties(self):
        """SCEN-3: QualityMetrics validates 5 required properties.
        
        Verifies IC-10: QualityMetrics has all 5 required properties.
        Creates QualityMetrics with all 5 required properties.
        """
        # IC-10: 5 required properties - maintainability, scalability, reliability, security, performance
        qm = QualityMetrics(
            maintainability=8.0,
            scalability=7.5,
            reliability=9.0,
            security=8.5,
            performance=7.0
        )

        assert qm.maintainability == 8.0
        assert qm.scalability == 7.5
        assert qm.reliability == 9.0
        assert qm.security == 8.5
        assert qm.performance == 7.0

    def test_quality_metrics_missing_required_property_raises_error(self):
        """SCEN-3: Missing required property should raise ValidationError.
        
        Verifies IC-10: All 5 required properties are mandatory.
        """
        with pytest.raises(ValidationError) as exc_info:
            QualityMetrics(
                maintainability=8.0,
                # Missing scalability, reliability, security, performance
            )

        errors = exc_info.value.errors()
        assert len(errors) == 4  # 4 missing required fields

    # SCEN-4: testability defaults to 7.0
    def test_testability_defaults_to_7_0(self):
        """SCEN-4: testability defaults to 7.0.
        
        AC-18: Verify testability property exists with default 7.0.
        IC-11: testability property defaults to 7.0.
        Creates QualityMetrics without specifying testability.
        """
        qm = QualityMetrics(
            maintainability=8.0,
            scalability=7.5,
            reliability=9.0,
            security=8.5,
            performance=7.0
        )

        # AC-18: testability property exists with default 7.0
        assert hasattr(qm, 'testability')
        assert qm.testability == 7.0

    def test_testability_explicit_value(self):
        """testability can be explicitly set to any valid value.
        
        Verifies IC-11: testability can be overridden.
        """
        qm = QualityMetrics(
            maintainability=8.0,
            scalability=7.5,
            reliability=9.0,
            security=8.5,
            performance=7.0,
            testability=9.5
        )

        assert qm.testability == 9.5

    # IC-10: Values in range 0-10
    def test_values_at_minimum_boundary(self):
        """IC-10: Values can be 0.0 (minimum boundary).
        
        Verifies all 5 required properties accept minimum boundary value.
        """
        qm = QualityMetrics(
            maintainability=0.0,
            scalability=0.0,
            reliability=0.0,
            security=0.0,
            performance=0.0
        )

        assert qm.maintainability == 0.0
        assert qm.scalability == 0.0
        assert qm.reliability == 0.0
        assert qm.security == 0.0
        assert qm.performance == 0.0

    def test_values_at_maximum_boundary(self):
        """IC-10: Values can be 10.0 (maximum boundary).
        
        Verifies all 5 required properties accept maximum boundary value.
        """
        qm = QualityMetrics(
            maintainability=10.0,
            scalability=10.0,
            reliability=10.0,
            security=10.0,
            performance=10.0
        )

        assert qm.maintainability == 10.0
        assert qm.scalability == 10.0
        assert qm.reliability == 10.0
        assert qm.security == 10.0
        assert qm.performance == 10.0

    def test_value_below_range_raises_error(self):
        """IC-10: Values below 0.0 should raise ValidationError.
        
        Verifies ge=0.0 constraint is enforced.
        """
        with pytest.raises(ValidationError) as exc_info:
            QualityMetrics(
                maintainability=-0.1,
                scalability=5.0,
                reliability=5.0,
                security=5.0,
                performance=5.0
            )

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]['loc'] == ('maintainability',)

    def test_value_above_range_raises_error(self):
        """IC-10: Values above 10.0 should raise ValidationError.
        
        Verifies le=10.0 constraint is enforced.
        """
        with pytest.raises(ValidationError) as exc_info:
            QualityMetrics(
                maintainability=10.1,
                scalability=5.0,
                reliability=5.0,
                security=5.0,
                performance=5.0
            )

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]['loc'] == ('maintainability',)

    # IC-11: testability range 0-10
    def test_testability_at_minimum_boundary(self):
        """IC-11: testability can be 0.0 (minimum boundary).
        
        Verifies testability range includes 0.0.
        """
        qm = QualityMetrics(
            maintainability=5.0,
            scalability=5.0,
            reliability=5.0,
            security=5.0,
            performance=5.0,
            testability=0.0
        )

        assert qm.testability == 0.0

    def test_testability_at_maximum_boundary(self):
        """IC-11: testability can be 10.0 (maximum boundary).
        
        Verifies testability range includes 10.0.
        """
        qm = QualityMetrics(
            maintainability=5.0,
            scalability=5.0,
            reliability=5.0,
            security=5.0,
            performance=5.0,
            testability=10.0
        )

        assert qm.testability == 10.0

    def test_testability_default_respects_range(self):
        """IC-11: testability default 7.0 is within valid range.
        
        Verifies default value 7.0 is valid for range 0-10.
        """
        qm = QualityMetrics(
            maintainability=5.0,
            scalability=5.0,
            reliability=5.0,
            security=5.0,
            performance=5.0
        )

        # Default is 7.0 which is within range 0-10
        assert 0.0 <= qm.testability <= 10.0
        assert qm.testability == 7.0

    def test_testability_below_range_raises_error(self):
        """IC-11: testability below 0.0 should raise ValidationError.
        
        Verifies testability ge=0.0 constraint is enforced.
        """
        with pytest.raises(ValidationError) as exc_info:
            QualityMetrics(
                maintainability=5.0,
                scalability=5.0,
                reliability=5.0,
                security=5.0,
                performance=5.0,
                testability=-0.1
            )

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]['loc'] == ('testability',)

    def test_testability_above_range_raises_error(self):
        """IC-11: testability above 10.0 should raise ValidationError.
        
        Verifies testability le=10.0 constraint is enforced.
        """
        with pytest.raises(ValidationError) as exc_info:
            QualityMetrics(
                maintainability=5.0,
                scalability=5.0,
                reliability=5.0,
                security=5.0,
                performance=5.0,
                testability=10.1
            )

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]['loc'] == ('testability',)
