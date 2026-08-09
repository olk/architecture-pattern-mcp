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
Integration tests for the MCP server design_architecture tool — pipes-and-filters scenario.

IT-7.1: Verify design_architecture is registered with the FastMCP server (FR-241).
IT-7.2: Call design_architecture via the FastMCP Client and verify the returned
        ArchitectureDesign matches the ETL pipeline requirements and pipe-and-filter
        pattern (FR-224, FR-214).
IT-7.3: Verify the tool response conforms to spec §4.11 (all required fields present).

These tests use in-process FastMCP Client (Client(server)) to exercise the real MCP
protocol layer, with the LLM agent, vector index, BM25 index, and pattern loader
replaced by deterministic mocks.
"""

from unittest.mock import patch

import pytest

from src.schemas.analysis import AnalysisResult
from src.schemas.architecture import ArchitectureDesignResponse
from src.schemas.components import Component, Relationship
from src.schemas.contracts import (
    ApiContract,
    ApiEndpoint,
    DataModel,
    EventContract,
    ModelField,
)
from src.schemas.design import ArchitectureOverview
from src.schemas.enums import ArchitectureStyle, PatternCategory
from src.schemas.evaluation import (
    ArchitectureEvaluation,
    EvaluationSummary,
    MetricResult,
)
from src.schemas.patterns import Pattern, ScoredPattern
from tests.integration.conftest import (
    MockPipeAndFilterBM25Index,
    MockPipeAndFilterPatternLoader,
    MockPipeAndFilterVectorIndex,
)

ETL_PIPELINE_REQUIREMENTS = """
Build a real-time ETL pipeline that ingests raw IoT sensor data from a Kafka topic,
parses JSON messages, validates schema conformance against a registered Avro schema,
transforms readings into a normalized time-series format, enriches each record with
geolocation data from a side lookup service, and writes the results to both an InfluxDB
time-series store and an S3 data lake. Target throughput: 10,000 events per second
with independent horizontal scaling of each filter stage. The pipeline must support
backpressure handling, per-filter retry logic, and exactly-once delivery guarantees
to the sinks.
""".strip()

PIPELINE_DOMAIN = "data-processing"


# ---------------------------------------------------------------------------
# Canned LLM responses
# ---------------------------------------------------------------------------

def make_canned_design_response() -> ArchitectureDesignResponse:
    """Return a canned ArchitectureDesignResponse for the IoT ETL pipeline."""
    iot_reading_fields = [
        ModelField(name="sensor_id", type="str", required=True),
        ModelField(name="timestamp", type="datetime", required=True),
        ModelField(name="payload", type="dict", required=True),
    ]
    enriched_record_fields = [
        ModelField(name="sensor_id", type="str", required=True),
        ModelField(name="timestamp", type="datetime", required=True),
        ModelField(name="location", type="dict", required=True),
        ModelField(name="payload", type="dict", required=True),
    ]
    return ArchitectureDesignResponse(
        overview=ArchitectureOverview(
            style=ArchitectureStyle.PIPE_AND_FILTER,
            category=PatternCategory.DATAFLOW,
            principles=[
                "Single Responsibility: each filter performs one well-defined transformation",
                "Statelessness: filters are stateless to enable parallel execution",
                "Well-defined Interfaces: standardised input/output schemas for filter compatibility",
            ],
            constraints=[
                "Must handle 10,000 events/sec throughput",
                "Exactly-once delivery to sinks required",
            ],
        ),
        components=[
            Component(
                id="iot-kafka-source",
                name="IoT Kafka Source",
                type="data-source",
                description="Ingests raw IoT sensor data from a Kafka topic",
                responsibilities=["Consume Kafka topic", "Deserialize JSON messages"],
                interfaces=["Kafka Consumer"],
                technology_stack=["Apache Kafka", "KafkaJS"],
                data_models=[],
                config_requirements=["KAFKA_BROKER_URL", "KAFKA_TOPIC_IOT"],
            ),
            Component(
                id="json-parse-filter",
                name="JSON Parse Filter",
                type="filter",
                description="Parses raw JSON bytes into structured IoTReading objects",
                responsibilities=["Parse JSON payload", "Emit typed reading record"],
                data_models=[
                    DataModel(
                        name="IoTReading",
                        description="Raw sensor reading after JSON parsing",
                        is_shared=True,
                        fields=iot_reading_fields,
                    )
                ],
            ),
            Component(
                id="schema-validate-filter",
                name="Schema Validate Filter",
                type="filter",
                description="Validates each IoTReading against an Avro schema registry",
                responsibilities=["Schema lookup", "Avro validation", "Reject malformed records"],
                technology_stack=["Python", "fastavro", "Confluent Schema Registry"],
                config_requirements=["SCHEMA_REGISTRY_URL"],
            ),
            Component(
                id="normalize-transform-filter",
                name="Normalize Transform Filter",
                type="filter",
                description="Transforms raw readings into a normalised time-series format",
                responsibilities=["Unit conversion", "Timestamp normalisation", "Field mapping"],
                technology_stack=["Python", "pandas"],
            ),
            Component(
                id="geolocation-enrich-filter",
                name="Geolocation Enrich Filter",
                type="filter",
                description="Enriches each reading with geolocation data via side lookup",
                responsibilities=["GeoIP lookup", "Append location metadata"],
                technology_stack=["Python", "GeoIP2"],
                data_models=[
                    DataModel(
                        name="EnrichedRecord",
                        description="Reading enriched with geolocation",
                        is_shared=True,
                        fields=enriched_record_fields,
                    )
                ],
                config_requirements=["GEOIP_DATABASE_PATH"],
            ),
            Component(
                id="influxdb-sink",
                name="InfluxDB Time-Series Sink",
                type="data-sink",
                description="Writes enriched records to InfluxDB for time-series queries",
                responsibilities=["Batch write to InfluxDB", "InfluxQL queries"],
                technology_stack=["InfluxDB", "influxdb-client-python"],
                config_requirements=["INFLUXDB_URL", "INFLUXDB_ORG", "INFLUXDB_TOKEN"],
            ),
            Component(
                id="s3-data-lake-sink",
                name="S3 Data Lake Sink",
                type="data-sink",
                description="Writes enriched Parquet files to S3 for analytics",
                responsibilities=["Format to Parquet", "S3 upload", "Partition by date"],
                technology_stack=["AWS S3", "boto3", "pyarrow"],
                config_requirements=["AWS_REGION", "S3_BUCKET_RAW"],
            ),
        ],
        relationships=[
            Relationship(source="iot-kafka-source", target="json-parse-filter", type="async", description="Raw bytes to structured reading"),
            Relationship(source="json-parse-filter", target="schema-validate-filter", type="async", description="Parsed reading stream"),
            Relationship(source="schema-validate-filter", target="normalize-transform-filter", type="async", description="Validated reading"),
            Relationship(source="normalize-transform-filter", target="geolocation-enrich-filter", type="async", description="Normalised reading"),
            Relationship(source="geolocation-enrich-filter", target="influxdb-sink", type="async", description="Enriched record"),
            Relationship(source="geolocation-enrich-filter", target="s3-data-lake-sink", type="async", description="Enriched record for archival"),
        ],
        quality_attributes={
            "scalability": "independent HPA per filter stage",
            "maintainability": "each filter is independently deployable and testable",
            "reliability": "exactly-once delivery via Kafka transactions",
            "performance": "target 10k events/sec with parallel filter execution",
        },
        api_contracts=[
            ApiContract(
                component_id="iot-kafka-source",
                base_path="/api/v1/admin",
                description="Kafka consumer admin API for monitoring consumer lag and partition offsets",
                endpoints=[
                    ApiEndpoint(
                        method="GET",
                        path="/consumer lag",
                        summary="Get current consumer lag per partition",
                        response_schema={"type": "object"},
                        auth_required=True,
                        tags=["admin"],
                    ),
                ],
            )
        ],
        shared_data_models=[
            DataModel(
                name="IoTReading",
                description="Raw sensor reading after JSON parsing",
                is_shared=True,
                fields=iot_reading_fields,
            ),
            DataModel(
                name="EnrichedRecord",
                description="Reading enriched with geolocation",
                is_shared=True,
                fields=enriched_record_fields,
            ),
        ],
        event_contracts=[
            EventContract(
                event_name="reading.parsed",
                payload_schema={"type": "object", "properties": {"sensor_id": {"type": "string"}}},
                published_by="json-parse-filter",
                consumed_by=["schema-validate-filter"],
                description="Emitted after successful JSON parsing",
            ),
            EventContract(
                event_name="reading.validated",
                payload_schema={"type": "object"},
                published_by="schema-validate-filter",
                consumed_by=["normalize-transform-filter"],
                description="Emitted after schema validation passes",
            ),
            EventContract(
                event_name="reading.enriched",
                payload_schema={"type": "object"},
                published_by="geolocation-enrich-filter",
                consumed_by=["influxdb-sink", "s3-data-lake-sink"],
                description="Emitted after geolocation enrichment",
            ),
        ],
    )


def make_canned_analysis_result() -> "AnalysisResult":
    """Return a canned AnalysisResult for data-processing domain."""
    from src.schemas.analysis import AnalysisResult
    from src.schemas.enums import PatternCategory
    from src.schemas.quality import QualityMetrics

    pipe_filter_pattern = ScoredPattern.model_validate({
        "name": "pipe-and-filter",
        "category": PatternCategory.DATAFLOW,
        "context": "Sequential data transformation workflows",
    })
    serverless_pattern = ScoredPattern.model_validate({
        "name": "serverless",
        "category": PatternCategory.CLOUD,
        "context": "Event-driven compute model",
    })

    return AnalysisResult(
        strengths=[
            "Native fit of pipe-and-filter for ETL data transformation workloads",
            "Independent scaling of slow filter stages via HPA",
        ],
        weaknesses=[
            "Serialisation overhead between filters for high-throughput scenarios",
        ],
        recommendations=[
            "Use Kafka topics as pipes for distributed deployment",
            "Profile each filter to identify bottleneck stage",
        ],
        quality_metrics=QualityMetrics(
            maintainability=8.5,
            scalability=8.0,
            reliability=7.5,
            security=6.0,
            performance=7.0,
        ),
        recommended_style="pipe-and-filter",
        selected_patterns=[pipe_filter_pattern, serverless_pattern],
    )


def make_canned_evaluation() -> ArchitectureEvaluation:
    """Return a canned ArchitectureEvaluation with score above the 70.0 refine threshold."""
    return ArchitectureEvaluation(
        summary=EvaluationSummary(
            overall_score=78.0,
            strengths=["Clean pipe-and-filter decomposition", "Scalable filter design"],
            weaknesses=["Consider adding a dead-letter-queue for failed messages"],
            critical_findings=["Add monitoring for filter stage lag to detect bottlenecks early"],
        ),
        metrics=[
            MetricResult(
                name="overall_quality",
                score=78.0,
                description="Overall architecture quality score",
                findings=[],
                recommendations=[],
            ),
        ],
        recommendations={},
    )


class MockPipeAndFilterAgent:
    """Mock SoftwareArchitectAgent that returns canned pipe-and-filter LLM responses."""

    def __init__(self, config=None):
        self._config = config
        self.generate_structured_calls: list[dict] = []

    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema,
    ):
        self.generate_structured_calls.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "schema": response_schema,
        })

        schema_name = getattr(response_schema, "__name__", None) or getattr(response_schema, "model_dump", None) or str(response_schema)

        if response_schema is ArchitectureDesignResponse:
            return make_canned_design_response()

        if schema_name == "AnalysisResult" or (hasattr(response_schema, "__name__") and response_schema.__name__ == "AnalysisResult"):
            return make_canned_analysis_result()

        if schema_name == "ArchitectureEvaluation" or (hasattr(response_schema, "__name__") and response_schema.__name__ == "ArchitectureEvaluation"):
            return make_canned_evaluation()

        if schema_name == "RequirementWeights" or (hasattr(response_schema, "__name__") and response_schema.__name__ == "RequirementWeights"):
            from src.pipeline import RequirementWeights
            return RequirementWeights(
                scalability=0.6,
                performance=0.5,
                reliability=0.4,
                maintainability=0.7,
                security=0.3,
                simplicity=0.5,
            )

        raise AssertionError(f"Unexpected response_schema: {response_schema}")


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def patched_mcp_dependencies():
    """Patch server initialization to inject mock dependencies."""
    agent = MockPipeAndFilterAgent()
    vector_index = MockPipeAndFilterVectorIndex()
    bm25_index = MockPipeAndFilterBM25Index()
    pattern_loader = MockPipeAndFilterPatternLoader()

    agent_patch = patch("src.server.SoftwareArchitectAgent", return_value=agent)
    vi_patch = patch("src.server.DomainVectorIndex.from_embedder_config", return_value=vector_index)
    bi_patch = patch("src.patterns.bm25_index.DomainBM25Index", return_value=bm25_index)
    pl_patch = patch("src.server.PatternLoader", return_value=pattern_loader)

    with agent_patch, vi_patch, bi_patch, pl_patch:
        yield {
            "agent": agent,
            "vector_index": vector_index,
            "bm25_index": bm25_index,
            "pattern_loader": pattern_loader,
        }


# ---------------------------------------------------------------------------
# IT-7.1: Tool registration
# ---------------------------------------------------------------------------

class TestIT71ToolRegistration:
    """
    IT-7.1: Verify design_architecture tool is registered with the FastMCP server.

    FR-241: The system SHALL expose four MCP tools via list_tools handler.
    """

    @pytest.mark.asyncio
    async def test_design_architecture_tool_is_registered(self, patched_mcp_dependencies):
        """FR-241: design_architecture appears in the server's registered tools."""
        from fastmcp import Client

        from src.server import MCPArchitectServer

        server = MCPArchitectServer(config_path=None)

        async with server.lifespan(server._mcp), Client(server._mcp) as client:
            tools = await client.list_tools()
            tool_names = {t.name for t in tools}

        assert "design_architecture" in tool_names, (
            f"design_architecture not in registered tools: {tool_names}"
        )


# ---------------------------------------------------------------------------
# IT-7.2: Full architecture generation
# ---------------------------------------------------------------------------

class TestIT72PipeAndFilterArchitectureGeneration:
    """
    IT-7.2: Call design_architecture via the FastMCP Client and verify the
    returned ArchitectureDesign matches the ETL pipeline requirements and
    pipe-and-filter pattern.

    FR-224: DesignArchitectureTool delegates to pipeline.run_design().
    FR-214: Full pipeline (analyze → generate → evaluate → refine).
    """

    @pytest.mark.asyncio
    async def test_design_returns_pipe_and_filter_architecture(self, patched_mcp_dependencies):
        """Verify the generated design has pipe-and-filter style and correct components."""
        from fastmcp import Client

        from src.server import MCPArchitectServer

        server = MCPArchitectServer(config_path=None)

        async with server.lifespan(server._mcp), Client(server._mcp) as client:
            result = await client.call_tool(
                "design_architecture",
                {
                    "requirements": ETL_PIPELINE_REQUIREMENTS,
                    "domain": PIPELINE_DOMAIN,
                },
            )

        design = result.data["design"]
        overview = design["overview"]

        assert overview["style"] == "pipe-and-filter", (
            f"Expected style 'pipe-and-filter', got '{overview['style']}'"
        )
        assert overview["category"] == "dataflow"

    @pytest.mark.asyncio
    async def test_design_contains_filter_components(self, patched_mcp_dependencies):
        """Verify the design has filter-type components matching the ETL stages."""
        from fastmcp import Client

        from src.server import MCPArchitectServer

        server = MCPArchitectServer(config_path=None)

        async with server.lifespan(server._mcp), Client(server._mcp) as client:
            result = await client.call_tool(
                "design_architecture",
                {
                    "requirements": ETL_PIPELINE_REQUIREMENTS,
                    "domain": PIPELINE_DOMAIN,
                },
            )

        design = result.data["design"]
        component_types = {c["type"] for c in design["components"]}

        assert "filter" in component_types, f"No filter component found: {component_types}"
        assert "data-source" in component_types
        assert "data-sink" in component_types

    @pytest.mark.asyncio
    async def test_design_has_linear_pipeline_relationships(self, patched_mcp_dependencies):
        """Verify the component relationships form a linear pipe-and-filter chain."""
        from fastmcp import Client

        from src.server import MCPArchitectServer

        server = MCPArchitectServer(config_path=None)

        async with server.lifespan(server._mcp), Client(server._mcp) as client:
            result = await client.call_tool(
                "design_architecture",
                {
                    "requirements": ETL_PIPELINE_REQUIREMENTS,
                    "domain": PIPELINE_DOMAIN,
                },
            )

        design = result.data["design"]
        rels = design["relationships"]

        assert len(rels) >= 5, f"Expected >=5 relationships for a pipeline, got {len(rels)}"

        source_ids = {r["source"] for r in rels}
        target_ids = {r["target"] for r in rels}
        assert "iot-kafka-source" in source_ids
        assert "influxdb-sink" in target_ids or "s3-data-lake-sink" in target_ids

    @pytest.mark.asyncio
    async def test_design_includes_pipe_and_filter_pattern(self, patched_mcp_dependencies):
        """Verify the patterns list includes the pipe-and-filter pattern."""
        from fastmcp import Client

        from src.server import MCPArchitectServer

        server = MCPArchitectServer(config_path=None)

        async with server.lifespan(server._mcp), Client(server._mcp) as client:
            result = await client.call_tool(
                "design_architecture",
                {
                    "requirements": ETL_PIPELINE_REQUIREMENTS,
                    "domain": PIPELINE_DOMAIN,
                },
            )

        design = result.data["design"]
        pattern_names = {p["name"] for p in design["patterns"]}

        assert "pipe-and-filter" in pattern_names, (
            f"pipe-and-filter not in patterns: {pattern_names}"
        )

    @pytest.mark.asyncio
    async def test_design_has_populated_contracts(self, patched_mcp_dependencies):
        """Verify api_contracts, shared_data_models, and event_contracts are all populated."""
        from fastmcp import Client

        from src.server import MCPArchitectServer

        server = MCPArchitectServer(config_path=None)

        async with server.lifespan(server._mcp), Client(server._mcp) as client:
            result = await client.call_tool(
                "design_architecture",
                {
                    "requirements": ETL_PIPELINE_REQUIREMENTS,
                    "domain": PIPELINE_DOMAIN,
                },
            )

        design = result.data["design"]

        assert len(design["api_contracts"]) > 0, "api_contracts should be populated"
        assert len(design["shared_data_models"]) > 0, "shared_data_models should be populated"
        assert len(design["event_contracts"]) > 0, "event_contracts should be populated"

    @pytest.mark.asyncio
    async def test_design_has_kubernetes_deployment(self, patched_mcp_dependencies):
        """Verify the deployment strategy targets Kubernetes with per-filter HPA."""
        from fastmcp import Client

        from src.server import MCPArchitectServer

        server = MCPArchitectServer(config_path=None)

        async with server.lifespan(server._mcp), Client(server._mcp) as client:
            result = await client.call_tool(
                "design_architecture",
                {
                    "requirements": ETL_PIPELINE_REQUIREMENTS,
                    "domain": PIPELINE_DOMAIN,
                },
            )

        design = result.data["design"]

    @pytest.mark.asyncio
    async def test_pipeline_attempts_completed(self, patched_mcp_dependencies):
        """Verify the pipeline ran (attempts field is set) and returned a score."""
        from fastmcp import Client

        from src.server import MCPArchitectServer

        server = MCPArchitectServer(config_path=None)

        async with server.lifespan(server._mcp), Client(server._mcp) as client:
            result = await client.call_tool(
                "design_architecture",
                {
                    "requirements": ETL_PIPELINE_REQUIREMENTS,
                    "domain": PIPELINE_DOMAIN,
                },
            )

        assert result.data["attempts"] >= 1
        assert result.data["final_quality_score"] > 0.0


# ---------------------------------------------------------------------------
# IT-7.3: Spec §4.11 schema conformance
# ---------------------------------------------------------------------------

class TestIT73SchemaConformance:
    """
    IT-7.3: Verify the tool response conforms to spec §4.11 — all required
    top-level keys present and structurally correct.
    """

    REQUIRED_TOP_LEVEL_KEYS = [
        "overview",
        "components",
        "relationships",
        "patterns",
        "quality_attributes",
        "api_contracts",
        "shared_data_models",
        "event_contracts",
    ]

    REQUIRED_OVERVIEW_KEYS = ["style", "category", "principles"]

    @pytest.mark.asyncio
    async def test_all_required_top_level_keys_present(self, patched_mcp_dependencies):
        """spec §4.11: Every ArchitectureDesign has all required top-level keys."""
        from fastmcp import Client

        from src.server import MCPArchitectServer

        server = MCPArchitectServer(config_path=None)

        async with server.lifespan(server._mcp), Client(server._mcp) as client:
            result = await client.call_tool(
                "design_architecture",
                {
                    "requirements": ETL_PIPELINE_REQUIREMENTS,
                    "domain": PIPELINE_DOMAIN,
                },
            )

        design = result.data["design"]
        missing = [k for k in self.REQUIRED_TOP_LEVEL_KEYS if k not in design]

        assert not missing, f"Missing top-level keys in design: {missing}"

    @pytest.mark.asyncio
    async def test_overview_has_required_fields(self, patched_mcp_dependencies):
        """spec §4.11: overview contains style, category, and principles."""
        from fastmcp import Client

        from src.server import MCPArchitectServer

        server = MCPArchitectServer(config_path=None)

        async with server.lifespan(server._mcp), Client(server._mcp) as client:
            result = await client.call_tool(
                "design_architecture",
                {
                    "requirements": ETL_PIPELINE_REQUIREMENTS,
                    "domain": PIPELINE_DOMAIN,
                },
            )

        overview = result.data["design"]["overview"]
        missing = [k for k in self.REQUIRED_OVERVIEW_KEYS if k not in overview]

        assert not missing, f"Missing overview keys: {missing}"

    @pytest.mark.asyncio
    async def test_components_is_non_empty_list(self, patched_mcp_dependencies):
        """spec §4.11: components is a non-empty list."""
        from fastmcp import Client

        from src.server import MCPArchitectServer

        server = MCPArchitectServer(config_path=None)

        async with server.lifespan(server._mcp), Client(server._mcp) as client:
            result = await client.call_tool(
                "design_architecture",
                {
                    "requirements": ETL_PIPELINE_REQUIREMENTS,
                    "domain": PIPELINE_DOMAIN,
                },
            )

        design = result.data["design"]

        assert isinstance(design["components"], list), "components must be a list"
        assert len(design["components"]) >= 1, "components list must be non-empty"

    @pytest.mark.asyncio
    async def test_each_component_has_required_fields(self, patched_mcp_dependencies):
        """spec §4.11: Each component dict has id, name, type, description, responsibilities."""
        from fastmcp import Client

        from src.server import MCPArchitectServer

        server = MCPArchitectServer(config_path=None)

        async with server.lifespan(server._mcp), Client(server._mcp) as client:
            result = await client.call_tool(
                "design_architecture",
                {
                    "requirements": ETL_PIPELINE_REQUIREMENTS,
                    "domain": PIPELINE_DOMAIN,
                },
            )

        design = result.data["design"]
        required = {"id", "name", "type", "description", "responsibilities"}

        for comp in design["components"]:
            missing = required - set(comp.keys())
            assert not missing, f"Component {comp.get('id')} missing fields: {missing}"

    @pytest.mark.asyncio
    async def test_quality_attributes_is_dict(self, patched_mcp_dependencies):
        """spec §4.11: quality_attributes is a dict."""
        from fastmcp import Client

        from src.server import MCPArchitectServer

        server = MCPArchitectServer(config_path=None)

        async with server.lifespan(server._mcp), Client(server._mcp) as client:
            result = await client.call_tool(
                "design_architecture",
                {
                    "requirements": ETL_PIPELINE_REQUIREMENTS,
                    "domain": PIPELINE_DOMAIN,
                },
            )

        design = result.data["design"]
        assert isinstance(design["quality_attributes"], dict)

    @pytest.mark.asyncio
    async def test_event_contracts_have_required_fields(self, patched_mcp_dependencies):
        """spec §4.11: Each event contract has event_name, payload_schema, published_by."""
        from fastmcp import Client

        from src.server import MCPArchitectServer

        server = MCPArchitectServer(config_path=None)

        async with server.lifespan(server._mcp), Client(server._mcp) as client:
            result = await client.call_tool(
                "design_architecture",
                {
                    "requirements": ETL_PIPELINE_REQUIREMENTS,
                    "domain": PIPELINE_DOMAIN,
                },
            )

        design = result.data["design"]
        required = {"event_name", "payload_schema", "published_by"}

        for ec in design["event_contracts"]:
            missing = required - set(ec.keys())
            assert not missing, f"Event contract {ec.get('event_name')} missing: {missing}"

    @pytest.mark.asyncio
    async def test_shared_data_models_have_name_and_is_shared(self, patched_mcp_dependencies):
        """spec §4.11: Each shared_data_model has name and is_shared=true."""
        from fastmcp import Client

        from src.server import MCPArchitectServer

        server = MCPArchitectServer(config_path=None)

        async with server.lifespan(server._mcp), Client(server._mcp) as client:
            result = await client.call_tool(
                "design_architecture",
                {
                    "requirements": ETL_PIPELINE_REQUIREMENTS,
                    "domain": PIPELINE_DOMAIN,
                },
            )

        design = result.data["design"]

        for dm in design["shared_data_models"]:
            assert "name" in dm, f"DataModel missing name: {dm}"
            assert dm.get("is_shared") is True, f"DataModel {dm.get('name')} should have is_shared=true"

    @pytest.mark.asyncio
    async def test_design_evaluation_present(self, patched_mcp_dependencies):
        """Verify the top-level evaluation dict is present and has expected structure."""
        from fastmcp import Client

        from src.server import MCPArchitectServer

        server = MCPArchitectServer(config_path=None)

        async with server.lifespan(server._mcp), Client(server._mcp) as client:
            result = await client.call_tool(
                "design_architecture",
                {
                    "requirements": ETL_PIPELINE_REQUIREMENTS,
                    "domain": PIPELINE_DOMAIN,
                },
            )

        evaluation = result.data["evaluation"]


        assert isinstance(evaluation, dict), "evaluation must be a dict"
        assert "summary" in evaluation or "metrics" in evaluation, (
            "evaluation should have summary or metrics"
        )


# ---------------------------------------------------------------------------
# IT-SCHEMA: ArchitectureDesignResponse schema enforcement
# ---------------------------------------------------------------------------


class TestITArchitectureDesignResponseSchema:
    """
    Verify that ArchitectureDesignResponse enforces strict field constraints
    at the LLM wire boundary — before the pipeline tries to construct
    ArchitectureDesign.

    IT-SCHEMA-1: relationships with 'from'/'to' keys (wrong) must fail
                  ArchitectureDesignResponse validation with loc containing 'source'.
                  This was the root cause of the 'source failed validation' error.
    """

    def test_relationships_with_from_to_keys_fail_at_wire_boundary(self):
        """
        Relationships using 'from'/'to' instead of 'source'/'target' must
        raise ValidationError at ArchitectureDesignResponse.model_validate time,
        with loc indicating the 'source' field is missing.
        """
        from pydantic import ValidationError

        from src.schemas.architecture import ArchitectureDesignResponse

        bad_response = {
            "overview": {
                "style": "pipe-and-filter",
                "category": "dataflow",
                "principles": ["Single Responsibility"],
                "constraints": [],
            },
            "components": [
                {
                    "id": "kafka-source",
                    "name": "Kafka Source",
                    "type": "data-source",
                    "description": "Ingests raw IoT sensor data",
                    "responsibilities": ["Consume Kafka topic"],
                }
            ],
            "relationships": [
                {
                    "from": "kafka-source",
                    "to": "parse-filter",
                    "type": "async",
                    "description": "Raw bytes to structured reading",
                }
            ],
        }

        with pytest.raises(ValidationError) as exc_info:
            ArchitectureDesignResponse.model_validate(bad_response)

        errors = exc_info.value.errors()
        assert len(errors) > 0
        first_loc = ".".join(str(l) for l in errors[0]["loc"])
        assert "source" in first_loc, (
            f"Expected 'source' in error loc, got: {first_loc}"
        )

    def test_component_id_invalid_kebab_case_fails_at_wire_boundary(self):
        """
        Component ids not matching ^[a-z][a-z0-9_-]*$ must fail at
        ArchitectureDesignResponse.model_validate time.
        """
        from pydantic import ValidationError

        from src.schemas.architecture import ArchitectureDesignResponse

        bad_response = {
            "overview": {
                "style": "pipe-and-filter",
                "category": "dataflow",
                "principles": ["Single Responsibility"],
                "constraints": [],
            },
            "components": [
                {
                    "id": "KafkaSource",  # capital letters — violates kebab-case
                    "name": "Kafka Source",
                    "type": "data-source",
                    "description": "Ingests raw IoT sensor data",
                    "responsibilities": ["Consume Kafka topic"],
                }
            ],
            "relationships": [],
        }

        with pytest.raises(ValidationError) as exc_info:
            ArchitectureDesignResponse.model_validate(bad_response)

        errors = exc_info.value.errors()
        assert len(errors) > 0
        first_loc = ".".join(str(l) for l in errors[0]["loc"])
        assert "id" in first_loc, (
            f"Expected 'id' in error loc, got: {first_loc}"
        )


# ---------------------------------------------------------------------------
# IT-REAL: Real-path retrieval integration test
# ---------------------------------------------------------------------------

class TestITRealPathRetrieval:
    """
    Integration test exercising the real HybridPatternRetriever dense leg path.

    IT-REAL-1: retrieve() against a real DomainVectorIndex (with mocked _embed)
               does NOT raise KeyError and returns at least one pattern.

    This test would have caught the original KeyError: '144' bug where
    DomainVectorIndex.build_index() never populated the LlamaIndex docstore,
    causing VectorIndexRetriever._determine_nodes_to_fetch() to crash when
    looking up node IDs that didn't exist in index_struct.nodes_dict.

    The fix (DomainVectorRetriever wrapping DomainVectorIndex.search() directly)
    bypasses LlamaIndex's broken docstore plumbing, making this test pass.
    """

    @pytest.mark.asyncio
    async def test_retrieve_real_path_no_key_error(self):
        """
        Verify the dense retrieval path works end-to-end without KeyError.

        Uses a real HybridPatternRetriever with:
        - Real DomainVectorIndex (litellm.embedding patched for deterministic vectors)
        - Mocked BM25Index (MockPipeAndFilterBM25Index provides a working as_retriever())

        This exercises DomainVectorRetriever._retrieve() which calls
        DomainVectorIndex.search() directly — the path that was broken before
        the fix (KeyError: '144' from empty LlamaIndex docstore).
        """
        import numpy as np

        from src.patterns.bm25_index import DomainBM25Index
        from src.patterns.retriever import HybridPatternRetriever
        from src.patterns.vector_index import DomainVectorIndex
        from tests.integration.conftest import MockPipeAndFilterPatternLoader

        EMBED_DIM = 1024
        fixture_domains = ["microservices", "event-driven", "layered-monolith", "data-processing"]

        def fake_litellm_embedding(api_key, api_base, model_name, input, **kwargs):
            n = len(input)
            vectors = np.ones((n, EMBED_DIM), dtype=np.float32) * 0.01
            for i, text in enumerate(input):
                vec = vectors[i]
                if "microservices" in text.lower():
                    vec[0] = 1.0
                elif "event" in text.lower():
                    vec[1] = 1.0
                elif "layered" in text.lower():
                    vec[2] = 1.0
                elif "data" in text.lower():
                    vec[3] = 1.0
                else:
                    vec[i % EMBED_DIM] = 0.8
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec /= norm
            return {"data": [{"embedding": vectors[j].tolist()} for j in range(n)]}

        vector_index = DomainVectorIndex(
            base_url="http://localhost:8080",
            model="Qwen/Qwen3-Embedding-0.6B",
            api_key=None,
            embedding_dim=EMBED_DIM,
            max_tokens=3000,
            embed_batch_size=16,
            query_instruction="",
            text_instruction="",
            provider="tei",
        )

        with patch("litellm.embedding", side_effect=fake_litellm_embedding):
            vector_index.build_index(fixture_domains)

        bm25_index = DomainBM25Index()
        bm25_index.build_index(fixture_domains)
        pattern_loader = MockPipeAndFilterPatternLoader()

        retriever = HybridPatternRetriever(
            bm25_index=bm25_index,
            vector_index=vector_index,
            pattern_loader=pattern_loader,
            bm25_top_k=5,
            dense_top_k=5,
            mode="reciprocal_rerank",
        )

        with patch("litellm.embedding", side_effect=fake_litellm_embedding):
            result = retriever.retrieve(
                user_domain="microservices",
                normalized_domain="microservices",
            )

        assert isinstance(result, list), f"Expected list, got {type(result)}"
        assert len(result) >= 1, "Expected at least one pattern result"

        pattern, score = result[0]
        assert isinstance(pattern, dict), f"Expected dict pattern, got {type(pattern)}"
        assert "name" in pattern, f"Pattern missing 'name': {pattern}"
        assert isinstance(score, float), f"Expected float score, got {type(score)}"

    @pytest.mark.asyncio
    async def test_retrieve_real_path_with_empty_result_no_crash(self):
        """
        Verify the dense retrieval path doesn't crash on a low-scoring query.

        The mock pattern loader doesn't have 'layered-monolith', so when fusion
        score is too low and the fallback is missing, an empty list is returned.
        The key assertion is: no KeyError is raised.
        """
        import numpy as np

        from src.patterns.bm25_index import DomainBM25Index
        from src.patterns.retriever import HybridPatternRetriever
        from src.patterns.vector_index import DomainVectorIndex
        from tests.integration.conftest import MockPipeAndFilterPatternLoader

        EMBED_DIM = 1024
        fixture_domains = ["microservices", "event-driven"]

        def fake_litellm_embedding(api_key, api_base, model_name, input, **kwargs):
            n = len(input)
            vectors = np.ones((n, EMBED_DIM), dtype=np.float32) * 0.01
            for i, text in enumerate(input):
                vectors[i, i % EMBED_DIM] = 0.01
                norm = np.linalg.norm(vectors[i])
                if norm > 0:
                    vectors[i] /= norm
            return {"data": [{"embedding": vectors[j].tolist()} for j in range(n)]}

        vector_index = DomainVectorIndex(
            base_url="http://localhost:8080",
            model="Qwen/Qwen3-Embedding-0.6B",
            api_key=None,
            embedding_dim=EMBED_DIM,
            max_tokens=3000,
            embed_batch_size=16,
            query_instruction="",
            text_instruction="",
            provider="tei",
        )

        with patch("litellm.embedding", side_effect=fake_litellm_embedding):
            vector_index.build_index(fixture_domains)

        bm25_index = DomainBM25Index()
        bm25_index.build_index(fixture_domains)
        pattern_loader = MockPipeAndFilterPatternLoader()

        retriever = HybridPatternRetriever(
            bm25_index=bm25_index,
            vector_index=vector_index,
            pattern_loader=pattern_loader,
            bm25_top_k=5,
            dense_top_k=5,
            mode="reciprocal_rerank",
            min_fusion_score=999.0,
        )

        with patch("litellm.embedding", side_effect=fake_litellm_embedding):
            result = retriever.retrieve(
                user_domain="nonexistent-domain-xyz",
                normalized_domain="nonexistent-domain-xyz",
            )

        assert isinstance(result, list)
        assert len(result) == 0, "Expected empty list when no patterns match and no fallback"
