"""Pydantic output schemas for the News Agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class NewsItem(BaseModel):
    """A single news article or event."""

    headline: str = Field(..., description="News headline")
    date: str = Field("", description="Publication date (YYYY-MM-DD)")
    category: str = Field("", description="Category, e.g. funding, product_launch, partnership")
    sentiment: str = Field("neutral", description="Sentiment: positive, negative, neutral, mixed")
    impact_score: int = Field(0, description="Business impact score (0-100)")
    url: str = Field("", description="URL to the original article")


class SignalsDetected(BaseModel):
    """Boolean buying-intent signals derived from recent news."""

    recent_funding: bool = Field(False, description="Company recently secured funding")
    expansion: bool = Field(False, description="Company is expanding (new offices, markets)")
    layoffs: bool = Field(False, description="Company announced layoffs")
    product_launch: bool = Field(False, description="Company launched a new product or service")


class NewsAgentData(BaseModel):
    """Payload containing news analysis results."""

    recent_news: list[NewsItem] = Field(
        default_factory=list, description="List of recent news items"
    )
    signals_detected: SignalsDetected = Field(
        default_factory=SignalsDetected, description="Buying-intent signals"
    )
    intent_score: int = Field(0, description="Overall buying intent score (0-100)")
    overall_sentiment_score: int = Field(0, description="Aggregate sentiment score (0-100)")


class SourceMetadata(BaseModel):
    """Metadata about the data provider used."""

    provider: str = Field(..., description="Provider name")
    api_version: str = Field("", description="API version used")
    timestamp_utc: str = Field("", description="UTC timestamp of the API call")


class NewsAgentOutput(BaseModel):
    """
    Structured JSON output schema for the news_agent.

    CrewAI will enforce that the agent returns data matching this schema
    when used with ``output_json=NewsAgentOutput`` on the Task.
    """

    request_id: str = Field(..., description="Unique request identifier")
    lead_id: str = Field(..., description="Salesforce lead ID")
    agent_name: str = Field("news_agent", description="Name of the agent")
    status: str = Field("success", description="Execution status")
    execution_time_ms: int = Field(0, description="Execution time in milliseconds")
    data: NewsAgentData = Field(..., description="News data payload")
    errors: list[str] = Field(default_factory=list, description="List of errors, if any")
    confidence_score: float = Field(0.0, description="Overall confidence score")
    source_metadata: SourceMetadata = Field(..., description="Source provider metadata")
