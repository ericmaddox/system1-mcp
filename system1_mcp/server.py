"""System 1 MCP Server - Jev-powered System 1 reflexes for AI agents."""

import logging
import sys
from typing import Any, Dict, List, Optional, Union

from dotenv import load_dotenv

load_dotenv()

# All logging to stderr to keep stdio JSON-RPC clean
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("system1_mcp")

try:
    from mcp.server.mcpserver import MCPServer
    mcp_server_factory = MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP
    mcp_server_factory = FastMCP

from system1_mcp.tools import guard_impl, judge_impl, score_impl, verify_impl

mcp = mcp_server_factory("system1-mcp", description="Jev-powered System 1 reflexes for AI agents")


@mcp.tool()
def fast_guard(
    command: str,
    goal: str,
    workspace: Optional[str] = None,
    block_threshold: float = 0.80,
    review_threshold: float = 0.40,
) -> Dict[str, Any]:
    """Check if a command or action is safe before running it.

    Returns risk probabilities and a recommended action (pass/review/block).
    Call this BEFORE executing shell commands, file modifications, or API calls.

    NOTE: This is advisory -- it returns a recommendation, not enforcement.

    Args:
        command: The shell command or action to evaluate.
        goal: The user's stated task objective / context.
        workspace: Optional current working directory or project context.
        block_threshold: Risk probability threshold above which to recommend 'block' (default 0.80).
        review_threshold: Risk probability threshold above which to recommend 'review' (default 0.40).

    Returns:
        JSON object with 'action' (pass/review/block), 'is_destructive', 'is_dangerous',
        'is_out_of_scope', and 'blast_radius'.
    """
    return guard_impl(
        command=command,
        goal=goal,
        workspace=workspace,
        block_threshold=block_threshold,
        review_threshold=review_threshold,
    )


@mcp.tool()
def fast_judge(
    question: str,
    options: Dict[str, Optional[str]],
    context: Optional[Union[str, Dict[str, Any]]] = None,
    confidence_floor: float = 0.60,
) -> Dict[str, Any]:
    """Instantly select the best option from a set of candidates.

    Returns the chosen option with full probability distribution and confidence.
    Call this when you need to pick one item from a known set without slow deliberation.

    Args:
        question: What to decide (e.g. 'Which file contains the database connection settings?').
        options: Dict mapping candidate keys to descriptions (at least 2 options).
        context: Optional context or state relevant to the decision.
        confidence_floor: Confidence floor (default 0.60) below which 'is_confident' is false.

    Returns:
        JSON object with 'choice', 'confidence', 'probabilities', and 'is_confident'.
    """
    return judge_impl(
        question=question,
        options=options,
        context=context,
        confidence_floor=confidence_floor,
    )


@mcp.tool()
def fast_verify(
    statement: str,
    evidence: Union[str, Dict[str, Any]],
    yes_means: Optional[str] = None,
    no_means: Optional[str] = None,
) -> Dict[str, Any]:
    """Check whether a condition is true or a task goal has been met.

    Returns the probability (0-1) that the statement is true given the evidence.
    Call this to verify goal completion, test outputs, status checks, and loop detection.

    Args:
        statement: The yes/no claim to verify against evidence.
        evidence: The output, log, or evidence to evaluate.
        yes_means: Optional clarification of what 'yes' / true means.
        no_means: Optional clarification of what 'no' / false means.

    Returns:
        JSON object with 'probability', 'is_true', and 'assessment'.
    """
    return verify_impl(
        statement=statement,
        evidence=evidence,
        yes_means=yes_means,
        no_means=no_means,
    )


@mcp.tool()
def fast_score(
    question: str,
    levels: List[str],
    content: Union[str, Dict[str, Any]],
    confidence_floor: float = 0.60,
) -> Dict[str, Any]:
    """Rate content along a defined scale with ordered levels.

    Returns a score, probability distribution across levels, and confidence.
    Call this for severity, quality, relevance, complexity, or any custom rating.

    Args:
        question: What dimension to rate (e.g. 'How severe is this bug report?').
        levels: Ordered list of level descriptions from lowest to highest (at least 2).
        content: The text or object to evaluate.
        confidence_floor: Confidence threshold (default 0.60).

    Returns:
        JSON object with 'score', 'confidence', 'legend', 'probabilities', and 'is_confident'.
    """
    return score_impl(
        question=question,
        levels=levels,
        content=content,
        confidence_floor=confidence_floor,
    )


def main():
    """Run the System 1 MCP server on stdio transport."""
    logger.info("Starting System 1 MCP Server (stdio transport)...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
