"""Tests for search endpoint graph expansion feature."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def create_async_result_mock(records):
    """Create a mock Neo4j result that works as an async iterator."""
    result = MagicMock()

    async def async_iter():
        for r in records:
            yield r

    result.__aiter__ = lambda self: async_iter()
    return result


def create_neo4j_session_mock():
    """Create a mock Neo4j session that works as an async context manager."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return session


class TestSearchExpandBackwardCompat:
    """Verify that search works identically when expand=False (default)."""

    @pytest.mark.asyncio
    async def test_search_without_expand_returns_normal_results(self):
        """Search with expand=False (default) should behave exactly as before."""
        mock_session = create_neo4j_session_mock()

        sample_decisions = [
            {
                "d": {
                    "id": "decision-1",
                    "trigger": "Choosing a database",
                    "decision": "Use PostgreSQL",
                    "confidence": 0.9,
                },
                "score": 0.95,
            }
        ]

        call_count = [0]

        async def mock_run(query, **params):
            call_count[0] += 1
            if call_count[0] == 1:
                return create_async_result_mock(sample_decisions)
            return create_async_result_mock([])

        mock_session.run = mock_run

        with patch(
            "routers.search.get_neo4j_session",
            new_callable=AsyncMock,
            return_value=mock_session,
        ):
            from routers.search import search

            results = await search(query="database", type="decision", expand=False, depth=1)

            assert len(results) == 1
            assert results[0].type == "decision"
            assert results[0].id == "decision-1"
            assert results[0].score == 0.95

    @pytest.mark.asyncio
    async def test_search_default_params_no_expansion(self):
        """Search with default params should not call graph_rag service."""
        mock_session = create_neo4j_session_mock()

        sample_decisions = [
            {
                "d": {
                    "id": "decision-1",
                    "trigger": "Choosing a database",
                    "decision": "Use PostgreSQL",
                    "confidence": 0.9,
                },
                "score": 0.95,
            }
        ]

        call_count = [0]

        async def mock_run(query, **params):
            call_count[0] += 1
            if call_count[0] == 1:
                return create_async_result_mock(sample_decisions)
            return create_async_result_mock([])

        mock_session.run = mock_run

        with (
            patch(
                "routers.search.get_neo4j_session",
                new_callable=AsyncMock,
                return_value=mock_session,
            ),
            patch(
                "routers.search.get_graph_rag_service",
            ) as mock_rag,
        ):
            from routers.search import search

            # When called directly (not via HTTP), pass expand=False explicitly
            # (FastAPI resolves Query defaults only through HTTP request handling)
            results = await search(query="database", type="decision", expand=False, depth=1)

            # graph_rag_service should NOT be called when expand=False
            mock_rag.assert_not_called()
            assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_empty_results_no_expansion(self):
        """When there are no results, expansion should not be attempted even if expand=True."""
        mock_session = create_neo4j_session_mock()
        mock_session.run = AsyncMock(return_value=create_async_result_mock([]))

        with (
            patch(
                "routers.search.get_neo4j_session",
                new_callable=AsyncMock,
                return_value=mock_session,
            ),
            patch(
                "routers.search.get_graph_rag_service",
            ) as mock_rag,
        ):
            from routers.search import search

            results = await search(query="nonexistent", type="decision", expand=True, depth=1)

            mock_rag.assert_not_called()
            assert results == []


class TestSearchExpandEnabled:
    """Verify graph expansion behavior when expand=True."""

    @pytest.mark.asyncio
    async def test_search_with_expand_appends_expanded_nodes(self):
        """Search with expand=True should append expanded nodes with score 0.5."""
        mock_session = create_neo4j_session_mock()

        sample_decisions = [
            {
                "d": {
                    "id": "decision-1",
                    "trigger": "Choosing a database",
                    "decision": "Use PostgreSQL",
                    "confidence": 0.9,
                },
                "score": 0.95,
            }
        ]

        call_count = [0]

        async def mock_run(query, **params):
            call_count[0] += 1
            if call_count[0] == 1:
                return create_async_result_mock(sample_decisions)
            return create_async_result_mock([])

        mock_session.run = mock_run

        mock_rag_service = AsyncMock()
        mock_rag_service.expand_subgraph.return_value = {
            "nodes": [
                {
                    "id": "entity-99",
                    "type": "entity",
                    "data": {"name": "PostgreSQL", "type": "technology"},
                },
                {
                    "id": "decision-1",  # duplicate of existing result
                    "type": "decision",
                    "data": {"trigger": "Choosing a database"},
                },
            ],
            "edges": [],
        }

        with (
            patch(
                "routers.search.get_neo4j_session",
                new_callable=AsyncMock,
                return_value=mock_session,
            ),
            patch(
                "routers.search.get_graph_rag_service",
                return_value=mock_rag_service,
            ),
        ):
            from routers.search import search

            results = await search(query="database", type="decision", expand=True, depth=2)

            # Should have original + 1 expanded (duplicate is skipped)
            assert len(results) == 2

            # Results should be sorted by score (0.95 first, 0.5 second)
            assert results[0].score == 0.95
            assert results[0].id == "decision-1"
            assert results[1].score == 0.5
            assert results[1].id == "entity-99"

            # Verify expand_subgraph was called with correct args
            mock_rag_service.expand_subgraph.assert_awaited_once_with(
                seed_ids=["decision-1"],
                depth=2,
            )

    @pytest.mark.asyncio
    async def test_search_expand_failure_returns_base_results(self):
        """If graph expansion fails, base results should still be returned."""
        mock_session = create_neo4j_session_mock()

        sample_decisions = [
            {
                "d": {
                    "id": "decision-1",
                    "trigger": "Choosing a database",
                    "decision": "Use PostgreSQL",
                    "confidence": 0.9,
                },
                "score": 0.95,
            }
        ]

        call_count = [0]

        async def mock_run(query, **params):
            call_count[0] += 1
            if call_count[0] == 1:
                return create_async_result_mock(sample_decisions)
            return create_async_result_mock([])

        mock_session.run = mock_run

        mock_rag_service = AsyncMock()
        mock_rag_service.expand_subgraph.side_effect = RuntimeError("Neo4j down")

        with (
            patch(
                "routers.search.get_neo4j_session",
                new_callable=AsyncMock,
                return_value=mock_session,
            ),
            patch(
                "routers.search.get_graph_rag_service",
                return_value=mock_rag_service,
            ),
        ):
            from routers.search import search

            results = await search(query="database", type="decision", expand=True, depth=1)

            # Should still get base results despite expansion failure
            assert len(results) == 1
            assert results[0].id == "decision-1"
