import asyncio
from app.flows.enrichment_flow import LeadEnrichmentFlow

async def main():
    flow = LeadEnrichmentFlow()
    flow.state.company_name = "Test Company"
    flow.state.enabled_tools = []
    
    # Simulate LLM output
    flow.state.llm_output = {
        "merged_contacts": [],
        "lead_scores": {"confidence_score": 1.0}
    }
    
    # Run hybrid_trigger
    try:
        flow.hybrid_trigger()
    except Exception as e:
        print(f"Exception: {e}")
        
    print(f"fallback_triggered: {flow.state.fallback_triggered}")
    print(f"target_gap: {flow.state.target_gap}")

if __name__ == "__main__":
    asyncio.run(main())
