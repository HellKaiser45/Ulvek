# agent_test.py
"""
Comprehensive test suite for all agents with detailed reporting and observability.
"""

import asyncio
import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import traceback
import sys
import os

# Add the project root to Python path if needed
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.app.agents.agent import (
    task_classification_agent,
    evaluator_agent,
    coding_agent,
    orchestrator_agent,
    context_retriever_agent,
    conversational_agent,
    run_agent_with_events,
)
from src.app.agents.schemas import (
    TaskType,
    Evaluation,
    WorkerResult,
    ProjectPlan,
    AssembledContext,
)


@dataclass
class TestMetrics:
    """Detailed metrics for agent execution."""

    start_time: float
    end_time: float
    duration_seconds: float
    total_tokens: int
    model_requests: int
    tool_calls: int
    streaming_events: int
    retry_attempts: int
    success: bool
    error_message: Optional[str] = None
    error_traceback: Optional[str] = None


@dataclass
class TestResult:
    """Complete test result with all execution details."""

    agent_name: str
    test_case_name: str
    prompt: str
    expected_output_type: str
    actual_output: Any
    actual_output_serialized: str
    metrics: TestMetrics
    events_log: List[Dict[str, Any]]
    validation_results: Dict[str, Any]
    human_readable_summary: str


class AgentTester:
    """Enhanced agent testing framework with comprehensive reporting."""

    def __init__(self, output_dir: str = ".agent_test"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.test_results: List[TestResult] = []

    async def run_comprehensive_tests(self) -> None:
        """Run all agent tests with various challenging scenarios."""
        print("🚀 Starting comprehensive agent testing...")

        # Test cases for each agent
        test_cases = [
            # Task Classification Agent
            {
                "agent": task_classification_agent,
                "agent_name": "task_classification_agent",
                "expected_type": TaskType,
                "test_cases": [
                    ("Simple chat question", "What is Python?"),
                    (
                        "Complex coding task",
                        "Build a REST API with authentication, database integration, and comprehensive error handling",
                    ),
                    (
                        "Context gathering task",
                        "I need to understand how this FastAPI project works before making changes",
                    ),
                    (
                        "Planning task",
                        "Refactor our entire microservices architecture to use event-driven design",
                    ),
                    ("Edge case - ambiguous", "Help me with my project"),
                ],
            },
            # Evaluator Agent
            {
                "agent": evaluator_agent,
                "agent_name": "evaluator_agent",
                "expected_type": Evaluation,
                "test_cases": [
                    (
                        "Evaluate good code",
                        "Evaluate this Python function:\n```python\ndef factorial(n: int) -> int:\n    if n <= 1:\n        return 1\n    return n * factorial(n - 1)\n```",
                    ),
                    (
                        "Evaluate bad code",
                        "Evaluate this code:\n```python\ndef bad_func(x):\n    return x/0\n```",
                    ),
                    (
                        "Evaluate incomplete work",
                        "The task was to create a user authentication system. Here's what was done: Created a User model class.",
                    ),
                    (
                        "Complex evaluation",
                        "Evaluate this microservice implementation for a payment system with considerations for security, scalability, and maintainability.",
                    ),
                ],
            },
            # Coding Agent
            {
                "agent": coding_agent,
                "agent_name": "coding_agent",
                "expected_type": WorkerResult,
                "test_cases": [
                    (
                        "Simple function",
                        "Create a Python function that validates email addresses using regex",
                    ),
                    (
                        "Class creation",
                        "Create a Python class for managing a simple in-memory cache with TTL support",
                    ),
                    (
                        "Bug fix scenario",
                        "Fix the bug in this code: def divide(a, b): return a / b",
                    ),
                    (
                        "Complex refactoring",
                        "Refactor this monolithic function into smaller, testable components",
                    ),
                    (
                        "Error handling",
                        "Add comprehensive error handling to this database connection function",
                    ),
                ],
            },
            # Orchestrator Agent
            {
                "agent": orchestrator_agent,
                "agent_name": "orchestrator_agent",
                "expected_type": ProjectPlan,
                "test_cases": [
                    ("Simple project", "Create a CLI tool for file organization"),
                    (
                        "Web application",
                        "Build a full-stack blog application with user authentication",
                    ),
                    (
                        "Microservices project",
                        "Design and implement a microservices-based e-commerce platform",
                    ),
                    ("Migration project", "Migrate our Django application to FastAPI"),
                    (
                        "Integration project",
                        "Integrate our existing system with multiple third-party APIs",
                    ),
                ],
            },
            # Context Retriever Agent
            {
                "agent": context_retriever_agent,
                "agent_name": "context_retriever_agent",
                "expected_type": AssembledContext,
                "test_cases": [
                    (
                        "Understand codebase",
                        "I need to understand the authentication system in this FastAPI project",
                    ),
                    (
                        "Database investigation",
                        "Help me understand how the database models are structured",
                    ),
                    (
                        "API analysis",
                        "Analyze the API endpoints and their relationships",
                    ),
                    (
                        "Testing strategy",
                        "What testing frameworks and patterns are used in this project?",
                    ),
                    (
                        "Performance analysis",
                        "Identify potential performance bottlenecks in the current architecture",
                    ),
                ],
            },
            # Conversational Agent
            {
                "agent": conversational_agent,
                "agent_name": "conversational_agent",
                "expected_type": str,  # Returns string, not structured output
                "test_cases": [
                    (
                        "Technical question",
                        "Explain the difference between async/await and threading in Python",
                    ),
                    ("Best practices", "What are the best practices for API design?"),
                    (
                        "Debugging help",
                        "My application is running slowly, how should I approach debugging this?",
                    ),
                    (
                        "Architecture advice",
                        "Should I use a monolithic or microservices architecture for my startup?",
                    ),
                    (
                        "Code review",
                        "Can you review this Python code and suggest improvements?",
                    ),
                ],
            },
        ]

        for agent_config in test_cases:
            await self._test_agent_suite(agent_config)

        # Generate comprehensive report
        await self._generate_master_report()
        print(f"✅ Testing complete! Reports saved to {self.output_dir}")

    async def _test_agent_suite(self, agent_config: Dict[str, Any]) -> None:
        """Test a single agent with multiple test cases."""
        agent = agent_config["agent"]
        agent_name = agent_config["agent_name"]
        expected_type = agent_config["expected_type"]

        print(f"\n🧪 Testing {agent_name}...")

        agent_results = []

        for test_case_name, prompt in agent_config["test_cases"]:
            print(f"  📝 Running: {test_case_name}")

            start_time = time.time()
            events_log = []
            metrics = TestMetrics(
                start_time=start_time,
                end_time=0,
                duration_seconds=0,
                total_tokens=0,
                model_requests=0,
                tool_calls=0,
                streaming_events=0,
                retry_attempts=0,
                success=False,
            )

            try:
                # Run the agent with event collection
                actual_output = None
                async for event in run_agent_with_events(agent, prompt):
                    event_data = {
                        "timestamp": time.time(),
                        "event_type": type(event).__name__,
                        "content": str(event) if event else None,
                    }
                    events_log.append(event_data)

                    # Track metrics from events
                    if hasattr(event, "model_requests"):
                        metrics.model_requests += 1
                    if hasattr(event, "tool_calls"):
                        metrics.tool_calls += 1

                    # Capture the final output
                    if isinstance(event, (dict, expected_type)) or (
                        expected_type is str and isinstance(event, str)
                    ):
                        actual_output = event

                metrics.success = actual_output is not None

            except Exception as e:
                metrics.error_message = str(e)
                metrics.error_traceback = traceback.format_exc()
                actual_output = None
                print(f"    ❌ Error: {e}")

            # Finalize metrics
            end_time = time.time()
            metrics.end_time = end_time
            metrics.duration_seconds = end_time - start_time

            # Validate output
            validation_results = self._validate_output(actual_output, expected_type)

            # Serialize output for JSON storage
            actual_output_serialized = self._serialize_output(actual_output)

            # Create human-readable summary
            human_readable_summary = self._create_summary(
                agent_name,
                test_case_name,
                prompt,
                actual_output,
                metrics,
                validation_results,
                len(events_log),
            )

            # Create test result
            test_result = TestResult(
                agent_name=agent_name,
                test_case_name=test_case_name,
                prompt=prompt,
                expected_output_type=str(expected_type),
                actual_output=actual_output,
                actual_output_serialized=actual_output_serialized,
                metrics=metrics,
                events_log=events_log,
                validation_results=validation_results,
                human_readable_summary=human_readable_summary,
            )

            agent_results.append(test_result)
            self.test_results.append(test_result)

            # Individual test report
            await self._save_individual_test_report(test_result)

        # Agent summary report
        await self._save_agent_summary_report(agent_name, agent_results)

    def _validate_output(self, output: Any, expected_type: type) -> Dict[str, Any]:
        """Validate agent output against expected schema."""
        validation_results = {
            "type_match": False,
            "schema_valid": False,
            "content_quality": "unknown",
            "errors": [],
        }

        try:
            if expected_type is str:
                validation_results["type_match"] = isinstance(output, str)
                validation_results["schema_valid"] = True
                validation_results["content_quality"] = (
                    "good" if output and len(output) > 10 else "poor"
                )
            else:
                validation_results["type_match"] = isinstance(output, expected_type)
                if isinstance(output, expected_type):
                    validation_results["schema_valid"] = True
                    validation_results["content_quality"] = "good"

        except Exception as e:
            validation_results["errors"].append(str(e))

        return validation_results

    def _serialize_output(self, output: Any) -> str:
        """Serialize output for JSON storage."""
        try:
            if hasattr(output, "model_dump"):
                return json.dumps(output.model_dump(), indent=2, default=str)
            elif hasattr(output, "__dict__"):
                return json.dumps(output.__dict__, indent=2, default=str)
            else:
                return json.dumps(output, indent=2, default=str)
        except Exception:
            return str(output)

    def _create_summary(
        self,
        agent_name: str,
        test_case_name: str,
        prompt: str,
        output: Any,
        metrics: TestMetrics,
        validation: Dict[str, Any],
        events_count: int = 0,
    ) -> str:
        """Create human-readable summary of test execution."""
        status = "✅ SUCCESS" if metrics.success else "❌ FAILED"
        type_match_icon = "✅" if validation["type_match"] else "❌"
        schema_valid_icon = "✅" if validation["schema_valid"] else "❌"

        output_str = str(output)
        output_preview = output_str[:500] + ("..." if len(output_str) > 500 else "")

        error_section = (
            f"ERROR: {metrics.error_message}" if metrics.error_message else ""
        )

        summary = f"""
=== {agent_name.upper()} - {test_case_name} ===

STATUS: {status}
DURATION: {metrics.duration_seconds:.2f}s
RETRIES: {metrics.retry_attempts}

PROMPT:
{prompt}

VALIDATION:
- Type Match: {type_match_icon}
- Schema Valid: {schema_valid_icon}
- Content Quality: {validation["content_quality"]}

METRICS:
- Model Requests: {metrics.model_requests}
- Tool Calls: {metrics.tool_calls}
- Events: {events_count}

OUTPUT PREVIEW:
{output_preview}

{error_section}
"""
        return summary.strip()

    async def _save_individual_test_report(self, result: TestResult) -> None:
        """Save detailed report for individual test."""
        filename = f"{result.agent_name}_{result.test_case_name.replace(' ', '_')}.json"
        filepath = self.output_dir / filename

        # Convert to dict for JSON serialization
        report_data = {
            "metadata": {
                "agent_name": result.agent_name,
                "test_case_name": result.test_case_name,
                "timestamp": datetime.now().isoformat(),
                "success": result.metrics.success,
            },
            "prompt": result.prompt,
            "expected_output_type": result.expected_output_type,
            "actual_output": result.actual_output_serialized,
            "metrics": asdict(result.metrics),
            "events_log": result.events_log,
            "validation_results": result.validation_results,
            "human_readable_summary": result.human_readable_summary,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, default=str)

    async def _save_agent_summary_report(
        self, agent_name: str, results: List[TestResult]
    ) -> None:
        """Save summary report for an agent across all test cases."""
        filepath = self.output_dir / f"{agent_name}_SUMMARY.md"

        total_tests = len(results)
        successful_tests = sum(1 for r in results if r.metrics.success)
        avg_duration = sum(r.metrics.duration_seconds for r in results) / total_tests

        content = f"""# {agent_name.upper()} - Test Summary Report

## Overview
- **Total Tests**: {total_tests}
- **Successful**: {successful_tests}/{total_tests} ({successful_tests / total_tests * 100:.1f}%)
- **Average Duration**: {avg_duration:.2f}s
- **Generated**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Test Results

"""

        for result in results:
            status_emoji = "✅" if result.metrics.success else "❌"
            content += f"""### {status_emoji} {result.test_case_name}
- **Duration**: {result.metrics.duration_seconds:.2f}s
- **Type Valid**: {"✅" if result.validation_results["type_match"] else "❌"}
- **Schema Valid**: {"✅" if result.validation_results["schema_valid"] else "❌"}
- **Quality**: {result.validation_results["content_quality"]}

**Prompt**: {result.prompt[:100]}...

---

"""

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

    async def _generate_master_report(self) -> None:
        """Generate comprehensive master report across all agents."""
        filepath = self.output_dir / "MASTER_REPORT.md"

        # Overall statistics
        total_tests = len(self.test_results)
        successful_tests = sum(1 for r in self.test_results if r.metrics.success)

        # Group by agent
        by_agent = {}
        for result in self.test_results:
            if result.agent_name not in by_agent:
                by_agent[result.agent_name] = []
            by_agent[result.agent_name].append(result)

        content = f"""# 🤖 Agent Testing - Master Report

## 📊 Executive Summary
- **Total Tests Run**: {total_tests}
- **Overall Success Rate**: {successful_tests}/{total_tests} ({successful_tests / total_tests * 100:.1f}%)
- **Test Date**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## 🔍 Agent Performance Overview

| Agent | Tests | Success Rate | Avg Duration |
|-------|-------|--------------|--------------|
"""

        for agent_name, results in by_agent.items():
            agent_success = sum(1 for r in results if r.metrics.success)
            agent_total = len(results)
            avg_duration = (
                sum(r.metrics.duration_seconds for r in results) / agent_total
            )

            content += f"| {agent_name} | {agent_total} | {agent_success}/{agent_total} ({agent_success / agent_total * 100:.1f}%) | {avg_duration:.2f}s |\n"

        content += """

## 🚨 Issues and Recommendations

### Failed Tests
"""

        failed_tests = [r for r in self.test_results if not r.metrics.success]
        if failed_tests:
            for result in failed_tests:
                content += f"- **{result.agent_name}** - {result.test_case_name}: {result.metrics.error_message}\n"
        else:
            content += "None! All tests passed successfully. 🎉\n"

        content += """

### Performance Insights
"""

        slowest = max(self.test_results, key=lambda x: x.metrics.duration_seconds)
        fastest = min(self.test_results, key=lambda x: x.metrics.duration_seconds)

        content += f"""- **Slowest Test**: {slowest.agent_name} - {slowest.test_case_name} ({slowest.metrics.duration_seconds:.2f}s)
- **Fastest Test**: {fastest.agent_name} - {fastest.test_case_name} ({fastest.metrics.duration_seconds:.2f}s)

## 📁 Detailed Reports
Individual test reports are available in the following files:

"""

        for result in self.test_results:
            filename = (
                f"{result.agent_name}_{result.test_case_name.replace(' ', '_')}.json"
            )
            content += (
                f"- `{filename}` - {result.agent_name} - {result.test_case_name}\n"
            )

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)


async def main():
    """Run the comprehensive agent test suite."""
    tester = AgentTester()
    await tester.run_comprehensive_tests()


if __name__ == "__main__":
    asyncio.run(main())
